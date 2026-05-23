from dataclasses import dataclass
from enum import StrEnum
from time import time


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


class DecisionAction(StrEnum):
    LONG = "long"
    SHORT = "short"
    SKIP = "skip"


class TradeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    ADOPTED = "adopted"


@dataclass(slots=True)
class Decision:
    symbol: str
    action: DecisionAction
    rationale: str
    allowed: bool
    stop_loss_px: float | None = None
    take_profit_px: float | None = None
    created_ts: float = 0

    def __post_init__(self) -> None:
        if self.created_ts == 0:
            self.created_ts = time()


@dataclass(slots=True)
class Trade:
    trade_id: str
    symbol: str
    side: Side
    status: TradeStatus
    notional_usd: float
    entry_px: float
    realized_pnl_usd: float | None = None
    created_ts: float = 0

    def __post_init__(self) -> None:
        if self.created_ts == 0:
            self.created_ts = time()


@dataclass(slots=True)
class PositionSnapshot:
    symbol: str
    side: Side
    size: float
    entry_px: float
    unrealized_pnl_usd: float
    liquidation_px: float | None = None


@dataclass(slots=True)
class TradeJournalEntry:
    trade_id: str
    submitted_live: bool
    symbol: str
    side: Side
    entry_px: float
    notional_usd: float
    leverage: float
    size_base: float
    stop_loss_px: float
    take_profit_px: float
    atr_pct: float
    rationale: str
    min_atr_pct: float
    min_ema_spread_pct: float
    max_extension_pct: float
    exit_px: float | None = None
    realized_pnl_usd: float | None = None
    realized_pnl_pct: float | None = None
    exit_reason: str | None = None
    highest_pnl_pct: float | None = None
    max_drawdown_pct: float | None = None
    created_ts: float = 0

    def __post_init__(self) -> None:
        if self.created_ts == 0:
            self.created_ts = time()
