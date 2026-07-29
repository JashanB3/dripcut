"""Gradio application shell.

This module composes: it creates the Blocks tree, injects the theme and assets,
builds each page, and wires navigation. It holds no business logic -- every action
a page performs goes through a service, and every service arrives through the
container built by :mod:`dripcut.core.bootstrap`.

The router is deliberately dumb. One column per page, exactly one visible at a
time, switched by real button clicks so there is no client-side state to drift out
of sync with the server.
"""

from __future__ import annotations

import inspect
import json
from typing import TYPE_CHECKING, Any

import gradio as gr

from dripcut import APP_NAME, APP_TAGLINE, __version__
from dripcut.core.config import save_settings
from dripcut.core.logging import get_logger
from dripcut.ui.components.shell import build_sidebar, build_statusbar, render_statusbar
from dripcut.ui.components.widgets import page_header, splash
from dripcut.ui.pages import build_pages, nav_items
from dripcut.ui.pages.base import PageContext
from dripcut.ui.theme import build_theme, load_css, load_js

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dripcut.core.container import ServiceContainer

__all__ = ["build_app", "launch"]

_log = get_logger("ui.app")


def _accepts(callable_obj: Any, name: str) -> bool:
    """True when ``callable_obj`` takes a keyword argument called ``name``.

    Gradio moved ``theme``, ``css`` and ``head`` from ``Blocks()`` to ``launch()``
    in 6.0, and dropped ``show_api``. Asking the signature is more durable than
    parsing a version string, and it keeps the declared ``gradio>=4.44`` floor
    honest on both sides of that change.
    """
    try:
        return name in inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):  # pragma: no cover - C-implemented callable
        return False


def _head(theme_mode: str, commands: list[dict[str, str]]) -> str:
    """Head markup: the client script plus the initial theme attribute.

    ``app.js`` goes in the head rather than a ``gr.HTML`` block because browsers do
    not execute scripts inserted through ``innerHTML``; it also needs to exist
    before first paint so the command palette is available immediately.
    """
    script = load_js()
    payload = json.dumps(commands, separators=(",", ":"))
    data = f"<script>window.__dripcutCommands={payload};</script>"
    boot = (
        "<script>(function(){var apply=function(){var r=document.querySelector('.dripcut');"
        f"if(r){{r.setAttribute('data-theme','{theme_mode}');}}else{{setTimeout(apply,80);}}}};"
        "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',apply);}"
        "else{apply();}})();</script>"
    )
    return data + (f"<script>{script}</script>" if script else "") + boot


def palette_commands(settings: Any) -> list[dict[str, str]]:
    """Every command-palette entry: one per page, plus the global actions."""
    entries: list[dict[str, str]] = []
    for page in build_pages():
        entries.extend(page.commands())
    entries.extend(
        [
            {"label": "Switch theme", "group": "View", "kind": "theme", "keywords": "dark light"},
            {"label": "Toggle sidebar", "group": "View", "kind": "sidebar", "keywords": "hide"},
            {"label": "Keyboard shortcuts", "group": "Help", "kind": "shortcuts", "keywords": "keys"},
            {
                "label": "Copy output folder",
                "group": "Help",
                "kind": "copy",
                "value": str(settings.output_path),
                "keywords": "path clipboard",
            },
        ]
    )
    return entries


def presentation_options(settings: Any) -> dict[str, Any]:
    """Theme, stylesheet and head markup, wherever this Gradio wants them."""
    mode = "light" if str(settings.ui.theme).lower() == "light" else "dark"
    return {
        "theme": build_theme(mode),
        "css": load_css(),
        "head": _head(mode, palette_commands(settings)),
    }


# Flips the root `data-theme` attribute client-side. Every colour in the
# stylesheet is a CSS variable keyed on that attribute, so this is the whole swap.
_THEME_JS = """() => {
  const root = document.querySelector('.dripcut');
  if (!root) return;
  const next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  root.setAttribute('data-theme', next);
  if (window.dripcutNotify) window.dripcutNotify(next === 'light' ? 'Light theme' : 'Dark theme', 'info');
}"""


def _status_snapshot(ctx: PageContext, notice: str = "") -> str:
    """Current status-bar markup, rebuilt from live service state."""
    try:
        ffmpeg_ready = bool(ctx.container.resolve("ffmpeg").version())
    except Exception:  # noqa: BLE001 - the status bar must never raise
        ffmpeg_ready = False

    try:
        ai = ctx.ai.status()
        if not ai["enabled"]:
            ai_state, ai_label = "off", "AI off"
        elif ai["ollama_up"] and ai["ollama_model_installed"] and ai["whisper_installed"]:
            ai_state, ai_label = "on", f"AI ready ({ai['ollama_model']})"
        elif ai["whisper_installed"]:
            ai_state, ai_label = "warn", "AI partial"
        else:
            ai_state, ai_label = "off", "AI unavailable"
    except Exception:  # noqa: BLE001 - ditto
        ai_state, ai_label = "off", "AI unavailable"

    counts = ctx.queue.stats()
    return render_statusbar(
        ready=ffmpeg_ready,
        ai_label=ai_label,
        ai_state=ai_state,
        jobs_running=counts.get("running", 0),
        jobs_queued=counts.get("queued", 0),
        output_label=str(ctx.output_dir),
        notice=notice,
    )


