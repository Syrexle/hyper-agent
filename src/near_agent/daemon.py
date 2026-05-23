from collections.abc import Callable
from datetime import date
from typing import Protocol

from near_agent.config import Settings
from near_agent.executor import DryRunExecutor, ExecutionPlan, LiveExecutionGate
from near_agent.llm_veto import DisabledVetoProvider
from near_agent.models import Decision, DecisionAction, PositionSnapshot, Side, Trade, TradeStatus
from near_agent.risk import RiskEngine
from near_agent.sizing import PositionSizing
from near_agent.state import StateStore
from near_agent.trailing import PositionControls


class AccountData(Protocol):
    def existing_position(self, symbol: str) -> PositionSnapshot | None:
        ...


class Executor(Protocol):
    def open_position(self, plan: ExecutionPlan):
        ...

    def close_position(self, symbol: str, reason: str):
        ...


class VetoProvider(Protocol):
    def review(self, decision: Decision):
        ...


class Notifier(Protocol):
    def signal(self, action: DecisionAction, *, symbol: str, price: float) -> None:
        ...

    def entry(self, side: Side, *, symbol: str, size_base: float, price: float, leverage) -> None:
        ...

    def exit(self, *, symbol: str, exit_price: float, reason: str, pnl_pct: float) -> None:
        ...


class TradingDaemon:
    def __init__(
        self,
        *,
        settings: Settings,
        state: StateStore,
        account_data: AccountData,
        executor: Executor,
        candidate_provider: Callable[[], Decision] | None = None,
        risk_engine: RiskEngine | None = None,
        veto_provider: VetoProvider | None = None,
        confirmation_gate: LiveExecutionGate | None = None,
        confirm_callback: Callable[[Decision], bool] | None = None,
        entry_price_provider: Callable[[], float] | None = None,
        position_exit_reason_provider: Callable[[PositionSnapshot], str | None] | None = None,
        sizing_provider: Callable[[float], PositionSizing] | None = None,
        notifier: Notifier | None = None,
    ):
        self.settings = settings
        self.state = state
        self.account_data = account_data
        self.executor = executor
        self.candidate_provider = candidate_provider
        self.risk_engine = risk_engine
        self.veto_provider = veto_provider or DisabledVetoProvider()
        self.confirmation_gate = confirmation_gate
        self.confirm_callback = confirm_callback
        self.entry_price_provider = entry_price_provider
        self.position_exit_reason_provider = position_exit_reason_provider
        self.sizing_provider = sizing_provider
        self.notifier = notifier

    def run_once(self, *, today: date, account_state_ok: bool = True) -> str:
        if not account_state_ok:
            return "account_state_unavailable"

        position = self.account_data.existing_position(self.settings.symbol)
        if position is not None:
            self._adopt_existing_position(position)
            if self.position_exit_reason_provider:
                reason = self.position_exit_reason_provider(position)
                if reason:
                    exit_px = self.entry_price_provider() if self.entry_price_provider else position.entry_px
                    if self.notifier:
                        self.notifier.exit(
                            symbol=position.symbol,
                            exit_price=exit_px,
                            reason=reason,
                            pnl_pct=_position_pnl_pct(position, exit_px),
                        )
                    return self.close_existing_position(reason)
            return "managed_existing_position"

        if self.candidate_provider is None:
            return "no_candidate_provider"

        decision = self.candidate_provider()
        if decision.action == DecisionAction.SKIP:
            self.state.record_decision(decision)
            return "skipped"

        risk = (self.risk_engine or RiskEngine(self.settings, self.state)).evaluate_candidate(
            decision,
            today=today,
            existing_position=None,
        )
        if not risk.allowed:
            self.state.record_decision(_blocked_decision(decision, "risk blocked: " + "; ".join(risk.reasons)))
            return "risk_blocked"

        veto = self.veto_provider.review(decision)
        if veto.veto:
            self.state.record_decision(_blocked_decision(decision, "LLM veto: " + veto.reason))
            return "vetoed"

        if self.settings.live_trading and self.confirmation_gate and self.confirmation_gate.requires_confirmation():
            if self.confirm_callback is None or not self.confirm_callback(decision):
                return "confirmation_required"

        trade_id = f"{self.settings.symbol}-{today.isoformat()}"
        entry_px = self.entry_price_provider() if self.entry_price_provider else 0
        if entry_px <= 0:
            self.state.record_decision(_blocked_decision(decision, "entry price unavailable"))
            return "entry_price_unavailable"

        sizing = self.sizing_provider(entry_px) if self.sizing_provider else PositionSizing(
            notional_usd=risk.notional_usd,
            leverage=risk.max_leverage,
            size_base=round(float(risk.notional_usd) / entry_px, 8),
            atr_pct=0.0,
        )

        self.state.record_decision(decision)
        if self.settings.live_trading and self.confirmation_gate and self.confirmation_gate.requires_confirmation():
            self.state.record_confirmation(trade_id)
        if self.notifier:
            self.notifier.signal(decision.action, symbol=decision.symbol, price=entry_px)
        result = self.executor.open_position(
            ExecutionPlan(
                trade_id=trade_id,
                symbol=decision.symbol,
                side=Side.LONG if decision.action == DecisionAction.LONG else Side.SHORT,
                action=decision.action,
                notional_usd=sizing.notional_usd,
                entry_px=entry_px,
                stop_loss_px=decision.stop_loss_px or 0,
                take_profit_px=decision.take_profit_px or 0,
                leverage=sizing.leverage,
                size_base=sizing.size_base,
            )
        )
        self.state.upsert_position_controls(
            PositionControls(
                symbol=decision.symbol,
                side=Side.LONG if decision.action == DecisionAction.LONG else Side.SHORT,
                entry_px=entry_px,
                initial_stop_px=decision.stop_loss_px or 0,
            )
        )
        self.state.mark_trade_opened(today)
        if self.notifier:
            self.notifier.entry(
                Side.LONG if decision.action == DecisionAction.LONG else Side.SHORT,
                symbol=decision.symbol,
                size_base=sizing.size_base,
                price=entry_px,
                leverage=sizing.leverage,
            )
        return "opened_live_position" if result.submitted else "opened_dry_run_position"

    def _adopt_existing_position(self, position: PositionSnapshot) -> None:
        self.state.upsert_trade(
            Trade(
                trade_id=f"adopted-{position.symbol}",
                symbol=position.symbol,
                side=position.side,
                status=TradeStatus.ADOPTED,
                notional_usd=abs(position.size * position.entry_px),
                entry_px=position.entry_px,
            )
        )

    def close_existing_position(self, reason: str) -> str:
        self.executor.close_position(self.settings.symbol, reason)
        self.state.clear_position_controls(self.settings.symbol)
        return "closed_existing_position"


def _blocked_decision(decision: Decision, reason: str) -> Decision:
    return Decision(
        symbol=decision.symbol,
        action=decision.action,
        allowed=False,
        rationale=f"{decision.rationale}; {reason}",
        stop_loss_px=decision.stop_loss_px,
        take_profit_px=decision.take_profit_px,
    )


def _position_pnl_pct(position: PositionSnapshot, mark_px: float) -> float:
    if position.entry_px <= 0:
        return 0.0
    if position.side == Side.LONG:
        return (mark_px - position.entry_px) / position.entry_px * 100
    return (position.entry_px - mark_px) / position.entry_px * 100
