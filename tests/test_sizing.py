from decimal import Decimal

from near_agent.config import Settings
from near_agent.sizing import VolatilitySizer
from near_agent.strategy import Candle


def candle(open_px, high, low, close):
    return Candle(open=open_px, high=high, low=low, close=close, volume=1000)


def test_volatility_sizer_keeps_fixed_notional_and_caps_leverage_at_ten():
    candles = [
        candle(2.0, 2.04, 1.98, 2.02),
        candle(2.02, 2.06, 2.0, 2.04),
        candle(2.04, 2.08, 2.02, 2.06),
        candle(2.06, 2.1, 2.04, 2.08),
    ]
    settings = Settings(_env_file=None, fixed_notional_usd=Decimal("10"), max_leverage=Decimal("10"))

    sizing = VolatilitySizer(settings).calculate(candles, price=2.0)

    assert sizing.notional_usd == Decimal("10")
    assert sizing.leverage <= Decimal("10")
    assert sizing.size_base == 5.0
    assert sizing.atr_pct > 0


def test_volatility_sizer_reduces_leverage_when_near_volatility_is_high():
    candles = [
        candle(2.0, 2.4, 1.6, 2.2),
        candle(2.2, 2.5, 1.7, 2.1),
        candle(2.1, 2.6, 1.8, 2.3),
        candle(2.3, 2.7, 1.9, 2.4),
    ]
    settings = Settings(_env_file=None, fixed_notional_usd=Decimal("10"), max_leverage=Decimal("10"))

    sizing = VolatilitySizer(settings).calculate(candles, price=2.0)

    assert sizing.leverage == Decimal("1")
