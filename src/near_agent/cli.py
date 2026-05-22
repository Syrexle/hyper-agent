from pathlib import Path

import typer

from near_agent.config import Settings
from near_agent.daemon import TradingDaemon
from near_agent.executor import DryRunExecutor
from near_agent.state import StateStore


app = typer.Typer(help="NEAR-USDC Hyperliquid trading daemon")


class NoAccountData:
    def existing_position(self, symbol: str):
        return None


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
                    "OPENAI_API_KEY=<openai-api-key>",
                    "LLM_PROVIDER=openai",
                    "LLM_REQUIRED=false",
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
def once(db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path")) -> None:
    settings = Settings()
    settings.validate_for_startup()
    store = StateStore(db)
    daemon = TradingDaemon(
        settings=settings,
        state=store,
        account_data=NoAccountData(),
        executor=DryRunExecutor(store),
    )
    result = daemon.run_once(today=__import__("datetime").date.today())
    typer.echo(result)


@app.command()
def daemon(db: Path = typer.Option(Path("near-agent.sqlite"), help="SQLite database path")) -> None:
    typer.echo("daemon loop is not started in this scaffold; use near-agent once for a single cycle")
