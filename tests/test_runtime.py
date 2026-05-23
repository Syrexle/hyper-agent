from datetime import datetime
from zoneinfo import ZoneInfo

from near_agent.config import Settings
from near_agent.models import PositionSnapshot, Side
from near_agent.runtime import build_position_exit_reason_provider, build_trailing_exit_reason_provider
from near_agent.state import StateStore
from near_agent.trailing import PositionControls


def test_position_exit_provider_flattens_after_configured_local_time():
    settings = Settings(end_of_day_flatten_time="23:30", local_timezone="America/New_York")
    provider = build_position_exit_reason_provider(
        settings,
        now_provider=lambda: datetime(2026, 5, 22, 23, 31, tzinfo=ZoneInfo("America/New_York")),
    )

    reason = provider(PositionSnapshot("NEAR-USDC", Side.LONG, 4, 2.4, 0.2))

    assert reason == "end_of_day_flatten"


def test_position_exit_provider_holds_before_configured_local_time():
    settings = Settings(end_of_day_flatten_time="23:30", local_timezone="America/New_York")
    provider = build_position_exit_reason_provider(
        settings,
        now_provider=lambda: datetime(2026, 5, 22, 23, 29, tzinfo=ZoneInfo("America/New_York")),
    )

    reason = provider(PositionSnapshot("NEAR-USDC", Side.LONG, 4, 2.4, 0.2))

    assert reason is None


def test_trailing_exit_provider_updates_and_persists_trailing_stop(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.upsert_position_controls(
        PositionControls(
            symbol="NEAR-USDC",
            side=Side.LONG,
            entry_px=2.0,
            initial_stop_px=1.94,
        )
    )
    provider = build_trailing_exit_reason_provider(
        Settings(_env_file=None, trailing_start_pct=1, trailing_distance_pct=0.5),
        store,
        mark_price_provider=lambda: 2.04,
    )

    reason = provider(PositionSnapshot("NEAR-USDC", Side.LONG, 4, 2.0, 0.1))

    assert reason is None
    loaded = store.get_position_controls("NEAR-USDC")
    assert loaded is not None
    assert round(loaded.trailing_stop_px or 0, 4) == 2.0298


def test_trailing_exit_provider_returns_reason_when_stop_is_hit(tmp_path):
    store = StateStore(tmp_path / "agent.sqlite")
    store.upsert_position_controls(
        PositionControls(
            symbol="NEAR-USDC",
            side=Side.LONG,
            entry_px=2.0,
            initial_stop_px=1.94,
            trailing_stop_px=2.03,
        )
    )
    provider = build_trailing_exit_reason_provider(
        Settings(_env_file=None, trailing_start_pct=1, trailing_distance_pct=0.5),
        store,
        mark_price_provider=lambda: 2.02,
    )

    reason = provider(PositionSnapshot("NEAR-USDC", Side.LONG, 4, 2.0, -0.1))

    assert reason == "trailing stop 2.030000"
