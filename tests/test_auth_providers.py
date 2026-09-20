"""Authentication provider selection and OAuth boundary tests."""

from __future__ import annotations

import ssl
from urllib.parse import parse_qs, urlparse

import pytest

from dripcut.api.contracts import OAuthTokenRequest
from dripcut.auth.models import AuthUser
from dripcut.auth.provider import build_auth_provider
from dripcut.auth.supabase import SupabaseAuthProvider
from dripcut.tenancy.models import Principal
from dripcut.tenancy.supabase import SupabaseTenantRepository


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @staticmethod
    def read() -> bytes:
        return b"{}"


@pytest.mark.parametrize(
    ("target", "call_adapter"),
    [
        (
            "dripcut.auth.supabase.urlopen",
            lambda: SupabaseAuthProvider("https://example.supabase.co", "anon-key")._request(
                "GET", "/auth/v1/user", access_token="access-token"
            ),
        ),
        (
            "dripcut.tenancy.supabase.urlopen",
            lambda: SupabaseTenantRepository(
                "https://example.supabase.co", "anon-key"
            )._request("GET", "/rest/v1/projects", access_token="access-token"),
        ),
    ],
)
def test_supabase_adapters_use_verified_ssl_context(
    target: str,
    call_adapter,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(_request, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(target, fake_urlopen)

    call_adapter()

    assert isinstance(captured["context"], ssl.SSLContext)


def test_supabase_google_authorize_url_contains_provider_and_redirect() -> None:
    provider = SupabaseAuthProvider("https://example.supabase.co", "anon-key")

    url = provider.google_authorize_url(
        redirect_to="https://app.example.com/auth/callback"
    )

    assert url is not None
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "example.supabase.co"
    assert parsed.path == "/auth/v1/authorize"
    assert parse_qs(parsed.query) == {
        "provider": ["google"],
        "redirect_to": ["https://app.example.com/auth/callback"],
    }


def test_oauth_exchange_accepts_supabase_short_refresh_tokens() -> None:
    payload = OAuthTokenRequest(
        access_token="header.payload.signature",
        refresh_token="shorttoken",
    )

    assert payload.refresh_token == "shorttoken"


def test_production_rejects_local_auth_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_ENV", "production")
    monkeypatch.setenv("DRIPCUT_AUTH_PROVIDER", "local")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Production requires"):
        build_auth_provider(tmp_path)


def test_supabase_is_selected_when_credentials_are_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_ENV", "development")
    monkeypatch.delenv("DRIPCUT_AUTH_PROVIDER", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")

    provider = build_auth_provider(tmp_path)

    assert isinstance(provider, SupabaseAuthProvider)


def test_signup_uses_configured_frontend_callback(monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_FRONTEND_URL", "https://dripcut.onrender.com/")
    provider = SupabaseAuthProvider("https://example.supabase.co", "anon-key")
    captured = {}

    def request(method, path, payload):
        captured.update(method=method, path=path)
        return {"id": "test-user", "email": payload["email"]}

    monkeypatch.setattr(provider, "_request", request)
    result = provider.signup(name="Test", email="test@example.test", password="test-password")
    assert result.requires_email_confirmation
    assert parse_qs(urlparse(captured["path"]).query) == {
        "redirect_to": ["https://dripcut.onrender.com/auth/callback"]
    }


def test_supabase_resource_access_reuses_short_lived_positive_check(monkeypatch) -> None:
    repository = SupabaseTenantRepository("https://example.supabase.co", "anon-key")
    principal = Principal(
        user=AuthUser(id="user-1", email="user@example.test", name="User"),
        workspace_id="workspace-1",
        role="owner",
        access_token="access-token",
    )
    calls = 0

    def request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [{"id": "source-1"}]

    monkeypatch.setattr(repository, "_request", request)

    assert repository.can_access(principal, "source", "source-1")
    assert repository.can_access(principal, "source", "source-1")
    assert calls == 1
