"""Social scheduler: plan posts from the latest DripCut ZIP."""

from __future__ import annotations

from datetime import datetime, timedelta

import gradio as gr

from dripcut.ui.components.widgets import banner, card, empty_state, stat_grid, table
from dripcut.ui.pages.base import Page, PageContext, safe_call

__all__ = ["SocialPage"]


class SocialPage(Page):
    """Prepare Instagram Reels and YouTube Shorts schedules."""

    key = "social"
    label = "Schedule"
    icon = "\u25ce"
    group = "Output"
    title = "Schedule"
    subtitle = "Turn the latest ZIP into a posting calendar for Reels and Shorts."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the social scheduling page."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page dc-social-page"]) as column:
            message = gr.HTML()
            with gr.Row(elem_classes=["dc-social-grid"], equal_height=False):
                with gr.Column(scale=2):
                    latest = gr.HTML(self._latest_card())
                    connections = gr.HTML(self._connections())
                    refresh = gr.Button(
                        "Refresh status",
                        elem_classes=["dc-btn", "dc-btn-secondary"],
                        elem_id="dc-primary-social",
                    )
                with gr.Column(scale=3):
                    gr.HTML(
                        card(
                            "<p>Choose where each clip should go, pick an interval, "
                            "and DripCut will create a clean posting plan. Actual "
                            "auto-posting switches on after OAuth credentials are configured.</p>",
                            title="Post planner",
                        )
                    )
                    platforms = gr.CheckboxGroup(
                        choices=[
                            ("Instagram Reels", "instagram"),
                            ("YouTube Shorts", "youtube"),
                        ],
                        value=["instagram", "youtube"],
                        label="Where should these clips go?",
                    )
                    with gr.Row(elem_classes=["dc-social-options"]):
                        start_at = gr.Textbox(
                            label="Start time",
                            value=self._default_start(),
                            placeholder="2026-08-22 18:30 or now",
                        )
                        interval = gr.Slider(
                            5,
                            1440,
                            value=60,
                            step=5,
                            label="Interval between posts (minutes)",
                        )
                    caption = gr.Textbox(
                        label="Caption template",
                        value="{clip} #shorts #reels",
                        lines=3,
                        placeholder="{clip} for the file name, {platform} for Instagram or YouTube",
                    )
                    create = gr.Button(
                        "Create schedule",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-social-create",
                    )
                    schedule = gr.HTML(self._schedule())

            refresh.click(
                self._refresh,
                outputs=[latest, connections, schedule, message],
                show_progress="hidden",
            )
            create.click(
                self._create,
                inputs=[platforms, interval, start_at, caption],
                outputs=[latest, connections, schedule, message],
            )
        return column

    # ---------------------------------------------------------------- panels

    def _latest_card(self) -> str:
        """Latest ZIP status."""
        if self._ctx is None:
            return ""
        summary, error = safe_call(self._ctx.social.latest_summary, fallback={})
        if error:
            return card(empty_state("No ZIP ready yet", "Create clips first."), title="Latest ZIP")
        if not summary or not summary.get("ready"):
            return card(
                empty_state("No ZIP ready yet", "Use Make Clips or AI Clips, then come back here."),
                title="Latest ZIP",
            )
        return card(
            stat_grid(
                [
                    ("Archive", summary.get("archive_name", "")),
                    ("Clips", summary.get("clips", 0)),
                    ("Size", summary.get("size", "")),
                ]
            ),
            title="Latest ZIP",
        )

    def _connections(self) -> str:
        """Connection readiness cards."""
        if self._ctx is None:
            return ""
        rows = []
        for item in self._ctx.social.connections():
            state = "Connected" if item.connected else "Setup needed"
            rows.append((item.label, state, item.detail, item.setup_hint))
        return card(
            table(["Account", "State", "Detail", "Setup"], rows),
            title="Accounts",
        )

    def _schedule(self) -> str:
        """Most recent schedule table."""
        if self._ctx is None:
            return ""
        schedule = self._ctx.social.latest_schedule()
        if schedule is None:
            return card(
                empty_state(
                    "No schedule yet",
                    "Create one after your ZIP is ready. It will show every clip and posting time.",
                ),
                title="Draft schedule",
            )
        rows = [
            (
                index,
                post.platform.title(),
                post.clip_name,
                post.publish_at,
                post.caption,
                post.status.title(),
            )
            for index, post in enumerate(schedule.posts, start=1)
        ]
        return card(
            table(["#", "Platform", "Clip", "Publish at", "Caption", "State"], rows, mono=(0, 3)),
            title=f"Draft schedule · {schedule.archive_name}",
        )

    def _refresh(self) -> tuple[str, str, str, str]:
        """Refresh every panel."""
        return self._latest_card(), self._connections(), self._schedule(), ""

    def _create(
        self,
        platforms: list[str],
        interval_minutes: float,
        start_at: str,
        caption: str,
    ) -> tuple[str, str, str, str]:
        """Create a new draft schedule from the latest ZIP."""
        if self._ctx is None:
            return *self._refresh()[:3], banner("Not ready yet.", level="error")
        _schedule, error = safe_call(
            self._ctx.social.create_schedule,
            platforms=platforms,
            interval_minutes=int(interval_minutes),
            start_at=start_at,
            caption=caption,
        )
        panels = self._refresh()[:3]
        if error:
            return *panels, error
        return *panels, banner(
            "Schedule created. Connect accounts to enable automatic publishing.",
            level="success",
            title="Ready to schedule",
        )

    @staticmethod
    def _default_start() -> str:
        """Default to the next hour-ish local slot."""
        return (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus main scheduling action."""
        return [
            *super().commands(),
            {
                "label": "Create social schedule",
                "group": "Schedule",
                "target": "dc-social-create",
                "keywords": "instagram youtube reels shorts interval publish",
            },
        ]
