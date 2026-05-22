from datetime import date
from decimal import Decimal

from near_agent.config import Settings
from near_agent.models import Decision, DecisionAction, Side, PositionSnapshot
from near_agent.risk import RiskEngine
from near_agent.state import StateStore


def long_decision():
    return Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.LONG,
        allowed=True,
        rationale="test",
        stop_loss_px=2.0,
        take_profit_px=2.4,
    )


def test_allows_valid_first_trade(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is True
    assert result.notional_usd == Decimal("10")


def test_blocks_non_near_usdc_symbol(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(), store)
    decision = long_decision()
    decision.symbol = "BTC-USDC"

    result = engine.evaluate_candidate(decision, today=date(2026, 5, 22))

    assert result.allowed is False
    assert "NEAR-USDC" in result.reasons[0]


def test_blocks_second_trade_same_day(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.mark_trade_opened(date(2026, 5, 22))
    engine = RiskEngine(Settings(), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "already been opened" in result.reasons[0]


def test_blocks_after_daily_loss(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.mark_loss(date(2026, 5, 22))
    engine = RiskEngine(Settings(), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "loss" in result.reasons[0]


def test_blocks_effective_leverage_above_two(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    settings = Settings(max_leverage=Decimal("2.5"))
    engine = RiskEngine(settings, store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "leverage" in result.reasons[0]


def test_blocks_missing_stop_or_target(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(), store)
    decision = long_decision()
    decision.stop_loss_px = None

    result = engine.evaluate_candidate(decision, today=date(2026, 5, 22))

    assert result.allowed is False
    assert "stop-loss" in result.reasons[0]


def test_blocks_new_entries_when_existing_position_is_active(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(), store)
    existing = PositionSnapshot(
        symbol="NEAR-USDC",
        side=Side.LONG,
        size=5,
        entry_px=2.1,
        unrealized_pnl_usd=0.2,
    )

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22), existing_position=existing)

    assert result.allowed is False
    assert "position-management mode" in result.reasons[0]
