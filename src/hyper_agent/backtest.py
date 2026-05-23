from hyper_agent.config import Settings
from hyper_agent.strategy import Candle, MultiTimeframeEmaStrategy, ema_values, calculate_atr


class BacktestEngine:
    def __init__(self, settings: Settings, *, strategy: MultiTimeframeEmaStrategy | None = None):
        self.settings = settings
        self.strategy = strategy or MultiTimeframeEmaStrategy(
            symbol=settings.symbol,
            ema_fast=settings.ema_fast,
            ema_slow=settings.ema_slow,
            atr_period=settings.atr_period,
            initial_stop_pct=float(settings.initial_stop_pct),
            min_atr_pct=float(settings.min_atr_pct),
            min_ema_spread_pct=float(settings.min_ema_spread_pct),
            max_extension_pct=float(settings.max_extension_pct),
        )

    def run(self, candles: list[Candle]) -> dict:
        s = self.strategy
        closes = [c.close for c in candles]

        # Compute EMA for full series once — O(n) instead of O(n²)
        fast_ema = ema_values(closes, s.ema_fast)
        slow_ema = ema_values(closes, s.ema_slow)

        capital = 1000.0
        gross_capital = 1000.0
        position: dict | None = None
        trades: list[dict] = []
        total_fee_cost = 0.0
        total_slippage_cost = 0.0
        total_funding_cost = 0.0

        start = max(s.ema_slow + 2, 4)
        for idx in range(start, len(candles)):
            prev_bullish = fast_ema[idx - 1] > slow_ema[idx - 1]
            curr_bullish = fast_ema[idx] > slow_ema[idx]

            if prev_bullish == curr_bullish:
                signal = None
            elif not prev_bullish and curr_bullish:
                signal = "long"
            else:
                signal = "short"

            price = candles[idx].close

            if position is None and signal in ("long", "short"):
                # Apply filters: ATR, EMA spread, extension
                atr = calculate_atr(candles[:idx + 1], s.atr_period)
                atr_pct = atr / price * 100 if price else 0
                spread_pct = abs((fast_ema[idx] - slow_ema[idx]) / slow_ema[idx] * 100) if slow_ema[idx] else 0
                extension_pct = abs((price - slow_ema[idx]) / slow_ema[idx] * 100) if slow_ema[idx] else 0

                if (atr_pct >= s.min_atr_pct
                        and spread_pct >= s.min_ema_spread_pct
                        and extension_pct <= s.max_extension_pct):
                    position = {
                        "side": signal,
                        "entry": price,
                        "size": float(self.settings.fixed_notional_usd) / price,
                        "notional": float(self.settings.fixed_notional_usd),
                    }
                continue

            if position is None:
                continue

            should_exit = (
                (position["side"] == "long" and signal == "short")
                or (position["side"] == "short" and signal == "long")
            )
            if not should_exit and idx != len(candles) - 1:
                continue

            if position["side"] == "long":
                pnl = position["size"] * (price - position["entry"])
            else:
                pnl = position["size"] * (position["entry"] - price)
            notional = position["notional"]
            fee_cost = notional * float(self.settings.backtest_fee_bps) / 10_000 * 2
            slippage_cost = notional * float(self.settings.backtest_slippage_bps) / 10_000 * 2
            funding_cost = notional * float(self.settings.backtest_funding_bps) / 10_000
            net_pnl = pnl - fee_cost - slippage_cost - funding_cost
            gross_capital += pnl
            capital += net_pnl
            total_fee_cost += fee_cost
            total_slippage_cost += slippage_cost
            total_funding_cost += funding_cost
            trades.append({
                "gross_pnl": pnl,
                "pnl": net_pnl,
                "return_pct": net_pnl / (position["size"] * position["entry"]) * 100,
            })
            position = None

        winners = [t for t in trades if t["pnl"] > 0]
        return {
            "symbol": self.settings.symbol,
            "final_capital": round(capital, 4),
            "gross_final_capital": round(gross_capital, 4),
            "gross_return_pct": round((gross_capital - 1000.0) / 1000.0 * 100, 4),
            "total_return_pct": round((capital - 1000.0) / 1000.0 * 100, 4),
            "total_cost_usd": round(total_fee_cost + total_slippage_cost + total_funding_cost, 4),
            "fee_cost_usd": round(total_fee_cost, 4),
            "slippage_cost_usd": round(total_slippage_cost, 4),
            "funding_cost_usd": round(total_funding_cost, 4),
            "trades": len(trades),
            "win_rate_pct": round(len(winners) / len(trades) * 100, 4) if trades else 0.0,
            "avg_trade_pct": round(sum(t["return_pct"] for t in trades) / len(trades), 4) if trades else 0.0,
        }
