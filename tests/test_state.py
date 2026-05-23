from datetime import date

from near_agent.models import Decision, DecisionAction, Side, Trade, TradeJournalEntry, TradeStatus
from near_agent.state import StateStore
from near_agent.trailing import PositionControls


def test_initializes_required_tables(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")

    tables = store.table_names()

    assert {"decisions", "orders", "trades", "daily_state", "confirmations", "trade_journal"} <= tables


def test_persists_decisions_across_reopen(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    store = StateStore(db_path)
    store.record_decision(
        Decision(
            symbol="NEAR-USDC",
            action=DecisionAction.LONG,
            rationale="trend confirmation",
            allowed=True,
        )
    )

    reopened = StateStore(db_path)

    decisions = reopened.list_decisions()
    assert len(decisions) == 1
    assert decisions[0].symbol == "NEAR-USDC"
    assert decisions[0].action == DecisionAction.LONG
    assert decisions[0].rationale == "trend confirmation"


def test_confirmation_count_survives_restart(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    store = StateStore(db_path)
    store.record_confirmation("trade-1")
    store.record_confirmation("trade-2")

    reopened = StateStore(db_path)

    assert reopened.confirmation_count() == 2


def test_daily_state_tracks_trade_and_loss(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    today = date(2026, 5, 22)

    assert store.has_trade_on(today) is False
    assert store.has_loss_on(today) is False

    store.mark_trade_opened(today)
    store.mark_loss(today)

    assert store.has_trade_on(today) is True
    assert store.has_loss_on(today) is True


def test_records_open_and_closed_trade(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    trade = Trade(
        trade_id="trade-1",
        symbol="NEAR-USDC",
        side=Side.LONG,
        status=TradeStatus.OPEN,
        notional_usd=10,
        entry_px=2.1,
    )

    store.upsert_trade(trade)
    trade.status = TradeStatus.CLOSED
    trade.realized_pnl_usd = -0.25
    store.upsert_trade(trade)

    loaded = store.get_trade("trade-1")
    assert loaded is not None
    assert loaded.status == TradeStatus.CLOSED
    assert loaded.realized_pnl_usd == -0.25


def test_persists_position_controls_for_trailing_stops(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    controls = PositionControls(
        symbol="NEAR-USDC",
        side=Side.LONG,
        entry_px=2.0,
        initial_stop_px=1.94,
        trailing_stop_px=2.03,
        highest_pnl_pct=2.5,
        max_drawdown_pct=-1.25,
    )

    store.upsert_position_controls(controls)

    loaded = store.get_position_controls("NEAR-USDC")
    assert loaded == controls


def test_records_trade_journal_entry_for_model_training(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    entry = TradeJournalEntry(
        trade_id="trade-1",
        submitted_live=True,
        symbol="NEAR-USDC",
        side=Side.LONG,
        entry_px=2.25,
        notional_usd=10,
        leverage=10,
        size_base=4.44444444,
        stop_loss_px=2.1,
        take_profit_px=2.6,
        atr_pct=1.2,
        rationale="multi-timeframe ema long",
        min_atr_pct=0.75,
        min_ema_spread_pct=0.35,
        max_extension_pct=8,
    )

    store.record_trade_journal_entry(entry)

    loaded = store.list_trade_journal_entries()
    assert loaded == [entry]


def test_updates_open_trade_journal_entry_on_close(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.upsert_trade(
        Trade(
            trade_id="trade-1",
            symbol="NEAR-USDC",
            side=Side.LONG,
            status=TradeStatus.OPEN,
            notional_usd=10,
            entry_px=2.0,
        )
    )
    store.record_trade_journal_entry(
        TradeJournalEntry(
            trade_id="trade-1",
            submitted_live=True,
            symbol="NEAR-USDC",
            side=Side.LONG,
            entry_px=2.0,
            notional_usd=10,
            leverage=10,
            size_base=5,
            stop_loss_px=1.9,
            take_profit_px=2.3,
            atr_pct=1.2,
            rationale="multi-timeframe ema long",
            min_atr_pct=0.75,
            min_ema_spread_pct=0.35,
            max_extension_pct=8,
        )
    )

    updated = store.close_open_trade_journal_entry(
        symbol="NEAR-USDC",
        exit_px=2.1,
        exit_reason="trailing stop",
        highest_pnl_pct=7.5,
        max_drawdown_pct=-1.5,
    )

    assert updated is not None
    assert updated.realized_pnl_usd == 0.5
    assert updated.realized_pnl_pct == 5.0
    assert updated.exit_reason == "trailing stop"
    assert updated.highest_pnl_pct == 7.5
    assert updated.max_drawdown_pct == -1.5
    trade = store.get_trade("trade-1")
    assert trade is not None
    assert trade.status == TradeStatus.CLOSED
    assert trade.realized_pnl_usd == 0.5
