from __future__ import annotations

import time
from datetime import datetime, timedelta
from getpass import getpass

from hyper_agent.backtest import BacktestEngine
from hyper_agent.config import Settings
from hyper_agent.daemon import TradingDaemon
from hyper_agent.executor import DryRunExecutor, HyperliquidLiveExecutor, LiveExecutionGate
from hyper_agent.llm_veto import build_veto_provider
from hyper_agent.market_data import HyperliquidAccountData, RootAiHttpMcpClient, RootAiMcpMarketData
from hyper_agent.models import Decision, DecisionAction
from hyper_agent.notifications import DiscordNotifier
from hyper_agent.risk import RiskEngine
from hyper_agent.sizing import VolatilitySizer
from hyper_agent.state import StateStore
from hyper_agent.strategy import (
    Candle,
    CompositeStrategy,
    FundingRateSentimentStrategy,
    MultiTimeframeEmaStrategy,
    RsiExtremeStrategy,
    calculate_rsi,
)
from hyper_agent.trailing import PositionControls, TrailingStopManager


class NoAccountData:
    def existing_position(self, symbol: str):
        return None


class MultiSymbolCandidateProvider:
    def __init__(self, market_data: RootAiMcpMarketData, settings: Settings, *, strategy_factory):
        self.market_data = market_data
        self.settings = settings
        self.last_primary_candles: list[Candle] = []
        self.last_confirm_candles: list[Candle] = []
        self._strategies = {symbol: strategy_factory(symbol) for symbol in settings.symbols}

    def __call__(self, excluded_symbols: set[str] | None = None) -> Decision:
        end_ms = int(time.time() * 1000)
        primary_start = end_ms - 48 * 3600 * 1000
        confirm_start = end_ms - 240 * 3600 * 1000
        skip_reasons: list[str] = []

        fg_score: float | None = None
        try:
            fg_score = self.market_data.fear_greed()["score"]
        except Exception:
            pass

        for symbol in self.settings.symbols:
            if excluded_symbols and symbol in excluded_symbols:
                continue
            try:
                primary = self.market_data.candles(symbol, interval=self.settings.primary_timeframe, start_time=primary_start, end_time=end_ms)
                confirm = self.market_data.candles(symbol, interval=self.settings.confirm_timeframe, start_time=confirm_start, end_time=end_ms)
            except Exception as exc:
                skip_reasons.append(f"{symbol}: data unavailable ({exc})")
                continue

            decision = self._strategies[symbol].evaluate(primary, confirm)
            if decision.action == DecisionAction.SKIP:
                skip_reasons.append(f"{symbol}: {decision.rationale}")
                continue

            # Fear/greed directional gate
            if fg_score is not None:
                if decision.action == DecisionAction.LONG and fg_score < 20:
                    skip_reasons.append(f"{symbol}: LONG vetoed — extreme fear ({fg_score:.0f})")
                    continue
                if decision.action == DecisionAction.SHORT and fg_score > 80:
                    skip_reasons.append(f"{symbol}: SHORT vetoed — extreme greed ({fg_score:.0f})")
                    continue

            # Edge signals: skip if a large recent move contradicts our direction
            try:
                signals = self.market_data.edge_signals(symbol)
                conflict = None
                for sig in signals:
                    kind = sig.get("kind")
                    value = float(sig.get("value", 0))
                    if kind in ("BIG_MOVE_24H", "FAST_MOVE"):
                        if decision.action == DecisionAction.LONG and value < -10:
                            conflict = f"big down move ({value:.1f}%)"
                            break
                        if decision.action == DecisionAction.SHORT and value > 10:
                            conflict = f"big up move ({value:.1f}%)"
                            break
                if conflict:
                    skip_reasons.append(f"{symbol}: {decision.action.value} vetoed — {conflict}")
                    continue
            except Exception:
                pass

            # 5-min reversal gate for RSI entries: require a confirming candle before entering
            if "RSI extreme" in decision.rationale:
                deny_reason = self._check_5min_reversal(symbol, decision.action, end_ms)
                if deny_reason:
                    skip_reasons.append(f"{symbol}: {deny_reason}")
                    continue

            self.last_primary_candles = primary
            self.last_confirm_candles = confirm
            return decision

        self.last_primary_candles = []
        self.last_confirm_candles = []
        return Decision(
            symbol=self.settings.symbols[0],
            action=DecisionAction.SKIP,
            allowed=False,
            rationale=" || ".join(skip_reasons),
        )

    def _check_5min_reversal(self, symbol: str, action: DecisionAction, end_ms: int) -> str | None:
        """Return a veto reason if the 5-min chart doesn't confirm a V-bottom/V-top RSI signal, or None if it does.

        Three checks must pass:
        1. Sharp prior move — price dropped/rose meaningfully into the extreme candle
        2. Rejection wick — the extreme candle has a long lower/upper wick showing price was pushed back
        3. Reversal candle — the latest candle is green/red and closing in the right direction
        """
        try:
            start_ms = end_ms - 45 * 60 * 1000  # last 45 minutes (~9 candles)
            candles = self.market_data.candles(symbol, interval="5m", start_time=start_ms, end_time=end_ms)
        except Exception:
            return None  # data unavailable — don't block the trade

        if len(candles) < 3:
            return None

        extreme = candles[-2]   # bottom/top candle with the wick
        recovery = candles[-1]  # reversal candle
        prior = candles[-3]     # candle before the extreme, used to measure the drop/rise

        candle_range = extreme.high - extreme.low

        if action == DecisionAction.LONG:
            # Check 1: sharp prior drop — price fell into the extreme candle's low
            drop_pct = (prior.close - extreme.low) / prior.close * 100
            if drop_pct < 0.3:
                return (
                    f"V-bottom check: prior drop too shallow ({drop_pct:.3f}% into low, need ≥0.3%)"
                )

            # Check 2: lower wick rejection — extreme candle has a long lower wick
            if candle_range > 0:
                lower_wick_ratio = (extreme.close - extreme.low) / candle_range
                if lower_wick_ratio < 0.4:
                    return (
                        f"V-bottom check: weak lower wick on bottom candle (ratio {lower_wick_ratio:.2f}, need ≥0.40)"
                    )

            # Check 3: green recovery candle closing above prior close
            if not (recovery.close > recovery.open and recovery.close > extreme.close):
                return (
                    f"V-bottom check: waiting for recovery candle "
                    f"(close {recovery.close:.4f} vs open {recovery.open:.4f}, extreme close {extreme.close:.4f})"
                )

        elif action == DecisionAction.SHORT:
            # Check 1: sharp prior rise — price rose into the extreme candle's high
            rise_pct = (extreme.high - prior.close) / prior.close * 100
            if rise_pct < 0.3:
                return (
                    f"V-top check: prior rise too shallow ({rise_pct:.3f}% into high, need ≥0.3%)"
                )

            # Check 2: upper wick rejection — extreme candle has a long upper wick
            if candle_range > 0:
                upper_wick_ratio = (extreme.high - extreme.close) / candle_range
                if upper_wick_ratio < 0.4:
                    return (
                        f"V-top check: weak upper wick on top candle (ratio {upper_wick_ratio:.2f}, need ≥0.40)"
                    )

            # Check 3: bearish recovery candle closing below prior close
            if not (recovery.close < recovery.open and recovery.close < extreme.close):
                return (
                    f"V-top check: waiting for rejection candle "
                    f"(close {recovery.close:.4f} vs open {recovery.open:.4f}, extreme close {extreme.close:.4f})"
                )

        return None


