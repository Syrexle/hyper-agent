import pytest

from near_agent.config import Settings


def test_defaults_are_safe_for_dry_run():
    settings = Settings()

    assert settings.live_trading is False
    assert settings.symbol == "NEAR-USDC"
    assert settings.fixed_notional_usd == 10
    assert settings.max_leverage == 2
    assert settings.confirm_first_n_trades == 5
    assert settings.rootai_mcp_url == "https://mcp.rootai.wtf/mcp"


def test_live_mode_requires_private_key_and_account_address():
    settings = Settings(live_trading=True)

    with pytest.raises(ValueError, match="HYPERLIQUID_PRIVATE_KEY"):
        settings.validate_for_startup()


def test_live_mode_accepts_required_secrets():
    settings = Settings(
        live_trading=True,
        hyperliquid_private_key="0x" + "1" * 64,
        hyperliquid_account_address="0x" + "2" * 40,
    )

    settings.validate_for_startup()


def test_rejects_effective_leverage_above_two():
    settings = Settings(max_leverage=3)

    with pytest.raises(ValueError, match="MAX_LEVERAGE"):
        settings.validate_for_startup()


def test_rejects_non_positive_notional():
    settings = Settings(fixed_notional_usd=0)

    with pytest.raises(ValueError, match="FIXED_NOTIONAL_USD"):
        settings.validate_for_startup()


def test_rejects_negative_confirmation_count():
    settings = Settings(confirm_first_n_trades=-1)

    with pytest.raises(ValueError, match="CONFIRM_FIRST_N_TRADES"):
        settings.validate_for_startup()
