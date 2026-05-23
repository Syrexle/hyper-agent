from datetime import date

from hyper_agent.config import Settings
from hyper_agent.daemon import TradingDaemon
from hyper_agent.executor import DryRunExecutor, ExecutionResult, LiveExecutionGate
from hyper_agent.llm_veto import VetoResult
from hyper_agent.models import Decision, DecisionAction, PositionSnapshot, Side, Trade, TradeJournalEntry, TradeStatus
from hyper_agent.risk import RiskEngine
from hyper_agent.sizing import PositionSizing
from hyper_agent.state import StateStore
from hyper_agent.trailing import PositionControls


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
        settings=Settings(_env_file=None),
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
        settings=Settings(_env_file=None),
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
        settings=Settings(_env_file=None),
        state=store,
        account_data=StaticAccountData(position),
        executor=executor,
        position_exit_reason_provider=lambda position: "end_of_day_flatten",
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "closed_existing_position"
    assert executor.closed_positions == [("NEAR-USDC", "end_of_day_flatten")]


def test_close_existing_position_updates_live_trade_journal(tmp_path):
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
    store.upsert_position_controls(
        PositionControls(
            symbol="NEAR-USDC",
            side=Side.LONG,
            entry_px=2.0,
            initial_stop_px=1.9,
            highest_pnl_pct=8,
            max_drawdown_pct=-2.5,
        )
    )
    daemon = TradingDaemon(
        settings=Settings(),
        state=store,
        account_data=StaticAccountData(None),
        executor=DryRunExecutor(store),
        entry_price_provider=lambda symbol: 2.1,
    )

    result = daemon.close_existing_position("manual_close")

    assert result == "closed_existing_position"
    journal = store.list_trade_journal_entries()[0]
    assert journal.exit_px == 2.1
    assert journal.realized_pnl_usd == 0.5
    assert journal.realized_pnl_pct == 5.0
    assert journal.exit_reason == "manual_close"
    assert journal.highest_pnl_pct == 8
    assert journal.max_drawdown_pct == -2.5


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


class SubmittedExecutor(CapturingExecutor):
    def open_position(self, plan):
        self.opened_plans.append(plan)
        self.state.upsert_trade(
            Trade(
                trade_id=plan.trade_id,
                symbol=plan.symbol,
                side=plan.side,
                status=TradeStatus.OPEN,
                notional_usd=float(plan.notional_usd),
                entry_px=plan.entry_px,
            )
        )
        return ExecutionResult(trade_id=plan.trade_id, submitted=True, message="submitted")


class RejectedLiveExecutor(CapturingExecutor):
    def open_position(self, plan):
        self.opened_plans.append(plan)
        return ExecutionResult(trade_id=plan.trade_id, submitted=False, message="minimum order value")


