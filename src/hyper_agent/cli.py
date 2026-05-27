import csv
import sys
from pathlib import Path
from time import perf_counter, sleep

import typer

from hyper_agent.config import Settings
from hyper_agent.market_data import RootAiHttpMcpClient, RootAiMcpMarketData
from hyper_agent.runtime import build_daemon, run_backtest, run_parameter_sweep, run_rsi_symbol_ranking
from hyper_agent.state import StateStore
from hyper_agent.sweep_env import apply_env_mapping

app = typer.Typer(help="Hyperliquid trading daemon")


@app.command()
def init(path: Path = typer.Option(Path("."), help="Directory to initialize")) -> None:
    path.mkdir(parents=True, exist_ok=True)
    env_example = path / ".env.example"
    if not env_example.exists():
        env_example.write_text(
            "\n".join(
                [
                    "LIVE_TRADING=false",
                    "HYPERLIQUID_PRIVATE_KEY=<local-wallet-private-key>",
                    "HYPERLIQUID_ACCOUNT_ADDRESS=<wallet-address>",
                    "LLM_PROVIDER=venice",
                    "LLM_REQUIRED=false",
                    "VENICE_API_KEY=<venice-api-key>",
                    "VENICE_BASE_URL=https://api.venice.ai/api/v1",
                    "VENICE_MODEL=llama-3.3-70b",
                    "OPENAI_API_KEY=<openai-api-key>",
                    "OPENAI_MODEL=gpt-4o-mini",
                    "CONFIRM_FIRST_N_TRADES=5",
                    "FIXED_NOTIONAL_USD=10",
                    "MAX_LEVERAGE=10",
                    "MAX_OPEN_POSITIONS=3",
                    "MAX_TOTAL_NOTIONAL_USD=100",
                    "LOCAL_TIMEZONE=America/New_York",
                    "END_OF_DAY_FLATTEN_TIME=23:30",
                    "ROOTAI_MCP_URL=https://mcp.rootai.wtf/mcp",
                    "PRIMARY_TIMEFRAME=1h",
                    "CONFIRM_TIMEFRAME=4h",
                    "EMA_FAST=9",
                    "EMA_SLOW=21",
                    "ATR_PERIOD=14",
                    "VOLATILITY_TARGET_PCT=2",
                    "TRAILING_START_PCT=1",
                    "TRAILING_DISTANCE_PCT=0.5",
                    "INITIAL_STOP_PCT=2",
                    "BACKTEST_DAYS=90",
                    "BACKTEST_FEE_BPS=5",
                    "BACKTEST_SLIPPAGE_BPS=10",
                    "BACKTEST_FUNDING_BPS=2",
                    "MIN_ATR_PCT=0.75",
                    "MIN_EMA_SPREAD_PCT=0.35",
                    "MAX_EXTENSION_PCT=8",
                    "DISCORD_WEBHOOK_URL=",
                    "",
                ]
            )
        )
    StateStore(path / "hyper-agent.sqlite")
    typer.echo(f"initialized {path}")


