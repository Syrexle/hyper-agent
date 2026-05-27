from hyper_agent.config import Settings
from hyper_agent.models import PositionSnapshot, Side
from hyper_agent.runtime import build_trailing_exit_reason_provider
from hyper_agent.state import StateStore
from hyper_agent.trailing import PositionControls


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
        mark_price_provider=lambda symbol: 2.04,
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
        mark_price_provider=lambda symbol: 2.02,
    )

    reason = provider(PositionSnapshot("NEAR-USDC", Side.LONG, 4, 2.0, -0.1))

    assert reason == "trailing stop 2.030000"