def build_app(container: ServiceContainer) -> gr.Blocks:
    """Build the Blocks application.

    Args:
        container: A fully wired service container.

    Returns:
        The Blocks app, ready to ``launch()``.
    """
    ctx = PageContext(container=container)
    settings = container.settings
    pages = build_pages()
    items = nav_items(pages)
    default_key = settings.ui.default_page
    if default_key not in {page.key for page in pages}:
        default_key = pages[0].key

    blocks_kwargs: dict[str, Any] = {
        "title": f"{APP_NAME} \u2014 {APP_TAGLINE}",
        "analytics_enabled": False,
        "fill_height": True,
    }
    if _accepts(gr.Blocks.__init__, "theme"):  # Gradio 4/5
        blocks_kwargs.update(presentation_options(settings))

    with gr.Blocks(**blocks_kwargs) as app:
        gr.HTML(splash())

        with gr.Row(elem_classes=["dc-shell"], equal_height=False):
            sidebar = build_sidebar(items, active=default_key)

            with gr.Column(elem_classes=["dc-main"]):
                heading = gr.HTML(_heading_for(pages, default_key))
                built = {
                    page.key: page.build(ctx, visible=page.key == default_key) for page in pages
                }
                status = build_statusbar(_status_snapshot(ctx))

        # -------------------------------------------------------------- router
        order = [page.key for page in pages]

        def route(target: str) -> list[Any]:
            """Show one page, update the heading, refresh the status bar."""
            _log.debug("navigating to %s", target)
            updates: list[Any] = [gr.update(visible=key == target) for key in order]
            updates.append(_heading_for(pages, target))
            updates.append(_status_snapshot(ctx))
            updates.extend(
                gr.update(
                    elem_classes=["dc-nav-item", "dc-active"]
                    if key == target
                    else ["dc-nav-item"]
                )
                for key in order
            )
            return updates

        outputs = [
            *[built[key] for key in order],
            heading,
            status.html,
            *[sidebar.buttons[key] for key in order],
        ]
        for key in order:
            sidebar.buttons[key].click(
                lambda target=key: route(target), outputs=outputs, show_progress="hidden"
            )

        # -------------------------------------------------------- theme toggle
        theme_button = gr.Button(visible=False, elem_id="dc-theme-toggle")

        def flip_theme() -> str:
            """Persist the opposite theme; the DOM swap happens in ``_THEME_JS``.

            Persistence is the server's job because the theme is a durable
            preference in settings.json -- there is deliberately no browser
            storage anywhere in DripCut.
            """
            current = "light" if str(settings.ui.theme).lower() == "light" else "dark"
            nxt = "dark" if current == "light" else "light"
            settings.ui.theme = nxt
            try:
                save_settings(settings, container.paths.config_file)
            except OSError:
                _log.warning("could not persist the theme change", exc_info=True)
            return _status_snapshot(ctx, notice=f"{nxt} theme")

        theme_button.click(
            flip_theme, outputs=status.html, js=_THEME_JS, show_progress="hidden"
        )

        app.load(lambda: _status_snapshot(ctx), outputs=status.html, show_progress="hidden")

    _log.info("interface composed with %d pages", len(pages))
    return app


def _heading_for(pages: list[Any], key: str) -> str:
    """Page header markup for the active page."""
    for page in pages:
        if page.key == key:
            return page_header(page.title or page.label, page.subtitle, eyebrow=page.group)
    return page_header(APP_NAME, APP_TAGLINE)


def launch(container: ServiceContainer, **overrides: Any) -> None:
    """Build and serve the application.

    Args:
        container: A wired service container.
        **overrides: Passed through to ``Blocks.launch`` for tests and embedding.
    """
    settings = container.settings
    app = build_app(container)
    options: dict[str, Any] = {
        "server_name": settings.server.host,
        "server_port": settings.server.port,
        "share": False,  # never: DripCut is local-only by design
        "inbrowser": False,  # the CLI opens the browser so it can time it
        "show_api": False,
        "quiet": True,
    }
    if not _accepts(gr.Blocks.__init__, "theme"):  # Gradio 6+ wants them here
        options.update(presentation_options(settings))

    logo = _package_logo()
    if logo is not None:
        options["favicon_path"] = str(logo)

    options.update(overrides)
    supported = {key: value for key, value in options.items() if _accepts(app.launch, key)}
    dropped = sorted(set(options) - set(supported))
    if dropped:
        _log.debug("this Gradio does not accept launch options: %s", ", ".join(dropped))
    _log.info("serving on http://%s:%s", options["server_name"], options["server_port"])
    app.launch(**supported)


def _package_logo() -> Any:
    """Path to the bundled logo, or ``None`` when it is missing."""
    from pathlib import Path  # noqa: PLC0415

    candidate = Path(__file__).resolve().parent / "assets" / "logo.svg"
    return candidate if candidate.exists() else None


def describe_app(container: ServiceContainer) -> str:
    """A JSON summary of the composed interface, used by tests and diagnostics."""
    pages = build_pages()
    return json.dumps(
        {
            "version": __version__,
            "theme": container.settings.ui.theme,
            "pages": [page.key for page in pages],
            "commands": sum(len(page.commands()) for page in pages),
        },
        indent=2,
    )
