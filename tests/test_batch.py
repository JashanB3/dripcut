"""Batch page: file collection, validation, and queueing one job for many files."""

from __future__ import annotations

import pytest

gr = pytest.importorskip("gradio", reason="gradio is not installed")

from dripcut.models.job import JobStatus  # noqa: E402
from dripcut.ui.pages.base import PageContext  # noqa: E402
from dripcut.ui.pages.batch import BatchPage  # noqa: E402
from tests.conftest import needs_ffmpeg  # noqa: E402


@pytest.fixture
def page(container) -> BatchPage:
    """A built Batch page bound to the test container."""
    built = BatchPage()
    with gr.Blocks():
        built.build(PageContext(container=container), visible=True)
    return built


def test_empty_list_renders_an_empty_state(page: BatchPage) -> None:
    assert "dc-empty" in page._listing([])
    assert "dc-grid" in page._stats([])


def test_operation_help_is_specific(page: BatchPage) -> None:
    for operation in ("resize", "audio", "gif", "thumbnail"):
        assert page._operation_help(operation).strip()
    assert page._operation_help("invented") == ""


def test_scan_needs_a_folder(page: BatchPage) -> None:
    *_, message = page._scan("", False)
    assert "folder" in message.lower()


def test_scan_rejects_a_missing_folder(page: BatchPage, tmp_path) -> None:
    *_, message = page._scan(str(tmp_path / "nope"), False)
    assert "not a folder" in message.lower()


def test_scan_of_an_empty_folder_says_so(page: BatchPage, tmp_path) -> None:
    """The service raises for an empty folder; the page renders it as a warning."""
    empty = tmp_path / "empty"
    empty.mkdir()
    items, _, _, message = page._scan(str(empty), False)
    assert items == []
    assert "dc-banner-warning" in message
    assert "no readable media" in message.lower()


@needs_ffmpeg
def test_scan_finds_media(page: BatchPage, sample_video) -> None:
    items, stats, listing, message = page._scan(str(sample_video.parent), False)
    assert len(items) >= 1
    assert "dc-table" in listing
    assert "imported" in message.lower()


@needs_ffmpeg
def test_add_skips_duplicates(page: BatchPage, sample_video) -> None:
    items, *_ = page._add([], [str(sample_video)])
    again, *_ = page._add(items, [str(sample_video)])
    assert len(again) == len(items) == 1


def test_add_needs_a_selection(page: BatchPage) -> None:
    *_, message = page._add([], [])
    assert "pick some files" in message.lower()


def test_run_refuses_an_empty_batch(page: BatchPage) -> None:
    _, message = page._run([], "resize", 640, 360, "fit", "m4a", 4, "")
    assert "empty batch" in message.lower()


@needs_ffmpeg
def test_resize_needs_a_target_size(page: BatchPage, media) -> None:
    _, message = page._run([media], "resize", 0, 0, "fit", "m4a", 4, "")
    assert "target size" in message.lower()


@needs_ffmpeg
def test_run_queues_one_job_for_the_whole_batch(page: BatchPage, container, media, tmp_path) -> None:
    card, message = page._run([media], "thumbnail", 320, 0, "fit", "m4a", 4, str(tmp_path))
    assert "Batch queued" in card
    assert "batch started" in message.lower()
    assert len(container.resolve("queue").all_jobs()) == 1, "a batch must be a single job"


@needs_ffmpeg
def test_batch_thumbnail_runs_to_completion(page: BatchPage, container, media, tmp_path) -> None:
    page._run([media], "thumbnail", 320, 0, "fit", "m4a", 4, str(tmp_path))
    assert container.resolve("queue").wait(timeout=90)
    job = container.resolve("queue").all_jobs()[0]
    assert job.status is JobStatus.SUCCEEDED, job.error
    assert job.result.outputs and job.result.outputs[0].exists()


@needs_ffmpeg
def test_stats_total_the_list(page: BatchPage, media) -> None:
    rendered = page._stats([media, media])
    assert "dc-stat" in rendered
    assert ">2<" in rendered


def test_page_declares_its_commands(page: BatchPage) -> None:
    targets = {command.get("target") for command in page.commands()}
    assert "dc-primary-batch" in targets