def build_daemon(settings: Settings, store: StateStore, *, offline: bool = False) -> TradingDaemon:
    if offline:
        return TradingDaemon(
            settings=settings,
            state=store,
            account_data=NoAccountData(),
            executor=DryRunExecutor(store),
        )

    market_data = RootAiMcpMarketData(RootAiHttpMcpClient(settings.rootai_mcp_url))
    account_data = _build_account_data(settings)
    executor = _build_executor(settings, store)
    def _build_composite(symbol: str) -> CompositeStrategy:
        return CompositeStrategy([
            MultiTimeframeEmaStrategy(
                symbol=symbol,
                ema_fast=settings.ema_fast,
                ema_slow=settings.ema_slow,
                atr_period=settings.atr_period,
                initial_stop_pct=float(settings.initial_stop_pct),
                min_atr_pct=float(settings.min_atr_pct),
                min_ema_spread_pct=float(settings.min_ema_spread_pct),
                max_extension_pct=float(settings.max_extension_pct),
            ),
            RsiExtremeStrategy(
                symbol=symbol,
                period=settings.rsi_period,
                overbought=float(settings.rsi_overbought),
                oversold=float(settings.rsi_oversold),
                initial_stop_pct=float(settings.initial_stop_pct),
            ),
            FundingRateSentimentStrategy(
                symbol=symbol,
                funding_provider=lambda s=symbol: market_data.funding(
                    s, start_time=int((time.time() - 8 * 3600) * 1000)
                ),
                threshold=float(settings.funding_rate_threshold),
                initial_stop_pct=float(settings.initial_stop_pct),
            ),
        ], symbol=symbol)

    candidate_provider = MultiSymbolCandidateProvider(
        market_data, settings, strategy_factory=_build_composite
    )
    sizer = VolatilitySizer(settings)
    return TradingDaemon(
        settings=settings,
        state=store,
        account_data=account_data,
        executor=executor,
        candidate_provider=candidate_provider,
        risk_engine=RiskEngine(settings, store),
        veto_provider=build_veto_provider(settings),
        confirmation_gate=LiveExecutionGate(store, confirm_first_n=settings.confirm_first_n_trades),
        confirm_callback=_confirm_live_trade,
        entry_price_provider=lambda symbol: market_data.mid(symbol),
        position_exit_reason_provider=build_trailing_exit_reason_provider(
            settings, store,
            mark_price_provider=lambda symbol: market_data.mid(symbol),
            market_data=market_data,
        ),
        sizing_provider=lambda price: sizer.calculate(candidate_provider.last_primary_candles, price=price),
        notifier=DiscordNotifier(settings.discord_webhook_url) if settings.discord_webhook_url else None,
    )


