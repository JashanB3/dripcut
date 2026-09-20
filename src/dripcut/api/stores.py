"""Storage interfaces and filesystem adapters for the first production slice."""

from __future__ import annotations

import json
import logging
import mimetypes
import shutil
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

from dripcut.core.errors import ValidationError
from dripcut.engines.export.queue import JobQueue, JobStateStore, JsonJobStateStore
from dripcut.models.job import Job
from dripcut.storage.local import LocalStorageProvider
from dripcut.storage.models import UploadRejected
from dripcut.storage.provider import StorageProvider
from dripcut.utils.fs import ensure_dir, safe_filename, slugify

logger = logging.getLogger(__name__)


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
    storage_key: str | None = None
    poster_storage_key: str | None = None
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
    storage_key: str | None = None


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

    def signed_url(self, record: SourceAssetRecord, *, poster: bool = False) -> str | None: ...


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

    def signed_url(self, record: ArtifactRecord, *, download: bool = False) -> str | None: ...


class JobStore(Protocol):
    def submit(self, job: Job) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def get_by_idempotency_key(self, key: str) -> Job | None: ...


class LocalSourceAssetStore:
    """Persist source files and metadata below one replaceable root."""

    def __init__(
        self,
        root: Path,
        storage: StorageProvider | None = None,
        *,
        max_bytes: int | None = None,
    ) -> None:
        self.root = ensure_dir(root / "sources")
        self.storage = storage or LocalStorageProvider(root / "objects")
        self.max_bytes = max_bytes
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
        written = 0
        try:
            with target.open("wb") as handle:
                while chunk := stream.read(1024 * 1024):
                    written += len(chunk)
                    if self.max_bytes is not None and written > self.max_bytes:
                        raise UploadRejected(
                            "This video is larger than the upload limit.",
                            code="UPLOAD_TOO_LARGE",
                            status_code=413,
                            hint="Choose a smaller video or shorten it before uploading.",
                        )
                    handle.write(chunk)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
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
        return self._write_manifest(record)

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
            self._write_manifest(record)
        return record

    def update(self, record: SourceAssetRecord) -> SourceAssetRecord:
        source = Path(record.path)
        if source.is_file():
            record.storage_key = record.storage_key or f"sources/{record.id}/{record.name}"
            self.storage.put_file(
                record.storage_key,
                source,
                content_type=record.mime_type,
            )
        poster = Path(record.poster_path) if record.poster_path else None
        if poster and poster.is_file():
            record.poster_storage_key = (
                record.poster_storage_key or f"sources/{record.id}/poster.jpg"
            )
            self.storage.put_file(
                record.poster_storage_key,
                poster,
                content_type="image/jpeg",
            )
        return self._write_manifest(record)

    def _write_manifest(self, record: SourceAssetRecord) -> SourceAssetRecord:
        manifest = self.root / record.id / "source.json"
        with self._lock:
            ensure_dir(manifest.parent)
            temporary = manifest.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
            temporary.replace(manifest)
            self.storage.put_file(
                self._metadata_key(record.id),
                manifest,
                content_type="application/json",
            )
        return record

    def get(self, source_id: str) -> SourceAssetRecord:
        manifest = self._manifest(source_id)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            record = SourceAssetRecord(**data)
        except (OSError, ValueError, TypeError) as error:
            raise ValidationError("That source video is no longer available.") from error
        if not Path(record.path).is_file() and record.storage_key:
            try:
                self.storage.materialize(record.storage_key, Path(record.path))
            except Exception as error:
                raise ValidationError(
                    "That source video is no longer available.", hint="Import it again."
                ) from error
        if record.poster_path and not Path(record.poster_path).is_file() and record.poster_storage_key:
            try:
                self.storage.materialize(record.poster_storage_key, Path(record.poster_path))
            except Exception:
                record.poster_path = None
        if not Path(record.path).is_file():
            raise ValidationError(
                "That source video is no longer available.", hint="Import it again."
            )
        return record

    def signed_url(self, record: SourceAssetRecord, *, poster: bool = False) -> str | None:
        key = record.poster_storage_key if poster else record.storage_key
        if not key:
            return None
        return self.storage.signed_url(key, expires_seconds=900)

    def _manifest(self, source_id: str) -> Path:
        try:
            UUID(source_id)
        except ValueError as error:
            raise ValidationError("That source video is not valid.") from error
        manifest = self.root / source_id / "source.json"
        if not manifest.is_file():
            try:
                self.storage.materialize(self._metadata_key(source_id), manifest)
            except Exception as error:
                raise ValidationError(
                    "That source video could not be found.", hint="Import it again."
                ) from error
        return manifest

    @staticmethod
    def _metadata_key(source_id: str) -> str:
        return f"metadata/sources/{source_id}.json"


