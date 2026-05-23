# NEAR Hyperliquid Agent

Python CLI daemon scaffold for a live-capable `NEAR-USDC` Hyperliquid perp trading agent.

## Safety Defaults

- Trades only `NEAR-USDC`.
- Starts with `LIVE_TRADING=false`.
- Uses fixed 10 USD notional by default.
- Caps bot effective leverage at 10x for NEAR-USDC.
- Requires confirmation for the first 5 live trades.
- Stops opening new trades after one bot-managed loss in a day.
- Detects existing `NEAR-USDC` positions through the account data adapter and switches to management mode.
- Flattens managed existing positions after `END_OF_DAY_FLATTEN_TIME`.
- Uses multi-timeframe EMA confirmation by default: `1h` primary and `4h` confirmation.
- Tracks ATR-derived sizing metadata while keeping the fixed-notional cap.
- Persists initial and trailing stop controls locally and checks them every daemon cycle.
- Can send Discord webhook alerts for signals, entries, exits, and errors.

## Setup

```bash
uv sync --extra dev
uv run near-agent init
uv run near-agent check
uv run near-agent once
```

For a no-network smoke check:

```bash
uv run near-agent once --offline
```

To run the daemon loop:

```bash
uv run near-agent daemon --interval-seconds 300
```

Use `--cycles 1` during setup when you want one bounded daemon cycle.

To run a simple historical strategy backtest from RootAI MCP market data:

```bash
uv run near-agent backtest
```

For live trading, create a local `.env` from `.env.example` and provide:

```bash
LIVE_TRADING=true
HYPERLIQUID_PRIVATE_KEY=<local-wallet-private-key>
HYPERLIQUID_ACCOUNT_ADDRESS=<wallet-address>
```

Never commit `.env`. The repository `.gitignore` excludes it.

## LLM Veto Provider

The veto layer supports OpenAI-compatible chat APIs. To use VeniceAI instead of OpenAI:

```bash
LLM_PROVIDER=venice
VENICE_API_KEY=<your-venice-api-key>
VENICE_BASE_URL=https://api.venice.ai/api/v1
VENICE_MODEL=llama-3.3-70b
```

Venice documents its chat completions endpoint as OpenAI-compatible at `https://api.venice.ai/api/v1/chat/completions`.

## Data Sources

The design uses the configured RootAI Edge MCP server for public market/context data:

```text
https://mcp.rootai.wtf/mcp
```

Private account state and live order placement belong behind the Hyperliquid SDK adapter, not the MCP.

## Strategy Controls

```bash
PRIMARY_TIMEFRAME=1h
CONFIRM_TIMEFRAME=4h
EMA_FAST=9
EMA_SLOW=21
ATR_PERIOD=14
VOLATILITY_TARGET_PCT=2
TRAILING_START_PCT=1
TRAILING_DISTANCE_PCT=0.5
INITIAL_STOP_PCT=2
BACKTEST_DAYS=90
DISCORD_WEBHOOK_URL=
```

## Current State

This build includes the tested config, state, multi-timeframe EMA strategy, ATR sizing metadata, trailing stop controls, backtesting, Discord notifications, risk, RootAI MCP HTTP client, LLM veto contract, dry-run executor, live Hyperliquid executor adapter, one-shot CLI runtime, and daemon loop. `LIVE_TRADING=false` records dry-run trades only; `LIVE_TRADING=true` requires Hyperliquid live dependencies, wallet settings, and confirmation while the initial confirmation window is active.