def test_opens_dry_run_trade_after_strategy_risk_and_veto_pass(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    executor = CapturingExecutor(store)
    settings = Settings(_env_file=None)
    decision = Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.LONG,
        allowed=True,
        rationale="trend continuation",
        stop_loss_px=2.1,
        take_profit_px=2.6,
    )
    daemon = TradingDaemon(
        settings=settings,
        state=store,
        account_data=StaticAccountData(position=None),
        executor=executor,
        candidate_provider=lambda: decision,
        risk_engine=RiskEngine(settings, store),
        veto_provider=AllowingVeto(),
        entry_price_provider=lambda symbol: 2.3,
        sizing_provider=lambda price: PositionSizing(
                notional_usd=settings.fixed_notional_usd,
                leverage=settings.max_leverage,
            size_base=4.34782609,
            atr_pct=1.2,
        ),
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "opened_dry_run_position"
    assert store.has_trade_on(date(2026, 5, 22))
    assert executor.opened_plans[0].symbol == "NEAR-USDC"
    assert executor.opened_plans[0].side == Side.LONG
    assert executor.opened_plans[0].notional_usd == settings.fixed_notional_usd
    controls = store.get_position_controls("NEAR-USDC")
    assert controls is not None
    assert controls.initial_stop_px == 2.1


class CapturingNotifier:
    def __init__(self):
        self.events = []

    def signal(self, action, *, symbol, price):
        self.events.append(("signal", action, symbol, price))

    def entry(self, side, *, symbol, size_base, price, leverage):
        self.events.append(("entry", side, symbol, size_base, price, leverage))

    def exit(self, *, symbol, exit_price, reason, pnl_pct):
        self.events.append(("exit", symbol, exit_price, reason, pnl_pct))

    def error(self, message):
        self.events.append(("error", message))


def test_notifier_receives_signal_and_entry_after_trade_opens(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    notifier = CapturingNotifier()
    decision = Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.LONG,
        allowed=True,
        rationale="trend continuation",
        stop_loss_px=2.1,
        take_profit_px=2.6,
    )
    daemon = TradingDaemon(
        settings=Settings(_env_file=None),
        state=store,
        account_data=StaticAccountData(position=None),
        executor=CapturingExecutor(store),
        candidate_provider=lambda: decision,
        risk_engine=RiskEngine(Settings(_env_file=None), store),
        veto_provider=AllowingVeto(),
        entry_price_provider=lambda symbol: 2.3,
        sizing_provider=lambda price: PositionSizing(
            Settings(_env_file=None).fixed_notional_usd,
            Settings(_env_file=None).max_leverage,
            4.34,
            1.2,
        ),
        notifier=notifier,
    )

    daemon.run_once(today=date(2026, 5, 22))

    assert notifier.events[0] == ("signal", DecisionAction.LONG, "NEAR-USDC", 2.3)
    assert notifier.events[1][0] == "entry"


def test_live_submitted_trade_records_journal_entry(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    decision = Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.LONG,
        allowed=True,
        rationale="trend continuation",
        stop_loss_px=2.1,
        take_profit_px=2.6,
    )
    settings = Settings(
        live_trading=True,
        hyperliquid_private_key="0x" + "1" * 64,
        hyperliquid_account_address="0xabc",
        confirm_first_n_trades=0,
    )
    daemon = TradingDaemon(
        settings=settings,
        state=store,
        account_data=StaticAccountData(position=None),
        executor=SubmittedExecutor(store),
        candidate_provider=lambda: decision,
        risk_engine=RiskEngine(settings, store),
        veto_provider=AllowingVeto(),
        entry_price_provider=lambda symbol: 2.3,
        sizing_provider=lambda price: PositionSizing(settings.fixed_notional_usd, settings.max_leverage, 4.34, 1.2),
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "opened_live_position"
    journal = store.list_trade_journal_entries()
    assert len(journal) == 1
    assert journal[0].submitted_live is True
    assert journal[0].symbol == "NEAR-USDC"
    assert journal[0].atr_pct == 1.2


def test_rejected_live_order_is_not_marked_open_or_journaled(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    decision = Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.SHORT,
        allowed=True,
        rationale="forced test",
        stop_loss_px=2.2,
        take_profit_px=1.8,
    )
    settings = Settings(
        live_trading=True,
        hyperliquid_private_key="0x" + "1" * 64,
        hyperliquid_account_address="0xabc",
        confirm_first_n_trades=0,
    )
    daemon = TradingDaemon(
        settings=settings,
        state=store,
        account_data=StaticAccountData(position=None),
        executor=RejectedLiveExecutor(store),
        candidate_provider=lambda: decision,
        risk_engine=RiskEngine(settings, store),
        veto_provider=AllowingVeto(),
        entry_price_provider=lambda symbol: 2.0,
        sizing_provider=lambda price: PositionSizing(1, 10, 0.5, 1.2),
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "live_order_rejected"
    assert store.list_trade_journal_entries() == []
    assert store.has_trade_on(date(2026, 5, 22)) is False


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
        entry_price_provider=lambda symbol: 2.4,
    )

    result = daemon.run_once(today=date(2026, 5, 22))

    assert result == "confirmation_required"
    assert store.confirmation_count() == 0
    assert not store.has_trade_on(date(2026, 5, 22))
