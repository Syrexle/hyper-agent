from dataclasses import dataclass

from near_agent.models import Decision, DecisionAction


@dataclass(frozen=True, slots=True)
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float


def calculate_atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0

    ranges: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    selected = ranges[-period:]
    if not selected:
        return 0.0
    return round(sum(selected) / len(selected), 8)


class NearStrategy:
    def __init__(self, symbol: str = "NEAR-USDC"):
        self.symbol = symbol

    def evaluate(self, candles: list[Candle]) -> Decision:
        if len(candles) < 20:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SKIP,
                allowed=False,
                rationale="Insufficient candle history for NEAR intraday swing signal",
            )

        last = candles[-1]
        atr = calculate_atr(candles, period=14)
        closes = [c.close for c in candles]
        short_ma = sum(closes[-5:]) / 5
        long_ma = sum(closes[-20:]) / 20
        recent_return = (closes[-1] - closes[-6]) / closes[-6]
        range_position = (last.close - last.low) / max(last.high - last.low, 1e-9)

        if last.close > short_ma > long_ma and recent_return > 0.04 and range_position > 0.65:
            stop = last.close - max(atr * 1.5, last.close * 0.012)
            target = last.close + max(atr * 2.25, last.close * 0.02)
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.LONG,
                allowed=True,
                rationale="Trend continuation long: price is above short and long averages with strong recent momentum",
                stop_loss_px=round(stop, 6),
                take_profit_px=round(target, 6),
            )

        stretch = (last.close - long_ma) / long_ma
        previous = candles[-2]
        prior = candles[-3]
        momentum_stalling = last.close < previous.close < prior.close
        if stretch > 0.15 and momentum_stalling:
            stop = last.close + max(atr * 1.5, last.close * 0.012)
            target = last.close - max(atr * 2.25, last.close * 0.02)
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SHORT,
                allowed=True,
                rationale="Stretched mean-reversion short: price is extended above average and latest closes show weakening momentum",
                stop_loss_px=round(stop, 6),
                take_profit_px=round(target, 6),
            )

        return Decision(
            symbol=self.symbol,
            action=DecisionAction.SKIP,
            allowed=False,
            rationale="No NEAR setup: trend and mean-reversion filters are not aligned",
        )