def build_trailing_exit_reason_provider(settings: Settings, store: StateStore, *, mark_price_provider, market_data=None):
    manager = TrailingStopManager(start_pct=settings.trailing_start_pct, distance_pct=settings.trailing_distance_pct)

    def exit_reason(position):
        mark_px = mark_price_provider(position.symbol)
        controls = store.get_position_controls(position.symbol)
        if controls is None:
            controls = PositionControls(
                symbol=position.symbol,
                side=position.side,
                entry_px=position.entry_px,
                initial_stop_px=_initial_stop_for_position(settings, position),
            )
        manager.update(controls, mark_px=mark_px)
        should_exit, reason = manager.check_exit(controls, mark_px=mark_px)
        store.upsert_position_controls(controls)
        if should_exit:
            return reason

        # RSI exhaustion exit: close long if overbought, close short if oversold
        if market_data is not None:
            try:
                end_ms = int(time.time() * 1000)
                candles = market_data.candles(
                    position.symbol,
                    interval=settings.primary_timeframe,
                    start_time=end_ms - 48 * 3600 * 1000,
                    end_time=end_ms,
                )
                rsi = calculate_rsi(candles, settings.rsi_period)
                if rsi:
                    curr_rsi = rsi[-1]
                    if position.side.value == "long" and curr_rsi >= float(settings.rsi_overbought):
                        return f"rsi_overbought_exit (RSI {curr_rsi:.1f})"
                    if position.side.value == "short" and curr_rsi <= float(settings.rsi_oversold):
                        return f"rsi_oversold_exit (RSI {curr_rsi:.1f})"
            except Exception:
                pass

        return None

    return exit_reason


def run_parameter_sweep(settings: Settings, market_data: RootAiMcpMarketData, top_n: int = 20) -> list[dict]:
    import itertools

    from hyper_agent.strategy import MultiTimeframeEmaStrategy

    end_time = int(time.time() * 1000)
    start_time = int((datetime.now() - timedelta(days=settings.backtest_days)).timestamp() * 1000)

    # Fetch candles once per symbol
    typer_echo = __import__("typer").echo
    candles_by_symbol: dict[str, list] = {}
    for symbol in settings.symbols:
        try:
            typer_echo(f"Fetching {symbol}...")
            candles_by_symbol[symbol] = market_data.candles(
                symbol, interval=settings.primary_timeframe, start_time=start_time, end_time=end_time
            )
        except Exception as exc:
            typer_echo(f"  skipping {symbol}: {exc}")

    if not candles_by_symbol:
        return []

    ema_fast_vals   = [5, 7, 9, 12]
    ema_slow_vals   = [18, 21, 26, 34, 50]
    min_atr_vals    = [0.5, 0.75, 1.0, 1.5, 2.0]
    min_spread_vals = [0.2, 0.35, 0.5, 0.75]
    stop_vals       = [2.0, 3.0, 5.0, 7.0]

    results: list[dict] = []
    combos = [
        (ef, es, atr, spread, stop)
        for ef, es, atr, spread, stop in itertools.product(
            ema_fast_vals, ema_slow_vals, min_atr_vals, min_spread_vals, stop_vals
        )
        if ef < es
    ]

    total = len(combos)
    typer_echo(f"Running {total} combos × {len(candles_by_symbol)} symbols...")
    for i, combo in enumerate(combos, 1):
        if i % 100 == 0 or i == total:
            typer_echo(f"  {i}/{total} combos done...")
        ema_fast, ema_slow, min_atr, min_spread, stop = combo
        sym_results = []
        for symbol, candles in candles_by_symbol.items():
            strategy = MultiTimeframeEmaStrategy(
                symbol=symbol,
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                atr_period=settings.atr_period,
                initial_stop_pct=stop,
                min_atr_pct=min_atr,
                min_ema_spread_pct=min_spread,
                max_extension_pct=float(settings.max_extension_pct),
            )
            r = BacktestEngine(settings, strategy=strategy).run(candles)
            r["symbol"] = symbol
            sym_results.append(r)

        total_trades = sum(r["trades"] for r in sym_results)
        if total_trades == 0:
            continue
        winners = sum(r["trades"] * r["win_rate_pct"] / 100 for r in sym_results)
        avg_return = sum(r["total_return_pct"] for r in sym_results) / len(sym_results)
        win_rate = winners / total_trades * 100

        results.append({
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "min_atr_pct": min_atr,
            "min_ema_spread_pct": min_spread,
            "initial_stop_pct": stop,
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "avg_return_pct": round(avg_return, 4),
        })

    results.sort(key=lambda r: (r["win_rate_pct"], r["avg_return_pct"]), reverse=True)
    return results[:top_n]


