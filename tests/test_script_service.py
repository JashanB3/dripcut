from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dripcut.api.app import build_service, create_app
from dripcut.auth.models import AuthUser
from dripcut.content.local import LocalContentRepository
from dripcut.content.models import ContentItemStatus, ContentSourceType, ContentType
from dripcut.content.service import ContentService
from dripcut.core.errors import AIProviderError
from dripcut.engines.ai.provider import AlternateHooks, ScriptBrief, ScriptDraft
from dripcut.services.script_service import ScriptStudioService
from dripcut.tenancy.local import LocalTenantRepository
from dripcut.tenancy.models import Principal, TenantAccessDenied
from dripcut.usage.local import LocalUsageRepository
from dripcut.usage.service import UsageService


class ScriptProvider:
    name = "controlled"
    model = "controlled-script-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def generate_script(self, brief: ScriptBrief) -> ScriptDraft:
        if self.fail:
            raise AIProviderError("The script provider is temporarily unavailable.")
        return _draft(brief.platform)

    def rewrite_script(self, script, *, action, brief) -> ScriptDraft:
        return _draft(brief.platform, title=f"{action}: {script[:12]}")

    def generate_hooks(self, script, *, brief) -> AlternateHooks:
        return AlternateHooks(hooks=[f"{brief.topic}: the surprise", f"Stop scrolling: {script[:20]}"])

    def adapt_script_for_platform(self, script, *, platform, brief) -> ScriptDraft:
        return _draft(platform, title=f"Adapted {platform}: {script[:10]}")


def _draft(platform: str, *, title: str = "A better creator workflow") -> ScriptDraft:
    return ScriptDraft.model_validate(
        {
            "title": title,
            "hook": "You are spending too much time on every short.",
            "sections": [
                {"type": "body", "text": "Start with one useful idea and one clear payoff."},
                {"type": "payoff", "text": "That makes the edit easier to watch and share."},
            ],
            "cta": "Save this workflow for your next video.",
            "estimated_duration_seconds": 42,
            "platform": platform,
            "language": "en",
            "description": "A practical creator workflow.",
            "caption": "One idea. One payoff. One stronger short.",
            "hashtags": ["creator", "shorts"],
        }
    )


def _brief(platform: str = "youtube") -> ScriptBrief:
    return ScriptBrief(
        topic="A faster creator workflow",
        platform=platform,
        audience="video creators",
        tone="conversational",
        language="en",
        target_duration_seconds=45,
        content_goal="teach one useful workflow",
        cta="save this",
        reference_text="Private reference copy that should not enter metadata.",
    )


def _principal(user_id: str, workspace_id: str) -> Principal:
    return Principal(
        user=AuthUser(id=user_id, email=f"{user_id}@example.test", name=user_id),
        workspace_id=workspace_id,
        role="owner",
        access_token=f"token-{user_id}",
    )


def test_manual_script_uses_universal_content_records(tmp_path: Path) -> None:
    tenants = LocalTenantRepository(tmp_path / "tenancy")
    content = ContentService(LocalContentRepository(tmp_path / "content"), tenants)
    principal = _principal("writer", "workspace-a")
    tenants.register(principal, "project", "project-a")
    service = ScriptStudioService(content, ScriptProvider())  # type: ignore[arg-type]

    workspace = service.create_manual(
        principal,
        "project-a",
        title="My own script",
        script="Hook. Body. Payoff.",
        platform="instagram",
        language="en",
        target_duration_seconds=30,
    )

    assert workspace.source.source_type is ContentSourceType.SCRIPT
    assert workspace.item.content_type is ContentType.SCRIPT
    assert workspace.item.script == "Hook. Body. Payoff."
    assert content.item(principal, workspace.item.id) == workspace.item


