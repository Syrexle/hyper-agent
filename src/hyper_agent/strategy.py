from collections.abc import Callable
from dataclasses import dataclass

from hyper_agent.models import Decision, DecisionAction


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


def ema_values(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(result[-1] + alpha * (float(value) - result[-1]))
    return [round(value, 8) for value in result]


class MultiTimeframeEmaStrategy:
    def __init__(
        self,
        *,
        symbol: str = "NEAR-USDC",
        ema_fast: int = 9,
        ema_slow: int = 21,
        atr_period: int = 14,
        initial_stop_pct: float = 2.0,
        min_atr_pct: float = 0.75,
        min_ema_spread_pct: float = 0.35,
        max_extension_pct: float = 8.0,
    ):
        if ema_fast >= ema_slow:
            raise ValueError("ema_fast must be less than ema_slow")
        self.symbol = symbol
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.initial_stop_pct = initial_stop_pct
        self.min_atr_pct = min_atr_pct
        self.min_ema_spread_pct = min_ema_spread_pct
        self.max_extension_pct = max_extension_pct

    def evaluate(self, primary: list[Candle], confirm: list[Candle]) -> Decision:
        minimum = self.ema_slow + 2
        if len(primary) < minimum or len(confirm) < minimum:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SKIP,
                allowed=False,
                rationale="Insufficient candle history for multi-timeframe EMA signal",
            )

        primary_signal = self._crossover_signal(primary)
        confirm_trend = self._trend(confirm)
        if primary_signal in {DecisionAction.LONG, DecisionAction.SHORT}:
            filter_reason = self._filter_reason(primary, confirm, primary_signal)
            if filter_reason:
                return Decision(
                    symbol=self.symbol,
                    action=DecisionAction.SKIP,
                    allowed=False,
                    rationale=filter_reason,
                )
        if primary_signal == DecisionAction.LONG and confirm_trend == DecisionAction.LONG:
            return self._decision(primary, DecisionAction.LONG)
        if primary_signal == DecisionAction.SHORT and confirm_trend == DecisionAction.SHORT:
            return self._decision(primary, DecisionAction.SHORT)
        return Decision(
            symbol=self.symbol,
            action=DecisionAction.SKIP,
            allowed=False,
            rationale="No NEAR setup: multi-timeframe EMA signals are not aligned",
        )

    def _crossover_signal(self, candles: list[Candle]) -> DecisionAction:
        closes = [c.close for c in candles]
        fast = ema_values(closes, self.ema_fast)
        slow = ema_values(closes, self.ema_slow)
        start = max(1, len(closes) - 4)
        for idx in range(start, len(closes)):
            was_bullish = fast[idx - 1] > slow[idx - 1]
            is_bullish = fast[idx] > slow[idx]
            if not was_bullish and is_bullish:
                return DecisionAction.LONG
            if was_bullish and not is_bullish:
                return DecisionAction.SHORT
        return DecisionAction.SKIP

    def _trend(self, candles: list[Candle]) -> DecisionAction:
        closes = [c.close for c in candles]
        fast = ema_values(closes, self.ema_fast)
        slow = ema_values(closes, self.ema_slow)
        return DecisionAction.LONG if fast[-1] > slow[-1] else DecisionAction.SHORT

    def _filter_reason(self, primary: list[Candle], confirm: list[Candle], action: DecisionAction) -> str | None:
        primary_stats = self._ema_stats(primary)
        confirm_stats = self._ema_stats(confirm)
        last = primary[-1]
        atr_pct = calculate_atr(primary, self.atr_period) / last.close * 100
        if atr_pct < self.min_atr_pct:
            return f"No NEAR setup: ATR {atr_pct:.4f}% is below minimum {self.min_atr_pct:.4f}%"

        strong_primary = primary_stats["spread_pct"] >= self.min_ema_spread_pct
        strong_confirm = confirm_stats["spread_pct"] >= self.min_ema_spread_pct
        if not strong_primary or not strong_confirm:
            return (
                "No NEAR setup: EMA spread is too small to avoid chop "
                f"(primary {primary_stats['spread_pct']:.4f}%, confirm {confirm_stats['spread_pct']:.4f}%)"
            )

        extension_pct = abs((last.close - primary_stats["slow"]) / primary_stats["slow"] * 100)
        if extension_pct > self.max_extension_pct:
            return (
                f"No NEAR setup: price is extended {extension_pct:.4f}% from slow EMA, "
                f"above max {self.max_extension_pct:.4f}%"
            )
        return None

    def _ema_stats(self, candles: list[Candle]) -> dict[str, float]:
        closes = [c.close for c in candles]
        fast = ema_values(closes, self.ema_fast)[-1]
        slow = ema_values(closes, self.ema_slow)[-1]
        return {
            "fast": fast,
            "slow": slow,
            "spread_pct": abs((fast - slow) / slow * 100),
        }

    def _decision(self, candles: list[Candle], action: DecisionAction) -> Decision:
        last = candles[-1]
        atr = calculate_atr(candles, self.atr_period)
        stop_distance = max(atr * 1.5, last.close * self.initial_stop_pct / 100)
        target_distance = max(atr * 2.25, last.close * self.initial_stop_pct * 1.5 / 100)
        if action == DecisionAction.LONG:
            stop = last.close - stop_distance
            target = last.close + target_distance
        else:
            stop = last.close + stop_distance
            target = last.close - target_distance
        return Decision(
            symbol=self.symbol,
            action=action,
            allowed=True,
            rationale=f"Multi-timeframe EMA {action.value}: primary crossover confirmed by higher timeframe trend",
            stop_loss_px=round(stop, 6),
            take_profit_px=round(target, 6),
        )


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


