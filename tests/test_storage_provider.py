"""Private local/S3 storage and upload policy tests."""

from __future__ import annotations

import shutil
import threading
import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from dripcut.api.app import build_service, create_app
from dripcut.api.stores import LocalArtifactStore, LocalSourceAssetStore, ObjectJobStateStore
from dripcut.core.events import EventBus
from dripcut.engines.export.queue import LocalJobQueue
from dripcut.models.job import Job, JobKind, JobResult, JobStatus
from dripcut.storage.local import LocalStorageProvider
from dripcut.storage.s3 import S3StorageProvider


class FakeS3Client:
    def __init__(self) -> None:
        self.upload: tuple[str, str, str, dict[str, str]] | None = None
        self.presign: tuple[str, dict[str, object], int] | None = None

    def upload_file(self, source: str, bucket: str, key: str, *, ExtraArgs: dict[str, str]) -> None:
        self.upload = (source, bucket, key, ExtraArgs)

    def generate_presigned_url(
        self, operation: str, *, Params: dict[str, object], ExpiresIn: int
    ) -> str:
        self.presign = (operation, Params, ExpiresIn)
        return "https://objects.example.test/private-signed-url"


def test_local_stores_restore_files_from_private_object_storage(tmp_path: Path) -> None:
    provider = LocalStorageProvider(tmp_path / "objects")
    sources = LocalSourceAssetStore(tmp_path / "state", provider, max_bytes=1024)
    source = sources.save_upload("source.mp4", BytesIO(b"video-bytes"))
    source.mime_type = "video/mp4"
    sources.update(source)
    assert source.storage_key
    Path(source.path).unlink()
    restored = sources.get(source.id)
    assert Path(restored.path).read_bytes() == b"video-bytes"

    artifacts = LocalArtifactStore(tmp_path / "state", provider)
    clip_path = artifacts.output_dir("job-1") / "clip.mp4"
    clip_path.write_bytes(b"rendered-clip")
    clip = artifacts.register_clip("job-1", clip_path, index=1, duration=1)
    assert clip.storage_key
    clip_path.unlink()
    recovered_clip = artifacts.get(clip.id)
    assert Path(recovered_clip.path).read_bytes() == b"rendered-clip"


def test_local_stores_recover_metadata_on_a_fresh_server(tmp_path: Path) -> None:
    provider = LocalStorageProvider(tmp_path / "objects")
    state_root = tmp_path / "state"
    sources = LocalSourceAssetStore(state_root, provider)
    source = sources.save_upload("fresh-source.mp4", BytesIO(b"fresh-video"))
    source.mime_type = "video/mp4"
    sources.update(source)

    artifacts = LocalArtifactStore(state_root, provider)
    clip_path = artifacts.output_dir("fresh-job") / "clip-01.mp4"
    clip_path.write_bytes(b"fresh-clip")
    clip = artifacts.register_clip("fresh-job", clip_path, index=1, duration=2)

    shutil.rmtree(state_root)

    fresh_sources = LocalSourceAssetStore(state_root, provider)
    restored_source = fresh_sources.get(source.id)
    assert restored_source.storage_key == source.storage_key
    assert Path(restored_source.path).read_bytes() == b"fresh-video"

    fresh_artifacts = LocalArtifactStore(state_root, provider)
    restored_clip = fresh_artifacts.get(clip.id)
    assert restored_clip.job_id == "fresh-job"
    assert Path(restored_clip.path).read_bytes() == b"fresh-clip"
    assert [item.id for item in fresh_artifacts.list_for_job("fresh-job")] == [clip.id]


def test_job_state_restores_from_object_storage_after_fresh_process(tmp_path: Path) -> None:
    provider = LocalStorageProvider(tmp_path / "objects")
    first_cache = tmp_path / "first" / "history.json"
    first = LocalJobQueue(
        EventBus(),
        state_store=ObjectJobStateStore(provider, first_cache),
    )
    try:
        submitted = first.submit(
            Job(kind=JobKind.TRIM, title="durable", run=lambda _job: JobResult())
        )
        assert first.wait(timeout=10)
        assert submitted.status is JobStatus.SUCCEEDED
    finally:
        first.shutdown()

    shutil.rmtree(first_cache.parent)
    second = LocalJobQueue(
        EventBus(),
        state_store=ObjectJobStateStore(provider, tmp_path / "second" / "history.json"),
    )
    try:
        restored = second.get(submitted.id)
        assert restored is not None
        assert restored.status is JobStatus.SUCCEEDED
    finally:
        second.shutdown()


def test_object_job_state_upload_does_not_block_queue_updates(tmp_path: Path) -> None:
    class BlockingStorage(LocalStorageProvider):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            self.started = threading.Event()
            self.release = threading.Event()

        def put_file(self, key: str, source: Path, *, content_type: str = ""):
            self.started.set()
            assert self.release.wait(timeout=2)
            return super().put_file(key, source, content_type=content_type)

    provider = BlockingStorage(tmp_path / "objects")
    store = ObjectJobStateStore(provider, tmp_path / "state" / "history.json")

    started = time.monotonic()
    store.save([{"id": "queued-job"}])
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert provider.started.wait(timeout=1)
    provider.release.set()
    assert store.flush(timeout=2)


def test_s3_provider_uses_private_uploads_and_signed_downloads(tmp_path: Path) -> None:
    client = FakeS3Client()
    provider = S3StorageProvider("private-bucket", client, prefix="tenant-media")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")

    stored = provider.put_file("artifacts/job/clip.mp4", source, content_type="video/mp4")
    assert stored.key == "artifacts/job/clip.mp4"
    assert client.upload == (
        str(source),
        "private-bucket",
        "tenant-media/artifacts/job/clip.mp4",
        {"ContentType": "video/mp4"},
    )
    url = provider.signed_url(stored.key, download_name="clip.mp4")
    assert url == "https://objects.example.test/private-signed-url"
    assert client.presign
    assert client.presign[1]["ResponseContentDisposition"] == 'attachment; filename="clip.mp4"'


def test_upload_type_is_rejected_before_media_processing(container) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/sources/upload",
            files={"video": ("notes.txt", b"not a video", "text/plain")},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_VIDEO_TYPE"


def test_upload_size_is_rejected_before_media_processing(container) -> None:
    container.settings.server.max_upload_mb = 0
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/sources/upload",
            files={"video": ("large.mp4", b"x", "video/mp4")},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
