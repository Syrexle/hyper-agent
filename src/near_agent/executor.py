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
    def __init__(self, state: StateStore, sdk_client, *, slippage: float = 0.01, size_decimals: int = 1):
        self.state = state
        self.sdk_client = sdk_client
        self.slippage = slippage
        self.size_decimals = size_decimals

    def open_position(self, plan: ExecutionPlan) -> ExecutionResult:
        coin = _to_hyperliquid_coin(plan.symbol)
        is_buy = plan.side == Side.LONG
        size = round(float(plan.notional_usd) / plan.entry_px, self.size_decimals)
        self.sdk_client.market_open(coin, is_buy=is_buy, sz=size, slippage=self.slippage)
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
            submitted=True,
            message="live open submitted",
        )

    def close_position(self, symbol: str, reason: str) -> ExecutionResult:
        self.sdk_client.market_close(_to_hyperliquid_coin(symbol), slippage=self.slippage)
        return ExecutionResult(
            trade_id=f"close-{symbol}",
            submitted=True,
            message=f"live close submitted: {reason}",
        )


def _to_hyperliquid_coin(symbol: str) -> str:
    if symbol == "NEAR-USDC":
        return "NEAR"
    raise ValueError(f"Unsupported live execution symbol: {symbol}")
