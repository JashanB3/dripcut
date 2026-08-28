"""Supabase Auth adapter implemented against the documented GoTrue HTTP API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dripcut.auth.models import AuthProviderError, AuthResult, AuthTokens, AuthUser
from dripcut.supabase_http import supabase_ssl_context


class SupabaseAuthProvider:
    name = "supabase"

    def __init__(self, url: str, anon_key: str) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    @classmethod
    def from_environment(cls) -> SupabaseAuthProvider:
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required.")
        return cls(url, key)

    def signup(self, *, name: str, email: str, password: str) -> AuthResult:
        data = self._request(
            "POST",
            "/auth/v1/signup",
            {"email": email.strip().lower(), "password": password, "data": {"name": name.strip()}},
        )
        return self._result(data)

    def login(self, *, email: str, password: str) -> AuthResult:
        data = self._request(
            "POST",
            "/auth/v1/token?grant_type=password",
            {"email": email.strip().lower(), "password": password},
        )
        return self._result(data)

    def get_user(self, access_token: str) -> AuthUser:
        return self._user(self._request("GET", "/auth/v1/user", access_token=access_token))

    def refresh(self, refresh_token: str) -> AuthResult:
        data = self._request(
            "POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": refresh_token}
        )
        return self._result(data)

    def logout(self, access_token: str) -> None:
        self._request("POST", "/auth/v1/logout", access_token=access_token)

    def request_password_reset(self, *, email: str, redirect_to: str) -> None:
        query = urlencode({"redirect_to": redirect_to})
        self._request("POST", f"/auth/v1/recover?{query}", {"email": email.strip().lower()})

    def reset_password(self, *, access_token: str, password: str) -> AuthUser:
        return self._user(
            self._request("PUT", "/auth/v1/user", {"password": password}, access_token=access_token)
        )

    def google_authorize_url(self, *, redirect_to: str) -> str | None:
        query = urlencode({"provider": "google", "redirect_to": redirect_to})
        return f"{self.url}/auth/v1/authorize?{query}"

    def accept_external_tokens(self, *, access_token: str, refresh_token: str) -> AuthResult:
        user = self.get_user(access_token)
        return AuthResult(user=user, tokens=AuthTokens(access_token, refresh_token))

    def _result(self, data: dict[str, Any]) -> AuthResult:
        user_data = data.get("user") or data
        user = self._user(user_data)
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        tokens = None
        if access_token and refresh_token:
            tokens = AuthTokens(
                access_token=str(access_token),
                refresh_token=str(refresh_token),
                expires_in=int(data.get("expires_in", 3600)),
            )
        return AuthResult(
            user=user,
            tokens=tokens,
            requires_email_confirmation=tokens is None,
        )

    @staticmethod
    def _user(data: dict[str, Any]) -> AuthUser:
        metadata = data.get("user_metadata") or {}
        email = str(data.get("email") or "")
        name = str(metadata.get("name") or metadata.get("full_name") or email.split("@", 1)[0])
        return AuthUser(
            id=str(data["id"]),
            email=email,
            name=name,
            email_confirmed=bool(data.get("email_confirmed_at") or data.get("confirmed_at")),
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"apikey": self.anon_key, "Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(  # noqa: S310 - configured Supabase URL
                request,
                timeout=20,
                context=supabase_ssl_context(),
            ) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            try:
                data = json.loads(error.read())
            except (json.JSONDecodeError, OSError):
                data = {}
            message = str(data.get("msg") or data.get("message") or "Authentication failed.")
            raise AuthProviderError(
                message,
                status_code=401 if error.code in {400, 401} else error.code,
                code=str(data.get("error_code") or data.get("code") or "SUPABASE_AUTH_ERROR"),
            ) from error
        except URLError as error:
            raise AuthProviderError(
                "Authentication service is temporarily unavailable.",
                status_code=503,
                code="AUTH_PROVIDER_UNAVAILABLE",
            ) from error
