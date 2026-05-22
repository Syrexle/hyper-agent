# NEAR Hyperliquid Agent Design

## Goal

Build a Python CLI daemon that trades only the `NEAR-USDC` perpetual on Hyperliquid using a live wallet key supplied locally by the operator. The bot is live-trading capable from day one, but every live order must pass hard risk gates, stateful daily limits, and an initial manual confirmation period.

## Non-Goals

- No web dashboard in the first version.
- No multi-asset trading.
- No autonomous LLM-created trades.
- No private key storage in source control, logs, prompts, or chat.
- No withdrawal, transfer, bridge, or spot-trading support.

## Runtime Model

The daemon runs from the terminal and wakes up on a fixed schedule. Each cycle fetches current NEAR market data, evaluates a deterministic strategy, applies risk checks, optionally sends the candidate to an LLM veto layer, and either skips, prompts for confirmation, or submits live orders through the Hyperliquid SDK.

The process persists all decisions, orders, fills, confirmations, and lockouts in SQLite so restarts do not bypass risk limits.

On startup, the daemon must inspect the connected Hyperliquid account for any existing `NEAR-USDC` position. If one exists and is not already tracked in SQLite, the bot must adopt it as an external position, record it, and manage exits without requiring operator confirmation.

## Trading Scope

- Market: Hyperliquid `NEAR-USDC` perpetual only.
- Direction: long or short.
- Style: intraday swing.
- Trade frequency: maximum one new trade per local calendar day.
- Loss rule: after one realized losing trade in a day, no more new trades that day.
- Position size: fixed 10 USD notional to start.
- Exchange market leverage: Hyperliquid currently reports `NEAR` / `NEAR-USDC` max leverage as 10x.
- Bot effective leverage cap: 2x max. The bot must never size orders above 2x effective leverage even if Hyperliquid allows a higher market leverage setting.
- Entries: hybrid execution. Try a conservative limit first, then use an aggressive limit if the signal is still valid and the conservative order times out.
- Exits: ATR-based stop-loss and take-profit, with active position monitoring.
- Holding period: target 4 to 12 hours, with mandatory flatten before the configured end-of-day cutoff.

## Strategy

The deterministic strategy supports two regimes:

1. Trend continuation: trade with confirmed strength or weakness when NEAR is trending.
2. Mean reversion: fade stretched moves only after momentum stalls and price structure confirms exhaustion.

The strategy may emit only three candidate actions: `long`, `short`, or `skip`.

Signal inputs:

- 1h and lower-timeframe candles.
- ATR for stop and target sizing.
- Recent highs and lows for invalidation context.
- Funding rate.
- Current mid price and order book spread.
- 24h volume and open interest context.

The strategy must include a clear rationale for each candidate so the operator can audit why a trade was considered.

## Data Sources

Use the configured RootAI Edge MCP server at `https://mcp.rootai.wtf/mcp` as the primary public market and context data source where it has coverage.

RootAI Edge MCP should provide:

- Hyperliquid public market metadata, summaries, mids, order books, candles, and funding.
- Crypto and macro news.
- Asset-filtered news for NEAR and major market drivers.
- Edge market signals when available.
- Binance public reference data when useful for broad market context.
- Pyth oracle prices when useful as an external reference.

Use the official Hyperliquid Python SDK for data the RootAI Edge MCP cannot retrieve or should not retrieve:

- Private account balance, margin, leverage, and fee-tier state.
- Existing account-level `NEAR-USDC` positions.
- Open orders, fills, realized PnL, and liquidation context for the connected wallet.
- Live order placement, cancellation, reduce-only exits, and position flattening.
- WebSocket-style account updates where available.

Useful optional data outside RootAI Edge MCP and Hyperliquid SDK:

- NEAR ecosystem-specific news, governance, unlocks, network incidents, and protocol announcements.
- Cross-venue NEAR spot/perp liquidity and funding from venues not covered by RootAI Edge MCP.
- Macro event calendar data for scheduled volatility events.
- Social sentiment or developer-activity data if later added as a veto-only signal.

These optional sources must never bypass deterministic strategy or risk gates. They may only inform skip/veto decisions or operator-facing rationale.

## LLM Veto

The LLM layer is pluggable. The first provider is OpenAI using `OPENAI_API_KEY` from the local environment.

The LLM may only veto a deterministic candidate. It cannot create a trade, change direction, increase size, widen stops, or bypass risk checks.

If the LLM provider is unavailable, the default behavior is configurable:

- `LLM_REQUIRED=false`: continue without veto.
- `LLM_REQUIRED=true`: skip all trades until the LLM provider works.

## Risk Gates

Every candidate must pass all gates before order placement:

