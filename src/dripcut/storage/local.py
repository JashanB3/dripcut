"""Private local object storage used by development and tests."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from dripcut.storage.models import StoredObject, UploadRejected
from dripcut.utils.fs import ensure_dir


class LocalStorageProvider:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)

    def put_file(self, key: str, source: Path, *, content_type: str) -> StoredObject:
        target = self._path(key)
        ensure_dir(target.parent)
        if source.resolve() != target.resolve():
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(source, temporary)
            temporary.replace(target)
        return StoredObject(key=key, size_bytes=target.stat().st_size, content_type=content_type)

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        content_type: str,
        max_bytes: int | None = None,
    ) -> StoredObject:
        target = self._path(key)
        ensure_dir(target.parent)
        temporary = target.with_suffix(target.suffix + ".tmp")
        written = 0
        try:
            with temporary.open("wb") as handle:
                while chunk := stream.read(1024 * 1024):
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        raise UploadRejected(
                            "This video is larger than the upload limit.",
                            code="UPLOAD_TOO_LARGE",
                            status_code=413,
                            hint="Choose a smaller video or shorten it before uploading.",
                        )
                    handle.write(chunk)
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return StoredObject(key=key, size_bytes=written, content_type=content_type)

    def materialize(self, key: str, destination: Path) -> Path:
        source = self._path(key)
        if not source.is_file():
            raise FileNotFoundError(key)
        ensure_dir(destination.parent)
        if source.resolve() != destination.resolve():
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        return destination

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def signed_url(
        self,
        key: str,
        *,
        expires_seconds: int = 900,
        download_name: str | None = None,
    ) -> str | None:
        del key, expires_seconds, download_name
        return None

    def _path(self, key: str) -> Path:
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Storage keys must be relative and cannot traverse directories.")
        return self.root.joinpath(*path.parts)
