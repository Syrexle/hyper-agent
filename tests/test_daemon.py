from datetime import date

from near_agent.config import Settings
from near_agent.daemon import TradingDaemon
from near_agent.executor import DryRunExecutor, LiveExecutionGate
from near_agent.llm_veto import VetoResult
from near_agent.models import Decision, DecisionAction, PositionSnapshot, Side, TradeStatus
from near_agent.risk import RiskEngine
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


def test_existing_position_is_closed_automatically_when_management_rule_triggers(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    position = PositionSnapshot(
        symbol="NEAR-USDC",
        side=Side.LONG,
        size=4,
        entry_px=2.4,
        unrealized_pnl_usd=0.2,
    )
    executor = DryRunExecutor(store)
    daemon = TradingDaemon(
        settings=Settings(),
        state=store,
        account_data=StaticAccountData(position),
        executor=executor,
        position_exit_reason_provider=lambda position: "end_of_day_flatten",
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "closed_existing_position"
    assert executor.closed_positions == [("NEAR-USDC", "end_of_day_flatten")]


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


class AllowingVeto:
    def review(self, decision):
        return VetoResult(veto=False, reason="ok")


class CapturingExecutor(DryRunExecutor):
    def __init__(self, state):
        super().__init__(state)
        self.opened_plans = []

    def open_position(self, plan):
        self.opened_plans.append(plan)
        return super().open_position(plan)


def test_opens_dry_run_trade_after_strategy_risk_and_veto_pass(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    executor = CapturingExecutor(store)
    decision = Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.LONG,
        allowed=True,
        rationale="trend continuation",
        stop_loss_px=2.1,
        take_profit_px=2.6,
    )
    daemon = TradingDaemon(
        settings=Settings(),
        state=store,
        account_data=StaticAccountData(position=None),
        executor=executor,
        candidate_provider=lambda: decision,
        risk_engine=RiskEngine(Settings(), store),
        veto_provider=AllowingVeto(),
        entry_price_provider=lambda: 2.3,
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "opened_dry_run_position"
    assert store.has_trade_on(date(2026, 5, 22))
    assert executor.opened_plans[0].symbol == "NEAR-USDC"
    assert executor.opened_plans[0].side == Side.LONG
    assert executor.opened_plans[0].notional_usd == Settings().fixed_notional_usd


def test_live_trade_requires_confirmation_during_initial_confirmation_window(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    decision = Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.SHORT,
        allowed=True,
        rationale="stretched reversal",
        stop_loss_px=2.7,
        take_profit_px=2.2,
    )
    settings = Settings(live_trading=True, hyperliquid_private_key="0x" + "1" * 64, hyperliquid_account_address="0xabc")
    daemon = TradingDaemon(
        settings=settings,
        state=store,
        account_data=StaticAccountData(position=None),
        executor=CapturingExecutor(store),
        candidate_provider=lambda: decision,
        risk_engine=RiskEngine(settings, store),
        veto_provider=AllowingVeto(),
        confirmation_gate=LiveExecutionGate(store, confirm_first_n=5),
        confirm_callback=lambda decision: False,
        entry_price_provider=lambda: 2.4,
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "confirmation_required"
    assert store.confirmation_count() == 0
    assert not store.has_trade_on(date(2026, 5, 22))