def run_rsi_symbol_ranking(settings: Settings, market_data: RootAiMcpMarketData) -> list[dict]:
    from hyper_agent.backtest import RsiBacktestEngine

    end_time = int(time.time() * 1000)
    start_time = int((datetime.now() - timedelta(days=settings.backtest_days)).timestamp() * 1000)
    results = []
    for symbol in settings.symbols:
        try:
            candles = market_data.candles(
                symbol,
                interval=settings.primary_timeframe,
                start_time=start_time,
                end_time=end_time,
            )
            result = RsiBacktestEngine(settings, symbol).run(candles)
            results.append(result)
        except Exception as exc:
            results.append({
                "symbol": symbol,
                "error": str(exc),
                "total_return_pct": -9999.0,
                "win_rate_pct": 0.0,
                "trades": 0,
                "avg_trade_pct": 0.0,
                "final_capital": 1000.0,
                "total_cost_usd": 0.0,
            })

    def _rank_key(r: dict):
        if r.get("error"):
            return (-9999.0, 0.0, 0)
        trades = r.get("trades", 0)
        # deprioritize symbols with fewer than 3 trades
        trade_bonus = 0 if trades >= 3 else -1000
        return (r.get("total_return_pct", -9999.0) + trade_bonus, r.get("win_rate_pct", 0.0), trades)

    results.sort(key=_rank_key, reverse=True)
    return results


def run_backtest(settings: Settings, market_data: RootAiMcpMarketData) -> list[dict]:
    end_time = int(time.time() * 1000)
    start_time = int((datetime.now() - timedelta(days=settings.backtest_days)).timestamp() * 1000)
    results = []
    for symbol in settings.symbols:
        try:
            candles = market_data.candles(
                symbol,
                interval=settings.primary_timeframe,
                start_time=start_time,
                end_time=end_time,
            )
            strategy = MultiTimeframeEmaStrategy(
                symbol=symbol,
                ema_fast=settings.ema_fast,
                ema_slow=settings.ema_slow,
                atr_period=settings.atr_period,
                initial_stop_pct=float(settings.initial_stop_pct),
                min_atr_pct=float(settings.min_atr_pct),
                min_ema_spread_pct=float(settings.min_ema_spread_pct),
                max_extension_pct=float(settings.max_extension_pct),
            )
            result = BacktestEngine(settings, strategy=strategy).run(candles)
            result["symbol"] = symbol
            results.append(result)
        except Exception as exc:
            results.append({"symbol": symbol, "error": str(exc)})
    return results


def _build_account_data(settings: Settings):
    if not settings.hyperliquid_account_address:
        return NoAccountData()
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
    except ImportError as exc:
        if settings.live_trading:
            raise RuntimeError("Install live dependencies with `uv sync --extra live` before live trading") from exc
        return NoAccountData()
    return HyperliquidAccountData(Info(constants.MAINNET_API_URL, skip_ws=True), settings.hyperliquid_account_address)


def _build_executor(settings: Settings, store: StateStore):
    if not settings.live_trading:
        return DryRunExecutor(store)
    try:
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
    except ImportError as exc:
        raise RuntimeError("Install live dependencies with `uv sync --extra live` before live trading") from exc
    wallet = Account.from_key(settings.hyperliquid_private_key)
    return HyperliquidLiveExecutor(
        store,
        Exchange(
            wallet,
            constants.MAINNET_API_URL,
            account_address=settings.hyperliquid_account_address,
        ),
    )


def _first_reason_provider(*providers):
    def exit_reason(position):
        for provider in providers:
            reason = provider(position)
            if reason:
                return reason
        return None

    return exit_reason


def _initial_stop_for_position(settings: Settings, position) -> float:
    distance = float(settings.initial_stop_pct) / 100
    if position.side.value == "long":
        return position.entry_px * (1 - distance)
    return position.entry_px * (1 + distance)


def _confirm_live_trade(decision) -> bool:
    answer = getpass(
        f"Confirm live {decision.action.value} {decision.symbol} trade? "
        "Type YES to submit, anything else to skip: "
    )
    return answer == "YES"
