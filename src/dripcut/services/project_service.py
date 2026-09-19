"""Project store: one directory per project, one JSON manifest inside it."""

from __future__ import annotations

import json
import shutil
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from dripcut.core.errors import ProjectError, ValidationError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.core.paths import AppPaths
from dripcut.models.media import MediaInfo
from dripcut.models.project import Project, ProjectSummary
from dripcut.utils.fs import dir_size, ensure_dir, human_size

if TYPE_CHECKING:
    from dripcut.storage.provider import StorageProvider

__all__ = ["ProjectService"]

_log = get_logger("services.projects")

MANIFEST_NAME = "project.json"


class ProjectService:
    """Create, load, save and delete projects.

    Deliberately file-based rather than SQLite: a project stays inspectable, is
    trivially backed up, and survives an app version the user never installs.
    """

    def __init__(
        self,
        paths: AppPaths,
        events: EventBus,
        storage: StorageProvider | None = None,
    ) -> None:
        self.paths = paths
        self.events = events
        self.storage = storage
        self._lock = threading.RLock()

    def configure_storage(self, storage: StorageProvider) -> None:
        """Mirror manifests to durable object storage for hosted processes."""
        self.storage = storage

    # -------------------------------------------------------------------- create

    def create(self, name: str, media: MediaInfo | None = None) -> Project:
        """Create a project directory and manifest."""
        clean_name = (name or "").strip() or (media.stem if media else "Untitled")
        project = Project(
            name=clean_name,
            source_path=media.path if media else None,
            duration=media.duration if media else 0.0,
        )
        ensure_dir(self.directory_for(project.id))
        self.save(project)
        self.events.publish(EventName.PROJECT_CREATED, project_id=project.id, name=project.name)
        _log.info("created project %s (%s)", project.name, project.id)
        return project

    def directory_for(self, project_id: str) -> Path:
        """Directory holding a project's manifest and artefacts."""
        return self.paths.project_dir(project_id)

    def clips_dir(self, project: Project) -> Path:
        """Where rendered clips for this project go."""
        return ensure_dir(self.directory_for(project.id) / "clips")

    def cache_dir(self, project: Project) -> Path:
        """Where derived data (transcript, subtitles) for this project goes."""
        return ensure_dir(self.directory_for(project.id) / "cache")

    # ---------------------------------------------------------------- persistence

    def save(self, project: Project) -> Path:
        """Write the manifest atomically and return its path."""
        project.touch()
        directory = ensure_dir(self.directory_for(project.id))
        manifest = directory / MANIFEST_NAME
        with self._lock:
            tmp = manifest.with_suffix(".json.tmp")
            try:
                tmp.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
                tmp.replace(manifest)
                if self.storage is not None:
                    self.storage.put_file(
                        self._metadata_key(project.id),
                        manifest,
                        content_type="application/json",
                    )
            except OSError as exc:
                raise ProjectError(
                    f"Could not save {project.name}.", hint=str(exc)[:160]
                ) from exc
        self.events.publish(EventName.PROJECT_UPDATED, project_id=project.id, name=project.name)
        return manifest

    def load(self, project_id: str) -> Project:
        """Read a project by id.

        Raises:
            ProjectError: If the manifest is missing or unreadable.
        """
        manifest = self.directory_for(project_id) / MANIFEST_NAME
        if not manifest.exists() and self.storage is not None:
            with suppress(Exception):
                self.storage.materialize(self._metadata_key(project_id), manifest)
        if not manifest.exists():
            raise ProjectError(f"Project {project_id} could not be found.")
        try:
            return Project.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
            raise ProjectError(
                f"Project {project_id} could not be read.",
                hint="Its manifest may be damaged. Check project.json.",
            ) from exc

    def list_projects(
        self,
        *,
        limit: int | None = None,
        project_ids: set[str] | None = None,
    ) -> list[ProjectSummary]:
        """Summaries for every readable project, most recently updated first."""
        summaries: list[ProjectSummary] = []
        if project_ids is not None:
            for project_id in project_ids:
                try:
                    summaries.append(self.load(project_id).summary())
                except ProjectError:
                    _log.debug("skipping unreadable project %s", project_id)
            summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
            return summaries[:limit] if limit else summaries
        if not self.paths.projects.exists():
            return summaries
        for directory in self.paths.projects.iterdir():
            if not directory.is_dir() or not (directory / MANIFEST_NAME).exists():
                continue
            try:
                summaries.append(self.load(directory.name).summary())
            except ProjectError:
                _log.debug("skipping unreadable project %s", directory.name)
        summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
        return summaries[:limit] if limit else summaries

    def delete(self, project_id: str, *, keep_outputs: bool = True) -> None:
        """Delete a project.

        Args:
            project_id: Project to remove.
            keep_outputs: Leave rendered clips on disk (the default, because losing
                renders to a mis-click is unforgivable).
        """
        if self.storage is not None:
            self.load(project_id)
        directory = self.directory_for(project_id)
        if not directory.exists():
            raise ProjectError(f"Project {project_id} could not be found.")
        if keep_outputs:
            clips = directory / "clips"
            if clips.exists() and any(clips.iterdir()):
                keep_root = ensure_dir(self.paths.output / f"{project_id}-kept")
                for item in clips.iterdir():
                    shutil.move(str(item), str(keep_root / item.name))
        shutil.rmtree(directory, ignore_errors=True)
        if self.storage is not None:
            try:
                self.storage.delete(self._metadata_key(project_id))
            except Exception:
                _log.warning("could not delete durable project manifest %s", project_id)
        self.events.publish(EventName.PROJECT_DELETED, project_id=project_id)
        _log.info("deleted project %s", project_id)

    @staticmethod
    def _metadata_key(project_id: str) -> str:
        return f"metadata/projects/{project_id}.json"

    def duplicate(self, project_id: str, *, name: str | None = None) -> Project:
        """Copy a project's plan and settings into a new project."""
        original = self.load(project_id)
        clone = Project(
            name=name or f"{original.name} copy",
            source_path=original.source_path,
            duration=original.duration,
            plan=original.plan,
            caption_style=original.caption_style,
            tags=list(original.tags),
            notes=original.notes,
        )
        ensure_dir(self.directory_for(clone.id))
        self.save(clone)
        return clone

    def rename(self, project_id: str, name: str) -> Project:
        """Rename a project."""
        if not (name or "").strip():
            raise ValidationError("A project needs a name.")
        project = self.load(project_id)
        project.name = name.strip()
        self.save(project)
        return project

    # ------------------------------------------------------------------ reporting

    def storage_report(self) -> list[tuple[str, str]]:
        """Disk usage per DripCut directory, for the Settings page."""
        return [
            ("Projects", human_size(dir_size(self.paths.projects))),
            ("Cache", human_size(dir_size(self.paths.cache))),
            ("Models", human_size(dir_size(self.paths.models))),
            ("Logs", human_size(dir_size(self.paths.logs))),
        ]

    def purge_cache(self) -> str:
        """Delete regenerable caches and report how much was freed."""
        freed = dir_size(self.paths.cache)
        for child in self.paths.cache.iterdir() if self.paths.cache.exists() else []:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        ensure_dir(self.paths.cache)
        ensure_dir(self.paths.temp)
        return human_size(freed)
