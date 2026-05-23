import pytest

from near_agent.config import Settings


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def test_defaults_are_safe_for_dry_run():
    settings = make_settings()

    assert settings.live_trading is False
    assert settings.symbol == "NEAR-USDC"
    assert settings.fixed_notional_usd == 10
    assert settings.max_leverage == 10
    assert settings.confirm_first_n_trades == 5
    assert settings.rootai_mcp_url == "https://mcp.rootai.wtf/mcp"
    assert settings.venice_base_url == "https://api.venice.ai/api/v1"
    assert settings.primary_timeframe == "1h"
    assert settings.confirm_timeframe == "4h"
    assert settings.trailing_start_pct == 1


def test_live_mode_requires_private_key_and_account_address():
    settings = make_settings(live_trading=True)

    with pytest.raises(ValueError, match="HYPERLIQUID_PRIVATE_KEY"):
        settings.validate_for_startup()


def test_live_mode_accepts_required_secrets():
    settings = make_settings(
        live_trading=True,
        hyperliquid_private_key="0x" + "1" * 64,
        hyperliquid_account_address="0x" + "2" * 40,
    )

    settings.validate_for_startup()


def test_rejects_effective_leverage_above_ten():
    settings = make_settings(max_leverage=11)

    with pytest.raises(ValueError, match="MAX_LEVERAGE"):
        settings.validate_for_startup()


def test_rejects_non_positive_notional():
    settings = make_settings(fixed_notional_usd=0)

    with pytest.raises(ValueError, match="FIXED_NOTIONAL_USD"):
        settings.validate_for_startup()


def test_rejects_negative_confirmation_count():
    settings = make_settings(confirm_first_n_trades=-1)

    with pytest.raises(ValueError, match="CONFIRM_FIRST_N_TRADES"):
        settings.validate_for_startup()


def test_venice_provider_requires_api_key_when_llm_required():
    settings = make_settings(llm_provider="venice", llm_required=True)

    with pytest.raises(ValueError, match="VENICE_API_KEY"):
        settings.validate_for_startup()


def test_venice_provider_accepts_api_key():
    settings = make_settings(llm_provider="venice", llm_required=True, venice_api_key="venice-key")

    settings.validate_for_startup()


def test_rejects_unsupported_timeframes():
    settings = make_settings(primary_timeframe="2h")

    with pytest.raises(ValueError, match="PRIMARY_TIMEFRAME"):
        settings.validate_for_startup()
