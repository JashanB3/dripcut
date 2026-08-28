"""Authenticated encryption for server-side OAuth credentials."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from dripcut.core.errors import SocialProviderError


class CredentialCipher:
    """Encrypt OAuth token payloads with an environment or local server key."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_environment(cls, key_file: Path) -> CredentialCipher:
        configured = os.environ.get("DRIPCUT_CREDENTIAL_ENCRYPTION_KEY", "").strip()
        if configured:
            return cls(configured.encode("ascii"))
        if os.environ.get("DRIPCUT_ENV", "").strip().lower() in {"production", "prod"}:
            raise RuntimeError(
                "DRIPCUT_CREDENTIAL_ENCRYPTION_KEY is required in production."
            )
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if not key_file.exists():
            key_file.write_bytes(Fernet.generate_key())
            key_file.chmod(0o600)
        return cls(key_file.read_bytes().strip())

    def encrypt(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw).decode("ascii")

    def decrypt(self, token: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._fernet.decrypt(token.encode("ascii")))
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
            raise SocialProviderError(
                "The saved social connection could not be unlocked.",
                hint="Reconnect the account from the Publishing page.",
            ) from error
        if not isinstance(payload, dict):
            raise SocialProviderError("The saved social credentials are invalid.")
        return payload
