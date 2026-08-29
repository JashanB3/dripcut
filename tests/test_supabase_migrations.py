"""Regression coverage for production Supabase migration guarantees."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TENANT_RELATION_MIGRATION = (
    ROOT / "supabase" / "migrations" / "202608290001_tenant_scoped_relations.sql"
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
