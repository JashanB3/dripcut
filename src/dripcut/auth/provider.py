"""Authentication provider contract and environment-safe provider selection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from dripcut.auth.models import AuthResult, AuthUser


class AuthProvider(Protocol):
    name: str

    def signup(self, *, name: str, email: str, password: str) -> AuthResult: ...

    def login(self, *, email: str, password: str) -> AuthResult: ...

    def get_user(self, access_token: str) -> AuthUser: ...

    def refresh(self, refresh_token: str) -> AuthResult: ...

    def logout(self, access_token: str) -> None: ...

    def request_password_reset(self, *, email: str, redirect_to: str) -> None: ...

    def reset_password(self, *, access_token: str, password: str) -> AuthUser: ...

    def google_authorize_url(self, *, redirect_to: str) -> str | None: ...

    def accept_external_tokens(self, *, access_token: str, refresh_token: str) -> AuthResult: ...


def _is_production() -> bool:
    environment = os.environ.get("DRIPCUT_ENV", "development").strip().lower()
    return environment in {"production", "prod"} or bool(
        os.environ.get("RENDER") or os.environ.get("AWS_EXECUTION_ENV")
    )


def build_auth_provider(root: Path) -> AuthProvider:
    """Select Supabase in production and an isolated local provider in development."""
    configured = os.environ.get("DRIPCUT_AUTH_PROVIDER", "").strip().lower()
    has_supabase = bool(
        os.environ.get("SUPABASE_URL", "").strip()
        and os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
    provider = configured or ("supabase" if has_supabase else "local")
    if provider == "supabase":
        from dripcut.auth.supabase import SupabaseAuthProvider

        return SupabaseAuthProvider.from_environment()
    if provider != "local":
        raise RuntimeError(f"Unsupported DRIPCUT_AUTH_PROVIDER: {provider}")
    if _is_production():
        raise RuntimeError(
            "Production requires DRIPCUT_AUTH_PROVIDER=supabase, SUPABASE_URL, and "
            "SUPABASE_ANON_KEY. The local auth provider is development-only."
        )
    from dripcut.auth.local import LocalAuthProvider

    return LocalAuthProvider(root / "auth")
