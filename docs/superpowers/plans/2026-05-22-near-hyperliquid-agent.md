# NEAR Hyperliquid Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested Python CLI daemon that can evaluate, gate, and manage live-capable `NEAR-USDC` Hyperliquid perp trades with RootAI Edge MCP public data and Hyperliquid SDK account/execution integration.

**Architecture:** The first build is a small Python package with isolated modules for config, state, market data, strategy, risk, LLM veto, execution, and CLI orchestration. Public market/context data is read through the configured RootAI Edge MCP where available; private account state and live order execution are behind a Hyperliquid SDK adapter. Tests use fakes for external APIs and verify risk gates before live execution wiring.

**Tech Stack:** Python 3.11+, `pytest`, `typer`, `pydantic-settings`, `python-dotenv`, SQLite stdlib, official Hyperliquid Python SDK, OpenAI SDK optional.

---

## File Structure

- `pyproject.toml`: package metadata, dependencies, CLI entrypoint, pytest config.
- `.gitignore`: excludes `.env`, local databases, caches, worktrees.
- `.env.example`: safe local configuration template with no secrets.
- `src/near_agent/config.py`: typed settings and startup validation.
- `src/near_agent/models.py`: dataclasses/enums shared across modules.
- `src/near_agent/state.py`: SQLite schema and persistence helpers.
- `src/near_agent/market_data.py`: RootAI Edge MCP and Hyperliquid SDK public/private data interfaces.
- `src/near_agent/strategy.py`: deterministic trend/mean-reversion candidate generation.
- `src/near_agent/risk.py`: daily lockout, one-trade-per-day, existing-position, leverage, stop/target gates.
- `src/near_agent/llm_veto.py`: pluggable veto provider with OpenAI implementation and disabled fallback.
- `src/near_agent/executor.py`: dry-run executor and Hyperliquid live executor interface.
- `src/near_agent/daemon.py`: evaluation loop, existing-position adoption, position management.
- `src/near_agent/cli.py`: `near-agent` commands.
- `tests/`: focused unit tests for each behavior.

## Task 1: Project Scaffold And Config

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/near_agent/__init__.py`
- Create: `src/near_agent/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py` with tests that prove live mode refuses missing secrets, defaults match the spec, and effective leverage cannot exceed 2.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_config.py -q`
Expected: import failure for missing `near_agent.config`.

- [ ] **Step 3: Implement package scaffold and config**

Create package metadata, safe ignores, `.env.example`, and `Settings.validate_for_startup()` that enforces:

- `LIVE_TRADING=true` requires `HYPERLIQUID_PRIVATE_KEY` and `HYPERLIQUID_ACCOUNT_ADDRESS`.
- `MAX_LEVERAGE <= 2`.
- `FIXED_NOTIONAL_USD > 0`.
- `CONFIRM_FIRST_N_TRADES >= 0`.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_config.py -q`
Expected: all config tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add project scaffold and config validation`

## Task 2: Domain Models And SQLite State

**Files:**
- Create: `src/near_agent/models.py`
- Create: `src/near_agent/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write failing state tests**

Tests must prove SQLite initializes required tables, persists decisions, counts confirmations, records daily trade/loss state, and survives reopening the database.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_state.py -q`
Expected: import failure for missing state/model code.

- [ ] **Step 3: Implement models and state store**

Add `Side`, `DecisionAction`, `TradeStatus`, `Decision`, `Trade`, `PositionSnapshot`, and `StateStore` with schema creation and focused methods for daily lockouts and confirmations.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_state.py -q`
Expected: all state tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add persistent trading state`

## Task 3: Strategy And ATR Signals

**Files:**
- Create: `src/near_agent/strategy.py`
- Test: `tests/test_strategy.py`

- [ ] **Step 1: Write failing strategy tests**

Tests must prove ATR calculation works, strong uptrend produces a long candidate, stretched weakening move produces a short candidate, and insufficient data returns skip.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_strategy.py -q`
Expected: import failure for missing strategy.

- [ ] **Step 3: Implement deterministic strategy**

Implement a conservative rule engine:

- Use 1h candles.
- Calculate ATR over 14 periods.
- Long when closes are above a short moving average, recent return is positive, and candle closes near range highs.
- Short when price is stretched above moving average and latest candles show lower momentum.
- Otherwise skip with rationale.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_strategy.py -q`
Expected: all strategy tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add near strategy engine`

## Task 4: Risk Gates

**Files:**
- Create: `src/near_agent/risk.py`
- Test: `tests/test_risk.py`

- [ ] **Step 1: Write failing risk tests**

Tests must prove risk blocks non-`NEAR-USDC`, second trade in same day, trading after a daily loss, effective leverage above 2, missing stop/target, and new entries while an existing position is active.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_risk.py -q`
Expected: import failure for missing risk module.

