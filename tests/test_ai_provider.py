"""Strict editorial AI provider contracts and safety boundaries."""

from __future__ import annotations

import json

import pytest

from dripcut.core.errors import AIProviderError
from dripcut.engines.ai.provider import (
    AIEditPlan,
    NvidiaAIProvider,
    ScriptBrief,
    StructuredAIProvider,
    ViralMomentAnalysis,
    _validate,
    build_ai_provider,
)


class StubProvider(StructuredAIProvider):
    name = "stub"
    model = "stub-model"

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.last_prompt = ""

    def _generate(self, prompt, schema, *, max_tokens):
        self.last_prompt = prompt
        return _validate(schema, self.payload)

    def health(self) -> dict[str, object]:
        return {"configured": True}


def test_nvidia_provider_requires_a_server_side_key() -> None:
    provider = NvidiaAIProvider(api_key=None)

    with pytest.raises(AIProviderError) as error:
        provider.plan_edit("Make one reel", duration=60)

    assert "NVIDIA_API_KEY" in (error.value.hint or "")


def test_nvidia_provider_requests_json_without_reasoning(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "platform": "instagram",
                                        "selection": "viral",
                                        "count": 3,
                                        "duration": 30,
                                        "aspect_ratio": "9:16",
                                        "captions": True,
                                        "caption_style": "dynamic",
                                        "reframe": "speaker",
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, **_kwargs):
        captured.update(json.loads(request.data))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = NvidiaAIProvider(api_key="server-secret")

    plan = provider.plan_edit("Create three reels", duration=120)

    assert plan.count == 3
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}


def test_nvidia_provider_uses_documented_model_and_endpoint_variables(monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_AI_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "server-secret")
    monkeypatch.setenv("DRIPCUT_NVIDIA_MODEL", "nvidia/test-model")
    monkeypatch.setenv("DRIPCUT_NVIDIA_BASE_URL", "https://nvidia.example/v1")
    monkeypatch.setenv("DRIPCUT_AI_MODEL", "legacy/model")
    monkeypatch.setenv("DRIPCUT_AI_ENDPOINT", "https://legacy.example/v1")

    provider = build_ai_provider(object())  # type: ignore[arg-type]

    assert isinstance(provider, NvidiaAIProvider)
    assert provider.model == "nvidia/test-model"
    assert provider.endpoint == "https://nvidia.example/v1"


def test_nvidia_provider_keeps_legacy_variable_compatibility(monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_AI_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "server-secret")
    monkeypatch.delenv("DRIPCUT_NVIDIA_MODEL", raising=False)
    monkeypatch.delenv("DRIPCUT_NVIDIA_BASE_URL", raising=False)
    monkeypatch.setenv("DRIPCUT_AI_MODEL", "legacy/model")
    monkeypatch.setenv("DRIPCUT_AI_ENDPOINT", "https://legacy.example/v1")

    provider = build_ai_provider(object())  # type: ignore[arg-type]

    assert isinstance(provider, NvidiaAIProvider)
    assert provider.model == "legacy/model"
    assert provider.endpoint == "https://legacy.example/v1"


def test_ai_edit_plan_rejects_unknown_or_unsafe_fields() -> None:
    provider = StubProvider(
        {
            "platform": "instagram",
            "selection": "viral",
            "count": 5,
            "duration": 30,
            "aspect_ratio": "9:16",
            "captions": True,
            "caption_style": "dynamic",
            "reframe": "speaker",
            "shell_command": "rm -rf /",
        }
    )

    with pytest.raises(AIProviderError):
        provider.plan_edit("Make clips", duration=300)


def test_viral_moments_are_platform_aware_and_range_checked() -> None:
    provider = StubProvider(
        {
            "segments": [
                {
                    "start": 10,
                    "end": 40,
                    "score": 92,
                    "hook_score": 95,
                    "retention_score": 90,
                    "shareability_score": 88,
                    "platform": "instagram",
                    "reason": "Immediate story with a complete payoff",
                    "hook": "Nobody expected this result",
                }
            ]
        }
    )

    result = provider.find_viral_moments(
        "[10-40] Nobody expected this result.",
        duration=60,
        platform="instagram",
        target_length=30,
        max_clips=3,
    )

    assert isinstance(result, ViralMomentAnalysis)
    assert result.segments[0].score == 92
    assert "emotion" in provider.last_prompt


def test_ai_plan_schema_contains_only_approved_actions() -> None:
    plan = AIEditPlan.model_validate(
        {
            "platform": "youtube",
            "selection": "standard",
            "count": 2,
            "duration": 30,
            "aspect_ratio": "9:16",
            "captions": True,
            "caption_style": "clean",
            "reframe": "center",
        }
    )
    assert plan.aspect_ratio == "9:16"


def test_script_generation_uses_strict_structured_output() -> None:
    provider = StubProvider(
        {
            "title": "A creator workflow",
            "hook": "Your editing process is backwards.",
            "sections": [{"type": "body", "text": "Start with one clear payoff."}],
            "cta": "Save this for your next video.",
            "estimated_duration_seconds": 35,
            "platform": "youtube",
            "language": "en",
            "description": "A simple editing workflow.",
            "caption": "One idea, one payoff.",
            "hashtags": ["creator"],
        }
    )

    draft = provider.generate_script(
        ScriptBrief(
            topic="A creator workflow",
            platform="youtube",
            audience="video creators",
            tone="clear",
            language="en",
            target_duration_seconds=35,
            content_goal="teach",
        )
    )

    assert draft.script.startswith("Your editing process")
    assert "complete thought" in provider.last_prompt


def test_script_generation_rejects_unknown_provider_fields() -> None:
    provider = StubProvider(
        {
            "title": "Unsafe",
            "hook": "Hook",
            "sections": [{"type": "body", "text": "Body"}],
            "cta": "CTA",
            "estimated_duration_seconds": 30,
            "platform": "instagram",
            "language": "en",
            "description": "",
            "caption": "",
            "hashtags": [],
            "raw_provider_payload": {"secret": True},
        }
    )

    with pytest.raises(AIProviderError):
        provider.generate_script(
            ScriptBrief(
                topic="Safe scripts",
                platform="instagram",
                audience="creators",
                tone="clear",
                language="en",
                target_duration_seconds=30,
                content_goal="teach",
            )
        )