def test_ai_script_generation_actions_and_safe_provenance(tmp_path: Path) -> None:
    tenants = LocalTenantRepository(tmp_path / "tenancy")
    content = ContentService(LocalContentRepository(tmp_path / "content"), tenants)
    principal = _principal("creator", "workspace-a")
    tenants.register(principal, "project", "project-a")
    service = ScriptStudioService(content, ScriptProvider())  # type: ignore[arg-type]

    generated = service.generate(principal, "project-a", _brief())
    hooks = service.hooks(principal, generated.item.id, brief=_brief())
    adapted = service.adapt(
        principal,
        generated.item.id,
        platform="instagram",
        brief=_brief("instagram"),
    )

    assert generated.source.source_type is ContentSourceType.AI_SCRIPT
    assert generated.item.content_type is ContentType.AI_SCRIPT
    assert generated.item.status is ContentItemStatus.REVIEW
    assert "reference_text" not in generated.source.metadata["brief"]
    assert generated.source.metadata["reference_text_supplied"] is True
    assert len(hooks.alternate_hooks) == 2
    assert adapted.item.metadata["intended_platform"] == "instagram"
    assert adapted.item.metadata["ai_action_history"] == ["generate", "generate_hooks", "adapt_instagram"]


def test_script_items_remain_tenant_isolated(tmp_path: Path) -> None:
    tenants = LocalTenantRepository(tmp_path / "tenancy")
    content = ContentService(LocalContentRepository(tmp_path / "content"), tenants)
    alice = _principal("alice", "workspace-a")
    bob = _principal("bob", "workspace-b")
    tenants.register(alice, "project", "project-a")
    tenants.register(bob, "project", "project-b")
    service = ScriptStudioService(content, ScriptProvider())  # type: ignore[arg-type]
    generated = service.generate(alice, "project-a", _brief())

    with pytest.raises(TenantAccessDenied):
        service.hooks(bob, generated.item.id, brief=_brief())


def test_script_api_commits_quota_and_persists_edits(container) -> None:
    container.ai.content_provider = ScriptProvider()
    usage = UsageService(LocalUsageRepository(container.paths.home / "script-usage"))
    app = create_app(build_service(container), usage_service=usage, require_auth=False)
    payload = {
        "topic": "A faster creator workflow",
        "platform": "youtube",
        "audience": "video creators",
        "tone": "conversational",
        "language": "en",
        "target_duration_seconds": 45,
        "content_goal": "teach one useful workflow",
        "cta": "save this",
        "reference_text": "",
    }

    with TestClient(app) as client:
        generated = client.post("/api/scripts/generate", json=payload)
        assert generated.status_code == 201, generated.text
        workspace = generated.json()
        item = workspace["item"]
        assert workspace["source"]["source_type"] == "ai_script"
        assert item["content_type"] == "ai_script"

        edited = client.patch(
            f"/api/content/{item['id']}",
            json={"script": f"{item['script']}\n\nA creator-added ending.", "status": "ready"},
        )
        assert edited.status_code == 200, edited.text
        reopened = client.get(f"/api/content/{item['id']}")
        assert reopened.status_code == 200
        assert reopened.json()["script"].endswith("A creator-added ending.")

        hooks = client.post(
            f"/api/scripts/{item['id']}/actions",
            json={**payload, "action": "generate_hooks"},
        )
        assert hooks.status_code == 200, hooks.text
        assert len(hooks.json()["alternate_hooks"]) == 2

        metric = next(
            value
            for value in client.get("/api/usage").json()["metrics"]
            if value["key"] == "ai_editor_actions"
        )
        assert metric["used"] == 2
        assert metric["reserved"] == 0


def test_script_api_releases_quota_and_removes_empty_project_on_failure(container) -> None:
    container.ai.content_provider = ScriptProvider(fail=True)
    usage = UsageService(LocalUsageRepository(container.paths.home / "script-failed-usage"))
    app = create_app(build_service(container), usage_service=usage, require_auth=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/scripts/generate",
            json={
                "topic": "A failing request",
                "platform": "youtube",
                "audience": "creators",
                "tone": "clear",
                "language": "en",
                "target_duration_seconds": 30,
                "content_goal": "test safe failure",
            },
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AI_UNAVAILABLE"
        assert client.get("/api/projects").json() == []
        metric = next(
            value
            for value in client.get("/api/usage").json()["metrics"]
            if value["key"] == "ai_editor_actions"
        )
        assert metric["used"] == 0
        assert metric["reserved"] == 0
