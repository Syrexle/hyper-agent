from near_agent.config import Settings
from near_agent.models import DecisionAction
from near_agent.strategy import Candle, MultiTimeframeEmaStrategy


class BacktestEngine:
    def __init__(self, settings: Settings, *, strategy: MultiTimeframeEmaStrategy | None = None):
        self.settings = settings
        self.strategy = strategy or MultiTimeframeEmaStrategy(
            symbol=settings.symbol,
            ema_fast=settings.ema_fast,
            ema_slow=settings.ema_slow,
            atr_period=settings.atr_period,
            initial_stop_pct=float(settings.initial_stop_pct),
        )

    def run(self, candles: list[Candle]) -> dict:
        capital = 1000.0
        position: dict | None = None
        trades: list[dict] = []

        for idx in range(max(self.strategy.ema_slow + 2, 4), len(candles)):
            window = candles[: idx + 1]
            decision = self.strategy.evaluate(window, window)
            price = candles[idx].close

            if position is None and decision.action in {DecisionAction.LONG, DecisionAction.SHORT}:
                position = {
                    "side": decision.action,
                    "entry": price,
                    "size": float(self.settings.fixed_notional_usd) / price,
                }
                continue

            if position is None:
                continue

            should_exit = (
                position["side"] == DecisionAction.LONG
                and decision.action == DecisionAction.SHORT
                or position["side"] == DecisionAction.SHORT
                and decision.action == DecisionAction.LONG
            )
            if not should_exit and idx != len(candles) - 1:
                continue

            if position["side"] == DecisionAction.LONG:
                pnl = position["size"] * (price - position["entry"])
            else:
                pnl = position["size"] * (position["entry"] - price)
            capital += pnl
            trades.append(
                {
                    "pnl": pnl,
                    "return_pct": pnl / (position["size"] * position["entry"]) * 100,
                }
            )
            position = None

        winners = [trade for trade in trades if trade["pnl"] > 0]
        return {
            "symbol": self.settings.symbol,
            "final_capital": round(capital, 4),
            "total_return_pct": round((capital - 1000.0) / 1000.0 * 100, 4),
            "trades": len(trades),
            "win_rate_pct": round(len(winners) / len(trades) * 100, 4) if trades else 0.0,
            "avg_trade_pct": round(sum(trade["return_pct"] for trade in trades) / len(trades), 4) if trades else 0.0,
        }
