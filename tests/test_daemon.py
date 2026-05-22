from datetime import date

from near_agent.config import Settings
from near_agent.daemon import TradingDaemon
from near_agent.executor import DryRunExecutor
from near_agent.models import Decision, DecisionAction, PositionSnapshot, Side, TradeStatus
from near_agent.state import StateStore


class StaticAccountData:
    def __init__(self, position=None):
        self.position = position

    def existing_position(self, symbol):
        return self.position


def test_adopts_existing_near_position_without_confirmation(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    position = PositionSnapshot(
        symbol="NEAR-USDC",
        side=Side.SHORT,
        size=4,
        entry_px=2.4,
        unrealized_pnl_usd=0.5,
    )
    daemon = TradingDaemon(
        settings=Settings(),
        state=store,
        account_data=StaticAccountData(position),
        executor=DryRunExecutor(store),
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "managed_existing_position"
    adopted = store.get_trade("adopted-NEAR-USDC")
    assert adopted is not None
    assert adopted.status == TradeStatus.ADOPTED


def test_existing_position_is_closed_without_confirmation_when_requested(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    position = PositionSnapshot(
        symbol="NEAR-USDC",
        side=Side.LONG,
        size=4,
        entry_px=2.4,
        unrealized_pnl_usd=-0.5,
    )
    executor = DryRunExecutor(store)
    daemon = TradingDaemon(
        settings=Settings(),
        state=store,
        account_data=StaticAccountData(position),
        executor=executor,
    )

    result = daemon.close_existing_position("risk_exit")

    assert result == "closed_existing_position"
    assert executor.closed_positions == [("NEAR-USDC", "risk_exit")]


def test_ambiguous_position_blocks_new_entries(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    decision = Decision(symbol="NEAR-USDC", action=DecisionAction.LONG, allowed=True, rationale="test")
    daemon = TradingDaemon(
        settings=Settings(),
        state=store,
        account_data=StaticAccountData(position=None),
        executor=DryRunExecutor(store),
        candidate_provider=lambda: decision,
    )

    result = daemon.run_once(today=date(2026, 5, 22), account_state_ok=False)

    assert result == "account_state_unavailable"
    assert store.list_decisions() == []
