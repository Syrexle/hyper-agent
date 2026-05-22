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
