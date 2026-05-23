import pytest

from hyper_agent.market_data import (
    HyperliquidAccountData,
    MarketDataUnavailable,
    RootAiHttpMcpClient,
    RootAiMcpMarketData,
    normalize_hyperliquid_symbol,
)
from hyper_agent.models import Side
from hyper_agent.strategy import Candle


class FakeMcpClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "hyperliquid_mids":
            return {"NEAR": "2.25"}
        if name == "hyperliquid_candles":
            return {
                "result": [
                    {"o": "2.0", "h": "2.2", "l": "1.9", "c": "2.1", "v": "1000"},
                ]
            }
        if name == "hyperliquid_funding":
            return {"result": [{"fundingRate": "0.0000125"}]}
        if name == "hyperliquid_summaries":
            return {"result": [{"coin": "NEAR", "max_leverage": 10, "open_interest": "100"}]}
        raise AssertionError(name)


class FakeHttpResponse:
    def __init__(self, *, text, headers=None):
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        return None


class FakeHttpClient:
    def __init__(self):
        self.posts = []

    def post(self, url, *, json, headers):
        self.posts.append((url, json, headers))
        if json["method"] == "initialize":
            return FakeHttpResponse(
                text='event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}}\n\n',
                headers={"mcp-session-id": "session-1"},
            )
        return FakeHttpResponse(
            text=(
                'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":'
                '{"structuredContent":{"NEAR":"2.25"}}}\n\n'
            )
        )


def test_normalizes_hyperliquid_near_symbol():
    assert normalize_hyperliquid_symbol("NEAR") == "NEAR-USDC"
    assert normalize_hyperliquid_symbol("NEAR-USDC") == "NEAR-USDC"


def test_fetches_near_mid_from_rootai_mcp():
    adapter = RootAiMcpMarketData(FakeMcpClient())

    assert adapter.mid("NEAR-USDC") == 2.25
    assert adapter.client.calls[0] == ("hyperliquid_mids", {"include_spot": False})


def test_http_mcp_client_initializes_session_and_parses_sse_structured_content():
    http = FakeHttpClient()
    client = RootAiHttpMcpClient("https://mcp.rootai.wtf/mcp", http_client=http)

    result = client.call_tool("hyperliquid_mids", {"include_spot": False})

    assert result == {"NEAR": "2.25"}
    assert http.posts[0][1]["method"] == "initialize"
    assert http.posts[1][1]["method"] == "tools/call"
    assert http.posts[1][2]["Mcp-Session-Id"] == "session-1"


def test_fetches_near_candles_from_rootai_mcp():
    adapter = RootAiMcpMarketData(FakeMcpClient())

    candles = adapter.candles("NEAR-USDC", interval="1h", start_time=1, end_time=2)

    assert candles == [Candle(open=2.0, high=2.2, low=1.9, close=2.1, volume=1000.0)]
    assert adapter.client.calls[0][0] == "hyperliquid_candles"
    assert adapter.client.calls[0][1]["coin"] == "NEAR"


def test_fetches_funding_and_summary():
    adapter = RootAiMcpMarketData(FakeMcpClient())

    assert adapter.funding("NEAR-USDC", start_time=1, end_time=2) == 0.0000125
    assert adapter.summary("NEAR-USDC")["max_leverage"] == 10


def test_missing_mid_fails_closed():
    class EmptyClient:
        def call_tool(self, name, arguments):
            return {}

    adapter = RootAiMcpMarketData(EmptyClient())

    with pytest.raises(MarketDataUnavailable):
        adapter.mid("NEAR-USDC")


def test_account_data_parses_existing_near_position():
    class FakeInfo:
        def user_state(self, address):
            return {
                "assetPositions": [
                    {
                        "position": {
                            "coin": "NEAR",
                            "szi": "-4.0",
                            "entryPx": "2.5",
                            "unrealizedPnl": "0.25",
                            "liquidationPx": "3.2",
                        }
                    }
                ]
            }

    account_data = HyperliquidAccountData(FakeInfo(), "0xabc")

    position = account_data.existing_position("NEAR-USDC")

    assert position is not None
    assert position.symbol == "NEAR-USDC"
    assert position.side == Side.SHORT
    assert position.size == 4.0
    assert position.entry_px == 2.5


def test_account_data_returns_none_without_near_position():
    class FakeInfo:
        def user_state(self, address):
            return {"assetPositions": []}

    assert HyperliquidAccountData(FakeInfo(), "0xabc").existing_position("NEAR-USDC") is None
