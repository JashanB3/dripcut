"""Benchmark real NVIDIA models against DripCut's structured AI contracts."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections.abc import Callable
from typing import Any

from dripcut.engines.ai.provider import NvidiaAIProvider

DEFAULT_MODELS = (
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
)

TRANSCRIPT = """
[00:00-00:18] I thought posting more videos was the answer, but the extra volume made
every result worse. The problem was not effort. It was that viewers had no reason to
stay after the first sentence.
[00:18-00:48] I changed one thing: before recording, I wrote the payoff first and then
built a ten-second opening that created a specific unanswered question. Average watch
time rose from twenty-two percent to sixty-one percent in one week.
[00:48-01:18] Here is the exact test. Remove your introduction, show the surprising
result immediately, and promise one useful explanation. If the promise cannot be paid
off inside the clip, cut the idea rather than stretching it.
[01:18-01:48] One creator tried this on a tutorial that had stalled at eight hundred
views. The rewritten version reached forty-six thousand views, but the important part
was that comments repeated the lesson in their own words. That showed the story was
clear, not merely sensational.
[01:48-02:18] Use this checklist: one question, one proof point, one payoff. Keep the
caption readable on a phone and end before the energy drops. Save this and test it on
your next short.
"""

CLIPS = [
    {
        "id": "clip-a",
        "start": 18,
        "end": 48,
        "transcript": "One opening change raised average watch time from 22% to 61%.",
    },
    {
        "id": "clip-b",
        "start": 48,
        "end": 78,
        "transcript": "Remove the introduction, show the result, then promise one explanation.",
    },
    {
        "id": "clip-c",
        "start": 78,
        "end": 108,
        "transcript": "A tutorial grew from 800 to 46,000 views after the rewrite.",
    },
]


def _score_viral(value: Any) -> tuple[int, int]:
    valid = bool(value.segments) and all(
        segment.platform == "youtube" and 0 <= segment.start < segment.end <= 138
        for segment in value.segments
    )
    quality_checks = (
        (
            bool(segment.hook),
            len(segment.reason.split()) >= 5,
            segment.score >= 50,
        )
        for segment in value.segments
    )
    return int(valid), min(5, sum(sum(parts) for parts in quality_checks))


def _score_plan(value: Any) -> tuple[int, int]:
    checks = (
        value.platform == "instagram",
        value.selection == "viral",
        value.count == 3,
        value.duration == 30,
        value.aspect_ratio == "9:16",
        value.captions is True,
        value.reframe == "speaker",
    )
    return int(all(checks)), round(5 * sum(checks) / len(checks))


def _score_social(value: Any) -> tuple[int, int]:
    checks = (
        bool(value.youtube_title),
        len(value.youtube_title) <= 100,
        bool(value.youtube_hashtags),
        bool(value.instagram_caption),
        bool(value.instagram_hashtags),
        bool(value.instagram_cta),
        bool(value.hook),
    )
    return int(all(checks)), round(5 * sum(checks) / len(checks))


def _score_ranking(value: Any) -> tuple[int, int]:
    expected = {clip["id"] for clip in CLIPS}
    returned = {clip.id for clip in value.clips}
    checks = (
        returned == expected,
        len(value.clips) == len(CLIPS),
        all(len(clip.reason.split()) >= 3 for clip in value.clips),
        all(0 <= clip.score <= 100 for clip in value.clips),
    )
    return int(all(checks)), round(5 * sum(checks) / len(checks))


def _score_brief(value: Any) -> tuple[int, int]:
    checks = (
        bool(value.headline),
        bool(value.visual_focus),
        bool(value.emotion),
        bool(value.composition),
        bool(value.frame_guidance),
        bool(value.avoid),
    )
    return int(all(checks)), round(5 * sum(checks) / len(checks))


def _operations(provider: NvidiaAIProvider) -> list[tuple[str, Callable[[], Any], Callable[[Any], tuple[int, int]]]]:
    return [
        (
            "viral_moments",
            lambda: provider.find_viral_moments(
                TRANSCRIPT,
                duration=138,
                platform="youtube",
                target_length=30,
                max_clips=3,
                language="English",
                metadata={"destination": "YouTube Shorts"},
            ),
            _score_viral,
        ),
        (
            "editor_plan",
            lambda: provider.plan_edit(
                "Find 3 viral Instagram clips, each 30 seconds, in 9:16 with dynamic captions and speaker tracking.",
                duration=138,
            ),
            _score_plan,
        ),
        ("social_metadata", lambda: provider.generate_social_metadata(TRANSCRIPT), _score_social),
        ("thumbnail_ranking", lambda: provider.rank_clips(CLIPS, platform="youtube"), _score_ranking),
        (
            "thumbnail_brief",
            lambda: provider.generate_thumbnail_brief(
                TRANSCRIPT, prompt="High-contrast mobile thumbnail, no misleading claims"
            ),
            _score_brief,
        ),
    ]


def benchmark(model: str, *, rounds: int, timeout: float) -> dict[str, Any]:
    provider = NvidiaAIProvider(
        api_key=os.environ.get("NVIDIA_API_KEY"),
        model=model,
        endpoint=os.environ.get("DRIPCUT_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout=timeout,
    )
    runs: list[dict[str, Any]] = []
    for round_number in range(1, rounds + 1):
        for name, operation, scorer in _operations(provider):
            started = time.perf_counter()
            try:
                value = operation()
                instruction, quality = scorer(value)
                runs.append(
                    {
                        "round": round_number,
                        "operation": name,
                        "latency_seconds": round(time.perf_counter() - started, 3),
                        "schema_valid": True,
                        "instruction_following": instruction,
                        "quality": quality,
                    }
                )
            except Exception as exc:  # benchmark must record provider/schema failures
                runs.append(
                    {
                        "round": round_number,
                        "operation": name,
                        "latency_seconds": round(time.perf_counter() - started, 3),
                        "schema_valid": False,
                        "instruction_following": 0,
                        "quality": 0,
                        "error": type(exc).__name__,
                    }
                )
    latencies = [run["latency_seconds"] for run in runs]
    return {
        "model": model,
        "calls": len(runs),
        "schema_reliability": sum(run["schema_valid"] for run in runs) / len(runs),
        "instruction_reliability": sum(run["instruction_following"] for run in runs) / len(runs),
        "quality_score": sum(run["quality"] for run in runs) / len(runs),
        "median_latency_seconds": statistics.median(latencies),
        "total_latency_seconds": round(sum(latencies), 3),
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if not os.environ.get("NVIDIA_API_KEY"):
        raise SystemExit("NVIDIA_API_KEY must be set in the backend environment")
    results = [benchmark(model, rounds=args.rounds, timeout=args.timeout) for model in (args.models or DEFAULT_MODELS)]
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
