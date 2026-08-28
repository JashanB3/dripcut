"""Object storage records and validation errors."""

from __future__ import annotations

from dataclasses import dataclass

from dripcut.core.errors import DripCutError


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class UploadRejected(DripCutError):
    """An upload failed a size, type, container, probe, or duration policy."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID_VIDEO",
        status_code: int = 400,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.code = code
        self.status_code = status_code
