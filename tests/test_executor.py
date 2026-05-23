from hyper_agent.executor import DryRunExecutor, ExecutionPlan, HyperliquidLiveExecutor, LiveExecutionGate
from hyper_agent.models import DecisionAction, Side
from hyper_agent.state import StateStore


def test_dry_run_executor_records_order_without_live_submit(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    executor = DryRunExecutor(store)
    plan = ExecutionPlan(
        trade_id="trade-1",
        symbol="NEAR-USDC",
        side=Side.LONG,
        action=DecisionAction.LONG,
        notional_usd=10,
        entry_px=2.2,
        stop_loss_px=2.0,
        take_profit_px=2.6,
        leverage=2,
        size_base=4.54545455,
    )

    result = executor.open_position(plan)

    assert result.submitted is False
    assert result.trade_id == "trade-1"
    assert store.get_trade("trade-1") is not None


def test_first_five_live_entries_require_confirmation(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    gate = LiveExecutionGate(store, confirm_first_n=5)

    assert gate.requires_confirmation() is True
    for i in range(5):
        store.record_confirmation(f"trade-{i}")

    assert gate.requires_confirmation() is False


def test_live_executor_delegates_market_open_to_hyperliquid_sdk(tmp_path):
    class FakeExchange:
        def __init__(self):
            self.calls = []

        def market_open(self, name, is_buy, sz, slippage):
            self.calls.append(("market_open", name, is_buy, sz, slippage))
            return {"status": "ok"}

    store = StateStore(tmp_path / "agent.sqlite")
    exchange = FakeExchange()
    executor = HyperliquidLiveExecutor(store, exchange)
    plan = ExecutionPlan(
        trade_id="trade-1",
        symbol="NEAR-USDC",
        side=Side.LONG,
        action=DecisionAction.LONG,
        notional_usd=10,
        entry_px=2.5,
        stop_loss_px=2.2,
        take_profit_px=3.0,
        leverage=2,
        size_base=4.0,
    )

    result = executor.open_position(plan)

    assert result.submitted is True
    assert exchange.calls == [("market_open", "NEAR", True, 4.0, 0.01)]
    assert store.get_trade("trade-1") is not None


def test_live_executor_does_not_record_rejected_market_open(tmp_path):
    class FakeExchange:
        def market_open(self, name, is_buy, sz, slippage):
            return {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {"statuses": [{"error": "Order must have minimum value of $10. asset=74"}]},
                },
            }

    store = StateStore(tmp_path / "agent.sqlite")
    executor = HyperliquidLiveExecutor(store, FakeExchange())
    plan = ExecutionPlan(
        trade_id="trade-1",
        symbol="NEAR-USDC",
        side=Side.SHORT,
        action=DecisionAction.SHORT,
        notional_usd=1,
        entry_px=2.0,
        stop_loss_px=2.2,
        take_profit_px=1.8,
        leverage=10,
        size_base=0.5,
    )

    result = executor.open_position(plan)

    assert result.submitted is False
    assert "minimum value" in result.message
    assert store.get_trade("trade-1") is None


def test_live_executor_delegates_market_close_to_hyperliquid_sdk(tmp_path):
    class FakeExchange:
        def __init__(self):
            self.calls = []

        def market_close(self, coin, slippage):
            self.calls.append(("market_close", coin, slippage))
            return {"status": "ok"}

    executor = HyperliquidLiveExecutor(StateStore(tmp_path / "agent.sqlite"), FakeExchange())

    result = executor.close_position("NEAR-USDC", "risk_exit")

    assert result.submitted is True
    assert result.message == "live close submitted: risk_exit"
