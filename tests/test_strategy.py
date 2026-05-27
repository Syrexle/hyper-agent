from hyper_agent.models import DecisionAction
from hyper_agent.strategy import (
    Candle,
    CompositeStrategy,
    FundingRateSentimentStrategy,
    MultiTimeframeEmaStrategy,
    NearStrategy,
    RsiExtremeStrategy,
    calculate_atr,
    calculate_rsi,
    ema_values,
)


def candle(open_px, high, low, close):
    return Candle(open=open_px, high=high, low=low, close=close, volume=1000)


def test_calculates_atr_from_true_ranges():
    candles = [
        candle(10, 12, 9, 11),
        candle(11, 13, 10, 12),
        candle(12, 15, 11, 14),
    ]

    assert calculate_atr(candles, period=2) == 3.5


def test_returns_skip_when_data_is_insufficient():
    strategy = NearStrategy()

    decision = strategy.evaluate([candle(1, 1.1, 0.9, 1.0)])

    assert decision.action == DecisionAction.SKIP
    assert "insufficient" in decision.rationale.lower()


def test_detects_trend_continuation_long():
    candles = [candle(1 + i * 0.02, 1.04 + i * 0.02, 0.99 + i * 0.02, 1.03 + i * 0.02) for i in range(20)]

    decision = NearStrategy().evaluate(candles)

    assert decision.action == DecisionAction.LONG
    assert decision.stop_loss_px < candles[-1].close
    assert decision.take_profit_px > candles[-1].close
    assert "trend" in decision.rationale.lower()


def test_detects_stretched_weakening_short():
    candles = [candle(1 + i * 0.01, 1.03 + i * 0.01, 0.99 + i * 0.01, 1.02 + i * 0.01) for i in range(17)]
    candles.extend(
        [
            candle(1.45, 1.55, 1.42, 1.53),
            candle(1.53, 1.56, 1.48, 1.50),
            candle(1.50, 1.52, 1.44, 1.46),
        ]
    )

    decision = NearStrategy().evaluate(candles)

    assert decision.action == DecisionAction.SHORT
    assert decision.stop_loss_px > candles[-1].close
    assert decision.take_profit_px < candles[-1].close
    assert "stretched" in decision.rationale.lower()


def test_calculates_ema_values():
    values = ema_values([1, 2, 3], period=3)

    assert values == [1, 1.5, 2.25]


def test_multi_timeframe_ema_confirms_near_long_signal():
    primary = [candle(px, px + 0.02, px - 0.02, px) for px in [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.05, 2.15]]
    confirm = [candle(px, px + 0.02, px - 0.02, px) for px in [1.8, 1.85, 1.9, 1.95, 2.0, 2.05, 2.1, 2.2]]
    strategy = MultiTimeframeEmaStrategy(symbol="NEAR-USDC", ema_fast=2, ema_slow=4)

    decision = strategy.evaluate(primary, confirm)

    assert decision.action == DecisionAction.LONG
    assert decision.stop_loss_px < primary[-1].close
    assert decision.take_profit_px > primary[-1].close
    assert "multi-timeframe ema" in decision.rationale.lower()


def test_multi_timeframe_ema_blocks_primary_signal_when_confirm_timeframe_disagrees():
    primary = [candle(px, px + 0.02, px - 0.02, px) for px in [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.05, 2.15]]
    confirm = [candle(px, px + 0.02, px - 0.02, px) for px in [2.2, 2.15, 2.1, 2.05, 2.0, 1.95, 1.9, 1.85]]
    strategy = MultiTimeframeEmaStrategy(symbol="NEAR-USDC", ema_fast=2, ema_slow=4)

    decision = strategy.evaluate(primary, confirm)

    assert decision.action == DecisionAction.SKIP
    assert "not aligned" in decision.rationale.lower()


def test_multi_timeframe_ema_blocks_when_atr_is_too_low():
    primary = [candle(px, px + 0.001, px - 0.001, px) for px in [2, 1.99, 1.98, 1.97, 1.98, 1.99, 2.01, 2.02]]
    confirm = [candle(px, px + 0.001, px - 0.001, px) for px in [1.9, 1.92, 1.94, 1.96, 1.98, 2.0, 2.02, 2.04]]
    strategy = MultiTimeframeEmaStrategy(
        symbol="NEAR-USDC",
        ema_fast=2,
        ema_slow=4,
        min_atr_pct=1.0,
    )

    decision = strategy.evaluate(primary, confirm)

    assert decision.action == DecisionAction.SKIP
    assert "atr" in decision.rationale.lower()


def test_multi_timeframe_ema_blocks_chop_when_ema_spread_is_too_small():
    primary = [candle(px, px + 0.02, px - 0.02, px) for px in [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.05, 2.15]]
    confirm = [candle(px, px + 0.02, px - 0.02, px) for px in [1.8, 1.85, 1.9, 1.95, 2.0, 2.05, 2.1, 2.2]]
    strategy = MultiTimeframeEmaStrategy(
        symbol="NEAR-USDC",
        ema_fast=2,
        ema_slow=4,
        min_ema_spread_pct=20.0,
    )

    decision = strategy.evaluate(primary, confirm)

    assert decision.action == DecisionAction.SKIP
    assert "spread" in decision.rationale.lower()


def test_multi_timeframe_ema_blocks_overextended_trend_entry():
    primary = [candle(px, px + 0.04, px - 0.04, px) for px in [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.2, 2.7]]
    confirm = [candle(px, px + 0.04, px - 0.04, px) for px in [1.8, 1.85, 1.9, 1.95, 2.0, 2.05, 2.1, 2.2]]
    strategy = MultiTimeframeEmaStrategy(
        symbol="NEAR-USDC",
        ema_fast=2,
        ema_slow=4,
        max_extension_pct=5.0,
    )

    decision = strategy.evaluate(primary, confirm)

    assert decision.action == DecisionAction.SKIP
    assert "extended" in decision.rationale.lower()


