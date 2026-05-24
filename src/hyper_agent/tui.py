from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env").exists():
            return parent
    return Path.cwd()


ROOT = _find_project_root()
_ENV_PATH = ROOT / ".env"
_DB_PATH = ROOT / "hyper-agent.sqlite"


def _load_env_symbols() -> list[str]:
    if not _ENV_PATH.exists():
        return []
    for line in _ENV_PATH.read_text().splitlines():
        if line.startswith("SYMBOLS="):
            value = line[len("SYMBOLS="):].strip()
            return [s.strip() for s in value.split(",") if s.strip()]
    return []


def _save_env_symbols(symbols: list[str]) -> None:
    content = _ENV_PATH.read_text() if _ENV_PATH.exists() else ""
    new_line = f"SYMBOLS={','.join(symbols)}"
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("SYMBOLS="):
            lines[i] = new_line
            _ENV_PATH.write_text("\n".join(lines) + "\n")
            return
    _ENV_PATH.write_text(content.rstrip() + "\n" + new_line + "\n")


def _normalize_symbol(raw: str) -> str:
    raw = raw.strip().upper()
    if not raw.endswith("-USDC"):
        raw = f"{raw}-USDC"
    return raw


def _parse_latest_scan(db_path: Path) -> tuple[dict[str, dict], str]:
    if not db_path.exists():
        return {}, "no db"
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT rationale, created_ts FROM decisions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        con.close()
    except Exception:
        return {}, "db error"
    if not row:
        return {}, "no data yet"
    rationale, ts = row
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S UTC")
    result: dict[str, dict] = {}
    for pair_text in rationale.split(" || "):
        sym_m = re.match(r"^([^:]+):", pair_text)
        if not sym_m:
            continue
        symbol = sym_m.group(1).strip()
        rsi_m = re.search(r"RSI (\d+\.\d+)", pair_text)
        fund_m = re.search(r"rate (-?[\d.]+)%", pair_text)
        result[symbol] = {
            "rsi": float(rsi_m.group(1)) if rsi_m else None,
            "funding": float(fund_m.group(1)) if fund_m else None,
            "unavailable": "data unavailable" in pair_text.lower(),
        }
    return result, dt


class AddPairModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    CSS = """
    AddPairModal { align: center middle; }
    #dialog {
        background: $surface;
        border: solid $accent;
        padding: 1 2;
        width: 48;
        height: auto;
    }
    #dialog-label { margin-bottom: 1; text-style: bold; }
    #dialog-hint { color: $text-muted; margin-bottom: 1; }
    #btn-row { margin-top: 1; }
    #btn-add { margin-right: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Add Pair", id="dialog-label")
            yield Label("Enter coin or full symbol (e.g. SOL or SOL-USDC)", id="dialog-hint")
            yield Input(placeholder="BTC-USDC", id="pair-input")
            with Center(id="btn-row"):
                yield Button("Add", variant="primary", id="btn-add")
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self) -> None:
        self._submit()

    def _submit(self) -> None:
        raw = self.query_one("#pair-input", Input).value.strip()
        self.dismiss(_normalize_symbol(raw) if raw else None)


class WatchApp(App):
    TITLE = "Agent Scanner"
    SUB_TITLE = "Hyperliquid Perps"

    CSS = """
    Screen { background: $surface; }
    DataTable { height: 1fr; }
    #status { height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        Binding("a", "add_pair", "Add pair", show=True),
        Binding("d", "remove_pair", "Remove pair", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, db_path: Path = _DB_PATH, env_path: Path = _ENV_PATH):
        super().__init__()
        self._db_path = db_path
        self._env_path = env_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Pair", "RSI", "Funding /8h", "RSI Status", "Tracked")
        self._do_refresh()
        self.set_interval(30, self._do_refresh)

    def _do_refresh(self) -> None:
        symbols = _load_env_symbols()
        scan, last_ts = _parse_latest_scan(self._db_path)

        table = self.query_one(DataTable)
        table.clear()

        # Show all scanned pairs, then any tracked-only ones not in scan
        ordered = list(scan.keys()) + [s for s in symbols if s not in scan]

        for sym in ordered:
            data = scan.get(sym, {})
            rsi: float | None = data.get("rsi")
            funding: float | None = data.get("funding")
            unavailable: bool = data.get("unavailable", False)
            tracked = "✓" if sym in symbols else ""

            if unavailable or (rsi is None and sym in scan):
                rsi_str, fund_str, status = "N/A", "N/A", "unavailable"
            elif rsi is None:
                rsi_str, fund_str, status = "—", "—", "not scanned"
            else:
                rsi_str = f"{rsi:.1f}"
                fund_str = f"{funding:+.4f}%" if funding is not None else "—"
                if rsi < 30:
                    status = "OVERSOLD  ▲ LONG?"
                elif rsi > 70:
                    status = "OVERBOUGHT ▼ SHORT?"
                else:
                    status = "neutral"

            table.add_row(sym, rsi_str, fund_str, status, tracked, key=sym)

        n = len(symbols)
        self.query_one("#status", Static).update(
            f" Last scan: {last_ts}  |  {n} pairs tracked  |  [a] add  [d] remove selected  [r] refresh"
        )

    def action_refresh(self) -> None:
        self._do_refresh()
        self.notify("Refreshed", timeout=2)

    def action_add_pair(self) -> None:
        def on_result(pair: str | None) -> None:
            if not pair:
                return
            symbols = _load_env_symbols()
            if pair in symbols:
                self.notify(f"{pair} is already tracked", severity="warning", timeout=3)
                return
            symbols.append(pair)
            _save_env_symbols(symbols)
            self._do_refresh()
            self.notify(f"Added {pair} — restart daemon to activate", timeout=4)

        self.push_screen(AddPairModal(), on_result)

    def action_remove_pair(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        try:
            row_data = table.get_row_at(table.cursor_row)
        except Exception:
            return
        sym = str(row_data[0])
        symbols = _load_env_symbols()
        if sym not in symbols:
            self.notify(f"{sym} is not in tracked list", severity="warning", timeout=3)
            return
        symbols.remove(sym)
        _save_env_symbols(symbols)
        self._do_refresh()
        self.notify(f"Removed {sym} — restart daemon to activate", timeout=4)
