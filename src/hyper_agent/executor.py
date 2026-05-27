from dataclasses import dataclass
from decimal import Decimal

from hyper_agent.models import DecisionAction, Side, Trade, TradeStatus
from hyper_agent.state import StateStore


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
    leverage: Decimal | float = Decimal("1")
    size_base: float | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    trade_id: str
    submitted: bool
    message: str
    stop_loss_protected: bool = True


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

    def cancel_open_orders(self, symbol: str) -> int:
        return 0

    def place_stop_loss(self, symbol: str, side: Side, size: float, stop_px: float) -> bool:
        return False


class HyperliquidLiveExecutor:
    def __init__(self, state: StateStore, sdk_client, *, slippage: float = 0.01, size_decimals: int = 1):
        self.state = state
        self.sdk_client = sdk_client
        self.slippage = slippage
        self.size_decimals = size_decimals
        self._sz_decimals_cache: dict[str, int] = {}

    def _sz_decimals_for(self, coin: str) -> int:
        if coin in self._sz_decimals_cache:
            return self._sz_decimals_cache[coin]
        try:
            meta = self.sdk_client.info.meta()
            for asset in meta.get("universe", []):
                self._sz_decimals_cache[asset["name"]] = int(asset.get("szDecimals", self.size_decimals))
        except Exception:
            pass
        return self._sz_decimals_cache.get(coin, self.size_decimals)

    def open_position(self, plan: ExecutionPlan) -> ExecutionResult:
        import math
        coin = _to_hyperliquid_coin(plan.symbol)
        is_buy = plan.side == Side.LONG
        raw = plan.size_base if plan.size_base is not None else float(plan.notional_usd) / plan.entry_px
        factor = 10 ** self._sz_decimals_for(coin)
        size = math.ceil(raw * factor) / factor

        # Open market position
        response = self.sdk_client.market_open(coin, is_buy=is_buy, sz=size, slippage=self.slippage)
        rejection = _order_rejection_reason(response)
        if rejection:
            return ExecutionResult(
                trade_id=plan.trade_id,
                submitted=False,
                message=rejection,
            )

        # Place native stop loss on the exchange. If this fails, the position is open but degraded.
        stop_loss_protected = True
        stop_loss_message = ""
        if plan.stop_loss_px and plan.stop_loss_px > 0:
            try:
                close_is_buy = not is_buy
                trigger_px = self.sdk_client._slippage_price(coin, close_is_buy, 0.0, plan.stop_loss_px)
                limit_px = self.sdk_client._slippage_price(coin, close_is_buy, self.slippage, plan.stop_loss_px)
                sl_response = self.sdk_client.order(
                    coin,
                    close_is_buy,
                    size,
                    limit_px,
                    {"trigger": {"triggerPx": trigger_px, "isMarket": True, "tpsl": "sl"}},
                    reduce_only=True,
                )
                sl_rejection = _order_rejection_reason(sl_response)
                if sl_rejection:
                    stop_loss_protected = False
                    stop_loss_message = f"; native stop loss failed: {sl_rejection}"
            except Exception as exc:
                stop_loss_protected = False
                stop_loss_message = f"; native stop loss failed: {exc}"

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
            message="live open submitted" + stop_loss_message,
            stop_loss_protected=stop_loss_protected,
        )

    def close_position(self, symbol: str, reason: str) -> ExecutionResult:
        self.sdk_client.market_close(_to_hyperliquid_coin(symbol), slippage=self.slippage)
        return ExecutionResult(
            trade_id=f"close-{symbol}",
            submitted=True,
            message=f"live close submitted: {reason}",
        )

    def cancel_open_orders(self, symbol: str) -> int:
        coin = _to_hyperliquid_coin(symbol)
        address = self.sdk_client.account_address
        open_orders = self.sdk_client.info.open_orders(address)
        cancelled = 0
        for order in open_orders:
            if order.get("coin") != coin:
                continue
            oid = order.get("oid")
            if oid is None:
                continue
            try:
                self.sdk_client.cancel(coin, oid)
                cancelled += 1
            except Exception:
                pass
        return cancelled

    def place_stop_loss(self, symbol: str, side: Side, size: float, stop_px: float) -> bool:
        import math
        coin = _to_hyperliquid_coin(symbol)
        is_buy = side == Side.LONG
        close_is_buy = not is_buy
        factor = 10 ** self._sz_decimals_for(coin)
        rounded_size = math.ceil(size * factor) / factor
        # trigger price: properly rounded to Hyperliquid's 5-sig-fig format
        trigger_px = self.sdk_client._slippage_price(coin, close_is_buy, 0.0, stop_px)
        # limit price: worst-case fill price (slippage below trigger for sells, above for buys)
        limit_px = self.sdk_client._slippage_price(coin, close_is_buy, self.slippage, stop_px)
        try:
            response = self.sdk_client.order(
                coin,
                close_is_buy,
                rounded_size,
                limit_px,
                {"trigger": {"triggerPx": trigger_px, "isMarket": True, "tpsl": "sl"}},
                reduce_only=True,
            )
            rejection = _order_rejection_reason(response)
            if rejection:
                print(f"[executor] place_stop_loss rejected for {symbol}: {rejection}")
                return False
            return True
        except Exception as exc:
            print(f"[executor] place_stop_loss failed for {symbol}: {exc}")
            return False


def _to_hyperliquid_coin(symbol: str) -> str:
    return symbol.split("-")[0]


def _order_rejection_reason(response) -> str | None:
    if not isinstance(response, dict):
        return None
    if response.get("status") == "err":
        return str(response.get("response") or "live order rejected")
    statuses = response.get("response", {}).get("data", {}).get("statuses", [])
    if not isinstance(statuses, list):
        return None
    errors = [status.get("error") for status in statuses if isinstance(status, dict) and status.get("error")]
    if errors:
        return "; ".join(str(error) for error in errors)
    return None
