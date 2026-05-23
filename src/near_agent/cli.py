from pathlib import Path
from time import sleep

import typer

from near_agent.config import Settings
from near_agent.market_data import RootAiHttpMcpClient, RootAiMcpMarketData
from near_agent.runtime import build_daemon, run_backtest
from near_agent.state import StateStore


app = typer.Typer(help="NEAR-USDC Hyperliquid trading daemon")


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
                    "MAX_LEVERAGE=2",
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
                    "DISCORD_WEBHOOK_URL=",
                    "",
                ]
            )
        )
    StateStore(path / "near-agent.sqlite")
    typer.echo(f"initialized {path}")


@app.command()
def check(db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path")) -> None:
    settings = Settings()
    settings.validate_for_startup()
    StateStore(db)
    typer.echo("config ok")
    typer.echo("state ok")


@app.command()
def status(db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path")) -> None:
    store = StateStore(db)
    typer.echo(f"confirmations: {store.confirmation_count()}")


@app.command()
def once(
    db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path"),
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
    db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path"),
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
        result = trading_daemon.run_once(today=__import__("datetime").date.today())
        typer.echo(f"cycle {cycle}: {result}")
        if cycles is not None and cycle >= cycles:
            return
        sleep(interval_seconds)


@app.command()
def backtest(
    db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path"),
    offline: bool = typer.Option(False, help="Skip RootAI market data fetch"),
) -> None:
    settings = Settings()
    settings.validate_for_startup()
    StateStore(db)
    if offline:
        typer.echo("offline backtest requires market data")
        return
    results = run_backtest(
        settings,
        RootAiMcpMarketData(RootAiHttpMcpClient(settings.rootai_mcp_url)),
    )
    typer.echo(
        " ".join(
            [
                f"symbol={results['symbol']}",
                f"trades={results['trades']}",
                f"return={results['total_return_pct']}%",
                f"win_rate={results['win_rate_pct']}%",
                f"avg_trade={results['avg_trade_pct']}%",
            ]
        )
    )
