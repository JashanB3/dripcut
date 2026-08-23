"""Storage interfaces and filesystem adapters for the first production slice."""

from __future__ import annotations

import json
import mimetypes
import shutil
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

from dripcut.core.errors import ValidationError
from dripcut.engines.export.queue import JobQueue
from dripcut.models.job import Job
from dripcut.utils.fs import ensure_dir, safe_filename, slugify


@dataclass(slots=True)
class SourceAssetRecord:
    id: str
    kind: Literal["upload", "youtube"]
    name: str
    title: str
    path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    channel: str | None = None
    youtube_url: str | None = None
    poster_path: str | None = None
    project_id: str | None = None


@dataclass(slots=True)
class ArtifactRecord:
    id: str
    job_id: str
    kind: Literal["clip", "zip", "thumbnail"]
    name: str
    path: str
    size_bytes: int
    mime_type: str
    index: int | None = None
    duration: float | None = None
    output_format: str = "source"
    captions_enabled: bool = False


class SourceAssetStore(Protocol):
    def save_upload(
        self,
        file_name: str,
        stream: BinaryIO,
        *,
        kind: Literal["upload", "youtube"] = "upload",
    ) -> SourceAssetRecord: ...

    def save_path(
        self,
        path: Path,
        *,
        kind: Literal["upload", "youtube"],
        title: str = "",
    ) -> SourceAssetRecord: ...

    def update(self, record: SourceAssetRecord) -> SourceAssetRecord: ...

    def get(self, source_id: str) -> SourceAssetRecord: ...


class ArtifactStore(Protocol):
    def output_dir(self, job_id: str) -> Path: ...

    def register_clip(
        self,
        job_id: str,
        path: Path,
        *,
        index: int,
        duration: float,
        output_format: str = "source",
        captions_enabled: bool = False,
    ) -> ArtifactRecord: ...

    def create_zip(self, job_id: str, clips: list[ArtifactRecord], *, source_title: str) -> ArtifactRecord: ...

    def register_thumbnail(
        self, job_id: str, path: Path, *, index: int
    ) -> ArtifactRecord: ...

    def list_for_job(self, job_id: str) -> list[ArtifactRecord]: ...

    def discover_clips(self, job_id: str) -> list[ArtifactRecord]: ...

    def get(self, artifact_id: str) -> ArtifactRecord: ...


class JobStore(Protocol):
    def submit(self, job: Job) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...


class LocalSourceAssetStore:
    """Persist source files and metadata below one replaceable root."""

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root / "sources")
        self._lock = threading.RLock()

    def save_upload(
        self,
        file_name: str,
        stream: BinaryIO,
        *,
        kind: Literal["upload", "youtube"] = "upload",
    ) -> SourceAssetRecord:
        source_id = uuid.uuid4().hex
        directory = ensure_dir(self.root / source_id)
        clean_name = safe_filename(Path(file_name).name, fallback="source.mp4")
        target = directory / clean_name
        with target.open("wb") as handle:
            shutil.copyfileobj(stream, handle, length=1024 * 1024)
        if target.stat().st_size == 0:
            shutil.rmtree(directory, ignore_errors=True)
            raise ValidationError("The uploaded video is empty.", hint="Choose a video with content.")
        record = SourceAssetRecord(
            id=source_id,
            kind=kind,
            name=clean_name,
            title=Path(clean_name).stem,
            path=str(target),
            mime_type=mimetypes.guess_type(clean_name)[0] or "application/octet-stream",
            size_bytes=target.stat().st_size,
        )
        return self.update(record)

    def save_path(
        self,
        path: Path,
        *,
        kind: Literal["upload", "youtube"],
        title: str = "",
    ) -> SourceAssetRecord:
        with path.open("rb") as stream:
            record = self.save_upload(path.name, stream, kind=kind)
        if title:
            record.title = title
            self.update(record)
        return record

    def update(self, record: SourceAssetRecord) -> SourceAssetRecord:
        manifest = self.root / record.id / "source.json"
        with self._lock:
            temporary = manifest.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
            temporary.replace(manifest)
        return record

    def get(self, source_id: str) -> SourceAssetRecord:
        manifest = self._manifest(source_id)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            record = SourceAssetRecord(**data)
        except (OSError, ValueError, TypeError) as error:
            raise ValidationError("That source video is no longer available.") from error
        if not Path(record.path).is_file():
            raise ValidationError("That source video is no longer available.", hint="Import it again.")
        return record

    def _manifest(self, source_id: str) -> Path:
        if len(source_id) != 32 or any(char not in "0123456789abcdef" for char in source_id):
            raise ValidationError("That source video is not valid.")
        manifest = self.root / source_id / "source.json"
        if not manifest.is_file():
            raise ValidationError("That source video could not be found.", hint="Import it again.")
        return manifest


