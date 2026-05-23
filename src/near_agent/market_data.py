import json
from itertools import count
from typing import Any, Protocol

from near_agent.strategy import Candle
from near_agent.models import PositionSnapshot, Side


class MarketDataUnavailable(RuntimeError):
    pass


class McpClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ...


class RootAiHttpMcpClient:
    def __init__(self, url: str, *, http_client: Any | None = None, timeout: float = 20.0):
        self.url = url
        self._http_client = http_client
        self.timeout = timeout
        self.session_id: str | None = None
        self._ids = count(1)

    @property
    def http_client(self):
        if self._http_client is None:
            import httpx

            self._http_client = httpx.Client(timeout=self.timeout)
        return self._http_client

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = self.http_client.post(self.url, json=payload, headers=self._headers())
        response.raise_for_status()
        message = _parse_mcp_sse_response(response.text)
        result = message.get("result", {})
        if isinstance(result, dict) and "structuredContent" in result:
            return result["structuredContent"]
        if isinstance(result, dict) and "content" in result:
            parsed = _parse_mcp_content(result["content"])
            if parsed is not None:
                return parsed
        return result

    def _ensure_session(self) -> None:
        if self.session_id:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "near-agent", "version": "0.1.0"},
            },
        }
        response = self.http_client.post(self.url, json=payload, headers=self._headers(include_session=False))
        response.raise_for_status()
        self.session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if not self.session_id:
            raise MarketDataUnavailable("RootAI MCP did not return a session id")
        _parse_mcp_sse_response(response.text)

    def _headers(self, *, include_session: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers


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


def _parse_mcp_sse_response(text: str) -> dict[str, Any]:
    data_lines = [line.removeprefix("data:").strip() for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MarketDataUnavailable("RootAI MCP returned an unparseable response") from exc
        if isinstance(parsed, dict):
            return parsed
        raise MarketDataUnavailable("RootAI MCP returned a non-object response")
    for line in reversed(data_lines):
        if line == "[DONE]":
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise MarketDataUnavailable("RootAI MCP returned no JSON data")


def _parse_mcp_content(content: Any) -> Any | None:
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return None
