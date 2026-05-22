from near_agent.executor import DryRunExecutor, ExecutionPlan, LiveExecutionGate
from near_agent.models import DecisionAction, Side
from near_agent.state import StateStore


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
