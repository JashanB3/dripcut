"""Workspace page: guard paths and real job creation for all nine tools.

These are smoke tests over the UI layer. They build the page inside a real Blocks
context, then call the handlers directly -- the same functions Gradio calls -- so a
broken signature or a bad service call fails here rather than in a browser.
"""

from __future__ import annotations

import pytest

gr = pytest.importorskip("gradio", reason="gradio is not installed")

from dripcut.models.job import JobStatus  # noqa: E402
from dripcut.ui.pages.base import PageContext  # noqa: E402
from dripcut.ui.pages.workspace import WorkspacePage  # noqa: E402
from tests.conftest import needs_ffmpeg  # noqa: E402


@pytest.fixture
def page(container) -> WorkspacePage:
    """A built Workspace page bound to the test container."""
    built = WorkspacePage()
    with gr.Blocks():
        built.build(PageContext(container=container), visible=True)
    return built


def _is_banner(markup: str) -> bool:
    return "dc-banner" in markup


@pytest.mark.parametrize(
    ("handler", "args"),
    [
        ("_trim", (None, 0.0, 1.0, True, "high", "")),
        ("_transform", (None, 0, 0, "fit", 0, "", 0, 1.0, "high", "")),
        ("_compress", (None, "small", 0, 0, "")),
        ("_convert", (None, "mp4", "balanced", "")),
        ("_audio", (None, "m4a", "192k", False, "")),
        ("_frames", (None, 1.0, 0, "png", "")),
        ("_gif", (None, 0, 2, 12, 320, "")),
        ("_watermark", (None, None, "hi", "bottom-right", 0.8, 24, "")),
    ],
)
def test_every_tool_guards_a_missing_file(page: WorkspacePage, handler: str, args) -> None:
    """No tool may raise when nothing has been dropped in yet."""
    _, message = getattr(page, handler)(*args)
    assert _is_banner(message)


def test_page_declares_a_primary_button(page: WorkspacePage) -> None:
    targets = {command.get("target") for command in page.commands()}
    assert "dc-primary-workspace" in targets


def test_commands_cover_all_nine_tools(page: WorkspacePage) -> None:
    workspace_commands = [c for c in page.commands() if c.get("group") == "Workspace"]
    assert len(workspace_commands) == 9


@needs_ffmpeg
def test_load_probes_the_file(page: WorkspacePage, sample_video) -> None:
    media, info, message = page._load(str(sample_video))
    assert media is not None
    assert "sample" in info
    assert message == ""


def test_load_ignores_an_empty_path(page: WorkspacePage) -> None:
    assert page._load(None) == (None, "", "")


@needs_ffmpeg
def test_trim_rejects_a_backwards_range(page: WorkspacePage, media) -> None:
    _, message = page._trim(media, 5.0, 1.0, True, "high", "")
    assert "end time" in message.lower()


@needs_ffmpeg
def test_transform_with_no_changes_is_refused(page: WorkspacePage, media) -> None:
    _, message = page._transform(media, 0, 0, "fit", 0, "", 0, 1.0, "high", "")
    assert "nothing to do" in message.lower()


@needs_ffmpeg
def test_watermark_needs_content(page: WorkspacePage, media) -> None:
    _, message = page._watermark(media, None, "  ", "bottom-right", 0.8, 24, "")
    assert _is_banner(message)


@needs_ffmpeg
def test_merge_needs_two_files(page: WorkspacePage, sample_video) -> None:
    _, message = page._merge([str(sample_video)], "merged", "mp4", "")
    assert "at least two" in message.lower()


@needs_ffmpeg
@pytest.mark.parametrize(
    ("handler", "extra"),
    [
        ("_compress", ("small", 0, 0)),
        ("_convert", ("mkv", "balanced")),
        ("_audio", ("m4a", "192k", False)),
        ("_frames", (2.0, 0, "png")),
    ],
)
def test_tools_queue_a_job(page: WorkspacePage, media, tmp_path, handler, extra) -> None:
    """Each tool must produce a real queued Job, not just a rendered confirmation."""
    card, message = getattr(page, handler)(media, *extra, str(tmp_path))
    assert message == "", message
    assert "Queued" in card
    assert "dc-table" in card


@needs_ffmpeg
def test_trim_runs_end_to_end(page: WorkspacePage, container, media, tmp_path) -> None:
    card, message = page._trim(media, 0.0, 1.0, True, "small", str(tmp_path))
    assert message == "" and "Queued" in card
    assert container.resolve("queue").wait(timeout=90)
    job = container.resolve("queue").all_jobs()[0]
    assert job.status is JobStatus.SUCCEEDED, job.error
    assert job.result.outputs[0].exists()