- Symbol is exactly `NEAR-USDC` perp.
- Fixed notional is 10 USD unless explicitly changed in config.
- Hyperliquid reports the NEAR market max leverage as 10x.
- Bot effective leverage is at or below 2x.
- No existing open bot-managed NEAR position unless the cycle is managing exits.
- If an existing account-level `NEAR-USDC` position is found, the bot must switch into position-management mode instead of opening a new trade.
- No new trade has already been opened today.
- No realized bot-managed loss has occurred today.
- Stop-loss and take-profit are present.
- Stop distance is derived from ATR and bounded by configured minimum and maximum percentages.
- Estimated order value and margin requirements are valid for account state.
- Live trading is enabled with `LIVE_TRADING=true`.
- The operator has confirmed the trade if fewer than 5 confirmed live trades have occurred.

Any failed gate turns the candidate into a skip and records the reason.

## Secrets And Configuration

Secrets are supplied locally through `.env`, which must be gitignored.

Required live-trading variables:

- `LIVE_TRADING=true`
- `HYPERLIQUID_PRIVATE_KEY=<local-wallet-private-key>`
- `HYPERLIQUID_ACCOUNT_ADDRESS=<wallet-address>`

Optional variables:

- `OPENAI_API_KEY=<openai-api-key>`
- `LLM_PROVIDER=openai`
- `LLM_REQUIRED=false`
- `CONFIRM_FIRST_N_TRADES=5`
- `FIXED_NOTIONAL_USD=10`
- `MAX_LEVERAGE=2`
- `LOCAL_TIMEZONE=America/New_York`
- `END_OF_DAY_FLATTEN_TIME=23:30`

The program must never print the private key. Startup validation should fail if `.env` is missing in live mode or if required risk settings are invalid.

## Persistence

Use SQLite for local state.

Tables:

- `decisions`: every evaluated candidate and skip reason.
- `orders`: submitted order metadata and status.
- `trades`: opened and closed bot-managed trades.
- `daily_state`: one-trade-per-day and stop-after-loss lockouts.
- `confirmations`: manual confirmations counted toward the first 5 live trades.

State is authoritative for daily limits. The bot must not rely only on in-memory counters.

## Order Management

When a trade is opened, the daemon manages it until closed.

Management loop:

- Poll current price, open orders, fills, and position state.
- Detect and adopt any existing `NEAR-USDC` account position that was opened outside the bot or before the bot started.
- For adopted positions, infer side, size, entry price, liquidation context, and current unrealized PnL from account state.
- Attach or replace protective stop-loss and take-profit orders for adopted positions using the same ATR policy, unless safer existing reduce-only protective orders are already present.
- Maintain stop-loss and take-profit orders where supported by the SDK.
- If protective orders cannot be placed atomically, place and verify them immediately after entry.
- Close adopted or bot-opened `NEAR-USDC` positions automatically when stop-loss, take-profit, trend invalidation, end-of-day flattening, or safety failure requires it.
- Flatten before the configured end-of-day cutoff.
- Record realized PnL after close.
- If realized PnL is negative, lock the day.

## Safety Behavior

The bot should fail closed.

Examples:

- If market data fails, skip.
- If account state cannot be read, skip.
- If position state is ambiguous, stop opening new trades and print an operator action.
- If an existing `NEAR-USDC` position is detected, prioritize managing and closing that position over generating new entries.
- If live order submission fails, record the error and do not retry blindly.
- If a protective stop cannot be verified after entry, immediately attempt to flatten.

## CLI

Commands:

- `near-agent init`: create `.env.example` and initialize SQLite.
- `near-agent check`: validate config, SDK access, market data, account state, and risk settings.
- `near-agent once`: run one evaluation cycle.
- `near-agent daemon`: run continuously.
- `near-agent status`: show current state, lockouts, position, and confirmation count.

## Testing

The project should use test-first development.

Coverage targets:

- Config validation refuses unsafe live settings.
- Strategy emits valid long, short, or skip decisions.
- Risk gates block trades after one daily trade.
- Risk gates block trades after one daily realized loss.
- Confirmation gate requires the first 5 live trades to be confirmed.
- LLM veto cannot create or modify trades.
- Executor dry-run records orders without submitting.
- State survives restart.

Live order placement should be isolated behind an executor interface so most tests run without Hyperliquid credentials.

## Implementation Notes

Use the official Hyperliquid Python SDK for signing, private account state, and exchange operations to avoid custom signing mistakes. Use the configured RootAI Edge MCP server for public market and context data where it has coverage. If RootAI Edge MCP is unavailable, the bot should fail closed for new entries unless a configured SDK fallback can reproduce the required public market inputs.

The first implementation should include dry-run support even though the bot is live-capable. Dry-run exists for testing and diagnostics, not as the only mode.
