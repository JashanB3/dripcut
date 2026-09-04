"""Regression coverage for production Supabase migration guarantees."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TENANT_RELATION_MIGRATION = (
    ROOT / "supabase" / "migrations" / "202608290001_tenant_scoped_relations.sql"
)
ADMIN_SECURITY_MIGRATION = (
    ROOT / "supabase" / "migrations" / "202608290002_protect_admin_and_account_cleanup.sql"
)
UNIVERSAL_CONTENT_MIGRATION = (
    ROOT / "supabase" / "migrations" / "202609010001_universal_content_architecture.sql"
)
UNIVERSAL_CONTENT_ANON_LOCKDOWN_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "202609010002_lock_down_universal_content_anon.sql"
)
UNIVERSAL_CONTENT_PROJECT_RELATION_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "202609010003_project_scoped_content_relations.sql"
)
UNIVERSAL_CONTENT_ACCOUNT_CLEANUP_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "202609010004_universal_content_account_cleanup.sql"
)


def test_tenant_scoped_relation_migration_covers_every_resource_link() -> None:
    sql = TENANT_RELATION_MIGRATION.read_text(encoding="utf-8")
    required_constraints = {
        "source_assets_project_workspace_fkey",
        "clips_project_workspace_fkey",
        "clips_source_workspace_fkey",
        "render_jobs_project_workspace_fkey",
        "render_jobs_source_workspace_fkey",
        "artifacts_project_workspace_fkey",
        "artifacts_render_job_workspace_fkey",
        "transcripts_project_workspace_fkey",
        "transcripts_source_workspace_fkey",
        "ai_analyses_project_workspace_fkey",
        "ai_analyses_source_workspace_fkey",
        "scheduled_posts_project_workspace_fkey",
        "scheduled_posts_artifact_workspace_fkey",
        "scheduled_posts_social_connection_workspace_fkey",
        "usage_events_project_workspace_fkey",
        "usage_reservations_project_workspace_fkey",
    }

    for constraint in required_constraints:
        assert constraint in sql

    assert "foreign key (%I, workspace_id)" in sql
    assert "references public.%I (id, workspace_id) not valid" in sql
    assert "validate constraint %I" in sql


def test_tenant_scoped_relation_migration_has_parent_unique_indexes() -> None:
    sql = TENANT_RELATION_MIGRATION.read_text(encoding="utf-8")

    for table in (
        "projects",
        "source_assets",
        "render_jobs",
        "artifacts",
        "social_connections",
    ):
        assert f"create unique index if not exists {table}_id_workspace_idx" in sql
        assert f"on public.{table}(id, workspace_id)" in sql


def test_admin_security_migration_prevents_profile_privilege_escalation() -> None:
    sql = ADMIN_SECURITY_MIGRATION.read_text(encoding="utf-8")

    assert "revoke update on public.profiles from authenticated" in sql
    assert "grant update (display_name, avatar_url)" in sql
    assert "is_dripcut_admin" not in sql.split("grant update", maxsplit=1)[1]


def test_admin_security_migration_restores_account_deletion_cascade() -> None:
    sql = ADMIN_SECURITY_MIGRATION.read_text(encoding="utf-8")

    assert "usage_reservations_owner_id_fkey" in sql
    assert "references public.profiles(id) on delete cascade" in sql


def test_universal_content_migration_is_tenant_scoped_and_forward_only() -> None:
    sql = UNIVERSAL_CONTENT_MIGRATION.read_text(encoding="utf-8")

    for table in ("content_sources", "content_items", "platform_targets"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"{table}_select_workspace" in sql
        assert f"{table}_insert_workspace" in sql
        assert f"{table}_update_workspace" in sql
        assert f"{table}_delete_workspace" in sql
    assert "drop table" not in sql.lower()
    assert "delete from" not in sql.lower()
    assert "update public.projects" not in sql.lower()


def test_universal_content_migration_blocks_cross_workspace_relations() -> None:
    sql = UNIVERSAL_CONTENT_MIGRATION.read_text(encoding="utf-8")
    constraints = {
        "content_sources_project_workspace_fkey",
        "content_sources_source_asset_workspace_fkey",
        "content_items_project_workspace_fkey",
        "content_items_source_workspace_fkey",
        "content_items_thumbnail_workspace_fkey",
        "content_items_video_workspace_fkey",
        "content_items_audio_workspace_fkey",
        "platform_targets_content_item_workspace_fkey",
        "platform_targets_social_connection_workspace_fkey",
    }
    for constraint in constraints:
        assert constraint in sql
    assert "foreign key (%I, workspace_id)" in sql
    assert "references public.%I (id, workspace_id)" in sql
    assert "validate constraint %I" in sql


def test_universal_content_migration_protects_immutable_relationship_columns() -> None:
    sql = UNIVERSAL_CONTENT_MIGRATION.read_text(encoding="utf-8")

    assert "revoke update on public.content_sources from authenticated" in sql
    assert "revoke update on public.content_items from authenticated" in sql
    assert "revoke update on public.platform_targets from authenticated" in sql
    assert "revoke update (id, workspace_id, owner_id, project_id" in sql
    assert "octet_length(metadata::text) <= 16384" in sql
    assert "octet_length(provider_metadata::text) <= 16384" in sql


def test_universal_content_tables_are_not_granted_to_anonymous_users() -> None:
    sql = UNIVERSAL_CONTENT_ANON_LOCKDOWN_MIGRATION.read_text(encoding="utf-8")

    for table in ("content_sources", "content_items", "platform_targets"):
        assert f"revoke all on table public.{table} from anon" in sql


def test_universal_content_relations_cannot_cross_projects() -> None:
    sql = UNIVERSAL_CONTENT_PROJECT_RELATION_MIGRATION.read_text(encoding="utf-8")

    for constraint in (
        "content_sources_source_asset_project_workspace_fkey",
        "content_items_source_project_workspace_fkey",
        "content_items_thumbnail_project_workspace_fkey",
        "content_items_video_project_workspace_fkey",
        "content_items_audio_project_workspace_fkey",
    ):
        assert constraint in sql
    assert "foreign key (%I, workspace_id, project_id)" in sql
    assert "references public.%I (id, workspace_id, project_id)" in sql
    assert "validate constraint %I" in sql


def test_universal_content_does_not_block_account_deletion() -> None:
    sql = UNIVERSAL_CONTENT_ACCOUNT_CLEANUP_MIGRATION.read_text(encoding="utf-8")

    for constraint in (
        "content_sources_owner_id_fkey",
        "content_items_owner_id_fkey",
        "platform_targets_owner_id_fkey",
    ):
        assert constraint in sql
    assert "references public.profiles(id) on delete cascade" in sql
    assert "validate constraint %I" in sql
