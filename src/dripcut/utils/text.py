"""Text helpers for captions, titles and LLM output cleanup."""

from __future__ import annotations

import json
import re
import textwrap
from typing import Any

__all__ = ["wrap_caption", "truncate", "extract_json", "strip_fences", "sentence_case"]

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")


def wrap_caption(text: str, *, max_chars: int = 34, max_lines: int = 2) -> str:
    """Wrap caption text to at most ``max_lines`` lines of ``max_chars``.

    Overflow is truncated with an ellipsis rather than pushed onto a third line,
    because burned-in captions must never cover the subject's face.
    """
    collapsed = " ".join((text or "").split())
    if not collapsed:
        return ""
    lines = textwrap.wrap(collapsed, width=max_chars) or [""]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    kept[-1] = truncate(kept[-1] + " " + " ".join(lines[max_lines:]), max_chars)
    return "\n".join(kept)


def truncate(text: str, max_chars: int) -> str:
    """Truncate with a trailing ellipsis, never mid-multibyte."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "\u2026"


def strip_fences(raw: str) -> str:
    """Remove Markdown code fences an LLM may have wrapped around its answer."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    return text


def extract_json(raw: str) -> Any:
    """Best-effort JSON extraction from a chatty local model response.

    Tries the whole string, then the outermost ``[...]`` or ``{...}`` span.

    Raises:
        ValueError: If no JSON value can be recovered.
    """
    text = strip_fences(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON value found in model response")


def sentence_case(text: str) -> str:
    """Capitalise the first letter and leave the rest of the string alone."""
    text = (text or "").strip()
    return text[:1].upper() + text[1:] if text else text
