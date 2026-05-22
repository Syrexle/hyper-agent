# NEAR Hyperliquid Agent

Python CLI daemon scaffold for a live-capable `NEAR-USDC` Hyperliquid perp trading agent.

## Safety Defaults

- Trades only `NEAR-USDC`.
- Starts with `LIVE_TRADING=false`.
- Uses fixed 10 USD notional by default.
- Caps bot effective leverage at 2x even though Hyperliquid reports NEAR max leverage as 10x.
- Requires confirmation for the first 5 live trades.
- Stops opening new trades after one bot-managed loss in a day.
- Detects existing `NEAR-USDC` positions through the account data adapter and switches to management mode.

## Setup

```bash
uv sync --extra dev
uv run near-agent init
uv run near-agent check
uv run near-agent once
```

For live trading, create a local `.env` from `.env.example` and provide:

```bash
LIVE_TRADING=true
HYPERLIQUID_PRIVATE_KEY=<local-wallet-private-key>
HYPERLIQUID_ACCOUNT_ADDRESS=<wallet-address>
```

Never commit `.env`. The repository `.gitignore` excludes it.

## Data Sources

The design uses the configured RootAI Edge MCP server for public market/context data:

```text
https://mcp.rootai.wtf/mcp
```

Private account state and live order placement belong behind the Hyperliquid SDK adapter, not the MCP.

## Current State

This build includes the tested config, state, strategy, risk, market-data adapter shape, LLM veto contract, dry-run executor, and CLI scaffold. The live Hyperliquid executor interface is intentionally isolated so SDK signing/order placement can be wired and tested separately.