# RSI tests

def make_candles_with_closes(closes: list[float]) -> list[Candle]:
    return [Candle(open=c, high=c + 0.05, low=c - 0.05, close=c, volume=1000) for c in closes]


def test_calculate_rsi_returns_empty_for_insufficient_data():
    assert calculate_rsi(make_candles_with_closes([1.0] * 10), period=14) == []


def test_calculate_rsi_returns_100_when_no_losses():
    # All prices rising — avg_loss stays 0, RSI should be 100
    closes = [float(i) for i in range(1, 20)]
    rsi = calculate_rsi(make_candles_with_closes(closes), period=14)
    assert len(rsi) >= 1
    assert all(r == 100.0 for r in rsi)


def test_calculate_rsi_returns_0_when_no_gains():
    closes = [float(20 - i) for i in range(20)]
    rsi = calculate_rsi(make_candles_with_closes(closes), period=14)
    assert len(rsi) >= 1
    assert all(r == 0.0 for r in rsi)


def test_rsi_extreme_skips_when_insufficient_data():
    strategy = RsiExtremeStrategy(period=14)
    candles = make_candles_with_closes([2.0] * 10)
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.SKIP
    assert "insufficient" in decision.rationale.lower()


def test_rsi_extreme_signals_short_on_overbought_cross():
    # 17 rising candles push RSI to 100; a large drop crosses it below 70
    closes = [1.0 + i * 0.15 for i in range(17)]
    closes.append(closes[-1] - 1.5)  # drop of 1.5 brings RSI to ~57 (crosses below 70)
    strategy = RsiExtremeStrategy(period=14, overbought=70.0, oversold=30.0)
    candles = make_candles_with_closes(closes)
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.SHORT
    assert decision.stop_loss_px > candles[-1].close
    assert decision.take_profit_px < candles[-1].close
    assert "overbought" in decision.rationale.lower()


def test_rsi_extreme_signals_long_on_oversold_cross():
    # 17 falling candles push RSI to 0; a large rise crosses it above 30
    closes = [5.0 - i * 0.15 for i in range(17)]
    closes.append(closes[-1] + 1.5)  # rise of 1.5 brings RSI to ~43 (crosses above 30)
    strategy = RsiExtremeStrategy(period=14, overbought=70.0, oversold=30.0)
    candles = make_candles_with_closes(closes)
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.LONG
    assert decision.stop_loss_px < candles[-1].close
    assert decision.take_profit_px > candles[-1].close
    assert "oversold" in decision.rationale.lower()


def test_rsi_extreme_skips_when_rsi_is_mid_range():
    # Alternating candles → RSI stays near 50
    closes = [2.0 + (0.1 if i % 2 == 0 else -0.1) for i in range(20)]
    strategy = RsiExtremeStrategy(period=14)
    decision = strategy.evaluate(make_candles_with_closes(closes), [])
    assert decision.action == DecisionAction.SKIP


# Funding rate sentiment tests

def test_funding_rate_signals_short_on_high_positive_rate():
    candles = make_candles_with_closes([2.0] * 20)
    strategy = FundingRateSentimentStrategy(
        funding_provider=lambda: 0.002,
        threshold=0.001,
    )
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.SHORT
    assert decision.stop_loss_px > candles[-1].close
    assert decision.take_profit_px < candles[-1].close
    assert "overleveraged long" in decision.rationale.lower()


def test_funding_rate_signals_long_on_high_negative_rate():
    candles = make_candles_with_closes([2.0] * 20)
    strategy = FundingRateSentimentStrategy(
        funding_provider=lambda: -0.002,
        threshold=0.001,
    )
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.LONG
    assert decision.stop_loss_px < candles[-1].close
    assert decision.take_profit_px > candles[-1].close
    assert "overleveraged short" in decision.rationale.lower()


def test_funding_rate_skips_when_neutral():
    candles = make_candles_with_closes([2.0] * 20)
    strategy = FundingRateSentimentStrategy(
        funding_provider=lambda: 0.0005,
        threshold=0.001,
    )
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.SKIP
    assert "neutral" in decision.rationale.lower()


def test_funding_rate_skips_when_provider_raises():
    candles = make_candles_with_closes([2.0] * 20)
    def failing_provider():
        raise RuntimeError("network error")
    strategy = FundingRateSentimentStrategy(funding_provider=failing_provider, threshold=0.001)
    decision = strategy.evaluate(candles, [])
    assert decision.action == DecisionAction.SKIP
    assert "unavailable" in decision.rationale.lower()


# Composite strategy tests

def test_composite_returns_first_non_skip():
    always_skip = RsiExtremeStrategy(period=14)  # insufficient candles → always skip
    always_short = FundingRateSentimentStrategy(funding_provider=lambda: 0.005, threshold=0.001)
    composite = CompositeStrategy([always_skip, always_short], symbol="NEAR-USDC")
    candles = make_candles_with_closes([2.0] * 10)
    decision = composite.evaluate(candles, [])
    assert decision.action == DecisionAction.SHORT


def test_composite_returns_skip_with_joined_rationale_when_all_skip():
    s1 = FundingRateSentimentStrategy(funding_provider=lambda: 0.0, threshold=0.001)
    s2 = FundingRateSentimentStrategy(funding_provider=lambda: 0.0, threshold=0.001)
    composite = CompositeStrategy([s1, s2], symbol="NEAR-USDC")
    decision = composite.evaluate(make_candles_with_closes([2.0] * 5), [])
    assert decision.action == DecisionAction.SKIP
    assert "|" in decision.rationale
