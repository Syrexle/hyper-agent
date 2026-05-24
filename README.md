# Hyper Agent

Python CLI daemon for live automated trading on Hyperliquid perpetual futures. Scans multiple pairs, generates signals from a composite strategy, manages positions with trailing stops, and sends Discord notifications.

## What It Does

- Scans a configurable list of perp pairs every cycle (default 5 min)
- Generates trade signals using three stacked strategies: multi-timeframe EMA crossover, RSI extremes, and funding rate sentiment
- Filters signals through a fear/greed gate and edge signal anomaly check (via RootAI MCP)
- Manages open positions with a trailing stop and a native exchange stop loss order
- Sends Discord notifications for signals, entries, exits, and errors
- Runs a parameter sweep to find optimal EMA settings and auto-applies them via Venice AI analysis
- Exports a full trade journal as CSV

## Daily Risk Rules

- **Loss lock** — if any trade closes at a loss, no new positions open for the rest of the day
- **Win cap** — after 3 profitable trades in a day, no more positions (no forced quota — the bot only trades when it sees a valid signal)
- No single-trade-per-day limit — the bot can open multiple positions as long as the daily rules above are not triggered

## Stop Loss

Every opened position places a **native stop loss order on Hyperliquid** at entry, so the exchange enforces it even if the daemon is offline. The daemon also runs a software trailing stop as a secondary layer.

## Setup

```bash
pip install -e ".[live]"
hyper-agent init
hyper-agent check
hyper-agent once
```

For a no-network smoke check:

```bash
hyper-agent once --offline
```

To run the daemon loop (scans every 5 minutes):

```bash
hyper-agent daemon --interval-seconds 300
```

## Commands

| Command | Description |
|---|---|
| `hyper-agent init` | Initialize `.env.example` and SQLite database |
| `hyper-agent check` | Validate config and database |
| `hyper-agent once` | Run a single scan cycle |
| `hyper-agent daemon` | Run continuous scan loop |
| `hyper-agent backtest` | Backtest EMA strategy across all tracked symbols |
| `hyper-agent sweep` | Parameter sweep — finds best EMA/stop settings, analyzes with Venice, auto-applies results |
| `hyper-agent watch` | Live TUI — monitor pairs and edit the tracked list |
| `hyper-agent status` | Show confirmation count |
| `hyper-agent export-journal` | Export trade journal as CSV |

## Live Trading Setup

Create a `.env` file (copy from `.env.example`) and fill in:

```bash
LIVE_TRADING=true
HYPERLIQUID_PRIVATE_KEY=<local-wallet-private-key>
HYPERLIQUID_ACCOUNT_ADDRESS=<wallet-address>
CONFIRM_FIRST_N_TRADES=0
```

Never commit `.env`. The repository `.gitignore` excludes it.

## Tracked Symbols

Configure which pairs to scan (comma-separated):

```bash
SYMBOLS=TON-USDC,ENA-USDC,JUP-USDC,BNB-USDC,NEAR-USDC
```

Edit live using the `hyper-agent watch` TUI (press `a` to add, `d` to remove).

## Strategy

Three strategies run in a composite — first non-skip wins:

1. **Multi-timeframe EMA** — crossover on primary timeframe (1h) confirmed by higher timeframe trend (4h), filtered by ATR, EMA spread, and price extension
2. **RSI Extremes** — fires when RSI drops below oversold (30) or rises above overbought (70)
3. **Funding Rate Sentiment** — contrarian signal when funding rate exceeds threshold (overleveraged long/short)

Additional filters applied after a signal fires:

- **Fear & Greed gate** — blocks LONG when score < 20 (extreme fear), blocks SHORT when score > 80 (extreme greed)
- **Edge signal filter** — skips trade if a BIG_MOVE or FAST_MOVE anomaly contradicts the direction

## Strategy Controls

```bash
PRIMARY_TIMEFRAME=1h
CONFIRM_TIMEFRAME=4h
EMA_FAST=12
EMA_SLOW=26
ATR_PERIOD=14
TRAILING_START_PCT=8
TRAILING_DISTANCE_PCT=0.5
INITIAL_STOP_PCT=2.0
MIN_ATR_PCT=0.75
MIN_EMA_SPREAD_PCT=0.2
MAX_EXTENSION_PCT=8
RSI_PERIOD=14
RSI_OVERBOUGHT=70
RSI_OVERSOLD=30
FUNDING_RATE_THRESHOLD=0.001
```

## Position Sizing

```bash
FIXED_NOTIONAL_USD=50   # position value (margin × leverage)
MAX_LEVERAGE=10          # $5 margin × 10x = $50 position
```

## Backtest & Parameter Sweep

Backtest runs across all tracked symbols and reports per-symbol results:

```bash
hyper-agent backtest
```

The sweep tests 1600+ EMA/filter combinations in-memory (candles fetched once), then sends the top results to Venice AI (`qwen3-235b-a22b-thinking-2507`) for analysis and automatically writes the recommended parameters to `.env`:

```bash
hyper-agent sweep
```

## LLM Veto

Every trade signal is reviewed by an LLM before execution. Two Venice models are used:

| Role | Model |
|---|---|
| Trade veto (real-time) | `deepseek-v4-flash` |
| Sweep analysis (parameter optimization) | `qwen3-235b-a22b-thinking-2507` |

```bash
LLM_PROVIDER=venice
LLM_REQUIRED=false
VENICE_API_KEY=<your-venice-api-key>
VENICE_BASE_URL=https://api.venice.ai/api/v1
VENICE_MODEL=deepseek-v4-flash
VENICE_SWEEP_MODEL=qwen3-235b-a22b-thinking-2507
```

## Notifications

```bash
DISCORD_WEBHOOK_URL=<your-webhook-url>
```

Sends alerts for: signal detected, position opened, position closed (with PnL), errors.

## Data Sources

- **RootAI Edge MCP** (`https://mcp.rootai.wtf/mcp`) — candles, funding rates, fear/greed index, edge signals
- **Hyperliquid SDK** — account state, live order placement, position management

## Package

```
src/hyper_agent/   ← main package
tests/             ← test suite
pyproject.toml     ← entry point: hyper-agent = "hyper_agent.cli:app"
```