@app.command()
def check(db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path")) -> None:
    settings = Settings()
    settings.validate_for_startup()
    StateStore(db)
    typer.echo("config ok")
    typer.echo("state ok")


@app.command()
def status(db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path")) -> None:
    store = StateStore(db)
    typer.echo(f"confirmations: {store.confirmation_count()}")


@app.command()
def once(
    db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path"),
    offline: bool = typer.Option(False, help="Skip RootAI/Hyperliquid network adapters"),
) -> None:
    settings = Settings()
    settings.validate_for_startup()
    store = StateStore(db)
    daemon = build_daemon(settings, store, offline=offline)
    result = daemon.run_once(today=__import__("datetime").date.today())
    typer.echo(result)


@app.command()
def daemon(
    db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path"),
    offline: bool = typer.Option(False, help="Skip RootAI/Hyperliquid network adapters"),
    interval_seconds: int = typer.Option(300, min=0, help="Seconds to wait between cycles"),
    cycles: int | None = typer.Option(None, min=1, help="Stop after this many cycles"),
) -> None:
    settings = Settings()
    settings.validate_for_startup()
    store = StateStore(db)
    trading_daemon = build_daemon(settings, store, offline=offline)
    cycle = 0
    while True:
        cycle += 1
        started = perf_counter()
        try:
            result = trading_daemon.run_once(today=__import__("datetime").date.today())
        except Exception as exc:
            elapsed = perf_counter() - started
            typer.echo(f"cycle {cycle}: error duration_seconds={elapsed:.3f} — {exc}", err=True)
            if cycles is not None and cycle >= cycles:
                return
            sleep(interval_seconds)
            continue
        elapsed = perf_counter() - started
        typer.echo(f"cycle {cycle}: {result} duration_seconds={elapsed:.3f}")
        if cycles is not None and cycle >= cycles:
            return
        sleep(interval_seconds)


@app.command()
def backtest(
    db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path"),
    offline: bool = typer.Option(False, help="Skip RootAI market data fetch"),
) -> None:
    settings = Settings()
    settings.validate_for_startup()
    StateStore(db)
    if offline:
        typer.echo("offline backtest requires market data")
        return
    all_results = run_backtest(
        settings,
        RootAiMcpMarketData(RootAiHttpMcpClient(settings.rootai_mcp_url)),
    )
    for results in all_results:
        if "error" in results:
            typer.echo(f"symbol={results['symbol']} error={results['error']}")
        else:
            typer.echo(
                " ".join(
                    [
                        f"symbol={results['symbol']}",
                        f"trades={results['trades']}",
                        f"gross_return={results['gross_return_pct']}%",
                        f"return={results['total_return_pct']}%",
                        f"costs=${results['total_cost_usd']}",
                        f"win_rate={results['win_rate_pct']}%",
                        f"avg_trade={results['avg_trade_pct']}%",
                    ]
                )
            )


@app.command()
def sweep(
    db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path"),
    top: int = typer.Option(20, help="Number of top results to show"),
    apply: bool = typer.Option(False, "--apply", help="Write the Venice recommendation to .env"),
) -> None:
    """Parameter sweep — find best EMA/stop settings across tracked symbols."""
    settings = Settings()
    settings.validate_for_startup()
    StateStore(db)
    results = run_parameter_sweep(
        settings,
        RootAiMcpMarketData(RootAiHttpMcpClient(settings.rootai_mcp_url)),
        top_n=top,
    )
    if not results:
        typer.echo("No results")
        return
    typer.echo(f"\n{'Rank':<5} {'EMA':^9} {'MinATR':>6} {'Spread':>7} {'Stop':>5} {'Trades':>7} {'WinRate':>8} {'AvgRet':>8}")
    typer.echo("-" * 65)
    rows = []
    for i, r in enumerate(results, 1):
        line = (
            f"{i:<5} {r['ema_fast']}/{r['ema_slow']:<4} "
            f"{r['min_atr_pct']:>6.2f} {r['min_ema_spread_pct']:>7.2f} "
            f"{r['initial_stop_pct']:>5.1f} {r['total_trades']:>7} "
            f"{r['win_rate_pct']:>7.2f}% {r['avg_return_pct']:>7.4f}%"
        )
        typer.echo(line)
        rows.append(line)

    # Venice analysis + auto-apply
    if settings.venice_api_key:
        typer.echo("\nAnalyzing results with Venice...")
        try:
            import re as _re

            import httpx as _httpx
            table = "\n".join(rows[:10])
            prompt = (
                f"You are a quant analyst reviewing EMA strategy parameter sweep results "
                f"from a 90-day crypto perps backtest across {len(settings.symbols)} configured symbols.\n"
                f"Symbols: {', '.join(settings.symbols)}.\n"
                f"Columns: Rank, EMA fast/slow, MinATR%, MinSpread%, Stop%, total trades, win rate, avg return.\n\n"
                f"{table}\n\n"
                f"Pick the single best parameter set that balances win rate, trade frequency, and avg return. "
                f"Prefer combos with at least 3 trades. Write a brief analysis (under 100 words), "
                f"then output your recommendation as a JSON block like this:\n"
                f"```json\n"
                f"{{\"ema_fast\": 12, \"ema_slow\": 26, \"min_atr_pct\": 0.75, \"min_ema_spread_pct\": 0.35, \"initial_stop_pct\": 3.0}}\n"
                f"```"
            )
            resp = _httpx.post(
                f"{settings.venice_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.venice_api_key}"},
                json={"model": settings.venice_sweep_model, "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            content = resp.json()["choices"][0]["message"]["content"]
            typer.echo(f"\nVenice analysis:\n{content}")

            # Extract JSON recommendation and apply to .env
            match = _re.search(r"```json\s*(\{.*?\})\s*```", content, _re.DOTALL)
            if match:
                import json as _json
                params = _json.loads(match.group(1))
                mapping = {
                    "EMA_FAST": str(int(params["ema_fast"])),
                    "EMA_SLOW": str(int(params["ema_slow"])),
                    "MIN_ATR_PCT": str(params["min_atr_pct"]),
                    "MIN_EMA_SPREAD_PCT": str(params["min_ema_spread_pct"]),
                    "INITIAL_STOP_PCT": str(params["initial_stop_pct"]),
                }
                if not apply:
                    typer.echo("\nRecommendation not applied. Re-run with --apply to write .env:")
                    for key, val in mapping.items():
                        typer.echo(f"  {key}={val}")
                else:
                    backup_path = apply_env_mapping(Path(".env"), mapping)
                    typer.echo("\nApplied to .env:")
                    for key, val in mapping.items():
                        typer.echo(f"  {key}={val}")
                    if backup_path:
                        typer.echo(f"Backup written to {backup_path}")
                    typer.echo("\nRestart the daemon to use the new parameters.")
        except Exception as exc:
            typer.echo(f"\nVenice analysis failed: {exc}")


@app.command()
def rank_symbols(
    db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path"),
    top: int = typer.Option(5, help="Number of top symbols to keep"),
    apply: bool = typer.Option(False, "--apply", help="Write top symbols to SYMBOLS in .env"),
) -> None:
    """Rank all symbols by RSI strategy backtest performance and optionally narrow SYMBOLS in .env."""
    settings = Settings()
    settings.validate_for_startup()
    StateStore(db)
    typer.echo(f"Running RSI backtest on {len(settings.symbols)} symbols ({settings.backtest_days} days)...")
    results = run_rsi_symbol_ranking(
        settings,
        RootAiMcpMarketData(RootAiHttpMcpClient(settings.rootai_mcp_url)),
    )

    typer.echo(f"\n{'Rank':<5} {'Symbol':<15} {'Trades':>7} {'WinRate':>8} {'AvgTrade':>9} {'Return':>8}")
    typer.echo("-" * 58)
    for i, r in enumerate(results, 1):
        if "error" in r:
            typer.echo(f"{i:<5} {r['symbol']:<15} ERROR: {r['error']}")
        else:
            typer.echo(
                f"{i:<5} {r['symbol']:<15} {r['trades']:>7} "
                f"{r['win_rate_pct']:>7.1f}% {r['avg_trade_pct']:>8.3f}% {r['total_return_pct']:>7.2f}%"
            )

    valid = [r for r in results if "error" not in r]
    top_symbols = [r["symbol"] for r in valid[:top]]
    typer.echo(f"\nTop {top}: {', '.join(top_symbols)}")

    if not apply:
        typer.echo("Re-run with --apply to write these symbols to .env")
        return

    from hyper_agent.sweep_env import apply_env_mapping
    backup = apply_env_mapping(Path(".env"), {"SYMBOLS": ",".join(top_symbols)})
    typer.echo("Updated SYMBOLS in .env")
    if backup:
        typer.echo(f"Backup: {backup}")
    typer.echo("Restart the daemon to use the new symbol list.")


@app.command()
def export_journal(db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path")) -> None:
    store = StateStore(db)
    fields = [
        "trade_id",
        "created_ts",
        "submitted_live",
        "symbol",
        "side",
        "entry_px",
        "notional_usd",
        "leverage",
        "size_base",
        "stop_loss_px",
        "take_profit_px",
        "atr_pct",
        "rationale",
        "min_atr_pct",
        "min_ema_spread_pct",
        "max_extension_pct",
        "exit_px",
        "realized_pnl_usd",
        "realized_pnl_pct",
        "exit_reason",
        "highest_pnl_pct",
        "max_drawdown_pct",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    for entry in store.list_trade_journal_entries():
        writer.writerow(
            {
                "trade_id": entry.trade_id,
                "created_ts": entry.created_ts,
                "submitted_live": entry.submitted_live,
                "symbol": entry.symbol,
                "side": entry.side.value,
                "entry_px": entry.entry_px,
                "notional_usd": entry.notional_usd,
                "leverage": entry.leverage,
                "size_base": entry.size_base,
                "stop_loss_px": entry.stop_loss_px,
                "take_profit_px": entry.take_profit_px,
                "atr_pct": entry.atr_pct,
                "rationale": entry.rationale,
                "min_atr_pct": entry.min_atr_pct,
                "min_ema_spread_pct": entry.min_ema_spread_pct,
                "max_extension_pct": entry.max_extension_pct,
                "exit_px": entry.exit_px,
                "realized_pnl_usd": entry.realized_pnl_usd,
                "realized_pnl_pct": entry.realized_pnl_pct,
                "exit_reason": entry.exit_reason,
                "highest_pnl_pct": entry.highest_pnl_pct,
                "max_drawdown_pct": entry.max_drawdown_pct,
            }
        )


@app.command()
def watch(
    db: Path = typer.Option(Path("hyper-agent.sqlite"), help="SQLite database path"),
) -> None:
    """Live TUI — monitor pairs and edit the tracked list."""
    from hyper_agent.tui import WatchApp
    WatchApp(db_path=db).run()
