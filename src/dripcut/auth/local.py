"""Small, secure-enough local auth provider for development and isolated tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from dripcut.auth.models import AuthProviderError, AuthResult, AuthTokens, AuthUser
from dripcut.utils.fs import ensure_dir


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class LocalAuthProvider:
    """Persist local users and issue signed tokens without pretending to be production auth."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self.users_file = self.root / "users.json"
        self.secret_file = self.root / "session.key"
        self._lock = threading.RLock()
        if not self.secret_file.exists():
            self.secret_file.write_text(secrets.token_hex(32), encoding="ascii")
            self.secret_file.chmod(0o600)
        self._secret = self.secret_file.read_text(encoding="ascii").strip().encode("ascii")

    def signup(self, *, name: str, email: str, password: str) -> AuthResult:
        normalized = self._normalize_email(email)
        self._validate_password(password)
        clean_name = name.strip()
        if not clean_name:
            raise AuthProviderError("Enter your name.", code="NAME_REQUIRED")
        with self._lock:
            users = self._read_users()
            if normalized in users:
                raise AuthProviderError(
                    "An account already exists for this email.",
                    status_code=409,
                    code="EMAIL_ALREADY_REGISTERED",
                )
            salt = secrets.token_bytes(16)
            user_id = str(uuid4())
            users[normalized] = {
                "id": user_id,
                "email": normalized,
                "name": clean_name,
                "password_salt": _b64encode(salt),
                "password_hash": _b64encode(self._password_hash(password, salt)),
            }
            self._write_users(users)
        user = AuthUser(id=user_id, email=normalized, name=clean_name)
        return AuthResult(user=user, tokens=self._tokens(user))

    def login(self, *, email: str, password: str) -> AuthResult:
        normalized = self._normalize_email(email)
        record = self._read_users().get(normalized)
        if not record:
            raise self._invalid_credentials()
        salt = _b64decode(str(record["password_salt"]))
        expected = _b64decode(str(record["password_hash"]))
        if not hmac.compare_digest(self._password_hash(password, salt), expected):
            raise self._invalid_credentials()
        user = self._user(record)
        return AuthResult(user=user, tokens=self._tokens(user))

    def get_user(self, access_token: str) -> AuthUser:
        payload = self._verify_token(access_token, expected_type="access")
        record = next(
            (item for item in self._read_users().values() if item.get("id") == payload.get("sub")),
            None,
        )
        if not record:
            raise AuthProviderError("Your session is no longer valid.", status_code=401, code="SESSION_INVALID")
        return self._user(record)

    def refresh(self, refresh_token: str) -> AuthResult:
        payload = self._verify_token(refresh_token, expected_type="refresh")
        record = next(
            (item for item in self._read_users().values() if item.get("id") == payload.get("sub")),
            None,
        )
        if not record:
            raise AuthProviderError("Your session is no longer valid.", status_code=401, code="SESSION_INVALID")
        user = self._user(record)
        return AuthResult(user=user, tokens=self._tokens(user))

    def logout(self, access_token: str) -> None:
        self._verify_token(access_token, expected_type="access")

    def request_password_reset(self, *, email: str, redirect_to: str) -> None:
        # Local development has no mail transport. The response remains deliberately generic.
        del redirect_to
        self._normalize_email(email)

    def reset_password(self, *, access_token: str, password: str) -> AuthUser:
        self._validate_password(password)
        user = self.get_user(access_token)
        with self._lock:
            users = self._read_users()
            record = users[user.email]
            salt = secrets.token_bytes(16)
            record["password_salt"] = _b64encode(salt)
            record["password_hash"] = _b64encode(self._password_hash(password, salt))
            self._write_users(users)
        return user

    def google_authorize_url(self, *, redirect_to: str) -> str | None:
        del redirect_to
        return None

    def accept_external_tokens(self, *, access_token: str, refresh_token: str) -> AuthResult:
        user = self.get_user(access_token)
        return AuthResult(user=user, tokens=AuthTokens(access_token, refresh_token))

    def _tokens(self, user: AuthUser) -> AuthTokens:
        return AuthTokens(
            access_token=self._sign_token(user.id, "access", 3600),
            refresh_token=self._sign_token(user.id, "refresh", 30 * 86400),
            expires_in=3600,
        )

    def _sign_token(self, user_id: str, token_type: str, lifetime: int) -> str:
        payload = _b64encode(
            json.dumps(
                {"sub": user_id, "type": token_type, "exp": int(time.time()) + lifetime},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signature = _b64encode(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def _verify_token(self, token: str, *, expected_type: str) -> dict[str, Any]:
        try:
            payload, signature = token.split(".", 1)
            expected = _b64encode(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            data = json.loads(_b64decode(payload))
            if data.get("type") != expected_type or int(data.get("exp", 0)) <= int(time.time()):
                raise ValueError
            return data
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise AuthProviderError(
                "Your session has expired. Please log in again.",
                status_code=401,
                code="SESSION_EXPIRED",
            ) from error

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise AuthProviderError("Password must be at least 8 characters.", code="PASSWORD_TOO_SHORT")

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise AuthProviderError("Enter a valid email address.", code="EMAIL_INVALID")
        return normalized

    @staticmethod
    def _invalid_credentials() -> AuthProviderError:
        return AuthProviderError(
            "The email or password is incorrect.", status_code=401, code="INVALID_CREDENTIALS"
        )

    @staticmethod
    def _user(record: dict[str, Any]) -> AuthUser:
        return AuthUser(id=str(record["id"]), email=str(record["email"]), name=str(record["name"]))

    def _read_users(self) -> dict[str, dict[str, Any]]:
        if not self.users_file.exists():
            return {}
        try:
            data = json.loads(self.users_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_users(self, users: dict[str, dict[str, Any]]) -> None:
        temporary = self.users_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(users, indent=2), encoding="utf-8")
        temporary.replace(self.users_file)
