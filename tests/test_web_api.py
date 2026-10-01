"""End-to-end HTTP tests for the React clipping pipeline."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dripcut.api.app import build_service, create_app
from dripcut.engines.ai.provider import (
    AIEditPlan as ProviderAIEditPlan,
)
from dripcut.engines.ai.provider import (
    RankedClip,
    RankedClips,
    SocialMetadata,
    ThumbnailBrief,
    ViralMoment,
    ViralMomentAnalysis,
)
from dripcut.models.job import Job, JobKind, JobStatus
from dripcut.models.transcript import Transcript, TranscriptSegment
from dripcut.services.youtube_service import (
    YouTubeImportError,
    YouTubeImportResult,
    YouTubeMetadata,
)


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 20) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.1)
    raise AssertionError("render job did not finish in time")


def test_health_reports_media_dependencies(container) -> None:
    app = create_app(build_service(container), require_auth=False)

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ffmpeg": True, "ffprobe": True}


def test_social_callback_without_session_returns_to_login(container) -> None:
    app = create_app(build_service(container), require_auth=True)

    with TestClient(app) as client:
        response = client.get(
            "/api/social/instagram/callback",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def test_social_oauth_callback_prefers_frontend_origin(monkeypatch) -> None:
    from dripcut.api.app import _social_callback_url

    monkeypatch.setenv("DRIPCUT_FRONTEND_URL", "https://dripcut.onrender.com")
    monkeypatch.setenv("DRIPCUT_PUBLIC_API_URL", "https://dripcut-api.onrender.com")

    assert (
        _social_callback_url("instagram")
        == "https://dripcut.onrender.com/api/social/instagram/callback"
    )


def test_social_oauth_errors_are_reduced_to_safe_actionable_codes() -> None:
    from dripcut.api.app import _social_oauth_error_code

    assert _social_oauth_error_code("instagram", "Only professional accounts are eligible") == "instagram-account"
    assert _social_oauth_error_code("instagram", "Publishing permission was declined") == "instagram-permissions"
    assert _social_oauth_error_code("instagram", "Instagram rejected the long-lived token exchange") == "instagram-configuration"
    assert _social_oauth_error_code("youtube", "No YouTube channel was found") == "youtube-channel"
    assert _social_oauth_error_code("instagram", "provider response was malformed") == "instagram"


def test_project_card_reconciles_an_interrupted_render(container) -> None:
    service = build_service(container)
    project = container.projects.create("Interrupted render")
    project.status = "processing"
    interrupted = Job(kind=JobKind.SPLIT, title="Interrupted")
    interrupted.status = JobStatus.FAILED
    interrupted.metadata["error_code"] = "WORKER_RESTARTED"
    project.latest_job_id = interrupted.id
    container.projects.save(project)
    service.jobs = SimpleNamespace(get=lambda job_id: interrupted if job_id == interrupted.id else None)

    payload = next(item for item in service.list_projects() if item.id == project.id)

    assert payload.status == "failed"


def test_completed_job_is_recovered_from_durable_project_artifacts(container, tmp_path) -> None:
    service = build_service(container)
    job_id = "11111111-1111-4111-8111-111111111111"
    source_id = "22222222-2222-4222-8222-222222222222"
    project = container.projects.create("Recovered render")
    project.status = "completed"
    project.source_asset_id = source_id
    project.latest_job_id = job_id
    clip_path = tmp_path / "clip-01.mp4"
    clip_path.write_bytes(b"durable clip")
    clip = service.artifacts.register_clip(
        job_id,
        clip_path,
        index=1,
        duration=15,
        output_format="portrait",
    )
    project.artifact_ids = [clip.id]
    container.projects.save(project)

    recovered = service.job_response(job_id)

    assert recovered.status == "succeeded"
    assert recovered.project_id == project.id
    assert recovered.source_id == source_id
    assert recovered.percent == 100
    assert [item.id for item in recovered.artifacts] == [clip.id]


def test_hosted_queue_uses_history_separate_from_desktop_queue(container) -> None:
    service = build_service(container)
    web_queue = service.jobs.queue

    assert web_queue.history_file == container.paths.projects / "web" / "jobs.json"
    assert web_queue.history_file != container.paths.history_file
    assert web_queue.state_store.key == "metadata/queue/web-jobs.json"


def test_upload_rejected_when_worker_disk_is_below_floor(container, monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_MIN_FREE_DISK_MB", "1536")
    monkeypatch.setattr(
        "dripcut.api.service.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10_000, used=9_500, free=500 * 1024 * 1024),
    )
    app = create_app(build_service(container), require_auth=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/sources/upload",
            files={"video": ("video.mp4", io.BytesIO(b"not-read"), "video/mp4")},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_CAPACITY_LOW"
    assert response.json()["error"]["retryable"] is True


def test_workspace_admin_can_read_aggregate_operations_metrics(container) -> None:
    app = create_app(build_service(container), require_auth=False)

    with TestClient(app) as client:
        response = client.get("/api/operations/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["completed_jobs"] == 0
    assert payload["failed_jobs"] == 0
    assert payload["encoder"]["codec"] == "h264"
    assert payload["encoder"]["provider"] in {
        "apple_videotoolbox",
        "nvidia_nvenc",
        "software",
    }
    assert payload["stages"] == []


def test_internal_admin_overview_rejects_workspace_owner_and_returns_safe_metrics(
    container, monkeypatch
) -> None:
    monkeypatch.setenv("DRIPCUT_ADMIN_EMAILS", "internal-admin@example.test")
    app = create_app(build_service(container), require_auth=True)

    with TestClient(app) as client:
        ordinary = client.post(
            "/api/auth/signup",
            json={
                "name": "Workspace Owner",
                "email": "owner@example.test",
                "password": "correct-horse",
            },
        )
        assert ordinary.status_code == 201
        assert ordinary.json()["user"]["role"] == "owner"
        assert ordinary.json()["user"]["is_dripcut_admin"] is False
        assert client.get("/api/admin/overview").status_code == 403

        assert client.post("/api/auth/logout").status_code == 204
        admin = client.post(
            "/api/auth/signup",
            json={
                "name": "Internal Admin",
                "email": "internal-admin@example.test",
                "password": "correct-horse",
            },
        )
        assert admin.status_code == 201
        assert admin.json()["user"]["is_dripcut_admin"] is True
        overview = client.get("/api/admin/overview")

    assert overview.status_code == 200, overview.text
    payload = overview.json()
    assert payload["metrics"]["total_users"] == 2
    assert payload["metrics"]["render_jobs"] == 0
    assert {user["email"] for user in payload["users"]} == {
        "owner@example.test",
        "internal-admin@example.test",
    }
    assert payload["errors"] == []


def test_production_allowed_origins_env(container, monkeypatch) -> None:
    monkeypatch.setenv(
        "DRIPCUT_ALLOWED_ORIGINS",
        "https://dripcut.example, https://studio.dripcut.example ",
    )
    app = create_app(build_service(container), require_auth=False)

    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "https://studio.dripcut.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://studio.dripcut.example"
    )


def test_auth_rate_limit_returns_normalized_json(container, monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_RATE_LIMIT_AUTH", "2")
    app = create_app(build_service(container), require_auth=True)

    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/auth/login",
                json={"email": "missing@example.test", "password": "wrong-password"},
            )
            assert response.status_code == 401
        limited = client.post(
            "/api/auth/login",
            json={"email": "missing@example.test", "password": "wrong-password"},
        )

    assert limited.status_code == 429
    assert limited.headers["retry-after"]
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_production_cookie_mutation_requires_allowed_origin(container, monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_CSRF_PROTECTION", "1")
    monkeypatch.setenv("DRIPCUT_ALLOWED_ORIGINS", "https://studio.dripcut.example")
    app = create_app(build_service(container), require_auth=True)

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={
                "name": "CSRF Test",
                "email": "csrf@example.test",
                "password": "correct-horse",
            },
        )
        assert signup.status_code == 201
        rejected = client.post("/api/auth/logout")
        accepted = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://studio.dripcut.example"},
        )

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "CSRF_ORIGIN_REJECTED"
    assert accepted.status_code == 204


def test_upload_plan_render_stream_and_download(container, sample_video: Path) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        with sample_video.open("rb") as source:
            upload = client.post(
                "/api/sources/upload",
                files={"video": ("sample.mp4", source, "video/mp4")},
            )
        assert upload.status_code == 201, upload.text
        asset = upload.json()
        assert asset["duration"] == 6
        assert asset["width"] == 160
        assert asset["height"] == 120
        assert asset["poster_url"]

        plan = client.post(
            f"/api/sources/{asset['id']}/standard-plan",
            json={"duration": 2, "count": "max"},
        )
        assert plan.status_code == 200
        planned = plan.json()
        assert planned["max_count"] == 3
        assert [(item["start"], item["end"]) for item in planned["segments"]] == [
            (0, 2),
            (2, 4),
            (4, 6),
        ]

        create = client.post(
            "/api/jobs/clips",
            json={"source_id": asset["id"], "segments": planned["segments"]},
        )
        assert create.status_code == 202, create.text
        finished = _wait_for_job(client, create.json()["id"])
        assert finished["status"] == "succeeded", finished
        assert finished["percent"] == 100
        clips = [item for item in finished["artifacts"] if item["kind"] == "clip"]
        assert len(clips) == 3
        assert all(item["size_bytes"] > 1000 for item in clips)
        assert all(item["duration"] == 2 for item in clips)

        content_sources = client.get(
            f"/api/projects/{asset['project_id']}/sources/content"
        )
        assert content_sources.status_code == 200
        assert content_sources.json()[0]["id"] == asset["id"]
        assert content_sources.json()[0]["source_type"] == "video_upload"

        content_items = client.get(f"/api/projects/{asset['project_id']}/content")
        assert content_items.status_code == 200
        mapped = content_items.json()
        assert {item["video_artifact_id"] for item in mapped} == {
            clip["id"] for clip in clips
        }
        assert all(item["content_type"] == "video_clip" for item in mapped)

        capabilities = client.get("/api/social/capabilities")
        assert capabilities.status_code == 200
        assert {item["platform"] for item in capabilities.json()} == {
            "youtube",
            "instagram",
        }

        stream = client.get(clips[0]["stream_url"], headers={"Range": "bytes=0-1023"})
        assert stream.status_code == 206
        assert stream.headers["content-range"].startswith("bytes 0-")
        assert stream.content

        clip_download = client.get(clips[0]["download_url"])
        assert clip_download.status_code == 200
        assert "attachment" in clip_download.headers["content-disposition"]
        assert len(clip_download.content) > 1000

        archive = client.get(finished["zip_artifact"]["download_url"])
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as handle:
            names = handle.namelist()
            assert len(names) == 3
            assert all(name.startswith("sample-clips/") for name in names)
            assert all(item.compress_type == zipfile.ZIP_STORED for item in handle.infolist())


def test_universal_content_api_crud_and_mass_assignment_protection(
    container, sample_video: Path
) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as video:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("content-api.mp4", video, "video/mp4")},
        ).json()
        project_id = asset["project_id"]
        source = client.post(
            f"/api/projects/{project_id}/sources/content",
            json={
                "source_type": "script",
                "title": "Launch script",
                "text_content": "A short hook and a clear payoff.",
                "metadata": {"language": "en"},
            },
        )
        assert source.status_code == 201, source.text

        created = client.post(
            f"/api/projects/{project_id}/content",
            json={
                "source_id": source.json()["id"],
                "content_type": "script",
                "title": "Launch short",
                "script": "A short hook and a clear payoff.",
                "hashtags": ["#launch", "creator"],
            },
        )
        assert created.status_code == 201, created.text
        content_id = created.json()["id"]

        updated = client.patch(
            f"/api/content/{content_id}",
            json={"title": "Launch short v2", "status": "ready"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["title"] == "Launch short v2"
        assert updated.json()["status"] == "ready"

        target = client.post(
            f"/api/content/{content_id}/targets",
            json={
                "platform": "linkedin",
                "scheduled_at": "2026-09-02T10:00:00+00:00",
            },
        )
        assert target.status_code == 201, target.text
        target_id = target.json()["id"]
        target = client.patch(
            f"/api/content/{content_id}/targets/{target_id}",
            json={"publish_status": "scheduled"},
        )
        assert target.status_code == 200, target.text
        assert target.json()["publish_status"] == "scheduled"
        assert len(client.get(f"/api/content/{content_id}/targets").json()) == 1

        protected = client.patch(
            f"/api/content/{content_id}",
            json={"workspace_id": "another-workspace"},
        )
        assert protected.status_code == 422
        assert protected.json()["error"]["code"] == "VALIDATION_ERROR"

        assert client.delete(
            f"/api/content/{content_id}/targets/{target_id}"
        ).status_code == 204
        assert client.delete(f"/api/content/{content_id}").status_code == 204
        assert client.get(f"/api/content/{content_id}").status_code == 404


def test_content_api_hides_other_workspaces_resources(container, sample_video: Path) -> None:
    app = create_app(build_service(container), require_auth=True)
    with TestClient(app) as client, sample_video.open("rb") as video:
        alice = client.post(
            "/api/auth/signup",
            json={
                "name": "Alice",
                "email": "alice-content@example.test",
                "password": "correct-horse",
            },
        )
        assert alice.status_code == 201
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("alice.mp4", video, "video/mp4")},
        ).json()
        content = client.post(
            f"/api/projects/{asset['project_id']}/content",
            json={"content_type": "script", "title": "Alice private draft"},
        )
        assert content.status_code == 201, content.text
        content_id = content.json()["id"]

        assert client.post("/api/auth/logout").status_code == 204
        bob = client.post(
            "/api/auth/signup",
            json={
                "name": "Bob",
                "email": "bob-content@example.test",
                "password": "correct-horse",
            },
        )
        assert bob.status_code == 201

        hidden = client.get(f"/api/content/{content_id}")
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_standard_plan_keeps_incomplete_tail(container, sample_video: Path) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("sample.mp4", source, "video/mp4")},
        ).json()
        plan = client.post(
            f"/api/sources/{asset['id']}/standard-plan",
            json={"duration": 2.5, "count": "max"},
        ).json()
        assert plan["max_count"] == 3
        assert abs(plan["segments"][-1]["end"] - 6) < 0.1


def test_render_idempotency_key_replays_the_original_job(
    container, sample_video: Path
) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("idempotent.mp4", source, "video/mp4")},
        ).json()
        request = {
            "source_id": asset["id"],
            "segments": [{"id": "clip-1", "index": 1, "start": 0, "end": 1}],
        }
        headers = {"Idempotency-Key": "render-button-click-1"}
        first = client.post("/api/jobs/clips", json=request, headers=headers)
        replay = client.post("/api/jobs/clips", json=request, headers=headers)

        assert first.status_code == 202, first.text
        assert replay.status_code == 202, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["idempotent_replay"] is True
        assert _wait_for_job(client, first.json()["id"])["status"] == "succeeded"


def test_portrait_caption_render_updates_project(
    container, sample_video: Path, monkeypatch
) -> None:
    class RemoteProvider:
        name = "groq"
        model = "test-whisper"
        version = "1"
        remote = True

        def available(self) -> bool:
            return True

    transcript = Transcript(
        source=sample_video,
        language="en",
        duration=6,
        segments=[
            TranscriptSegment(
                index=0,
                start=0.1,
                end=1.8,
                text="A compact caption for a vertical clip.",
            )
        ],
    )
    container.ai.groq_transcription = RemoteProvider()
    container.settings.ai.transcription_provider = "groq"
    monkeypatch.setattr(container.ai, "transcribe", lambda *_args, **_kwargs: transcript)

    class ThumbnailProvider:
        name = "test-thumbnail"
        model = "test-thumbnail-model"

        def rank_clips(self, clips, *, platform):
            del platform
            return RankedClips(
                clips=[
                    RankedClip(
                        id=str(item["id"]),
                        score=max(70, 100 - index),
                        reason="Clear frame with useful composition.",
                    )
                    for index, item in enumerate(clips)
                ]
            )

        def generate_thumbnail_brief(self, _transcript, *, prompt=""):
            return ThumbnailBrief(
                headline="A clear surprising moment",
                visual_focus=prompt or "The main subject",
                emotion="Curious",
                composition="Center the subject and reserve space for a short headline.",
                frame_guidance="Use the sharpest expressive frame.",
                avoid=["Tiny text", "Clutter"],
            )

    container.ai.content_provider = ThumbnailProvider()
    service = build_service(container)
    app = create_app(service, require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("caption-source.mp4", source, "video/mp4")},
        ).json()
        create = client.post(
            "/api/jobs/clips",
            json={
                "source_id": asset["id"],
                "segments": [
                    {"id": "clip-1", "index": 1, "start": 0, "end": 2}
                ],
                "output_format": "portrait",
                "auto_captions": True,
                "platforms": ["youtube", "instagram"],
            },
        )
        finished = _wait_for_job(client, create.json()["id"], timeout=45)
        project = client.get(f"/api/projects/{finished['project_id']}").json()

    assert finished["status"] == "succeeded", finished
    clip = next(item for item in finished["artifacts"] if item["kind"] == "clip")
    assert clip["output_format"] == "portrait"
    assert clip["captions_enabled"] is True
    media = container.media.import_file(service.get_artifact(clip["id"]).path)
    assert media.video.display_resolution == (1080, 1920)
    assert project["status"] == "completed"
    assert project["clip_count"] == 1
    assert project["captions_enabled"] is True
    assert project["download_artifact_id"] == finished["zip_artifact"]["id"]
    job = service.jobs.get(finished["id"])
    assert job is not None and job.result is not None
    timings = job.result.data["pipeline_timings"]
    assert timings["clip_render_seconds"] >= 0
    assert timings["subtitle_preparation_seconds"] >= 0
    assert timings["single_pass_caption_render"] is True
    assert timings["caption_encoding_in_final_pass"] is True
    assert timings["final_render_seconds"] >= 0

    with TestClient(app) as client:
        thumbnails = client.post(
            f"/api/projects/{project['id']}/thumbnails",
            json={"prompt": "Clear subject", "target": "youtube"},
        )
        assert thumbnails.status_code == 201, thumbnails.text
        generated = thumbnails.json()
        candidates = generated["candidates"]
        assert len(candidates) == 4
        assert all(item["kind"] == "thumbnail" for item in candidates)
        assert generated["brief"]["headline"] == "A clear surprising moment"
        assert len(generated["ranking"]) == 4
        image = client.get(candidates[0]["stream_url"])
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/")
        refreshed_project = client.get(f"/api/projects/{project['id']}").json()
        assert refreshed_project["download_artifact_id"] == finished["zip_artifact"]["id"]

        schedule = client.post(
            "/api/schedules",
            json={
                "project_id": project["id"],
                "platforms": ["youtube", "instagram"],
                "interval_minutes": 30,
                "start_at": "now",
                "caption": "{clip} for {platform}",
            },
        )
        assert schedule.status_code == 201, schedule.text
        assert len(schedule.json()["posts"]) == 2
        assert schedule.json()["publish_ready"] is False


def test_ai_edit_plan_is_reviewable_and_bounded(container, sample_video: Path) -> None:
    class PlanningProvider:
        name = "test-provider"
        model = "test-planner"

        def plan_edit(self, *_args, **_kwargs):
            return ProviderAIEditPlan(
                platform="instagram",
                selection="standard",
                count=1,
                duration=5,
                aspect_ratio="9:16",
                captions=True,
                caption_style="dynamic",
                reframe="speaker",
            )

    container.ai.content_provider = PlanningProvider()
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("short-edit.mp4", source, "video/mp4")},
        ).json()
        response = client.post(
            "/api/ai/edit-plan",
            json={
                "source_id": asset["id"],
                "prompt": "Make a 5 second portrait clip with captions",
            },
        )

    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["output_format"] == "portrait"
    assert plan["auto_captions"] is True
    assert plan["segments"][0]["end"] == 5
    assert {item["kind"] for item in plan["actions"]} == {
        "platform", "selection", "trim", "format", "captions", "style", "reframe"
    }
    assert plan["platform"] == "instagram"
    assert plan["selection"] == "standard"


def test_social_metadata_is_generated_as_one_editable_package(
    container, sample_video: Path, monkeypatch
) -> None:
    class SocialProvider:
        name = "test-provider"
        model = "test-social"

        def generate_social_metadata(self, _transcript):
            return SocialMetadata(
                youtube_title="The surprising lesson",
                youtube_description="A complete short description.",
                youtube_hashtags=["#shorts", "#learn"],
                instagram_caption="Nobody expected this result.",
                instagram_hashtags=["#reels", "#creator"],
                instagram_cta="Save this for later.",
                hook="This changed everything",
                category="Education",
                posting_description="Publish when your audience is active.",
            )

    transcript = Transcript(
        source=sample_video,
        language="en",
        duration=6,
        segments=[TranscriptSegment(index=0, start=0, end=5, text="This changed everything.")],
    )
    container.ai.content_provider = SocialProvider()
    monkeypatch.setattr(container.ai, "transcribe", lambda *_args, **_kwargs: transcript)
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("social.mp4", source, "video/mp4")},
        ).json()
        response = client.post(
            f"/api/projects/{asset['project_id']}/social-metadata",
            json={},
        )

    assert response.status_code == 200, response.text
    package = response.json()
    assert package["youtube_title"] == "The surprising lesson"
    assert package["instagram_cta"] == "Save this for later."


def test_real_viral_analysis_endpoint_returns_provider_scores(
    container, sample_video: Path, monkeypatch
) -> None:
    class ViralProvider:
        name = "test-provider"
        model = "test-viral-model"
        analysis_version = "viral-test-v1"

        def health(self):
            return {"configured": True}

        def find_viral_moments(self, *_args, **_kwargs):
            return ViralMomentAnalysis(
                segments=[
                    ViralMoment(
                        start=0,
                        end=5,
                        score=93,
                        hook_score=96,
                        retention_score=91,
                        shareability_score=89,
                        platform="instagram",
                        reason="Strong opening and complete payoff",
                        hook="This changed everything",
                    )
                ]
            )

    transcript = Transcript(
        source=sample_video,
        language="en",
        duration=6,
        segments=[TranscriptSegment(index=0, start=0, end=5, text="This changed everything.")],
    )
    container.ai.content_provider = ViralProvider()
    monkeypatch.setattr(container.ai, "transcribe", lambda *_args, **_kwargs: transcript)
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("viral.mp4", source, "video/mp4")},
        ).json()
        response = client.post(
            f"/api/sources/{asset['id']}/viral-moments",
            json={"platform": "instagram", "target_length": 30, "max_clips": 5},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["model"] == "test-viral-model"
    assert payload["segments"][0]["score"] == 93
    assert payload["segments"][0]["hook"] == "This changed everything"


def test_invalid_youtube_url_returns_a_useful_error(container) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        response = client.post("/api/sources/youtube", json={"url": "https://example.com/video"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == "That is not a supported YouTube link."
    assert error["hint"] == "Use a youtube.com or youtu.be video URL."
    assert error["code"] == "VALIDATION_ERROR"
    assert error["retryable"] is False
    assert error["request_id"] == response.headers["x-request-id"]


def test_youtube_diagnostics_are_safe_for_operator_visibility(container) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        response = client.get("/api/youtube/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["yt_dlp_version"]
    assert payload["strategies"][0] == "web_embedded"
    assert "web_embedded" in payload["strategies"]
    assert "last_successful_strategy" in payload
    assert "last_failure_class" in payload
    assert "cookie_file" not in payload
    assert "proxy" not in payload


def test_youtube_import_job_registers_a_verified_source(
    container,
    sample_video: Path,
    monkeypatch,
) -> None:
    def import_video(url: str, *, on_progress=None) -> YouTubeImportResult:
        if on_progress:
            on_progress(0.25, "Fetching video information")
            on_progress(0.75, "Downloading video")
        return YouTubeImportResult(
            path=sample_video,
            metadata=YouTubeMetadata(
                video_id="abc123",
                title="Imported public video",
                duration=6,
                channel="Demo channel",
                webpage_url=url,
            ),
            strategy="web_safari_hls",
            format_id="96",
            attempts=2,
            elapsed=1.5,
        )

    monkeypatch.setattr(container.youtube, "import_video", import_video)
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        queued = client.post(
            "/api/jobs/youtube",
            json={
                "url": "https://www.youtube.com/watch?v=abc123",
                "rights_confirmed": True,
            },
        )
        assert queued.status_code == 202, queued.text
        finished = _wait_for_job(client, queued.json()["id"])
        assert finished["status"] == "succeeded", finished
        assert finished["source_id"]
        source = client.get(f"/api/sources/{finished['source_id']}")

    assert source.status_code == 200
    assert source.json()["title"] == "Imported public video"
    assert source.json()["channel"] == "Demo channel"


def test_youtube_import_job_preserves_normalized_error_code(container, monkeypatch) -> None:
    def blocked(_url: str, *, on_progress=None):
        raise YouTubeImportError(
            "BOT_CHALLENGE",
            "YouTube asked the processing server for additional verification.",
            retryable=True,
        )

    monkeypatch.setattr(container.youtube, "import_video", blocked)
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        queued = client.post(
            "/api/jobs/youtube",
            json={"url": "https://youtu.be/abc123", "rights_confirmed": True},
        )
        finished = _wait_for_job(client, queued.json()["id"])

    assert finished["status"] == "failed"
    assert finished["error_code"] == "BOT_CHALLENGE"


def test_youtube_import_requires_content_rights_confirmation(container) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/youtube",
            json={"url": "https://www.youtube.com/watch?v=abc123"},
        )

    assert response.status_code == 400
    assert "permission" in response.json()["error"]["message"].lower()


def test_validation_errors_use_the_stable_json_contract(container) -> None:
    app = create_app(build_service(container), require_auth=False)
    with TestClient(app) as client:
        response = client.post("/api/jobs/clips", json={})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]
    assert all("input" not in item for item in response.json()["error"]["details"])
    assert response.json()["error"]["retryable"] is False
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_unexpected_errors_return_safe_json(container, monkeypatch) -> None:
    service = build_service(container)

    def fail(*, limit=None):
        del limit
        raise RuntimeError("private implementation detail")

    monkeypatch.setattr(service, "list_projects", fail)
    app = create_app(service, require_auth=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/projects")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert response.json()["error"]["retryable"] is True
    assert "private implementation detail" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_api_responses_are_never_shared_cached(container) -> None:
    """A static-host API proxy must not cache tenant data or auth failures."""
    app = create_app(build_service(container), require_auth=True)
    with TestClient(app) as client:
        for path in ("/api/health", "/api/projects"):
            response = client.get(path)
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-request-id"]