- [ ] **Step 3: Implement risk engine**

Implement `RiskEngine.evaluate_candidate()` returning allowed/blocked with reasons. Include stop/target derivation from ATR, fixed 10 USD notional, 2x effective leverage cap, one-trade-per-day, and stop-after-one-loss.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_risk.py -q`
Expected: all risk tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add hard risk gates`

## Task 5: Market Data Adapters

**Files:**
- Create: `src/near_agent/market_data.py`
- Test: `tests/test_market_data.py`

- [ ] **Step 1: Write failing market data tests**

Tests must prove the RootAI adapter builds MCP calls for mids, candles, funding, and summaries, maps Hyperliquid `NEAR` to internal `NEAR-USDC`, and fails closed when required public data is missing.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_market_data.py -q`
Expected: import failure for missing market data module.

- [ ] **Step 3: Implement adapters**

Implement interface classes:

- `PublicMarketData` protocol.
- `RootAiMcpMarketData` for public market data.
- `HyperliquidAccountData` protocol for private account/position data.
- Fake-friendly response normalization.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_market_data.py -q`
Expected: all market data tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add market data adapters`

## Task 6: LLM Veto

**Files:**
- Create: `src/near_agent/llm_veto.py`
- Test: `tests/test_llm_veto.py`

- [ ] **Step 1: Write failing veto tests**

Tests must prove disabled veto approves candidates, OpenAI veto can block but cannot change trade fields, and provider errors block only when `LLM_REQUIRED=true`.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_llm_veto.py -q`
Expected: import failure for missing veto module.

- [ ] **Step 3: Implement veto provider**

Implement `VetoProvider`, `DisabledVetoProvider`, and `OpenAiVetoProvider` with a strict JSON response contract: `{"veto": boolean, "reason": string}`.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_llm_veto.py -q`
Expected: all veto tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add llm veto layer`

## Task 7: Executor And Position Management

**Files:**
- Create: `src/near_agent/executor.py`
- Create: `src/near_agent/daemon.py`
- Test: `tests/test_executor.py`
- Test: `tests/test_daemon.py`

- [ ] **Step 1: Write failing executor and daemon tests**

Tests must prove dry-run executor records without live submission, first five live trades require confirmation, existing `NEAR-USDC` positions are adopted, adopted positions can be closed without confirmation, and ambiguous position state blocks new entries.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_executor.py tests/test_daemon.py -q`
Expected: import failures for missing executor/daemon.

- [ ] **Step 3: Implement executor and daemon orchestration**

Implement:

- `DryRunExecutor`.
- `HyperliquidLiveExecutor` interface shell with SDK import isolated.
- `TradingDaemon.run_once()`.
- Existing-position adoption and management mode.
- Confirmation prompt abstraction for first 5 live entries.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_executor.py tests/test_daemon.py -q`
Expected: all executor and daemon tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add executor and daemon orchestration`

## Task 8: CLI And End-To-End Checks

**Files:**
- Create: `src/near_agent/cli.py`
- Test: `tests/test_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI tests**

Tests must prove `near-agent init`, `check`, `status`, and `once` invoke the expected services with fake dependencies and do not require secrets in dry-run mode.

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_cli.py -q`
Expected: import failure for missing CLI.

- [ ] **Step 3: Implement CLI and README**

Implement Typer commands:

- `near-agent init`
- `near-agent check`
- `near-agent status`
- `near-agent once`
- `near-agent daemon`

Document local setup, `.env`, dry-run, live-trading warnings, and RootAI MCP dependency.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_cli.py -q`
Expected: all CLI tests pass.

- [ ] **Step 5: Run full verification and commit**

Run: `pytest -q`
Expected: all tests pass.

Commit message: `feat: add near agent cli`

## Self-Review

- Spec coverage: covered config, RootAI Edge MCP public data, Hyperliquid SDK private/execution data, deterministic strategy, LLM veto, risk gates, existing-position adoption, CLI, persistence, and tests.
- Placeholder scan: no placeholder markers or unspecified implementation tasks remain.
- Type consistency: market is represented internally as `NEAR-USDC`; Hyperliquid public coin symbol `NEAR` is normalized in market data adapters.
