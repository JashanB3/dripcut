"""Reusable presentation fragments.

Every function here returns an HTML string and imports nothing from Gradio. That
keeps the visual vocabulary in one place, makes it unit-testable without a browser
or a server, and means a page can compose chrome without pulling in the framework.

Class names are the contract published by ``ui/assets/styles.css``. Nothing here
invents a class: if a fragment needs a new look, the stylesheet gains a rule and
this module uses it.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "banner",
    "card",
    "chips",
    "clip_card",
    "commands_script",
    "empty_state",
    "kbd",
    "notes_list",
    "page_header",
    "project_card",
    "rail",
    "splash",
    "stat_grid",
    "status_dot",
    "table",
    "timecode",
    "timeline_strip",
]

_LEVEL_ICONS: Mapping[str, str] = {
    "success": "\u2714",
    "warning": "\u25b2",
    "error": "\u2716",
    "info": "\u00b7",
}


def _esc(value: object) -> str:
    """HTML-escape any value, including ``None``."""
    return html.escape("" if value is None else str(value), quote=True)


def _field(record: object, key: str, default: object = "") -> object:
    """Read ``key`` from a mapping or an object, so both records and dicts work."""
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _level(name: str) -> str:
    """Normalise a level name to one the stylesheet knows."""
    lowered = str(name).lower()
    return lowered if lowered in _LEVEL_ICONS else "info"


# ------------------------------------------------------------------ structure


def page_header(title: str, subtitle: str = "", *, eyebrow: str = "") -> str:
    """Page title block: optional eyebrow, display title, optional subtitle."""
    parts = ['<div class="dc-page-head">']
    if eyebrow:
        parts.append(f'<div class="dc-eyebrow">{_esc(eyebrow)}</div>')
    parts.append(f'<div class="dc-display">{_esc(title)}</div>')
    if subtitle:
        parts.append(f'<div class="dc-sub">{_esc(subtitle)}</div>')
    parts.append("</div>")
    return "".join(parts)


def card(body: str, *, title: str = "", eyebrow: str = "", tight: bool = False) -> str:
    """Panel wrapper. ``body`` is trusted HTML produced by another builder."""
    classes = "dc-card dc-card-tight" if tight else "dc-card"
    parts = [f'<div class="{classes}">']
    if eyebrow:
        parts.append(f'<div class="dc-eyebrow">{_esc(eyebrow)}</div>')
    if title:
        parts.append(f'<div class="dc-title">{_esc(title)}</div>')
    parts.append(body)
    parts.append("</div>")
    return "".join(parts)


def empty_state(headline: str, detail: str = "") -> str:
    """The 'nothing here yet' placeholder, with a suggestion for what to do."""
    detail_html = f"<div>{_esc(detail)}</div>" if detail else ""
    return f'<div class="dc-empty"><strong>{_esc(headline)}</strong>{detail_html}</div>'


# ----------------------------------------------------------------------- data


def stat_grid(stats: Sequence[tuple[str, object]]) -> str:
    """A row of headline numbers: ``[(label, value), ...]``."""
    if not stats:
        return ""
    cells = "".join(
        f'<div class="dc-stat"><div class="dc-stat-value">{_esc(value)}</div>'
        f'<div class="dc-stat-label">{_esc(label)}</div></div>'
        for label, value in stats
    )
    return f'<div class="dc-grid">{cells}</div>'


def table(headers: Sequence[str], rows: Iterable[Sequence[object]], *, mono: Sequence[int] = ()) -> str:
    """A compact data table.

    Args:
        headers: Column headings.
        rows: Row values, coerced to strings.
        mono: Indices of columns to render in the monospaced timecode face.
    """
    monoset = set(mono)
    head = "".join(f"<th>{_esc(name)}</th>" for name in headers)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(
            f'<td class="dc-mono">{_esc(value)}</td>' if index in monoset else f"<td>{_esc(value)}</td>"
            for index, value in enumerate(row)
        )
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        return empty_state("Nothing to show yet")
    return (
        f'<table class="dc-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def chips(labels: Iterable[str], *, accent: Iterable[str] = (), mint: Iterable[str] = ()) -> str:
    """Inline tag pills, with optional accent or mint emphasis per label."""
    accent_set, mint_set = set(accent), set(mint)
    out = []
    for label in labels:
        extra = " dc-chip-accent" if label in accent_set else " dc-chip-mint" if label in mint_set else ""
        out.append(f'<span class="dc-chip{extra}">{_esc(label)}</span>')
    return "".join(out)


def timecode(label: str, *, large: bool = False) -> str:
    """A monospaced timecode. Clicking one copies it (see app.js)."""
    cls = "dc-tc dc-tc-lg" if large else "dc-tc"
    return f'<span class="{cls}" title="Click to copy">{_esc(label)}</span>'


def kbd(*keys: str) -> str:
    """Keyboard hint glyphs."""
    return "".join(f'<span class="dc-kbd">{_esc(key)}</span>' for key in keys)


# ------------------------------------------------------------------- progress


def rail(fraction: float, label: str = "", *, state: str = "") -> str:
    """The sprocket rail: DripCut's signature progress indicator.

    Args:
        fraction: Completion between 0 and 1.
        label: Caption shown beneath the rail.
        state: ``"done"`` or ``"failed"`` to recolour the fill.
    """
    percent = max(0.0, min(1.0, float(fraction))) * 100
    modifier = f" dc-{state}" if state in {"done", "failed"} else ""
    label_html = f'<div class="dc-rail-label">{_esc(label)}</div>' if label else ""
    return (
        f'<div class="dc-rail"><div class="dc-rail-fill{modifier}" '
        f'style="width:{percent:.1f}%"></div></div>{label_html}'
    )


def timeline_strip(segments: Sequence[Mapping[str, Any]], *, total: float = 0.0) -> str:
    """Filmstrip of clip segments.

    Args:
        segments: Mappings with ``index``, ``label`` and optionally ``range``,
            ``width`` (a 0-1 share) and ``ai`` (truthy for AI-found clips).
        total: Source duration, used to size cells when ``width`` is absent.
    """
    if not segments:
        return empty_state("No clips planned yet", "Choose a split mode and press Plan.")
    cells = []
    for segment in segments:
        share = segment.get("width")
        if share is None and total > 0 and segment.get("duration") is not None:
            share = float(segment["duration"]) / total
        flex = f"flex:{max(0.02, float(share)):.4f}" if share else "flex:1"
        extra = " dc-ai" if segment.get("ai") else ""
        title = _esc(segment.get("range", ""))
        cells.append(
            f'<div class="dc-strip-cell{extra}" style="{flex}" title="{title}">'
            f'{_esc(segment.get("label", segment.get("index", "")))}</div>'
        )
    return f'<div class="dc-strip">{"".join(cells)}</div>'


# -------------------------------------------------------------- notifications


def banner(message: str, *, level: str = "info", title: str = "") -> str:
    """A prominent inline message."""
    resolved = _level(level)
    suffix = "" if resolved == "info" else f" dc-banner-{resolved}"
    strong = f"<strong>{_esc(title)}</strong>" if title else ""
    return f'<div class="dc-banner{suffix}">{strong}{_esc(message)}</div>'


def notes_list(notes: Sequence[Any], *, limit: int = 8) -> str:
    """Render :class:`~dripcut.services.notification_service.Notification` records.

    Accepts anything exposing ``level``, ``message``, ``detail`` and ``created_at``
    (or dict keys of the same names), so tests can pass plain dictionaries.
    """
    if not notes:
        return empty_state("No activity yet", "Jobs and warnings show up here.")
    rows = []
    for note in list(notes)[:limit]:
        level = _level(str(_field(note, "level", "info")))
        detail = _field(note, "detail", "")
        stamp = _field(note, "time_label", "") or _field(note, "created_label", "")
        rows.append(
            f'<div class="dc-note dc-note-{level}">'
            f'<div class="dc-note-icon">{_LEVEL_ICONS[level]}</div>'
            f'<div class="dc-note-body"><div class="dc-note-message">'
            f'{_esc(_field(note, "message", ""))}</div>'
            + (f'<div class="dc-note-detail">{_esc(detail)}</div>' if detail else "")
            + "</div>"
            + (f'<div class="dc-note-time">{_esc(stamp)}</div>' if stamp else "")
            + "</div>"
        )
    return "".join(rows)


def status_dot(state: str, label: str) -> str:
    """A status-bar indicator. ``state`` is ``on``, ``warn``, ``off`` or ``busy``."""
    modifier = state if state in {"on", "warn", "off", "busy"} else "off"
    return f'<span class="dc-dot dc-{modifier}"></span>{_esc(label)}'


# ----------------------------------------------------------------- rich cards


def clip_card(
    *,
    index: int,
    title: str,
    time_range: str,
    duration: str,
    score: float | None = None,
    reason: str = "",
) -> str:
    """One planned clip, as shown in the split and workspace pages."""
    meta = [timecode(time_range), f'<span class="dc-num">{_esc(duration)}</span>']
    if score is not None:
        meta.append(f'<span class="dc-chip dc-chip-accent">{score:.0%}</span>')
    detail = f'<div class="dc-note-detail">{_esc(reason)}</div>' if reason else ""
    return card(
        f'<div class="dc-project-name">{index:02d} \u00b7 {_esc(title)}</div>'
        f'<div class="dc-project-meta">{"".join(meta)}</div>{detail}',
        tight=True,
    )


def project_card(*, name: str, meta: str, thumbnail: str = "") -> str:
    """A project tile for the projects page and dashboard."""
    thumb = (
        f'<div class="dc-project-thumb" style="background-image:url({_esc(thumbnail)})"></div>'
        if thumbnail
        else '<div class="dc-project-thumb"></div>'
    )
    return (
        f'<div class="dc-project-card">{thumb}'
        f'<div class="dc-project-body"><div class="dc-project-name">{_esc(name)}</div>'
        f'<div class="dc-project-meta">{_esc(meta)}</div></div></div>'
    )


def splash() -> str:
    """First-paint overlay. The stylesheet fades it out on its own."""
    return '<div class="dc-splash"><div class="dc-splash-mark"></div></div>'


def commands_script(commands: Sequence[Mapping[str, Any]]) -> str:
    """Publish the command palette's entries for ``app.js`` to read.

    A ``<script type="application/json">`` block is data, not code: the browser
    never executes it, and the palette can open without a server round trip.
    """
    payload = json.dumps(list(commands), separators=(",", ":"))
    return f'<script type="application/json" id="dc-commands-data">{payload}</script>'
