from datetime import date
from decimal import Decimal

from hyper_agent.config import Settings
from hyper_agent.models import Decision, DecisionAction, PositionSnapshot, Side
from hyper_agent.risk import RiskEngine
from hyper_agent.state import StateStore


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
    engine = RiskEngine(Settings(_env_file=None), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is True
    assert result.notional_usd == Decimal("10")


def test_blocks_symbol_outside_tracked_list(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(_env_file=None), store)
    decision = long_decision()
    decision.symbol = "NOTLISTED-USDC"

    result = engine.evaluate_candidate(decision, today=date(2026, 5, 22))

    assert result.allowed is False
    assert "tracked symbol list" in result.reasons[0]


def test_allows_multiple_trades_same_day_until_loss_or_win_cap(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.mark_trade_opened(date(2026, 5, 22))
    engine = RiskEngine(Settings(_env_file=None), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is True


def test_blocks_after_daily_loss(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.mark_loss(date(2026, 5, 22))
    engine = RiskEngine(Settings(_env_file=None), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "loss" in result.reasons[0]


def test_blocks_effective_leverage_above_ten(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    settings = Settings(_env_file=None, max_leverage=Decimal("10.5"))
    engine = RiskEngine(settings, store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "leverage" in result.reasons[0]


def test_blocks_missing_stop_or_target(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(_env_file=None), store)
    decision = long_decision()
    decision.stop_loss_px = None

    result = engine.evaluate_candidate(decision, today=date(2026, 5, 22))

    assert result.allowed is False
    assert "stop-loss" in result.reasons[0]


def test_blocks_new_entries_when_existing_position_is_active(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    engine = RiskEngine(Settings(_env_file=None), store)
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


def test_blocks_when_max_open_positions_reached(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    for idx, symbol in enumerate(["BTC-USDC", "ETH-USDC", "SOL-USDC"]):
        from hyper_agent.models import Trade, TradeStatus
        store.upsert_trade(Trade(f"trade-{idx}", symbol=symbol, side=Side.LONG, status=TradeStatus.OPEN, notional_usd=10, entry_px=1))
    engine = RiskEngine(Settings(_env_file=None, max_open_positions=3), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "max open positions" in result.reasons[0]


def test_blocks_when_projected_notional_exceeds_cap(tmp_path):
    from hyper_agent.models import Trade, TradeStatus
    store = StateStore(tmp_path / "agent.sqlite")
    store.upsert_trade(Trade("trade-1", symbol="BTC-USDC", side=Side.LONG, status=TradeStatus.OPEN, notional_usd=95, entry_px=1))
    engine = RiskEngine(Settings(_env_file=None, max_total_notional_usd=Decimal("100"), fixed_notional_usd=Decimal("10")), store)

    result = engine.evaluate_candidate(long_decision(), today=date(2026, 5, 22))

    assert result.allowed is False
    assert "max total notional" in result.reasons[0]
