from __future__ import annotations

import time
from dataclasses import dataclass, field
from getpass import getpass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from near_agent.backtest import BacktestEngine
from near_agent.config import Settings
from near_agent.daemon import TradingDaemon
from near_agent.executor import DryRunExecutor, HyperliquidLiveExecutor, LiveExecutionGate
from near_agent.llm_veto import build_veto_provider
from near_agent.market_data import HyperliquidAccountData, RootAiHttpMcpClient, RootAiMcpMarketData
from near_agent.notifications import DiscordNotifier
from near_agent.risk import RiskEngine
from near_agent.sizing import VolatilitySizer
from near_agent.state import StateStore
from near_agent.strategy import Candle, MultiTimeframeEmaStrategy
from near_agent.trailing import PositionControls, TrailingStopManager


class NoAccountData:
    def existing_position(self, symbol: str):
        return None


@dataclass(slots=True)
class StrategyCandidateProvider:
    market_data: RootAiMcpMarketData
    strategy: MultiTimeframeEmaStrategy
    symbol: str
    interval: str = "1h"
    confirm_interval: str = "4h"
    lookback_hours: int = 48
    confirm_lookback_hours: int = 240
    last_primary_candles: list[Candle] = field(default_factory=list)
    last_confirm_candles: list[Candle] = field(default_factory=list)

    def __call__(self):
        end_time = int(time.time() * 1000)
        start_time = end_time - self.lookback_hours * 60 * 60 * 1000
        confirm_start_time = end_time - self.confirm_lookback_hours * 60 * 60 * 1000
        self.last_primary_candles = self.market_data.candles(
            self.symbol,
            interval=self.interval,
            start_time=start_time,
            end_time=end_time,
        )
        self.last_confirm_candles = self.market_data.candles(
            self.symbol,
            interval=self.confirm_interval,
            start_time=confirm_start_time,
            end_time=end_time,
        )
        return self.strategy.evaluate(self.last_primary_candles, self.last_confirm_candles)


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
    candidate_provider = StrategyCandidateProvider(
        market_data,
        MultiTimeframeEmaStrategy(
            symbol=settings.symbol,
            ema_fast=settings.ema_fast,
            ema_slow=settings.ema_slow,
            atr_period=settings.atr_period,
            initial_stop_pct=float(settings.initial_stop_pct),
        ),
        settings.symbol,
        interval=settings.primary_timeframe,
        confirm_interval=settings.confirm_timeframe,
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
        entry_price_provider=lambda: market_data.mid(settings.symbol),
        position_exit_reason_provider=_first_reason_provider(
            build_trailing_exit_reason_provider(settings, store, mark_price_provider=lambda: market_data.mid(settings.symbol)),
            build_position_exit_reason_provider(settings),
        ),
        sizing_provider=lambda price: sizer.calculate(candidate_provider.last_primary_candles, price=price),
        notifier=DiscordNotifier(settings.discord_webhook_url) if settings.discord_webhook_url else None,
    )


def build_position_exit_reason_provider(settings: Settings, *, now_provider=lambda: datetime.now(ZoneInfo("UTC"))):
    def exit_reason(_position):
        local_now = now_provider().astimezone(ZoneInfo(settings.local_timezone))
        flatten_hour, flatten_minute = _parse_hh_mm(settings.end_of_day_flatten_time)
        if (local_now.hour, local_now.minute) >= (flatten_hour, flatten_minute):
            return "end_of_day_flatten"
        return None

    return exit_reason


def build_trailing_exit_reason_provider(settings: Settings, store: StateStore, *, mark_price_provider):
    manager = TrailingStopManager(start_pct=settings.trailing_start_pct, distance_pct=settings.trailing_distance_pct)

    def exit_reason(position):
        mark_px = mark_price_provider()
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
        return reason if should_exit else None

    return exit_reason


def run_backtest(settings: Settings, market_data: RootAiMcpMarketData) -> dict:
    end_time = int(time.time() * 1000)
    start_time = int((datetime.now() - timedelta(days=settings.backtest_days)).timestamp() * 1000)
    candles = market_data.candles(
        settings.symbol,
        interval=settings.primary_timeframe,
        start_time=start_time,
        end_time=end_time,
    )
    return BacktestEngine(settings).run(candles)


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


def _parse_hh_mm(value: str) -> tuple[int, int]:
    hour_raw, minute_raw = value.split(":", maxsplit=1)
    hour = int(hour_raw)
    minute = int(minute_raw)
    if hour not in range(24) or minute not in range(60):
        raise ValueError("END_OF_DAY_FLATTEN_TIME must be HH:MM")
    return hour, minute
