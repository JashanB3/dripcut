from __future__ import annotations

from pathlib import Path

import pytest

from dripcut.auth.models import AuthUser
from dripcut.content.local import LocalContentRepository
from dripcut.content.models import (
    ContentItem,
    ContentItemStatus,
    ContentSource,
    ContentSourceStatus,
    ContentSourceType,
    ContentType,
    PlatformTarget,
    PlatformTargetStatus,
    TargetPlatform,
)
from dripcut.content.service import ContentService
from dripcut.core.errors import ValidationError
from dripcut.social.models import SocialAccount
from dripcut.social.store import LocalSocialStore
from dripcut.tenancy.local import LocalTenantRepository
from dripcut.tenancy.models import Principal, TenantAccessDenied


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com", name=user_id),
        workspace_id=workspace_id,
        role="owner",
        access_token=f"token-{user_id}",
    )


def _service(tmp_path: Path):
    tenants = LocalTenantRepository(tmp_path / "tenancy")
    repository = LocalContentRepository(tmp_path / "content")
    social = LocalSocialStore(tmp_path / "social")
    source_projects = {"media-a": "project-a"}
    artifact_projects = {"artifact-a": "project-a"}
    service = ContentService(
        repository,
        tenants,
        social_store=social,
        source_project_id=source_projects.get,
        artifact_project_id=artifact_projects.get,
    )
    alice = _principal("alice", "workspace-a")
    bob = _principal("bob", "workspace-b")
    tenants.register(alice, "project", "project-a")
    tenants.register(alice, "source", "media-a", project_id="project-a")
    tenants.register(alice, "artifact", "artifact-a", project_id="project-a")
    tenants.register(bob, "project", "project-b")
    return service, tenants, repository, social, alice, bob


def test_content_ids_are_canonical_across_postgrest_uuid_formatting() -> None:
    hyphenated = "4d496776-bd23-4303-a241-53465943241b"
    compact = "4d496776bd234303a24153465943241b"

    source = ContentSource(
        id=hyphenated,
        workspace_id="workspace",
        owner_id="owner",
        project_id="project",
        source_type=ContentSourceType.VIDEO_UPLOAD,
        title="Source",
        source_asset_id=hyphenated,
    )
    item = ContentItem(
        id=hyphenated,
        workspace_id="workspace",
        owner_id="owner",
        project_id="project",
        content_type=ContentType.VIDEO_CLIP,
        title="Clip",
        source_id=hyphenated,
        video_artifact_id=hyphenated,
    )
    target = PlatformTarget(
        id=hyphenated,
        workspace_id="workspace",
        owner_id="owner",
        content_item_id=hyphenated,
        platform=TargetPlatform.YOUTUBE,
    )

    assert (source.id, source.source_asset_id) == (compact, compact)
    assert (item.id, item.source_id, item.video_artifact_id) == (compact, compact, compact)
    assert (target.id, target.content_item_id) == (compact, compact)


def test_all_content_source_types_are_supported(tmp_path: Path) -> None:
    service, _, _, _, alice, _ = _service(tmp_path)

    upload = service.create_source(
        alice,
        "project-a",
        source_type=ContentSourceType.VIDEO_UPLOAD,
        title="Upload",
        source_asset_id="media-a",
        status=ContentSourceStatus.READY,
    )
    youtube = service.create_source(
        alice,
        "project-a",
        source_type=ContentSourceType.YOUTUBE_URL,
        title="YouTube",
        external_url="https://www.youtube.com/watch?v=demo",
    )
    text_sources = [
        service.create_source(
            alice,
            "project-a",
            source_type=source_type,
            title=source_type.value,
            text_content="A creator-safe idea",
        )
        for source_type in (
            ContentSourceType.SCRIPT,
            ContentSourceType.AI_SCRIPT,
            ContentSourceType.AI_PROMPT,
        )
    ]

    assert upload.source_asset_id == "media-a"
    assert youtube.external_url and "youtube.com" in youtube.external_url
    assert [source.source_type for source in text_sources] == [
        ContentSourceType.SCRIPT,
        ContentSourceType.AI_SCRIPT,
        ContentSourceType.AI_PROMPT,
    ]
    assert len(service.repository.list_sources("workspace-a", "project-a")) == 5