def calculate_rsi(candles: list[Candle], period: int = 14) -> list[float]:
    closes = [c.close for c in candles]
    if len(closes) < period + 2:
        return []
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = []
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
        rsi = 100.0 if avg_loss == 0 else round(100 - (100 / (1 + rs)), 4)
        result.append(rsi)
    return result


class RsiExtremeStrategy:
    def __init__(
        self,
        *,
        symbol: str = "NEAR-USDC",
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        initial_stop_pct: float = 5.0,
    ):
        self.symbol = symbol
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.initial_stop_pct = initial_stop_pct

    def evaluate(self, primary: list[Candle], confirm: list[Candle]) -> Decision:
        rsi = calculate_rsi(primary, self.period)
        if len(rsi) < 2:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SKIP,
                allowed=False,
                rationale="RSI extreme: insufficient candle history",
            )
        prev_rsi, curr_rsi = rsi[-2], rsi[-1]
        last = primary[-1]
        atr = calculate_atr(primary, self.period)
        stop_distance = max(atr * 1.5, last.close * self.initial_stop_pct / 100)
        if curr_rsi > self.overbought:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SHORT,
                allowed=True,
                rationale=f"RSI extreme short: RSI {curr_rsi:.1f} above overbought {self.overbought}",
                stop_loss_px=round(last.close + stop_distance, 6),
                take_profit_px=round(last.close - stop_distance * 1.5, 6),
            )
        if curr_rsi < self.oversold:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.LONG,
                allowed=True,
                rationale=f"RSI extreme long: RSI {curr_rsi:.1f} below oversold {self.oversold}",
                stop_loss_px=round(last.close - stop_distance, 6),
                take_profit_px=round(last.close + stop_distance * 1.5, 6),
            )
        return Decision(
            symbol=self.symbol,
            action=DecisionAction.SKIP,
            allowed=False,
            rationale=f"RSI extreme: neutral (RSI {curr_rsi:.1f})",
        )


class FundingRateSentimentStrategy:
    def __init__(
        self,
        *,
        symbol: str = "NEAR-USDC",
        funding_provider: Callable[[], float],
        threshold: float = 0.001,
        initial_stop_pct: float = 5.0,
    ):
        self.symbol = symbol
        self.funding_provider = funding_provider
        self.threshold = threshold
        self.initial_stop_pct = initial_stop_pct

    def evaluate(self, primary: list[Candle], confirm: list[Candle]) -> Decision:
        try:
            rate = self.funding_provider()
        except Exception:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SKIP,
                allowed=False,
                rationale="Funding rate sentiment: data unavailable",
            )
        if not primary:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SKIP,
                allowed=False,
                rationale="Funding rate sentiment: no candle data for stop calculation",
            )
        last = primary[-1]
        atr = calculate_atr(primary, 14)
        stop_distance = max(atr * 1.5, last.close * self.initial_stop_pct / 100)
        if rate > self.threshold:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.SHORT,
                allowed=True,
                rationale=f"Funding rate sentiment short: rate {rate:.4%} above threshold {self.threshold:.4%} (market overleveraged long)",
                stop_loss_px=round(last.close + stop_distance, 6),
                take_profit_px=round(last.close - stop_distance * 1.5, 6),
            )
        if rate < -self.threshold:
            return Decision(
                symbol=self.symbol,
                action=DecisionAction.LONG,
                allowed=True,
                rationale=f"Funding rate sentiment long: rate {rate:.4%} below -{self.threshold:.4%} (market overleveraged short)",
                stop_loss_px=round(last.close - stop_distance, 6),
                take_profit_px=round(last.close + stop_distance * 1.5, 6),
            )
        return Decision(
            symbol=self.symbol,
            action=DecisionAction.SKIP,
            allowed=False,
            rationale=f"Funding rate sentiment: neutral (rate {rate:.4%})",
        )


class CompositeStrategy:
    def __init__(self, strategies: list, *, symbol: str = "NEAR-USDC"):
        self.strategies = strategies
        self.symbol = symbol

    def evaluate(self, primary: list[Candle], confirm: list[Candle]) -> Decision:
        skips = []
        for strategy in self.strategies:
            decision = strategy.evaluate(primary, confirm)
            if decision.action != DecisionAction.SKIP:
                return decision
            skips.append(decision.rationale)
        return Decision(
            symbol=self.symbol,
            action=DecisionAction.SKIP,
            allowed=False,
            rationale=" | ".join(skips),
        )
