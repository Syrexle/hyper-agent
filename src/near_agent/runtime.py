from __future__ import annotations

import time
from dataclasses import dataclass
from getpass import getpass
from datetime import datetime
from zoneinfo import ZoneInfo

from near_agent.config import Settings
from near_agent.daemon import TradingDaemon
from near_agent.executor import DryRunExecutor, HyperliquidLiveExecutor, LiveExecutionGate
from near_agent.llm_veto import build_veto_provider
from near_agent.market_data import HyperliquidAccountData, RootAiHttpMcpClient, RootAiMcpMarketData
from near_agent.risk import RiskEngine
from near_agent.state import StateStore
from near_agent.strategy import NearStrategy


class NoAccountData:
    def existing_position(self, symbol: str):
        return None


@dataclass(frozen=True, slots=True)
class StrategyCandidateProvider:
    market_data: RootAiMcpMarketData
    strategy: NearStrategy
    symbol: str
    interval: str = "1h"
    lookback_hours: int = 48

    def __call__(self):
        end_time = int(time.time() * 1000)
        start_time = end_time - self.lookback_hours * 60 * 60 * 1000
        candles = self.market_data.candles(
            self.symbol,
            interval=self.interval,
            start_time=start_time,
            end_time=end_time,
        )
        return self.strategy.evaluate(candles)


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
    return TradingDaemon(
        settings=settings,
        state=store,
        account_data=account_data,
        executor=executor,
        candidate_provider=StrategyCandidateProvider(market_data, NearStrategy(), settings.symbol),
        risk_engine=RiskEngine(settings, store),
        veto_provider=build_veto_provider(settings),
        confirmation_gate=LiveExecutionGate(store, confirm_first_n=settings.confirm_first_n_trades),
        confirm_callback=_confirm_live_trade,
        entry_price_provider=lambda: market_data.mid(settings.symbol),
        position_exit_reason_provider=build_position_exit_reason_provider(settings),
    )


def build_position_exit_reason_provider(settings: Settings, *, now_provider=lambda: datetime.now(ZoneInfo("UTC"))):
    def exit_reason(_position):
        local_now = now_provider().astimezone(ZoneInfo(settings.local_timezone))
        flatten_hour, flatten_minute = _parse_hh_mm(settings.end_of_day_flatten_time)
        if (local_now.hour, local_now.minute) >= (flatten_hour, flatten_minute):
            return "end_of_day_flatten"
        return None

    return exit_reason


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
