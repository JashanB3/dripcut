"""Prompt templates for the local LLM.

Prompts live in their own module because they are product surface, not plumbing:
tuning the highlight rubric changes what users get without touching engine code.
Every prompt demands strict JSON and states the schema, which is what makes a 3B
quantised model usable for structured work.
"""

from __future__ import annotations

__all__ = [
    "SYSTEM_EDITOR",
    "HIGHLIGHT_PROMPT",
    "HOOK_PROMPT",
    "TITLE_PROMPT",
    "SUMMARY_PROMPT",
    "CHAPTER_PROMPT",
    "FOCUS_RUBRICS",
]

SYSTEM_EDITOR = (
    "You are a senior short-form video editor. You judge spoken transcripts for "
    "clip-worthiness with a cold eye: a moment only counts if it lands without "
    "surrounding context. You always answer with valid JSON and nothing else."
)

FOCUS_RUBRICS: dict[str, str] = {
    "auto": (
        "Pick the moments with the strongest pull, whatever kind they are: a sharp "
        "claim, a surprising fact, a funny beat, or a clean explanation."
    ),
    "hooks": (
        "Pick moments that open strongly - a question, a contradiction, a promise, or "
        "a bold claim in the first sentence."
    ),
    "funny": "Pick moments that are actually funny: a punchline, a roast, a good mistake.",
    "educational": (
        "Pick moments that teach one complete idea: a definition, a mechanism, a "
        "worked example, a rule of thumb."
    ),
    "story": (
        "Pick narrative peaks: the turn, the reveal, the consequence. A setup without "
        "a payoff does not count."
    ),
    "quotes": "Pick the most quotable single sentences, the kind that work as a caption.",
}

HIGHLIGHT_PROMPT = """\
{rubric}

You are given a timed transcript. Each line is:
[index] HH:MM:SS -> HH:MM:SS  text

Choose up to {max_clips} moments. Each moment must:
- be between {min_length:.0f} and {max_length:.0f} seconds long, aiming for about {target_length:.0f} seconds,
- start at the beginning of a sentence and end at the end of one,
- make sense to someone who has not watched anything before it,
- not overlap another chosen moment.

Return JSON in exactly this shape:
{{"clips": [{{"start": "HH:MM:SS", "end": "HH:MM:SS", "title": "under 60 characters",
"score": 0.0, "reason": "under 90 characters", "tags": ["one", "two"]}}]}}

score is your confidence from 0 to 1 that this clip performs on its own.

TRANSCRIPT
{transcript}
"""

HOOK_PROMPT = """\
Find the strongest opening lines in this transcript - sentences that would make a
viewer stop scrolling within two seconds.

Return JSON: {{"hooks": [{{"time": "HH:MM:SS", "text": "the line, verbatim",
"strength": 0.0, "why": "under 80 characters"}}]}}

Pick at most {max_hooks}. strength runs 0 to 1.

TRANSCRIPT
{transcript}
"""

TITLE_PROMPT = """\
Write {count} titles for a short video containing this speech. Rules: under 60
characters, no emoji, no hashtags, no clickbait phrasing like "you won't believe",
plain sentence case, specific rather than vague.

Return JSON: {{"titles": ["...", "..."]}}

SPEECH
{text}
"""

SUMMARY_PROMPT = """\
Summarise what is said in this transcript.

Return JSON: {{"summary": "two sentences", "topics": ["up to five topics"],
"tone": "one word"}}

TRANSCRIPT
{transcript}
"""

CHAPTER_PROMPT = """\
Split this transcript into chapters at genuine topic changes. Use at most {max_chapters}.

Return JSON: {{"chapters": [{{"time": "HH:MM:SS", "title": "under 50 characters"}}]}}

TRANSCRIPT
{transcript}
"""
