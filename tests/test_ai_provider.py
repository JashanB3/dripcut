"""Strict editorial AI provider contracts and safety boundaries."""

from __future__ import annotations

import pytest

from dripcut.core.errors import AIProviderError
from dripcut.engines.ai.provider import (
    AIEditPlan,
    NvidiaAIProvider,
    StructuredAIProvider,
    ViralMomentAnalysis,
    _validate,
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