def test_content_item_and_platform_target_crud(tmp_path: Path) -> None:
    service, _, _, _, alice, _ = _service(tmp_path)
    source = service.create_source(
        alice,
        "project-a",
        source_type=ContentSourceType.SCRIPT,
        title="Original script",
        text_content="Hook, body, payoff.",
    )
    item = service.create_item(
        alice,
        "project-a",
        source_id=source.id,
        content_type=ContentType.SCRIPT,
        title="First short",
        script="Hook, body, payoff.",
        hashtags=["#creator", "creator", "shorts"],
        metadata={"origin": "test"},
    )

    updated = service.update_item(
        alice,
        item.id,
        title="Updated short",
        status=ContentItemStatus.READY,
    )
    target = service.create_target(
        alice,
        item.id,
        platform=TargetPlatform.TIKTOK,
        scheduled_at="2026-09-02T10:00:00+00:00",
    )
    target = service.update_target(
        alice,
        item.id,
        target.id,
        publish_status=PlatformTargetStatus.SCHEDULED,
        provider_metadata={"variant": "vertical"},
    )

    assert updated.title == "Updated short"
    assert updated.hashtags == ["creator", "shorts"]
    assert target.publish_status is PlatformTargetStatus.SCHEDULED
    assert service.list_targets(alice, item.id) == [target]

    service.delete_target(alice, item.id, target.id)
    assert service.list_targets(alice, item.id) == []
    service.delete_item(alice, item.id)
    with pytest.raises(TenantAccessDenied):
        service.item(alice, item.id)


def test_existing_media_and_clip_artifacts_map_without_duplication(tmp_path: Path) -> None:
    service, _, repository, _, alice, _ = _service(tmp_path)

    first_source = service.ensure_media_source(
        alice,
        project_id="project-a",
        source_asset_id="media-a",
        kind="upload",
        title="Interview",
    )
    second_source = service.ensure_media_source(
        alice,
        project_id="project-a",
        source_asset_id="media-a",
        kind="upload",
        title="Interview",
    )
    first_clip = service.ensure_rendered_clip(
        alice,
        project_id="project-a",
        source_id=first_source.id,
        artifact_id="artifact-a",
        title="Interview 01",
        duration_seconds=30,
        output_format="portrait",
        captions_enabled=True,
        job_id="job-a",
        index=1,
    )
    second_clip = service.ensure_rendered_clip(
        alice,
        project_id="project-a",
        source_id=first_source.id,
        artifact_id="artifact-a",
        title="Interview 01",
        duration_seconds=30,
        output_format="portrait",
        captions_enabled=True,
        job_id="job-a",
        index=1,
    )

    assert first_source.id == second_source.id == "media-a"
    assert first_clip.id == second_clip.id == "artifact-a"
    assert first_clip.video_artifact_id == "artifact-a"
    assert first_clip.aspect_ratio == "9:16"
    assert len(repository.list_items("workspace-a", "project-a")) == 1


def test_cross_workspace_and_cross_project_references_are_rejected(tmp_path: Path) -> None:
    service, tenants, _, _, alice, bob = _service(tmp_path)
    source = service.create_source(
        alice,
        "project-a",
        source_type=ContentSourceType.SCRIPT,
        title="Private script",
        text_content="Private workspace content",
    )

    with pytest.raises(TenantAccessDenied):
        service.create_item(
            bob,
            "project-b",
            source_id=source.id,
            content_type=ContentType.SCRIPT,
            title="Stolen content",
        )

    tenants.register(alice, "project", "project-a-2")
    with pytest.raises(TenantAccessDenied):
        service.create_item(
            alice,
            "project-a-2",
            source_id=source.id,
            content_type=ContentType.SCRIPT,
            title="Wrong project",
        )

    with pytest.raises(TenantAccessDenied):
        service.item(bob, source.id)


def test_invalid_artifacts_connections_and_metadata_are_rejected(tmp_path: Path) -> None:
    service, _, _, social, alice, _ = _service(tmp_path)
    source = service.create_source(
        alice,
        "project-a",
        source_type=ContentSourceType.SCRIPT,
        title="Script",
        text_content="Text",
    )
    item = service.create_item(
        alice,
        "project-a",
        source_id=source.id,
        content_type=ContentType.SCRIPT,
        title="Item",
    )
    social.save_account(
        SocialAccount(
            id="connection-a",
            workspace_id=alice.workspace_id,
            owner_id=alice.user.id,
            platform="youtube",
            external_account_id="channel-a",
            display_name="Channel",
            encrypted_credentials="encrypted",
        )
    )

    with pytest.raises(TenantAccessDenied):
        service.create_target(
            alice,
            item.id,
            platform=TargetPlatform.YOUTUBE,
            social_connection_id="connection-b",
        )
    with pytest.raises(ValidationError, match="too (large|long)"):
        service.update_item(alice, item.id, metadata={"payload": "x" * 17_000})
    with pytest.raises(ValidationError, match="nested too deeply"):
        service.update_item(
            alice,
            item.id,
            metadata={"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}},
        )


def test_delete_project_only_removes_callers_content(tmp_path: Path) -> None:
    service, _, repository, _, alice, bob = _service(tmp_path)
    alice_item = service.create_item(
        alice,
        "project-a",
        content_type=ContentType.SCRIPT,
        title="Alice",
    )
    bob_item = service.create_item(
        bob,
        "project-b",
        content_type=ContentType.SCRIPT,
        title="Bob",
    )

    service.delete_project(alice, "project-a")

    with pytest.raises(TenantAccessDenied):
        repository.item(alice.workspace_id, alice_item.id)
    assert repository.item(bob.workspace_id, bob_item.id).title == "Bob"
