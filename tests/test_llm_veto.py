import pytest

from hyper_agent.config import Settings
from hyper_agent.llm_veto import (
    DisabledVetoProvider,
    OpenAiCompatibleChatClient,
    OpenAiVetoProvider,
    VetoError,
    build_veto_provider,
)
from hyper_agent.models import Decision, DecisionAction


def decision():
    return Decision(
        symbol="NEAR-USDC",
        action=DecisionAction.LONG,
        allowed=True,
        rationale="trend",
        stop_loss_px=2.0,
        take_profit_px=2.4,
    )


def test_disabled_veto_approves_without_changes():
    candidate = decision()

    result = DisabledVetoProvider().review(candidate)

    assert result.veto is False
    assert result.reason == "LLM veto disabled"
    assert candidate.action == DecisionAction.LONG


def test_openai_veto_can_block_but_not_change_candidate():
    class FakeClient:
        def veto(self, payload):
            return {"veto": True, "reason": "official news risk", "action": "short"}

    candidate = decision()
    result = OpenAiVetoProvider(FakeClient(), required=True).review(candidate)

    assert result.veto is True
    assert result.reason == "official news risk"
    assert candidate.action == DecisionAction.LONG


def test_provider_error_allows_when_not_required():
    class BrokenClient:
        def veto(self, payload):
            raise RuntimeError("network")

    result = OpenAiVetoProvider(BrokenClient(), required=False).review(decision())

    assert result.veto is False
    assert "unavailable" in result.reason


def test_provider_error_blocks_when_required():
    class BrokenClient:
        def veto(self, payload):
            raise RuntimeError("network")

    with pytest.raises(VetoError):
        OpenAiVetoProvider(BrokenClient(), required=True).review(decision())


def test_builds_venice_provider_from_settings():
    settings = Settings(llm_provider="venice", venice_api_key="venice-key", venice_model="venice-model")

    provider = build_veto_provider(settings)

    assert isinstance(provider.client, OpenAiCompatibleChatClient)
    assert provider.client.api_key == "venice-key"
    assert provider.client.base_url == "https://api.venice.ai/api/v1"
    assert provider.client.model == "venice-model"