class LocalArtifactStore:
    """Persist clips and archive manifests without exposing filesystem paths."""

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root / "artifacts")
        self._lock = threading.RLock()

    def output_dir(self, job_id: str) -> Path:
        return ensure_dir(self.root / job_id / "clips")

    def register_clip(
        self,
        job_id: str,
        path: Path,
        *,
        index: int,
        duration: float,
        output_format: str = "source",
        captions_enabled: bool = False,
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            id=uuid.uuid4().hex,
            job_id=job_id,
            kind="clip",
            name=path.name,
            path=str(path),
            size_bytes=path.stat().st_size,
            mime_type=mimetypes.guess_type(path.name)[0] or "video/mp4",
            index=index,
            duration=round(duration, 3),
            output_format=output_format,
            captions_enabled=captions_enabled,
        )
        self._append(record)
        return record

    def create_zip(self, job_id: str, clips: list[ArtifactRecord], *, source_title: str) -> ArtifactRecord:
        directory = ensure_dir(self.root / job_id)
        folder_name = f"{slugify(source_title, max_length=80)}-clips"
        archive = directory / f"{folder_name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as handle:
            for clip in clips:
                handle.write(clip.path, arcname=f"{folder_name}/{clip.name}")
        record = ArtifactRecord(
            id=uuid.uuid4().hex,
            job_id=job_id,
            kind="zip",
            name=archive.name,
            path=str(archive),
            size_bytes=archive.stat().st_size,
            mime_type="application/zip",
        )
        self._append(record)
        return record

    def register_thumbnail(
        self, job_id: str, path: Path, *, index: int
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            id=uuid.uuid4().hex,
            job_id=job_id,
            kind="thumbnail",
            name=path.name,
            path=str(path),
            size_bytes=path.stat().st_size,
            mime_type=mimetypes.guess_type(path.name)[0] or "image/jpeg",
            index=index,
        )
        self._append(record)
        return record

    def list_for_job(self, job_id: str) -> list[ArtifactRecord]:
        return sorted(
            self._read_manifest(job_id),
            key=lambda item: (item.kind == "zip", item.index or 0, item.name),
        )

    def discover_clips(self, job_id: str) -> list[ArtifactRecord]:
        """Register valid partial clips only after a failed job has stopped."""
        records = self._read_manifest(job_id)
        known_paths = {record.path for record in records}
        clips_dir = self.root / job_id / "clips"
        for index, path in enumerate(sorted(clips_dir.glob("*")), start=1) if clips_dir.exists() else []:
            if (
                path.is_file()
                and str(path) not in known_paths
                and path.suffix.lower() in {".mp4", ".mov"}
                and path.stat().st_size > 0
            ):
                records.append(self.register_clip(job_id, path, index=index, duration=0.0))
        return self.list_for_job(job_id)

    def get(self, artifact_id: str) -> ArtifactRecord:
        if len(artifact_id) != 32 or any(char not in "0123456789abcdef" for char in artifact_id):
            raise ValidationError("That download is not valid.")
        for manifest in self.root.glob("*/artifacts.json"):
            for record in self._read_manifest(manifest.parent.name):
                if record.id == artifact_id and Path(record.path).is_file():
                    return record
        raise ValidationError("That download could not be found.", hint="Render the clips again.")

    def _append(self, record: ArtifactRecord) -> None:
        with self._lock:
            records = self._read_manifest(record.job_id)
            records = [existing for existing in records if existing.path != record.path]
            records.append(record)
            manifest = self.root / record.job_id / "artifacts.json"
            ensure_dir(manifest.parent)
            temporary = manifest.with_suffix(".json.tmp")
            temporary.write_text(json.dumps([asdict(item) for item in records], indent=2), encoding="utf-8")
            temporary.replace(manifest)

    def _read_manifest(self, job_id: str) -> list[ArtifactRecord]:
        manifest = self.root / job_id / "artifacts.json"
        if not manifest.is_file():
            return []
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return [ArtifactRecord(**item) for item in payload if Path(item["path"]).is_file()]
        except (OSError, ValueError, TypeError, KeyError):
            return []


class QueueJobStore:
    """JobStore adapter backed by DripCut's existing observable queue."""

    def __init__(self, queue: JobQueue) -> None:
        self.queue = queue

    def submit(self, job: Job) -> Job:
        return self.queue.submit(job)

    def get(self, job_id: str) -> Job | None:
        return self.queue.get(job_id)
