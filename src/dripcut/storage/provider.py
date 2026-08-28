"""Storage provider contract and environment-driven provider selection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Protocol

from dripcut.storage.models import StoredObject


class StorageProvider(Protocol):
    name: str

    def put_file(self, key: str, source: Path, *, content_type: str) -> StoredObject: ...

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        content_type: str,
        max_bytes: int | None = None,
    ) -> StoredObject: ...

    def materialize(self, key: str, destination: Path) -> Path: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def signed_url(
        self,
        key: str,
        *,
        expires_seconds: int = 900,
        download_name: str | None = None,
    ) -> str | None: ...


def build_storage_provider(root: Path) -> StorageProvider:
    provider = os.environ.get("DRIPCUT_STORAGE_PROVIDER", "local").strip().lower()
    if provider == "local":
        from dripcut.storage.local import LocalStorageProvider

        return LocalStorageProvider(root)
    if provider in {"s3", "r2"}:
        from dripcut.storage.s3 import S3StorageProvider

        return S3StorageProvider.from_environment()
    raise RuntimeError(f"Unsupported DRIPCUT_STORAGE_PROVIDER: {provider}")
