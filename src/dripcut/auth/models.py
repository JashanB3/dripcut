"""Provider-neutral authentication values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: str
    email: str
    name: str
    email_confirmed: bool = True


@dataclass(frozen=True, slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int = 3600


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: AuthUser
    tokens: AuthTokens | None
    requires_email_confirmation: bool = False


class AuthProviderError(Exception):
    """A normalized authentication failure safe to surface to the API layer."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "AUTH_ERROR",
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.retryable = (
            status_code == 429 or status_code >= 500
            if retryable is None
            else retryable
        )
