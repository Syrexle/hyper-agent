from near_agent.backtest import BacktestEngine
from near_agent.config import Settings
from near_agent.strategy import Candle, MultiTimeframeEmaStrategy


def candle(px):
    return Candle(open=px, high=px + 0.02, low=px - 0.02, close=px, volume=1000)


def test_backtest_returns_summary_for_near_strategy():
    prices = [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.05, 2.15, 2.1, 2.0, 1.9, 1.85, 1.8]
    candles = [candle(px) for px in prices]
    strategy = MultiTimeframeEmaStrategy(symbol="NEAR-USDC", ema_fast=2, ema_slow=4)

    result = BacktestEngine(Settings(_env_file=None), strategy=strategy).run(candles)

    assert result["symbol"] == "NEAR-USDC"
    assert result["trades"] >= 1
    assert "total_return_pct" in result
    assert "win_rate_pct" in result
