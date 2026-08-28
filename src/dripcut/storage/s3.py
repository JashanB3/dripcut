"""AWS S3 and Cloudflare R2 compatible private object storage."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from dripcut.storage.models import StoredObject, UploadRejected
from dripcut.utils.fs import ensure_dir


class S3StorageProvider:
    name = "s3"

    def __init__(self, bucket: str, client: Any, *, prefix: str = "") -> None:
        if not bucket:
            raise RuntimeError("DRIPCUT_STORAGE_BUCKET is required for S3 storage.")
        self.bucket = bucket
        self.client = client
        self.prefix = prefix.strip("/")

    @classmethod
    def from_environment(cls) -> S3StorageProvider:
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("Install boto3 to use DRIPCUT_STORAGE_PROVIDER=s3.") from error
        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("DRIPCUT_STORAGE_ENDPOINT_URL") or None,
            region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "auto",
        )
        return cls(
            os.environ.get("DRIPCUT_STORAGE_BUCKET", "").strip(),
            client,
            prefix=os.environ.get("DRIPCUT_STORAGE_PREFIX", "").strip(),
        )

    def put_file(self, key: str, source: Path, *, content_type: str) -> StoredObject:
        value = self._key(key)
        self.client.upload_file(
            str(source),
            self.bucket,
            value,
            ExtraArgs={"ContentType": content_type},
        )
        return StoredObject(key=key, size_bytes=source.stat().st_size, content_type=content_type)

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        content_type: str,
        max_bytes: int | None = None,
    ) -> StoredObject:
        value = self._key(key)
        data = stream.read(None if max_bytes is None else max_bytes + 1)
        if max_bytes is not None and len(data) > max_bytes:
            raise UploadRejected(
                "This video is larger than the upload limit.",
                code="UPLOAD_TOO_LARGE",
                status_code=413,
            )
        self.client.put_object(
            Bucket=self.bucket,
            Key=value,
            Body=data,
            ContentType=content_type,
        )
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def materialize(self, key: str, destination: Path) -> Path:
        ensure_dir(destination.parent)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            self.client.download_file(self.bucket, self._key(key), str(temporary))
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:
            return False

    def signed_url(
        self,
        key: str,
        *,
        expires_seconds: int = 900,
        download_name: str | None = None,
    ) -> str | None:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": self._key(key)}
        if download_name:
            safe_name = download_name.replace('"', "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe_name}"'
        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=max(60, min(expires_seconds, 3600)),
            )
        )

    def _key(self, key: str) -> str:
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Storage keys must be relative and cannot traverse directories.")
        value = str(path)
        return f"{self.prefix}/{value}" if self.prefix else value
