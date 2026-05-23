import json
from dataclasses import asdict, dataclass
from typing import Protocol

from near_agent.config import Settings
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


class OpenAiCompatibleChatClient:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def veto(self, payload: dict) -> dict:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a trading risk veto layer. Return only JSON with keys "
                        "veto:boolean and reason:string. You may veto but never modify trades."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, sort_keys=True),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        return {
            "veto": bool(parsed.get("veto", False)),
            "reason": str(parsed.get("reason", "No reason provided")),
        }


def build_veto_provider(settings: Settings):
    if settings.llm_provider == "disabled":
        return DisabledVetoProvider()
    if settings.llm_provider == "venice":
        if not settings.venice_api_key:
            if settings.llm_required:
                raise VetoError("VENICE_API_KEY is required for Venice veto provider")
            return DisabledVetoProvider()
        return OpenAiVetoProvider(
            OpenAiCompatibleChatClient(
                api_key=settings.venice_api_key,
                base_url=settings.venice_base_url,
                model=settings.venice_model,
            ),
            required=settings.llm_required,
        )
    if not settings.openai_api_key:
        if settings.llm_required:
            raise VetoError("OPENAI_API_KEY is required for OpenAI veto provider")
        return DisabledVetoProvider()
    return OpenAiVetoProvider(
        OpenAiCompatibleChatClient(
            api_key=settings.openai_api_key,
            base_url="https://api.openai.com/v1",
            model=settings.openai_model,
        ),
        required=settings.llm_required,
    )
