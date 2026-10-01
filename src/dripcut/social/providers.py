"""Official YouTube and Instagram OAuth/publishing adapters."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

import httpx

from dripcut.core.errors import SocialProviderError
from dripcut.social.models import (
    OAuthResult,
    PlatformName,
    ProviderCapabilities,
    PublishResult,
    SocialCredentials,
)


class SocialProvider(Protocol):
    platform: PlatformName
    label: str

    @property
    def configured(self) -> bool: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthResult: ...

    def publish(
        self,
        credentials: SocialCredentials,
        *,
        video_path: Path,
        media_url: str | None,
        title: str,
        caption: str,
        publish_at: str | None = None,
        privacy: str = "private",
    ) -> PublishResult: ...

    def revoke(self, credentials: SocialCredentials) -> None: ...


def _provider_error(provider: str, response: httpx.Response) -> SocialProviderError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    detail = ""
    if isinstance(payload, dict):
        nested = payload.get("error")
        if isinstance(nested, dict):
            detail = str(nested.get("message") or nested.get("error_description") or "")
        detail = detail or str(payload.get("error_description") or payload.get("message") or "")
    return SocialProviderError(
        f"{provider} rejected the request.",
        hint=(detail[:240] or "Reconnect the account and try again."),
    )


def _youtube_scopes_from_environment() -> tuple[str, ...]:
    configured = os.environ.get("DRIPCUT_YOUTUBE_SCOPES", "").strip()
    if not configured:
        return YouTubeProvider.default_scopes
    scopes = tuple(scope.strip() for scope in configured.replace(",", " ").split() if scope.strip())
    return scopes or YouTubeProvider.default_scopes


class YouTubeProvider:
    """Google OAuth and YouTube Data API resumable uploads."""

    platform: PlatformName = "youtube"
    label = "YouTube Shorts"
    auth_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    api_root = "https://www.googleapis.com/youtube/v3"
    upload_endpoint = "https://www.googleapis.com/upload/youtube/v3/videos"
    default_scopes = (
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    )

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        *,
        scopes: tuple[str, ...] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.scopes = scopes or self.default_scopes
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)

    @classmethod
    def from_environment(cls) -> YouTubeProvider:
        return cls(
            os.environ.get("DRIPCUT_YOUTUBE_CLIENT_ID", ""),
            os.environ.get("DRIPCUT_YOUTUBE_CLIENT_SECRET", ""),
            scopes=_youtube_scopes_from_environment(),
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            platform=self.platform,
            can_upload_video=True,
            can_publish_short=True,
            can_schedule=True,
            can_publish_thumbnail=False,
            can_edit_metadata=False,
            can_fetch_analytics=False,
            supported_aspect_ratios=("9:16", "1:1", "16:9"),
            max_video_duration_seconds=_optional_positive_int(
                "DRIPCUT_YOUTUBE_MAX_VIDEO_DURATION_SECONDS"
            ),
            supported_content_types=("video_clip",),
        )

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_configured()
        return f"{self.auth_endpoint}?{urlencode({'client_id': self.client_id, 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': ' '.join(self.scopes), 'access_type': 'offline', 'include_granted_scopes': 'true', 'prompt': 'consent', 'state': state})}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthResult:
        self._require_configured()
        response = self.client.post(
            self.token_endpoint,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if response.is_error:
            raise _provider_error("Google", response)
        payload = response.json()
        refresh_token = str(payload.get("refresh_token") or "") or None
        if not refresh_token:
            raise SocialProviderError(
                "Google did not provide durable YouTube access.",
                hint="Remove DripCut from Google account permissions, then connect YouTube again.",
            )
        credentials = SocialCredentials(
            access_token=str(payload["access_token"]),
            refresh_token=refresh_token,
            expires_at=time.time() + float(payload.get("expires_in") or 3600),
            token_type=str(payload.get("token_type") or "Bearer"),
            scopes=tuple(str(payload.get("scope") or "").split()),
        )
        channel = self.client.get(
            f"{self.api_root}/channels",
            params={"part": "snippet", "mine": "true"},
            headers=self._authorization(credentials.access_token),
        )
        if channel.is_error:
            raise _provider_error("YouTube", channel)
        items = channel.json().get("items", [])
        if not items:
            raise SocialProviderError(
                "No YouTube channel was found for this Google account.",
                hint="Create or select a YouTube channel, then connect again.",
            )
        selected = items[0]
        snippet = selected.get("snippet", {})
        thumbnails = snippet.get("thumbnails", {}) if isinstance(snippet, dict) else {}
        avatar = ""
        if isinstance(thumbnails, dict):
            for size in ("high", "medium", "default"):
                candidate = thumbnails.get(size, {})
                if isinstance(candidate, dict) and candidate.get("url"):
                    avatar = str(candidate["url"])
                    break
        credentials = SocialCredentials(
            **{
                **credentials.to_dict(),
                "extra": {
                    "channel_id": str(selected["id"]),
                    "avatar_url": avatar,
                },
            }
        )
        return OAuthResult(
            external_account_id=str(selected["id"]),
            display_name=str(selected.get("snippet", {}).get("title") or "YouTube channel"),
            credentials=credentials,
        )

    def publish(
        self,
        credentials: SocialCredentials,
        *,
        video_path: Path,
        media_url: str | None,
        title: str,
        caption: str,
        publish_at: str | None = None,
        privacy: str = "private",
    ) -> PublishResult:
        del media_url
        current = self._refresh(credentials)
        selected_privacy = privacy if privacy in {"private", "unlisted", "public"} else "private"
        status_metadata: dict[str, object] = {
            "privacyStatus": "private" if publish_at else selected_privacy,
            "selfDeclaredMadeForKids": False,
        }
        if publish_at:
            status_metadata["publishAt"] = publish_at
        metadata = {
            "snippet": {
                "title": (title.strip() or video_path.stem)[:100],
                "description": caption[:5000],
                "categoryId": os.environ.get("DRIPCUT_YOUTUBE_CATEGORY_ID", "22"),
            },
            "status": status_metadata,
        }
        init = self.client.post(
            self.upload_endpoint,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                **self._authorization(current.access_token),
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(video_path.stat().st_size),
            },
            json=metadata,
        )
        if init.is_error or not init.headers.get("location"):
            raise _provider_error("YouTube", init)
        with video_path.open("rb") as media:
            upload = self.client.put(
                init.headers["location"],
                content=media,
                headers={
                    "Content-Type": "video/*",
                    "Content-Length": str(video_path.stat().st_size),
                },
                timeout=900,
            )
        if upload.is_error:
            raise _provider_error("YouTube", upload)
        video_id = str(upload.json().get("id") or "")
        if not video_id:
            raise SocialProviderError("YouTube did not return an uploaded video id.")
        return PublishResult(
            external_post_id=video_id,
            url=f"https://www.youtube.com/shorts/{video_id}",
            credentials=current,
            status=(
                "scheduled_on_youtube"
                if publish_at
                else "published" if selected_privacy == "public" else "uploaded"
            ),
        )

    def revoke(self, credentials: SocialCredentials) -> None:
        token = credentials.refresh_token or credentials.access_token
        if not token:
            return
        response = self.client.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.is_error and response.status_code not in {400, 401}:
            raise _provider_error("Google", response)

    def _refresh(self, credentials: SocialCredentials) -> SocialCredentials:
        if credentials.expires_at is None or credentials.expires_at > time.time() + 90:
            return credentials
        if not credentials.refresh_token:
            raise SocialProviderError(
                "The YouTube connection expired.", hint="Reconnect YouTube to continue scheduling."
            )
        response = self.client.post(
            self.token_endpoint,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": credentials.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.is_error:
            raise _provider_error("Google", response)
        payload = response.json()
        return SocialCredentials(
            access_token=str(payload["access_token"]),
            refresh_token=credentials.refresh_token,
            expires_at=time.time() + float(payload.get("expires_in") or 3600),
            token_type=str(payload.get("token_type") or credentials.token_type),
            scopes=credentials.scopes,
            extra=credentials.extra,
        )

    def _require_configured(self) -> None:
        if not self.configured:
            raise SocialProviderError(
                "YouTube OAuth is not configured.",
                hint="Set DRIPCUT_YOUTUBE_CLIENT_ID and DRIPCUT_YOUTUBE_CLIENT_SECRET.",
            )

    @staticmethod
    def _authorization(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


class InstagramProvider:
    """Instagram Login and Instagram Graph API Reels publishing."""

    platform: PlatformName = "instagram"
    label = "Instagram Reels"
    scopes = ("instagram_business_basic", "instagram_business_content_publish")

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        *,
        graph_version: str = "v23.0",
        client: httpx.Client | None = None,
    ) -> None:
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.graph_version = graph_version.strip().lstrip("/") or "v23.0"
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)

    @classmethod
    def from_environment(cls) -> InstagramProvider:
        return cls(
            os.environ.get("DRIPCUT_INSTAGRAM_APP_ID", ""),
            os.environ.get("DRIPCUT_INSTAGRAM_APP_SECRET", ""),
            graph_version=os.environ.get("DRIPCUT_META_GRAPH_VERSION", "v23.0"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            platform=self.platform,
            can_upload_video=True,
            can_publish_short=True,
            can_schedule=True,
            can_publish_thumbnail=False,
            can_edit_metadata=False,
            can_fetch_analytics=False,
            supported_aspect_ratios=("9:16", "1:1"),
            max_video_duration_seconds=_optional_positive_int(
                "DRIPCUT_INSTAGRAM_MAX_VIDEO_DURATION_SECONDS"
            ),
            supported_content_types=("video_clip",),
        )

    @property
    def graph_root(self) -> str:
        return f"https://graph.instagram.com/{self.graph_version}"

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_configured()
        query = urlencode(
            {
                "client_id": self.app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "scope": ",".join(self.scopes),
                "enable_fb_login": "false",
            }
        )
        return f"https://www.instagram.com/oauth/authorize?{query}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthResult:
        self._require_configured()
        response = self.client.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if response.is_error:
            error = _provider_error("Instagram", response)
            raise SocialProviderError(
                "Instagram could not exchange the sign-in code.",
                hint=error.hint,
                code="INSTAGRAM_TOKEN_EXCHANGE_FAILED",
            )
        payload = response.json()
        if "data" in payload:
            rows = payload["data"]
            if not isinstance(rows, list) or len(rows) != 1 or "access_token" in payload:
                raise SocialProviderError("Instagram returned an ambiguous account. Connect again.")
            payload = rows[0]
        short_token = str(payload.get("access_token") or "")
        user_id = str(payload.get("user_id") or "")
        if not short_token or not user_id:
            raise SocialProviderError("Instagram did not return an account token. Connect again.")
        granted = payload.get("permissions")
        if granted is not None:
            permissions = set(granted.replace(",", " ").split()) if isinstance(granted, str) else set(granted)
            if not set(self.scopes).issubset(permissions):
                raise SocialProviderError("Allow profile and publishing access to schedule Instagram Reels.")
        long_lived = self.client.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self.app_secret,
                "access_token": short_token,
            },
        )
        if long_lived.is_error:
            error = _provider_error("Instagram", long_lived)
            raise SocialProviderError(
                "Instagram rejected the long-lived token exchange.",
                hint=error.hint,
                code="INSTAGRAM_LONG_LIVED_TOKEN_FAILED",
            )
        token_payload = long_lived.json()
        token = str(token_payload["access_token"])
        profile = self.client.get(
            f"{self.graph_root}/me",
            params={"fields": "user_id,username", "access_token": token},
        )
        if profile.is_error:
            error = _provider_error("Instagram", profile)
            raise SocialProviderError(
                "Instagram could not load the connected professional account.",
                hint=error.hint,
                code="INSTAGRAM_PROFILE_LOOKUP_FAILED",
            )
        instagram = profile.json()
        if str(instagram.get("user_id") or "") != user_id:
            raise SocialProviderError("Instagram could not verify the connected account. Connect again.")
        credentials = SocialCredentials(
            access_token=token,
            expires_at=time.time() + float(token_payload["expires_in"]),
            scopes=self.scopes,
            extra={"instagram_user_id": user_id, "login_method": "instagram"},
        )
        return OAuthResult(
            external_account_id=user_id,
            display_name=str(instagram.get("username") or "Instagram"),
            credentials=credentials,
        )

    def _refresh(self, credentials: SocialCredentials) -> SocialCredentials:
        # Existing Facebook Page tokens retain their original API and lifecycle.
        if credentials.extra.get("login_method") != "instagram":
            return credentials
        expiry = credentials.expires_at
        if expiry is None or expiry <= time.time():
            raise SocialProviderError("The Instagram connection expired. Reconnect Instagram.")
        if expiry > time.time() + 7 * 86400:
            return credentials
        response = self.client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": credentials.access_token},
        )
        if response.is_error:
            raise _provider_error("Instagram", response)
        payload = response.json()
        return SocialCredentials(
            access_token=str(payload["access_token"]),
            expires_at=time.time() + float(payload["expires_in"]),
            scopes=credentials.scopes,
            extra=credentials.extra,
        )

    def publish(
        self,
        credentials: SocialCredentials,
        *,
        video_path: Path,
        media_url: str | None,
        title: str,
        caption: str,
        publish_at: str | None = None,
        privacy: str = "private",
    ) -> PublishResult:
        del video_path, title, publish_at, privacy
        if not media_url or not media_url.startswith("https://"):
            raise SocialProviderError(
                "Instagram needs a temporary HTTPS media URL.",
                hint="Use S3 or R2 object storage when automatic Instagram publishing is enabled.",
            )
        credentials = self._refresh(credentials)
        graph_root = (
            f"https://graph.facebook.com/{self.graph_version}"
            if credentials.extra.get("page_id") and credentials.extra.get("login_method") != "instagram"
            else self.graph_root
        )
        instagram_id = credentials.extra.get("instagram_user_id")
        if not instagram_id:
            raise SocialProviderError("The Instagram account id is missing. Reconnect Instagram.")
        create = self.client.post(
            f"{graph_root}/{instagram_id}/media",
            data={
                "media_type": "REELS",
                "video_url": media_url,
                "caption": caption[:2200],
                "share_to_feed": "true",
                "access_token": credentials.access_token,
            },
        )
        if create.is_error:
            raise _provider_error("Instagram", create)
        creation_id = str(create.json().get("id") or "")
        if not creation_id:
            raise SocialProviderError("Instagram did not return a media container id.")
        self._wait_for_container(creation_id, credentials.access_token, graph_root=graph_root)
        publish = self.client.post(
            f"{graph_root}/{instagram_id}/media_publish",
            data={"creation_id": creation_id, "access_token": credentials.access_token},
        )
        if publish.is_error:
            raise _provider_error("Instagram", publish)
        media_id = str(publish.json().get("id") or "")
        if not media_id:
            raise SocialProviderError("Instagram did not return a published media id.")
        # Publishing has succeeded; an optional permalink lookup must not turn
        # this into a failed job that the user could publish again.
        url = None
        try:
            permalink = self.client.get(
                f"{graph_root}/{media_id}",
                params={"fields": "permalink", "access_token": credentials.access_token},
            )
            if not permalink.is_error:
                url = str(permalink.json().get("permalink") or "") or None
        except (httpx.HTTPError, ValueError):
            pass
        return PublishResult(external_post_id=media_id, url=url, status="published", credentials=credentials)

    def revoke(self, credentials: SocialCredentials) -> None:
        del credentials

    def _wait_for_container(self, creation_id: str, token: str, *, graph_root: str | None = None) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            response = self.client.get(
                f"{graph_root or self.graph_root}/{creation_id}",
                params={"fields": "status_code,status", "access_token": token},
            )
            if response.is_error:
                raise _provider_error("Instagram", response)
            status = str(response.json().get("status_code") or "").upper()
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise SocialProviderError(
                    "Instagram could not process this Reel.",
                    hint=str(response.json().get("status") or "Try another clip."),
                )
            time.sleep(3)
        raise SocialProviderError("Instagram timed out while processing this Reel.")

    def _require_configured(self) -> None:
        if not self.configured:
            raise SocialProviderError(
                "Instagram OAuth is not configured.",
                hint="Set DRIPCUT_INSTAGRAM_APP_ID and DRIPCUT_INSTAGRAM_APP_SECRET from Instagram API setup with Instagram Login.",
            )


def _optional_positive_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None
