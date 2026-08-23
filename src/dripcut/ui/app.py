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
from dripcut.core.network import pick_server_port
from dripcut.ui.components.shell import build_sidebar, build_statusbar, render_statusbar
from dripcut.ui.components.widgets import page_header, splash
from dripcut.ui.pages import build_pages, group_for, nav_items, nav_layout
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
        "<script>(function(){var apply=function(){var r=document.querySelector('.dripcut')||document.body;"
        f"if(r){{r.classList.add('dripcut');r.setAttribute('data-theme','{theme_mode}');}}else{{setTimeout(apply,80);}}}};"
        "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',apply);}"
        "else{apply();}})();</script>"
    )
    return data + (f"<script>{script}</script>" if script else "") + boot


def palette_commands(_settings: Any) -> list[dict[str, str]]:
    """Every command-palette entry: one per page, plus the global actions."""
    entries: list[dict[str, str]] = []
    for page in build_pages():
        entries.extend(page.commands())
    entries.extend(
        [
            {"label": "Switch theme", "group": "View", "kind": "theme", "keywords": "dark light"},
            {"label": "Toggle sidebar", "group": "View", "kind": "sidebar", "keywords": "hide"},
            {"label": "Keyboard shortcuts", "group": "Help", "kind": "shortcuts", "keywords": "keys"},
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
  const root = document.querySelector('.dripcut') || document.body;
  if (!root) return;
  root.classList.add('dripcut');
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
            ai_state, ai_label = "off", "AI optional"
        elif ai["ollama_up"] and ai["ollama_model_installed"] and ai["whisper_installed"]:
            ai_state, ai_label = "on", "AI captions ready"
        elif ai["whisper_installed"]:
            ai_state, ai_label = "warn", "Captions ready"
        else:
            ai_state, ai_label = "off", "Captions need setup"
    except Exception:  # noqa: BLE001 - ditto
        ai_state, ai_label = "off", "Captions need setup"

    counts = ctx.queue.stats()
    return render_statusbar(
        ready=ffmpeg_ready,
        ai_label=ai_label,
        ai_state=ai_state,
        jobs_running=counts.get("running", 0),
        jobs_queued=counts.get("queued", 0),
        output_label="Download mode",
        notice=notice,
    )


# --------------------------------------------------------------------- welcome
#
# The welcome screen is the only part of DripCut a person meets before they have
# done any work, so it carries the whole promise on one screen: what this is, and
# two ways in. Log in and Sign up are one card with a segmented switch rather than
# two competing forms, because showing both at once makes a visitor read before
# they can act.


def _auth_nav() -> str:
    """Marketing top bar above the welcome split."""
    return (
        '<nav class="dc-auth-nav" aria-label="DripCut">'
        '<div class="dc-auth-brand">'
        '<span class="dc-auth-logo" aria-hidden="true"></span>'
        '<span class="dc-auth-word">DripCut</span>'
        "</div>"
        '<div class="dc-auth-links">'
        "<span>Clips</span><span>Captions</span><span>Templates</span><span>Pricing</span>"
        "</div>"
        '<div class="dc-auth-nav-actions"><span>Log in</span><span>Sign up free</span></div>'
        "</nav>"
    )


def _auth_marketing() -> str:
    """The left half of the welcome split: what DripCut does, in three claims."""
    return (
        '<div class="dc-auth-copy">'
        '<div class="dc-auth-eyebrow">\u2728 Free while it runs on your machine</div>'
        "<h1>What will you <em>clip</em> today?</h1>"
        "<p>Turn one long video into a set of captioned clips for Reels, Shorts "
        "and TikTok. Upload, pick a style, download the ZIP.</p>"
        '<ul class="dc-auth-points">'
        "<li><i>\u2702</i><div>Clip in one pass"
        "<small>Scene, silence or AI highlights \u2014 you pick.</small></div></li>"
        "<li><i>\u2263</i><div>Captions that fit vertical"
        "<small>Burned in, sized for phone screens.</small></div></li>"
        "<li><i>\u2913</i><div>One ZIP, ready to post"
        "<small>No export maze, no watermark, nothing to upload.</small></div></li>"
        "</ul>"
        '<div class="dc-auth-proof">'
        '<span class="dc-auth-faces"><span></span><span></span><span></span><span></span></span>'
        "Everything renders locally. Your footage never leaves this computer."
        "</div>"
        "</div>"
    )


_AUTH_COPY: dict[str, dict[str, str]] = {
    "login": {
        "heading": "Welcome back",
        "detail": "Log in to pick up your latest clips and ZIPs.",
        "submit": "Log in",
        "fine": "New to DripCut? Choose <b>Sign up</b> above \u2014 it takes one field.",
    },
    "signup": {
        "heading": "Create your account",
        "detail": "Start clipping in under a minute. No card, no upload limits.",
        "submit": "Create free account",
        "fine": "By continuing you agree to the <b>Terms</b> and <b>Privacy Policy</b>.",
    },
}


def _auth_card_head(mode: str) -> str:
    """Heading block inside the auth card for ``login`` or ``signup``."""
    copy = _AUTH_COPY.get(mode, _AUTH_COPY["login"])
    return (
        '<div class="dc-auth-card-head">'
        f'<h2>{copy["heading"]}</h2>'
        f'<p>{copy["detail"]}</p>'
        "</div>"
    )


def _auth_fineprint(mode: str) -> str:
    """Small print under the submit button."""
    return f'<p class="dc-auth-fineprint">{_AUTH_COPY[mode]["fine"]}</p>'


def _topbar_search() -> str:
    """Search chip in the header.

    ``data-dc-palette`` is the hook ``app.js`` already listens for, so this chip
    and the Cmd+K shortcut open exactly the same command palette rather than two
    similar-looking things that behave differently.
    """
    return (
        '<div class="dc-topbar-search" data-dc-palette role="button" tabindex="0">'
        '<span class="dc-topbar-search-icon" aria-hidden="true">\u2315</span>'
        "<span>Search tools and pages</span>"
        '<span class="dc-kbd">\u2318K</span>'
        "</div>"
    )


def _topbar_account() -> str:
    """Account chip in the editor header."""
    return (
        '<div class="dc-topbar-account">'
        '<span class="dc-topbar-plan">Studio</span>'
        '<span class="dc-avatar" aria-hidden="true">D</span>'
        "</div>"
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
    layout = nav_layout(items)
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

        auth_buttons: list[gr.Button] = []
        with gr.Column(elem_classes=["dc-auth-screen"]) as auth_screen:
            gr.HTML(_auth_nav())
            with gr.Row(elem_classes=["dc-auth-stage"], equal_height=False):
                gr.HTML(_auth_marketing())
                with gr.Column(elem_classes=["dc-auth-card"]):
                    card_head = gr.HTML(_auth_card_head("login"))
                    with gr.Row(elem_classes=["dc-auth-switch"]):
                        login_tab = gr.Button(
                            "Log in", elem_classes=["dc-auth-tab", "dc-on"]
                        )
                        signup_tab = gr.Button("Sign up", elem_classes=["dc-auth-tab"])
                    with gr.Column(elem_classes=["dc-auth-oauth"]):
                        # The provider marks are drawn by the stylesheet so the
                        # button label stays plain text for screen readers.
                        google_button = gr.Button(
                            "Continue with Google",
                            elem_classes=["dc-btn", "dc-auth-alt", "dc-auth-google"],
                        )
                        apple_button = gr.Button(
                            "Continue with Apple",
                            elem_classes=["dc-btn", "dc-auth-alt", "dc-auth-apple"],
                        )
                    gr.HTML('<div class="dc-auth-divider">or use your email</div>')
                    name_field = gr.Textbox(
                        label="Name",
                        placeholder="Your creator name",
                        visible=False,
                        elem_classes=["dc-auth-input"],
                    )
                    gr.Textbox(
                        label="Email",
                        placeholder="you@example.com",
                        type="email",
                        elem_classes=["dc-auth-input"],
                    )
                    gr.Textbox(
                        label="Password",
                        placeholder="At least 8 characters",
                        type="password",
                        elem_classes=["dc-auth-input"],
                    )
                    forgot = gr.HTML(
                        '<div class="dc-auth-forgot">Forgot password?</div>'
                    )
                    submit_button = gr.Button(
                        "Log in",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary", "dc-auth-submit"],
                    )
                    guest_button = gr.Button(
                        "Skip \u2014 open the studio",
                        elem_classes=["dc-btn", "dc-auth-ghost"],
                    )
                    fineprint = gr.HTML(_auth_fineprint("login"))
                    auth_buttons.extend(
                        [submit_button, google_button, apple_button, guest_button]
                    )

        with gr.Row(elem_classes=["dc-shell"], equal_height=False, visible=False) as shell:
            # "Create" starts open so the five making tools are visible on
            # first run rather than hidden behind a row nobody has clicked yet.
            sidebar = build_sidebar(
                items,
                layout,
                active=default_key,
                open_groups=("create",),
            )

            with gr.Column(elem_classes=["dc-main"]):
                with gr.Row(elem_classes=["dc-topbar"], equal_height=True):
                    heading = gr.HTML(_heading_for(pages, default_key))
                    with gr.Row(elem_classes=["dc-topbar-actions"]):
                        gr.HTML(_topbar_search())
                        theme_button = gr.Button(
                            "\u25d0",
                            elem_id="dc-theme-toggle",
                            elem_classes=["dc-btn", "dc-icon-btn"],
                        )
                        gr.HTML(_topbar_account())
                built = {
                    page.key: page.build(ctx, visible=page.key == default_key) for page in pages
                }
                status = build_statusbar(_status_snapshot(ctx))

        # -------------------------------------------------------------- router
        order = [page.key for page in pages]
        group_keys = list(sidebar.panels)
        group_state = {key: gr.State(True) for key in group_keys}
        nested = {
            key: bool(group_for(layout, key)) for key in order
        }

        def _nav_classes(key: str, *, active: bool) -> list[str]:
            """Classes for a navigation row in its current state."""
            classes = ["dc-nav-item"]
            if nested.get(key):
                classes.append("dc-nav-sub")
            if active:
                classes.append("dc-active")
            return classes

        def _toggle_classes(*, open_: bool) -> list[str]:
            classes = ["dc-nav-item", "dc-nav-toggle"]
            if open_:
                classes.append("dc-open")
            return classes

        def route(target: str, *states: Any) -> list[Any]:
            """Show one page, update the heading, refresh the status bar.

            Navigating into a collapsed group opens it, because arriving on a
            page whose row is hidden leaves no trace of where you are.
            """
            _log.debug("navigating to %s", target)
            updates: list[Any] = [gr.update(visible=key == target) for key in order]
            updates.append(_heading_for(pages, target))
            updates.append(_status_snapshot(ctx))
            updates.extend(
                gr.update(elem_classes=_nav_classes(key, active=key == target))
                for key in order
            )
            owner = group_for(layout, target)
            for index, group_key in enumerate(group_keys):
                is_open = bool(states[index]) or group_key == owner
                updates.append(is_open)
                updates.append(gr.update(visible=is_open))
                updates.append(gr.update(elem_classes=_toggle_classes(open_=is_open)))
            return updates

        outputs = [
            *[built[key] for key in order],
            heading,
            status.html,
            *[sidebar.buttons[key] for key in order],
        ]
        for group_key in group_keys:
            outputs.extend(
                [
                    group_state[group_key],
                    sidebar.panels[group_key],
                    sidebar.toggles[group_key],
                ]
            )
        route_inputs = [group_state[key] for key in group_keys]
        for key in order:
            sidebar.buttons[key].click(
                lambda *states, target=key: route(target, *states),
                inputs=route_inputs,
                outputs=outputs,
                show_progress="hidden",
            )

        # ------------------------------------------------------ group toggles
        def flip_group(is_open: Any) -> tuple[Any, Any, Any]:
            """Open or close one sidebar disclosure."""
            nxt = not bool(is_open)
            return (
                nxt,
                gr.update(visible=nxt),
                gr.update(elem_classes=_toggle_classes(open_=nxt)),
            )

        for group_key, toggle in sidebar.toggles.items():
            toggle.click(
                flip_group,
                inputs=group_state[group_key],
                outputs=[
                    group_state[group_key],
                    sidebar.panels[group_key],
                    toggle,
                ],
                show_progress="hidden",
            )

        # ----------------------------------------------------------- auth gate
        def enter_app() -> tuple[Any, Any, str]:
            """Move from the public welcome screen into the editor workspace."""
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                _status_snapshot(ctx, notice="Welcome to DripCut"),
            )

        for button in auth_buttons:
            button.click(
                enter_app,
                outputs=[auth_screen, shell, status.html],
                js="() => { setTimeout(() => window.scrollTo({top: 0, left: 0}), 50); }",
                show_progress="hidden",
            )

        def switch_auth(mode: str) -> tuple[Any, ...]:
            """Swap the card between logging in and signing up.

            One card, two states: the segmented control, heading, name field,
            submit label and small print all move together so the person is never
            looking at a form that half belongs to the other mode.
            """
            signing_up = mode == "signup"
            return (
                _auth_card_head(mode),
                gr.update(visible=signing_up, interactive=signing_up),
                gr.update(visible=not signing_up),
                gr.update(value=_AUTH_COPY[mode]["submit"]),
                _auth_fineprint(mode),
                gr.update(
                    elem_classes=["dc-auth-tab"]
                    if signing_up
                    else ["dc-auth-tab", "dc-on"]
                ),
                gr.update(
                    elem_classes=["dc-auth-tab", "dc-on"]
                    if signing_up
                    else ["dc-auth-tab"]
                ),
            )

        auth_switch_outputs = [
            card_head,
            name_field,
            forgot,
            submit_button,
            fineprint,
            login_tab,
            signup_tab,
        ]
        login_tab.click(
            lambda: switch_auth("login"),
            outputs=auth_switch_outputs,
            show_progress="hidden",
        )
        signup_tab.click(
            lambda: switch_auth("signup"),
            outputs=auth_switch_outputs,
            show_progress="hidden",
        )

        # -------------------------------------------------------- theme toggle

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
    _enable_queue(app, container)
    options: dict[str, Any] = {
        "server_name": settings.server.host,
        "server_port": settings.server.port,
        "share": False,  # never: DripCut is local-only by design
        "inbrowser": False,  # the CLI opens the browser so it can time it
        "show_api": False,
        "quiet": True,
    }
    paths = getattr(container, "paths", None)
    if paths is not None:
        options["allowed_paths"] = [str(paths.temp), str(paths.cache)]
    if not _accepts(gr.Blocks.__init__, "theme"):  # Gradio 6+ wants them here
        options.update(presentation_options(settings))

    logo = _package_logo()
    if logo is not None:
        options["favicon_path"] = str(logo)

    options.update(overrides)
    options["server_port"] = pick_server_port(
        str(options["server_name"]), int(options["server_port"])
    )
    supported = {key: value for key, value in options.items() if _accepts(app.launch, key)}
    dropped = sorted(set(options) - set(supported))
    if dropped:
        _log.debug("this Gradio does not accept launch options: %s", ", ".join(dropped))
    _log.info("serving on http://%s:%s", options["server_name"], options["server_port"])
    app.launch(**supported)


def _enable_queue(app: gr.Blocks, container: ServiceContainer) -> None:
    """Use Gradio's queue so long renders can stream progress and finish cleanly."""
    queue = getattr(app, "queue", None)
    if queue is None:
        return
    video_settings = getattr(container.settings, "video", None)
    max_workers = max(1, int(getattr(video_settings, "max_workers", 1)))
    options = {
        "status_update_rate": "auto",
        "default_concurrency_limit": max_workers,
    }
    supported = {key: value for key, value in options.items() if _accepts(queue, key)}
    try:
        queue(**supported)
    except TypeError:
        _log.debug("this Gradio queue does not accept configured options", exc_info=True)


def _package_logo() -> Any:
    """Path to the bundled logo, or ``None`` when it is missing."""
    from pathlib import Path  # noqa: PLC0415

    assets = Path(__file__).resolve().parent / "assets"
    for name in ("logo.png", "logo.svg"):  # the PNG is the real brand mark
        candidate = assets / name
        if candidate.exists():
            return candidate
    return None


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
