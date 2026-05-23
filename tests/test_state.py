from datetime import date

from near_agent.models import Decision, DecisionAction, Side, Trade, TradeStatus
from near_agent.state import StateStore
from near_agent.trailing import PositionControls


def test_initializes_required_tables(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")

    tables = store.table_names()

    assert {"decisions", "orders", "trades", "daily_state", "confirmations"} <= tables


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
    )

    store.upsert_position_controls(controls)

    loaded = store.get_position_controls("NEAR-USDC")
    assert loaded == controls
