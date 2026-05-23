from dataclasses import dataclass

from hyper_agent.models import Side


@dataclass(slots=True)
class PositionControls:
    symbol: str
    side: Side
    entry_px: float
    initial_stop_px: float
    trailing_stop_px: float | None = None
    highest_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0

    def current_pnl_pct(self, mark_px: float) -> float:
        if self.side == Side.LONG:
            return (mark_px - self.entry_px) / self.entry_px * 100
        return (self.entry_px - mark_px) / self.entry_px * 100


class TrailingStopManager:
    def __init__(self, *, start_pct, distance_pct):
        self.start_pct = float(start_pct)
        self.distance_pct = float(distance_pct)

    def update(self, controls: PositionControls, *, mark_px: float) -> float | None:
        pnl_pct = controls.current_pnl_pct(mark_px)
        if pnl_pct > controls.highest_pnl_pct:
            controls.highest_pnl_pct = round(pnl_pct, 8)
        if pnl_pct < controls.max_drawdown_pct:
            controls.max_drawdown_pct = round(pnl_pct, 8)
        if pnl_pct < self.start_pct:
            return None

        if controls.side == Side.LONG:
            new_stop = mark_px * (1 - self.distance_pct / 100)
            if controls.trailing_stop_px is None or new_stop > controls.trailing_stop_px:
                controls.trailing_stop_px = new_stop
                return new_stop
        else:
            new_stop = mark_px * (1 + self.distance_pct / 100)
            if controls.trailing_stop_px is None or new_stop < controls.trailing_stop_px:
                controls.trailing_stop_px = new_stop
                return new_stop
        return None

    def check_exit(self, controls: PositionControls, *, mark_px: float) -> tuple[bool, str]:
        if controls.side == Side.LONG:
            if controls.trailing_stop_px is not None and mark_px <= controls.trailing_stop_px:
                return True, f"trailing stop {controls.trailing_stop_px:.6f}"
            if mark_px <= controls.initial_stop_px:
                return True, f"stop loss {controls.initial_stop_px:.6f}"
        else:
            if controls.trailing_stop_px is not None and mark_px >= controls.trailing_stop_px:
                return True, f"trailing stop {controls.trailing_stop_px:.6f}"
            if mark_px >= controls.initial_stop_px:
                return True, f"stop loss {controls.initial_stop_px:.6f}"
        return False, ""
