from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from near_agent.config import Settings
from near_agent.models import Decision, DecisionAction, PositionSnapshot
from near_agent.state import StateStore


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

        if decision.symbol != "NEAR-USDC":
            reasons.append("Candidate symbol must be exactly NEAR-USDC")
        if decision.action == DecisionAction.SKIP:
            reasons.append("Skip decisions are not eligible for order placement")
        if self.settings.max_leverage > Decimal("2"):
            reasons.append("Bot effective leverage must be at or below 2x")
        if self.settings.fixed_notional_usd <= 0:
            reasons.append("Fixed notional must be greater than zero")
        if existing_position and existing_position.symbol == "NEAR-USDC":
            reasons.append("Existing NEAR-USDC position found; switch into position-management mode")
        if self.state.has_trade_on(today):
            reasons.append("A bot trade has already been opened today")
        if self.state.has_loss_on(today):
            reasons.append("A realized bot-managed loss has already occurred today")
        if decision.stop_loss_px is None or decision.take_profit_px is None:
            reasons.append("Candidate must include stop-loss and take-profit prices")

        return RiskResult(
            allowed=not reasons,
            reasons=reasons,
            notional_usd=self.settings.fixed_notional_usd,
            max_leverage=self.settings.max_leverage,
        )
