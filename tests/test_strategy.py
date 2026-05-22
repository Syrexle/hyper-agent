from near_agent.models import DecisionAction
from near_agent.strategy import Candle, NearStrategy, calculate_atr


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
