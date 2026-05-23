from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from hyper_agent.config import Settings
from hyper_agent.models import Decision, DecisionAction, PositionSnapshot
from hyper_agent.state import StateStore


@dataclass(frozen=True, slots=True)
class RiskResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    notional_usd: Decimal = Decimal("0")
    max_leverage: Decimal = Decimal("0")


class RiskEngine:
    def __init__(self, settings: Settings, state: StateStore):
        self.settings = settings
        self.state = state

    def evaluate_candidate(
        self,
        decision: Decision,
        *,
        today: date,
        existing_position: PositionSnapshot | None = None,
    ) -> RiskResult:
        reasons: list[str] = []

        if decision.symbol not in self.settings.symbols:
            reasons.append(f"Candidate symbol {decision.symbol} is not in the tracked symbol list")
        if decision.action == DecisionAction.SKIP:
            reasons.append("Skip decisions are not eligible for order placement")
        if self.settings.max_leverage > Decimal("10"):
            reasons.append("Bot effective leverage must be at or below 10x")
        if self.settings.fixed_notional_usd <= 0:
            reasons.append("Fixed notional must be greater than zero")
        if existing_position and existing_position.symbol == decision.symbol:
            reasons.append(f"Existing {decision.symbol} position found; switch into position-management mode")
        if self.state.has_loss_on(today):
            reasons.append("Loss occurred today — no new positions until tomorrow")
        if self.state.daily_win_count(today) >= 3:
            reasons.append("3 winning trades today — daily cap reached")
        if decision.stop_loss_px is None or decision.take_profit_px is None:
            reasons.append("Candidate must include stop-loss and take-profit prices")

        return RiskResult(
            allowed=not reasons,
            reasons=reasons,
            notional_usd=self.settings.fixed_notional_usd,
            max_leverage=self.settings.max_leverage,
        )
