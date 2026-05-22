from dataclasses import dataclass
from decimal import Decimal

from near_agent.models import DecisionAction, Side, Trade, TradeStatus
from near_agent.state import StateStore


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    trade_id: str
    symbol: str
    side: Side
    action: DecisionAction
    notional_usd: Decimal | float
    entry_px: float
    stop_loss_px: float
    take_profit_px: float


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    trade_id: str
    submitted: bool
    message: str


class LiveExecutionGate:
    def __init__(self, state: StateStore, *, confirm_first_n: int):
        self.state = state
        self.confirm_first_n = confirm_first_n

    def requires_confirmation(self) -> bool:
        return self.state.confirmation_count() < self.confirm_first_n


class DryRunExecutor:
    def __init__(self, state: StateStore):
        self.state = state
        self.closed_positions: list[tuple[str, str]] = []

    def open_position(self, plan: ExecutionPlan) -> ExecutionResult:
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
        return ExecutionResult(
            trade_id=plan.trade_id,
            submitted=False,
            message="dry-run order recorded without live submission",
        )

    def close_position(self, symbol: str, reason: str) -> ExecutionResult:
        self.closed_positions.append((symbol, reason))
        return ExecutionResult(
            trade_id=f"close-{symbol}",
            submitted=False,
            message=f"dry-run close recorded: {reason}",
        )


class HyperliquidLiveExecutor:
    def __init__(self, state: StateStore, sdk_client):
        self.state = state
        self.sdk_client = sdk_client

    def open_position(self, plan: ExecutionPlan) -> ExecutionResult:
        raise NotImplementedError("Live Hyperliquid execution is wired behind this interface")

    def close_position(self, symbol: str, reason: str) -> ExecutionResult:
        raise NotImplementedError("Live Hyperliquid close is wired behind this interface")
