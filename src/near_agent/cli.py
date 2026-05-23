from pathlib import Path
from time import sleep

import typer

from near_agent.config import Settings
from near_agent.runtime import build_daemon
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
