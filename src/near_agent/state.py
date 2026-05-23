from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from near_agent.models import Decision, DecisionAction, Side, Trade, TradeJournalEntry, TradeStatus
from near_agent.trailing import PositionControls


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    allowed INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_ts REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    created_ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notional_usd REAL NOT NULL,
                    entry_px REAL NOT NULL,
                    realized_pnl_usd REAL
                );

                CREATE TABLE IF NOT EXISTS daily_state (
                    trade_date TEXT PRIMARY KEY,
                    trade_opened INTEGER NOT NULL DEFAULT 0,
                    loss_realized INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS confirmations (
                    trade_id TEXT PRIMARY KEY,
                    confirmed_ts REAL NOT NULL DEFAULT (strftime('%s', 'now'))
                );

                CREATE TABLE IF NOT EXISTS position_controls (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_px REAL NOT NULL,
                    initial_stop_px REAL NOT NULL,
                    trailing_stop_px REAL,
                    highest_pnl_pct REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS trade_journal (
                    trade_id TEXT PRIMARY KEY,
                    created_ts REAL NOT NULL,
                    submitted_live INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_px REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    leverage REAL NOT NULL,
                    size_base REAL NOT NULL,
                    stop_loss_px REAL NOT NULL,
                    take_profit_px REAL NOT NULL,
                    atr_pct REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    min_atr_pct REAL NOT NULL,
                    min_ema_spread_pct REAL NOT NULL,
                    max_extension_pct REAL NOT NULL,
                    exit_px REAL,
                    realized_pnl_usd REAL,
                    realized_pnl_pct REAL,
                    exit_reason TEXT,
                    highest_pnl_pct REAL,
                    max_drawdown_pct REAL
                );
                """
            )

    def table_names(self) -> set[str]:
        with self._connect() as con:
            rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {row["name"] for row in rows}

    def record_decision(self, decision: Decision) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO decisions (created_ts, symbol, action, rationale, allowed)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    decision.created_ts,
                    decision.symbol,
                    decision.action.value,
                    decision.rationale,
                    int(decision.allowed),
                ),
            )

    def list_decisions(self) -> list[Decision]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT created_ts, symbol, action, rationale, allowed FROM decisions ORDER BY id"
            ).fetchall()
        return [
            Decision(
                created_ts=row["created_ts"],
                symbol=row["symbol"],
                action=DecisionAction(row["action"]),
                rationale=row["rationale"],
                allowed=bool(row["allowed"]),
            )
            for row in rows
        ]

    def record_confirmation(self, trade_id: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO confirmations (trade_id) VALUES (?)",
                (trade_id,),
            )

    def confirmation_count(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT COUNT(*) AS count FROM confirmations").fetchone()
        return int(row["count"])

    def mark_trade_opened(self, trade_date: date) -> None:
        self._upsert_daily_state(trade_date, trade_opened=True)

    def mark_loss(self, trade_date: date) -> None:
        self._upsert_daily_state(trade_date, loss_realized=True)

    def has_trade_on(self, trade_date: date) -> bool:
        row = self._daily_row(trade_date)
        return bool(row and row["trade_opened"])

    def has_loss_on(self, trade_date: date) -> bool:
        row = self._daily_row(trade_date)
        return bool(row and row["loss_realized"])

    def _daily_row(self, trade_date: date) -> sqlite3.Row | None:
        with self._connect() as con:
            return con.execute(
                "SELECT trade_opened, loss_realized FROM daily_state WHERE trade_date = ?",
                (trade_date.isoformat(),),
            ).fetchone()

    def _upsert_daily_state(
        self,
        trade_date: date,
        *,
        trade_opened: bool = False,
        loss_realized: bool = False,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO daily_state (trade_date, trade_opened, loss_realized)
                VALUES (?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    trade_opened = MAX(trade_opened, excluded.trade_opened),
                    loss_realized = MAX(loss_realized, excluded.loss_realized)
                """,
                (trade_date.isoformat(), int(trade_opened), int(loss_realized)),
            )

    def upsert_trade(self, trade: Trade) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO trades (
                    trade_id, created_ts, symbol, side, status, notional_usd, entry_px, realized_pnl_usd
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    status = excluded.status,
                    notional_usd = excluded.notional_usd,
                    entry_px = excluded.entry_px,
                    realized_pnl_usd = excluded.realized_pnl_usd
                """,
                (
                    trade.trade_id,
                    trade.created_ts,
                    trade.symbol,
                    trade.side.value,
                    trade.status.value,
                    trade.notional_usd,
                    trade.entry_px,
                    trade.realized_pnl_usd,
                ),
            )

    def get_trade(self, trade_id: str) -> Trade | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT trade_id, created_ts, symbol, side, status, notional_usd, entry_px, realized_pnl_usd
                FROM trades
                WHERE trade_id = ?
                """,
                (trade_id,),
            ).fetchone()
        if row is None:
            return None
        return Trade(
            trade_id=row["trade_id"],
            created_ts=row["created_ts"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            status=TradeStatus(row["status"]),
            notional_usd=row["notional_usd"],
            entry_px=row["entry_px"],
            realized_pnl_usd=row["realized_pnl_usd"],
        )

    def upsert_position_controls(self, controls: PositionControls) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO position_controls (
                    symbol, side, entry_px, initial_stop_px, trailing_stop_px, highest_pnl_pct
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    side = excluded.side,
                    entry_px = excluded.entry_px,
                    initial_stop_px = excluded.initial_stop_px,
                    trailing_stop_px = excluded.trailing_stop_px,
                    highest_pnl_pct = excluded.highest_pnl_pct
                """,
                (
                    controls.symbol,
                    controls.side.value,
                    controls.entry_px,
                    controls.initial_stop_px,
                    controls.trailing_stop_px,
                    controls.highest_pnl_pct,
                ),
            )

    def get_position_controls(self, symbol: str) -> PositionControls | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT symbol, side, entry_px, initial_stop_px, trailing_stop_px, highest_pnl_pct
                FROM position_controls
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        return PositionControls(
            symbol=row["symbol"],
            side=Side(row["side"]),
            entry_px=row["entry_px"],
            initial_stop_px=row["initial_stop_px"],
            trailing_stop_px=row["trailing_stop_px"],
            highest_pnl_pct=row["highest_pnl_pct"],
        )

    def clear_position_controls(self, symbol: str) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM position_controls WHERE symbol = ?", (symbol,))

    def record_trade_journal_entry(self, entry: TradeJournalEntry) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO trade_journal (
                    trade_id, created_ts, submitted_live, symbol, side, entry_px, notional_usd,
                    leverage, size_base, stop_loss_px, take_profit_px, atr_pct, rationale,
                    min_atr_pct, min_ema_spread_pct, max_extension_pct, exit_px,
                    realized_pnl_usd, realized_pnl_pct, exit_reason, highest_pnl_pct,
                    max_drawdown_pct
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    submitted_live = excluded.submitted_live,
                    entry_px = excluded.entry_px,
                    notional_usd = excluded.notional_usd,
                    leverage = excluded.leverage,
                    size_base = excluded.size_base,
                    stop_loss_px = excluded.stop_loss_px,
                    take_profit_px = excluded.take_profit_px,
                    atr_pct = excluded.atr_pct,
                    rationale = excluded.rationale,
                    min_atr_pct = excluded.min_atr_pct,
                    min_ema_spread_pct = excluded.min_ema_spread_pct,
                    max_extension_pct = excluded.max_extension_pct,
                    exit_px = excluded.exit_px,
                    realized_pnl_usd = excluded.realized_pnl_usd,
                    realized_pnl_pct = excluded.realized_pnl_pct,
                    exit_reason = excluded.exit_reason,
                    highest_pnl_pct = excluded.highest_pnl_pct,
                    max_drawdown_pct = excluded.max_drawdown_pct
                """,
                (
                    entry.trade_id,
                    entry.created_ts,
                    int(entry.submitted_live),
                    entry.symbol,
                    entry.side.value,
                    entry.entry_px,
                    entry.notional_usd,
                    entry.leverage,
                    entry.size_base,
                    entry.stop_loss_px,
                    entry.take_profit_px,
                    entry.atr_pct,
                    entry.rationale,
                    entry.min_atr_pct,
                    entry.min_ema_spread_pct,
                    entry.max_extension_pct,
                    entry.exit_px,
                    entry.realized_pnl_usd,
                    entry.realized_pnl_pct,
                    entry.exit_reason,
                    entry.highest_pnl_pct,
                    entry.max_drawdown_pct,
                ),
            )

    def list_trade_journal_entries(self) -> list[TradeJournalEntry]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT
                    trade_id, created_ts, submitted_live, symbol, side, entry_px, notional_usd,
                    leverage, size_base, stop_loss_px, take_profit_px, atr_pct, rationale,
                    min_atr_pct, min_ema_spread_pct, max_extension_pct, exit_px,
                    realized_pnl_usd, realized_pnl_pct, exit_reason, highest_pnl_pct,
                    max_drawdown_pct
                FROM trade_journal
                ORDER BY created_ts, trade_id
                """
            ).fetchall()
        return [
            TradeJournalEntry(
                trade_id=row["trade_id"],
                created_ts=row["created_ts"],
                submitted_live=bool(row["submitted_live"]),
                symbol=row["symbol"],
                side=Side(row["side"]),
                entry_px=row["entry_px"],
                notional_usd=row["notional_usd"],
                leverage=row["leverage"],
                size_base=row["size_base"],
                stop_loss_px=row["stop_loss_px"],
                take_profit_px=row["take_profit_px"],
                atr_pct=row["atr_pct"],
                rationale=row["rationale"],
                min_atr_pct=row["min_atr_pct"],
                min_ema_spread_pct=row["min_ema_spread_pct"],
                max_extension_pct=row["max_extension_pct"],
                exit_px=row["exit_px"],
                realized_pnl_usd=row["realized_pnl_usd"],
                realized_pnl_pct=row["realized_pnl_pct"],
                exit_reason=row["exit_reason"],
                highest_pnl_pct=row["highest_pnl_pct"],
                max_drawdown_pct=row["max_drawdown_pct"],
            )
            for row in rows
        ]
