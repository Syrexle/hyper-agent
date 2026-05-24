from hyper_agent.backtest import BacktestEngine
from hyper_agent.config import Settings
from hyper_agent.strategy import Candle, MultiTimeframeEmaStrategy


def candle(px):
    return Candle(open=px, high=px + 0.02, low=px - 0.02, close=px, volume=1000)


def test_backtest_returns_summary_for_near_strategy():
    prices = [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.05, 2.15, 2.1, 2.0, 1.9, 1.85, 1.8]
    candles = [candle(px) for px in prices]
    strategy = MultiTimeframeEmaStrategy(symbol="NEAR-USDC", ema_fast=2, ema_slow=4, min_atr_pct=0, min_ema_spread_pct=0)

    result = BacktestEngine(Settings(_env_file=None), strategy=strategy).run(candles)

    assert result["symbol"] == "NEAR-USDC"
    assert result["trades"] >= 1
    assert "total_return_pct" in result
    assert "win_rate_pct" in result


def test_backtest_reports_fees_funding_slippage_and_net_return():
    prices = [2, 1.95, 1.9, 1.88, 1.9, 1.95, 2.05, 2.15, 2.1, 2.0, 1.9, 1.85, 1.8]
    candles = [candle(px) for px in prices]
    settings = Settings(
        _env_file=None,
        backtest_fee_bps=5,
        backtest_slippage_bps=10,
        backtest_funding_bps=2,
    )
    strategy = MultiTimeframeEmaStrategy(symbol="NEAR-USDC", ema_fast=2, ema_slow=4, min_atr_pct=0, min_ema_spread_pct=0)

    result = BacktestEngine(settings, strategy=strategy).run(candles)

    assert result["gross_return_pct"] > result["total_return_pct"]
    assert result["total_cost_usd"] > 0
    assert result["fee_cost_usd"] > 0
    assert result["slippage_cost_usd"] > 0
    assert result["funding_cost_usd"] > 0
