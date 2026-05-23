from datetime import datetime
from zoneinfo import ZoneInfo

from near_agent.config import Settings
from near_agent.models import PositionSnapshot, Side
from near_agent.runtime import build_position_exit_reason_provider


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
