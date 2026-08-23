from __future__ import annotations

import zipfile

import pytest

from dripcut.core.errors import ValidationError
from dripcut.services.social_service import SocialScheduleService


def _write_last_render(paths, archive) -> None:
    paths.cache.mkdir(parents=True, exist_ok=True)
    (paths.cache / "last_render.json").write_text(
        (
            "{"
            f'"archive": "{archive}",'
            '"source": "demo.mp4",'
            '"clip_count": 2,'
            '"status": "Done"'
            "}"
        ),
        encoding="utf-8",
    )


def test_social_connections_read_environment(paths, monkeypatch) -> None:
    service = SocialScheduleService(paths)

    assert not any(item.connected for item in service.connections())

    monkeypatch.setenv("DRIPCUT_YOUTUBE_CLIENT_ID", "id")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_REFRESH_TOKEN", "refresh")

    status = service.connection_map()
    assert status["youtube"].configured
    assert not status["youtube"].connected
    assert not status["instagram"].connected


def test_create_schedule_from_latest_zip(paths) -> None:
    archive = paths.cache / "clips.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("clip-001.mp4", b"one")
        zipped.writestr("clip-002.mp4", b"two")
    _write_last_render(paths, archive)

    service = SocialScheduleService(paths)
    schedule = service.create_schedule(
        platforms=["instagram", "youtube"],
        interval_minutes=30,
        start_at="2026-08-22 18:00",
        caption="{clip} for {platform}",
    )

    assert schedule.archive_name == "clips.zip"
    assert len(schedule.posts) == 4
    assert schedule.posts[0].platform == "instagram"
    assert schedule.posts[0].publish_at == "2026-08-22 18:00"
    assert schedule.posts[1].platform == "youtube"
    assert schedule.posts[1].publish_at == "2026-08-22 18:30"
    assert "clip-001" in schedule.posts[0].caption
    assert service.latest_schedule() is not None


def test_create_schedule_requires_latest_zip(paths) -> None:
    service = SocialScheduleService(paths)

    with pytest.raises(ValidationError):
        service.create_schedule(
            platforms=["youtube"],
            interval_minutes=30,
            start_at="now",
            caption="{clip}",
        )
