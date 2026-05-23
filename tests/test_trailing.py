from near_agent.models import Side
from near_agent.trailing import PositionControls, TrailingStopManager


def test_trailing_stop_activates_after_profit_threshold_for_long():
    controls = PositionControls(
        symbol="NEAR-USDC",
        side=Side.LONG,
        entry_px=2.0,
        initial_stop_px=1.94,
    )
    manager = TrailingStopManager(start_pct=1.0, distance_pct=0.5)

    update = manager.update(controls, mark_px=2.04)

    assert update is not None
    assert round(controls.trailing_stop_px or 0, 4) == 2.0298
    assert controls.highest_pnl_pct == 2.0
    assert controls.max_drawdown_pct == 0.0


def test_trailing_controls_track_max_drawdown():
    controls = PositionControls(
        symbol="NEAR-USDC",
        side=Side.LONG,
        entry_px=2.0,
        initial_stop_px=1.94,
    )
    manager = TrailingStopManager(start_pct=1.0, distance_pct=0.5)

    manager.update(controls, mark_px=1.96)

    assert controls.max_drawdown_pct == -2.0


def test_trailing_stop_exit_triggers_for_short():
    controls = PositionControls(
        symbol="NEAR-USDC",
        side=Side.SHORT,
        entry_px=2.0,
        initial_stop_px=2.06,
        trailing_stop_px=1.95,
    )
    manager = TrailingStopManager(start_pct=1.0, distance_pct=0.5)

    should_exit, reason = manager.check_exit(controls, mark_px=1.96)

    assert should_exit is True
    assert "trailing stop" in reason.lower()
