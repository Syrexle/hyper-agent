from dataclasses import asdict, dataclass
from typing import Protocol

from near_agent.models import Decision


class VetoError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VetoResult:
    veto: bool
    reason: str


class VetoClient(Protocol):
    def veto(self, payload: dict) -> dict:
        ...


class DisabledVetoProvider:
    def review(self, decision: Decision) -> VetoResult:
        return VetoResult(veto=False, reason="LLM veto disabled")


class OpenAiVetoProvider:
    def __init__(self, client: VetoClient, *, required: bool):
        self.client = client
        self.required = required

    def review(self, decision: Decision) -> VetoResult:
        try:
            response = self.client.veto(asdict(decision))
        except Exception as exc:
            if self.required:
                raise VetoError("LLM veto provider unavailable") from exc
            return VetoResult(veto=False, reason="LLM veto provider unavailable; continuing because LLM_REQUIRED=false")

        return VetoResult(
            veto=bool(response.get("veto", False)),
            reason=str(response.get("reason", "No veto reason provided")),
        )