class LocalArtifactStore:
    """Persist clips and archive manifests without exposing filesystem paths."""

    def __init__(self, root: Path, storage: StorageProvider | None = None) -> None:
        self.root = ensure_dir(root / "artifacts")
        self.storage = storage or LocalStorageProvider(root / "objects")
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
        artifact_id = uuid.uuid4().hex
        record = ArtifactRecord(
            id=artifact_id,
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
            storage_key=f"artifacts/{job_id}/{artifact_id}/{path.name}",
        )
        self.storage.put_file(record.storage_key, path, content_type=record.mime_type)
        self._append(record)
        return record

    def create_zip(self, job_id: str, clips: list[ArtifactRecord], *, source_title: str) -> ArtifactRecord:
        directory = ensure_dir(self.root / job_id)
        folder_name = f"{slugify(source_title, max_length=80)}-clips"
        archive = directory / f"{folder_name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as handle:
            for clip in clips:
                handle.write(clip.path, arcname=f"{folder_name}/{clip.name}")
        artifact_id = uuid.uuid4().hex
        record = ArtifactRecord(
            id=artifact_id,
            job_id=job_id,
            kind="zip",
            name=archive.name,
            path=str(archive),
            size_bytes=archive.stat().st_size,
            mime_type="application/zip",
            storage_key=f"artifacts/{job_id}/{artifact_id}/{archive.name}",
        )
        self.storage.put_file(record.storage_key, archive, content_type=record.mime_type)
        self._append(record)
        return record

    def register_thumbnail(
        self, job_id: str, path: Path, *, index: int
    ) -> ArtifactRecord:
        artifact_id = uuid.uuid4().hex
        record = ArtifactRecord(
            id=artifact_id,
            job_id=job_id,
            kind="thumbnail",
            name=path.name,
            path=str(path),
            size_bytes=path.stat().st_size,
            mime_type=mimetypes.guess_type(path.name)[0] or "image/jpeg",
            index=index,
            storage_key=f"artifacts/{job_id}/{artifact_id}/{path.name}",
        )
        self.storage.put_file(record.storage_key, path, content_type=record.mime_type)
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
        try:
            UUID(artifact_id)
        except ValueError as error:
            raise ValidationError("That download is not valid.") from error
        for manifest in self.root.glob("*/artifacts.json"):
            for record in self._read_manifest(manifest.parent.name):
                if record.id != artifact_id:
                    continue
                if not Path(record.path).is_file() and record.storage_key:
                    try:
                        self.storage.materialize(record.storage_key, Path(record.path))
                    except Exception:
                        continue
                if Path(record.path).is_file():
                    return record
        record = self._restore_by_id(artifact_id)
        if record is not None:
            return record
        raise ValidationError("That download could not be found.", hint="Render the clips again.")

    def signed_url(self, record: ArtifactRecord, *, download: bool = False) -> str | None:
        if not record.storage_key:
            return None
        return self.storage.signed_url(
            record.storage_key,
            expires_seconds=900,
            download_name=record.name if download else None,
        )

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
            self.storage.put_file(
                self._job_metadata_key(record.job_id),
                manifest,
                content_type="application/json",
            )
            record_manifest = manifest.parent / f"{record.id}.json"
            record_manifest.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
            self.storage.put_file(
                self._artifact_metadata_key(record.id),
                record_manifest,
                content_type="application/json",
            )

    def _read_manifest(self, job_id: str) -> list[ArtifactRecord]:
        manifest = self.root / job_id / "artifacts.json"
        if not manifest.is_file():
            try:
                self.storage.materialize(self._job_metadata_key(job_id), manifest)
            except Exception:
                return []
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return [ArtifactRecord(**item) for item in payload]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def _restore_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        manifest = self.root / "recovered" / f"{artifact_id}.json"
        try:
            self.storage.materialize(self._artifact_metadata_key(artifact_id), manifest)
            record = ArtifactRecord(**json.loads(manifest.read_text(encoding="utf-8")))
            if record.storage_key and not Path(record.path).is_file():
                self.storage.materialize(record.storage_key, Path(record.path))
            if not Path(record.path).is_file():
                return None
            self._append(record)
            return record
        except Exception:
            # Object providers use SDK-specific not-found exceptions.
            return None

    @staticmethod
    def _job_metadata_key(job_id: str) -> str:
        return f"metadata/jobs/{job_id}/artifacts.json"

    @staticmethod
    def _artifact_metadata_key(artifact_id: str) -> str:
        return f"metadata/artifacts/{artifact_id}.json"


class QueueJobStore:
    """JobStore adapter backed by DripCut's existing observable queue."""

    def __init__(self, queue: JobQueue) -> None:
        self.queue = queue

    def submit(self, job: Job) -> Job:
        return self.queue.submit(job)

    def get(self, job_id: str) -> Job | None:
        return self.queue.get(job_id)

    def get_by_idempotency_key(self, key: str) -> Job | None:
        return self.queue.get_by_idempotency_key(key)


class ObjectJobStateStore(JobStateStore):
    """Persist the single-instance queue snapshot in private object storage."""

    def __init__(
        self,
        storage: StorageProvider,
        cache_path: Path,
        *,
        key: str = "metadata/queue/jobs.json",
    ) -> None:
        self.storage = storage
        self.cache_path = cache_path
        self.key = key
        self.local = JsonJobStateStore(cache_path)

    def load(self) -> list[dict[str, object]]:
        if not self.cache_path.is_file():
            try:
                self.storage.materialize(self.key, self.cache_path)
            except Exception:
                return []
        return self.local.load()

    def save(self, jobs: list[dict[str, object]]) -> None:
        self.local.save(jobs)
        if not self.cache_path.is_file():
            return
        try:
            self.storage.put_file(
                self.key,
                self.cache_path,
                content_type="application/json",
            )
        except Exception:
            logger.warning("could not persist durable job state", exc_info=True)

    def save_local(self, jobs: list[dict[str, object]]) -> None:
        """Checkpoint live progress without a blocking object-store round trip."""
        self.local.save(jobs)
