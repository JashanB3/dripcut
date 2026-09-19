"""Project service: the full create, read, update, delete cycle on disk."""

from __future__ import annotations

import json
import shutil

import pytest

from dripcut.core.errors import ProjectError
from dripcut.storage.local import LocalStorageProvider
from tests.conftest import needs_ffmpeg


def test_create_and_save(container, paths) -> None:
    project = container.projects.create("First project")
    manifest = container.projects.save(project)
    assert manifest.exists() and manifest.name == "project.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["name"] == "First project"


def test_manifest_is_readable_without_the_app(container) -> None:
    """A project must stay recoverable with a text editor."""
    project = container.projects.create("Readable")
    payload = json.loads(container.projects.save(project).read_text(encoding="utf-8"))
    assert {"name", "id", "version"} <= set(payload)


def test_load_round_trips(container) -> None:
    created = container.projects.create("Round trip")
    container.projects.save(created)
    loaded = container.projects.load(created.id)
    assert loaded.id == created.id and loaded.name == created.name


def test_load_rejects_an_unknown_id(container) -> None:
    with pytest.raises(ProjectError):
        container.projects.load("no-such-project")


def test_list_returns_summaries(container) -> None:
    for name in ("Alpha", "Beta", "Gamma"):
        container.projects.save(container.projects.create(name))
    summaries = container.projects.list_projects()
    assert len(summaries) == 3
    assert {item.name for item in summaries} == {"Alpha", "Beta", "Gamma"}


def test_list_honours_a_limit(container) -> None:
    for index in range(5):
        container.projects.save(container.projects.create(f"Project {index}"))
    assert len(container.projects.list_projects(limit=2)) == 2


def test_projects_restore_from_object_storage_after_fresh_process(container, paths) -> None:
    storage = LocalStorageProvider(paths.home / "durable-objects")
    container.projects.configure_storage(storage)
    project = container.projects.create("Durable project")
    shutil.rmtree(paths.projects)

    restored = container.projects.load(project.id)
    listed = container.projects.list_projects(project_ids={project.id})

    assert restored.name == "Durable project"
    assert [item.id for item in listed] == [project.id]


def test_rename_keeps_the_id(container) -> None:
    project = container.projects.create("Before")
    container.projects.save(project)
    renamed = container.projects.rename(project.id, "After")
    assert renamed.id == project.id and renamed.name == "After"


def test_duplicate_makes_a_new_id(container) -> None:
    original = container.projects.create("Original")
    container.projects.save(original)
    copy = container.projects.duplicate(original.id)
    assert copy.id != original.id
    assert len(container.projects.list_projects()) == 2


def test_delete_removes_it(container) -> None:
    project = container.projects.create("Doomed")
    container.projects.save(project)
    container.projects.delete(project.id)
    assert container.projects.list_projects() == []


def test_storage_report_has_rows(container) -> None:
    container.projects.save(container.projects.create("Sized"))
    report = container.projects.storage_report()
    assert report and all(len(row) == 2 for row in report)


def test_purge_cache_is_safe_when_empty(container) -> None:
    assert isinstance(container.projects.purge_cache(), str)


@needs_ffmpeg
def test_project_records_its_source(container, media) -> None:
    project = container.projects.create("With media", media)
    container.projects.save(project)
    loaded = container.projects.load(project.id)
    assert loaded.source_path
    assert loaded.duration == pytest.approx(media.duration, abs=0.1)


def test_slug_is_filesystem_safe(container) -> None:
    project = container.projects.create("Name: with / awkward * characters")
    assert "/" not in project.slug and ":" not in project.slug
