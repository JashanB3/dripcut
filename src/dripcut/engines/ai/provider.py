"""Replaceable, schema-validated providers for editorial AI capabilities."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

import certifi
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dripcut.core.errors import AIProviderError, ModelUnavailableError
from dripcut.engines.ai.llm import OllamaClient
from dripcut.utils.text import extract_json

Platform = Literal["youtube", "instagram"]
SchemaT = TypeVar("SchemaT", bound=BaseModel)

_SYSTEM = (
    "You are DripCut's editorial planning engine. Return only valid JSON matching "
    "the requested schema. Never add prose or markdown. Never invent timestamps "
    "outside the supplied source duration."
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptAnalysis(StrictModel):
    summary: str = Field(max_length=600)
    language: str = Field(default="", max_length=40)
    topics: list[str] = Field(default_factory=list, max_length=8)
    tone: str = Field(default="", max_length=60)


class ViralMoment(StrictModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    score: int = Field(ge=0, le=100)
    hook_score: int = Field(ge=0, le=100)
    retention_score: int = Field(ge=0, le=100)
    shareability_score: int = Field(ge=0, le=100)
    platform: Platform
    reason: str = Field(min_length=3, max_length=240)
    hook: str = Field(default="", max_length=180)

    @model_validator(mode="after")
    def valid_range(self) -> ViralMoment:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class ViralMomentAnalysis(StrictModel):
    segments: list[ViralMoment] = Field(default_factory=list, max_length=40)


class AIEditPlan(StrictModel):
    platform: Platform
    selection: Literal["standard", "viral"]
    count: int = Field(ge=1, le=40)
    duration: float = Field(ge=5, le=300)
    aspect_ratio: Literal["source", "16:9", "9:16", "1:1"]
    captions: bool
    caption_style: Literal["clean", "dynamic", "minimal", "bold"] = "dynamic"
    reframe: Literal["source", "center", "speaker", "blur_background"] = "speaker"


class RankedClip(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=3, max_length=240)


class RankedClips(StrictModel):
    clips: list[RankedClip] = Field(default_factory=list, max_length=40)


class SocialMetadata(StrictModel):
    youtube_title: str = Field(max_length=100)
    youtube_description: str = Field(max_length=5000)
    youtube_hashtags: list[str] = Field(default_factory=list, max_length=15)
    instagram_caption: str = Field(max_length=2200)
    instagram_hashtags: list[str] = Field(default_factory=list, max_length=30)
    instagram_cta: str = Field(max_length=240)
    hook: str = Field(max_length=180)
    category: str = Field(max_length=80)
    posting_description: str = Field(max_length=500)


class ThumbnailBrief(StrictModel):
    headline: str = Field(max_length=80)
    visual_focus: str = Field(max_length=240)
    emotion: str = Field(max_length=80)
    composition: str = Field(max_length=300)
    frame_guidance: str = Field(max_length=300)
    avoid: list[str] = Field(default_factory=list, max_length=12)


class AIProvider(ABC):
    """Strict editorial AI boundary. Providers never execute media commands."""

    name: str
    model: str

    @abstractmethod
    def analyze_transcript(self, transcript: str, *, language: str = "") -> TranscriptAnalysis: ...

    @abstractmethod
    def find_viral_moments(
        self,
        transcript: str,
        *,
        duration: float,
        platform: Platform,
        target_length: float,
        max_clips: int,
        language: str = "",
        metadata: dict[str, str] | None = None,
    ) -> ViralMomentAnalysis: ...

    @abstractmethod
    def plan_edit(self, prompt: str, *, duration: float) -> AIEditPlan: ...

    @abstractmethod
    def rank_clips(self, clips: list[dict[str, Any]], *, platform: Platform) -> RankedClips: ...

    @abstractmethod
    def generate_social_metadata(self, transcript: str) -> SocialMetadata: ...

    @abstractmethod
    def generate_thumbnail_brief(self, transcript: str, *, prompt: str = "") -> ThumbnailBrief: ...

    @abstractmethod
    def health(self) -> dict[str, object]: ...


class StructuredAIProvider(AIProvider):
    """Prompt implementation shared by hosted NVIDIA and local Ollama."""

    analysis_version = "viral-v1"

    @abstractmethod
    def _generate(self, prompt: str, schema: type[SchemaT], *, max_tokens: int) -> SchemaT: ...

    def analyze_transcript(self, transcript: str, *, language: str = "") -> TranscriptAnalysis:
        return self._generate(
            f"Analyze this {language or 'unknown-language'} transcript. Return summary, language, topics, and tone.\n\n{_bounded(transcript)}",
            TranscriptAnalysis,
            max_tokens=900,
        )

    def find_viral_moments(
        self,
        transcript: str,
        *,
        duration: float,
        platform: Platform,
        target_length: float,
        max_clips: int,
        language: str = "",
        metadata: dict[str, str] | None = None,
    ) -> ViralMomentAnalysis:
        rubric = (
            "hook, information value, retention, completeness, and search discovery"
            if platform == "youtube"
            else "hook, emotion, relatability, visual/social potential, and shareability"
        )
        result = self._generate(
            "Find standalone viral moments for "
            f"{platform}. Score {rubric}. Source duration: {duration:.3f}s. "
            f"Target duration: {target_length:.3f}s. Return at most {max_clips} segments. "
            f"Language: {language or 'unknown'}. Metadata: {json.dumps(metadata or {})}. "
            "Each segment needs start, end, score, hook_score, retention_score, "
            "shareability_score, platform, reason, and hook.\n\n"
            f"{_bounded(transcript)}",
            ViralMomentAnalysis,
            max_tokens=2600,
        )
        for segment in result.segments:
            if segment.end > duration + 0.01:
                raise AIProviderError(
                    "The AI returned an invalid clip range.",
                    hint="Run viral analysis again.",
                )
            if segment.duration < 4 or segment.duration > max(300, target_length * 2.2):
                raise AIProviderError(
                    "The AI returned a clip outside the supported duration.",
                    hint="Run viral analysis again with a different clip length.",
                )
        result.segments.sort(key=lambda item: item.score, reverse=True)
        return ViralMomentAnalysis(segments=result.segments[:max_clips])

    def plan_edit(self, prompt: str, *, duration: float) -> AIEditPlan:
        return self._generate(
            f"Convert this request into a safe edit plan for a {duration:.3f}s source. "
            "Allowed values are encoded in the JSON schema. AI only plans; it never runs tools. "
            f"Request: {prompt}",
            AIEditPlan,
            max_tokens=700,
        )

    def rank_clips(self, clips: list[dict[str, Any]], *, platform: Platform) -> RankedClips:
        return self._generate(
            f"Rank these candidate clips for {platform}. Return each id, score, and reason.\n"
            f"{json.dumps(clips)[:40000]}",
            RankedClips,
            max_tokens=1400,
        )

    def generate_social_metadata(self, transcript: str) -> SocialMetadata:
        return self._generate(
            "Create one editable social package for YouTube Shorts and Instagram Reels. "
            "Return every field in the schema in one response. Do not make unverifiable claims.\n\n"
            f"{_bounded(transcript)}",
            SocialMetadata,
            max_tokens=1600,
        )

    def generate_thumbnail_brief(self, transcript: str, *, prompt: str = "") -> ThumbnailBrief:
        return self._generate(
            "Create an original thumbnail brief emphasizing a clear subject, emotion, "
            "composition, and readable mobile framing. "
            f"Creator direction: {prompt or 'automatic'}.\n\n{_bounded(transcript)}",
            ThumbnailBrief,
            max_tokens=900,
        )


class NvidiaAIProvider(StructuredAIProvider):
    """NVIDIA NIM's OpenAI-compatible chat endpoint with no browser-side secret."""

    name = "nvidia"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "nvidia/nemotron-3.5-lightning-30b-a3b",
        endpoint: str = "https://integrate.api.nvidia.com/v1",
        timeout: float = 90.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("NVIDIA AI endpoint must use HTTPS outside local development")

    def _generate(self, prompt: str, schema: type[SchemaT], *, max_tokens: int) -> SchemaT:
        if not self.api_key:
            raise AIProviderError(
                "NVIDIA AI is not configured.",
                hint="Set NVIDIA_API_KEY on the backend server.",
            )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": f"JSON schema: {json.dumps(schema.model_json_schema())}\n\n{prompt}",
                },
            ],
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - endpoint is validated above
                request,
                timeout=self.timeout,
                context=_ssl_context(),
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = str(payload["choices"][0]["message"]["content"])
            return _validate(schema, extract_json(content))
        except AIProviderError:
            raise
        except urllib.error.HTTPError as exc:
            raise AIProviderError(
                "NVIDIA AI could not complete this request.",
                hint=f"Provider returned HTTP {exc.code}. Try again shortly.",
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIProviderError(
                "NVIDIA AI is temporarily unreachable.", hint="Try again shortly."
            ) from exc
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIProviderError(
                "NVIDIA AI returned an invalid structured response.",
                hint="Run this AI step again.",
            ) from exc

    def health(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "model": self.model,
            "configured": bool(self.api_key),
            "endpoint": self.endpoint,
            "analysis_version": self.analysis_version,
        }


class OllamaAIProvider(StructuredAIProvider):
    """Local adapter used when hosted credentials are intentionally absent."""

    name = "ollama"

    def __init__(self, client: OllamaClient) -> None:
        self.client = client
        self.model = client.model

    def _generate(self, prompt: str, schema: type[SchemaT], *, max_tokens: int) -> SchemaT:
        try:
            payload = self.client.generate_json(
                f"JSON schema: {json.dumps(schema.model_json_schema())}\n\n{prompt}",
                system=_SYSTEM,
                max_tokens=max_tokens,
            )
            return _validate(schema, payload)
        except (ModelUnavailableError, ValidationError, ValueError) as exc:
            raise AIProviderError(
                "The local AI provider did not return a valid plan.",
                hint="Start Ollama or configure NVIDIA_API_KEY on the server.",
            ) from exc

    def health(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "model": self.model,
            "configured": self.client.is_up() and self.client.has_model(),
            "endpoint": self.client.host,
            "analysis_version": self.analysis_version,
        }


def build_ai_provider(client: OllamaClient) -> AIProvider:
    configured = os.environ.get("DRIPCUT_AI_PROVIDER", "auto").strip().lower()
    nvidia_key = os.environ.get("NVIDIA_API_KEY")
    if configured == "nvidia" or (configured == "auto" and nvidia_key):
        return NvidiaAIProvider(
            api_key=nvidia_key,
            model=os.environ.get(
                "DRIPCUT_AI_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"
            ),
            endpoint=os.environ.get(
                "DRIPCUT_AI_ENDPOINT", "https://integrate.api.nvidia.com/v1"
            ),
        )
    if configured not in {"auto", "ollama", "local"}:
        raise RuntimeError(f"Unsupported DRIPCUT_AI_PROVIDER: {configured}")
    return OllamaAIProvider(client)


def _validate(schema: type[SchemaT], payload: Any) -> SchemaT:
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise AIProviderError(
            "The AI returned a response that failed schema validation.",
            hint="Run this AI step again.",
        ) from exc


def _bounded(text: str, limit: int = 60000) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:limit]


def _ssl_context():
    import ssl

    return ssl.create_default_context(cafile=certifi.where())
