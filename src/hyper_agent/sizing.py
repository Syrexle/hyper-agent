from dataclasses import dataclass
from decimal import Decimal

from hyper_agent.config import Settings
from hyper_agent.strategy import Candle, calculate_atr


@dataclass(frozen=True, slots=True)
class PositionSizing:
    notional_usd: Decimal
    leverage: Decimal
    size_base: float
    atr_pct: float


class VolatilitySizer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def calculate(self, candles: list[Candle], *, price: float) -> PositionSizing:
        atr = calculate_atr(candles, period=self.settings.atr_period)
        atr_pct = (atr / price) * 100 if price > 0 else 0.0
        leverage = self._leverage_for_volatility(atr_pct)
        return PositionSizing(
            notional_usd=self.settings.fixed_notional_usd,
            leverage=leverage,
            size_base=round(float(self.settings.fixed_notional_usd) / price, 8),
            atr_pct=round(atr_pct, 8),
        )

    def _leverage_for_volatility(self, atr_pct: float) -> Decimal:
        if atr_pct <= float(self.settings.volatility_target_pct):
            return self.settings.max_leverage
        return Decimal("1")
