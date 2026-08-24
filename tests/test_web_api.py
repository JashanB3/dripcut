"""End-to-end HTTP tests for the React clipping pipeline."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from dripcut.api.app import build_service, create_app
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
    app = create_app(build_service(container))

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ffmpeg": True, "ffprobe": True}


def test_production_allowed_origins_env(container, monkeypatch) -> None:
    monkeypatch.setenv(
        "DRIPCUT_ALLOWED_ORIGINS",
        "https://dripcut.example, https://studio.dripcut.example ",
    )
    app = create_app(build_service(container))

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


def test_upload_plan_render_stream_and_download(container, sample_video: Path) -> None:
    app = create_app(build_service(container))
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


def test_standard_plan_drops_incomplete_tail(container, sample_video: Path) -> None:
    app = create_app(build_service(container))
    with TestClient(app) as client, sample_video.open("rb") as source:
        asset = client.post(
            "/api/sources/upload",
            files={"video": ("sample.mp4", source, "video/mp4")},
        ).json()
        plan = client.post(
            f"/api/sources/{asset['id']}/standard-plan",
            json={"duration": 2.5, "count": "max"},
        ).json()
        assert plan["max_count"] == 2
        assert plan["segments"][-1]["end"] == 5


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
    service = build_service(container)
    app = create_app(service)
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
        candidates = thumbnails.json()
        assert len(candidates) == 4
        assert all(item["kind"] == "thumbnail" for item in candidates)
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
    app = create_app(build_service(container))
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
        "trim",
        "format",
        "captions",
    }


def test_invalid_youtube_url_returns_a_useful_error(container) -> None:
    app = create_app(build_service(container))
    with TestClient(app) as client:
        response = client.post("/api/sources/youtube", json={"url": "https://example.com/video"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == "That is not a supported YouTube link."
    assert error["hint"] == "Use a youtube.com or youtu.be video URL."
    assert error["code"] == "VALIDATIONERROR"
    assert error["request_id"] == response.headers["x-request-id"]


def test_youtube_diagnostics_are_safe_for_operator_visibility(container) -> None:
    app = create_app(build_service(container))
    with TestClient(app) as client:
        response = client.get("/api/youtube/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["yt_dlp_version"]
    assert payload["strategies"][0] == "recommended"
    assert "web_embedded" in payload["strategies"]
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
    app = create_app(build_service(container))
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
            "PUBLIC_EXTRACTION_BLOCKED",
            "We couldn't retrieve this public video from YouTube right now.",
            retryable=True,
        )

    monkeypatch.setattr(container.youtube, "import_video", blocked)
    app = create_app(build_service(container))
    with TestClient(app) as client:
        queued = client.post(
            "/api/jobs/youtube",
            json={"url": "https://youtu.be/abc123", "rights_confirmed": True},
        )
        finished = _wait_for_job(client, queued.json()["id"])

    assert finished["status"] == "failed"
    assert finished["error_code"] == "PUBLIC_EXTRACTION_BLOCKED"


def test_youtube_import_requires_content_rights_confirmation(container) -> None:
    app = create_app(build_service(container))
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/youtube",
            json={"url": "https://www.youtube.com/watch?v=abc123"},
        )

    assert response.status_code == 400
    assert "permission" in response.json()["error"]["message"].lower()


def test_validation_errors_use_the_stable_json_contract(container) -> None:
    app = create_app(build_service(container))
    with TestClient(app) as client:
        response = client.post("/api/jobs/clips", json={})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_unexpected_errors_return_safe_json(container, monkeypatch) -> None:
    service = build_service(container)

    def fail(*, limit=None):
        del limit
        raise RuntimeError("private implementation detail")

    monkeypatch.setattr(service, "list_projects", fail)
    app = create_app(service)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/projects")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "private implementation detail" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
