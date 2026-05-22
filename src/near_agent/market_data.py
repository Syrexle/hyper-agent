from typing import Any, Protocol

from near_agent.strategy import Candle
from near_agent.models import PositionSnapshot, Side


class MarketDataUnavailable(RuntimeError):
    pass


class McpClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ...


def normalize_hyperliquid_symbol(symbol: str) -> str:
    if symbol in {"NEAR", "NEAR-USDC"}:
        return "NEAR-USDC"
    return symbol


def to_hyperliquid_coin(symbol: str) -> str:
    normalized = normalize_hyperliquid_symbol(symbol)
    if normalized == "NEAR-USDC":
        return "NEAR"
    raise MarketDataUnavailable(f"Unsupported symbol: {symbol}")


class RootAiMcpMarketData:
    def __init__(self, client: McpClient):
        self.client = client

    def mid(self, symbol: str) -> float:
        coin = to_hyperliquid_coin(symbol)
        result = self.client.call_tool("hyperliquid_mids", {"include_spot": False})
        try:
            return float(result[coin])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataUnavailable(f"Missing mid price for {symbol}") from exc

    def candles(self, symbol: str, *, interval: str, start_time: int, end_time: int | None = None) -> list[Candle]:
        coin = to_hyperliquid_coin(symbol)
        args: dict[str, Any] = {"coin": coin, "interval": interval, "start_time": start_time}
        if end_time is not None:
            args["end_time"] = end_time
        result = self.client.call_tool("hyperliquid_candles", args)
        rows = result.get("result") if isinstance(result, dict) else None
        if not rows:
            raise MarketDataUnavailable(f"Missing candles for {symbol}")
        return [
            Candle(
                open=float(row["o"]),
                high=float(row["h"]),
                low=float(row["l"]),
                close=float(row["c"]),
                volume=float(row["v"]),
            )
            for row in rows
        ]

    def funding(self, symbol: str, *, start_time: int, end_time: int | None = None) -> float:
        coin = to_hyperliquid_coin(symbol)
        args: dict[str, Any] = {"coin": coin, "start_time": start_time}
        if end_time is not None:
            args["end_time"] = end_time
        result = self.client.call_tool("hyperliquid_funding", args)
        rows = result.get("result") if isinstance(result, dict) else None
        if not rows:
            raise MarketDataUnavailable(f"Missing funding for {symbol}")
        return float(rows[-1]["fundingRate"])

    def summary(self, symbol: str) -> dict[str, Any]:
        coin = to_hyperliquid_coin(symbol)
        result = self.client.call_tool("hyperliquid_summaries", {})
        rows = result.get("result") if isinstance(result, dict) else None
        if not rows:
            raise MarketDataUnavailable(f"Missing summaries for {symbol}")
        for row in rows:
            if row.get("coin") == coin:
                return row
        raise MarketDataUnavailable(f"Missing summary for {symbol}")


class HyperliquidAccountData:
    def __init__(self, info_client: Any, account_address: str):
        self.info_client = info_client
        self.account_address = account_address

    def existing_position(self, symbol: str) -> PositionSnapshot | None:
        coin = to_hyperliquid_coin(symbol)
        state = self.info_client.user_state(self.account_address)
        for item in state.get("assetPositions", []):
            position = item.get("position", {})
            if position.get("coin") != coin:
                continue
            signed_size = float(position.get("szi", "0"))
            if signed_size == 0:
                return None
            return PositionSnapshot(
                symbol=normalize_hyperliquid_symbol(coin),
                side=Side.LONG if signed_size > 0 else Side.SHORT,
                size=abs(signed_size),
                entry_px=float(position.get("entryPx", 0)),
                unrealized_pnl_usd=float(position.get("unrealizedPnl", 0)),
                liquidation_px=_optional_float(position.get("liquidationPx")),
            )
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
