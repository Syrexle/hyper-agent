from collections.abc import Callable
from datetime import date
from typing import Protocol

from near_agent.config import Settings
from near_agent.executor import DryRunExecutor
from near_agent.models import Decision, DecisionAction, PositionSnapshot, Trade, TradeStatus
from near_agent.state import StateStore


class AccountData(Protocol):
    def existing_position(self, symbol: str) -> PositionSnapshot | None:
        ...


class TradingDaemon:
    def __init__(
        self,
        *,
        settings: Settings,
        state: StateStore,
        account_data: AccountData,
        executor: DryRunExecutor,
        candidate_provider: Callable[[], Decision] | None = None,
    ):
        self.settings = settings
        self.state = state
        self.account_data = account_data
        self.executor = executor
        self.candidate_provider = candidate_provider

    def run_once(self, *, today: date, account_state_ok: bool = True) -> str:
        if not account_state_ok:
            return "account_state_unavailable"

        position = self.account_data.existing_position(self.settings.symbol)
        if position is not None:
            self._adopt_existing_position(position)
            return "managed_existing_position"

        if self.candidate_provider is None:
            return "no_candidate_provider"

        decision = self.candidate_provider()
        if decision.action == DecisionAction.SKIP:
            self.state.record_decision(decision)
            return "skipped"

        self.state.record_decision(decision)
        return "candidate_recorded"

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
        return "closed_existing_position"
