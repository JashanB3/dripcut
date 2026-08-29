-- Enforce tenant consistency across every resource relationship.
--
-- RLS prevents members of one workspace from reading another workspace's rows,
-- but a plain UUID foreign key can still reference a hidden row when its UUID is
-- known. Composite foreign keys make workspace ownership part of the relation.

create unique index if not exists projects_id_workspace_idx
  on public.projects(id, workspace_id);
create unique index if not exists source_assets_id_workspace_idx
  on public.source_assets(id, workspace_id);
create unique index if not exists render_jobs_id_workspace_idx
  on public.render_jobs(id, workspace_id);
create unique index if not exists artifacts_id_workspace_idx
  on public.artifacts(id, workspace_id);
create unique index if not exists social_connections_id_workspace_idx
  on public.social_connections(id, workspace_id);

do $$
declare
  relation record;
begin
  for relation in
    select *
    from (values
      ('source_assets', 'source_assets_project_workspace_fkey', 'project_id', 'projects'),
      ('clips', 'clips_project_workspace_fkey', 'project_id', 'projects'),
      ('clips', 'clips_source_workspace_fkey', 'source_asset_id', 'source_assets'),
      ('render_jobs', 'render_jobs_project_workspace_fkey', 'project_id', 'projects'),
      ('render_jobs', 'render_jobs_source_workspace_fkey', 'source_asset_id', 'source_assets'),
      ('artifacts', 'artifacts_project_workspace_fkey', 'project_id', 'projects'),
      ('artifacts', 'artifacts_render_job_workspace_fkey', 'render_job_id', 'render_jobs'),
      ('transcripts', 'transcripts_project_workspace_fkey', 'project_id', 'projects'),
      ('transcripts', 'transcripts_source_workspace_fkey', 'source_asset_id', 'source_assets'),
      ('ai_analyses', 'ai_analyses_project_workspace_fkey', 'project_id', 'projects'),
      ('ai_analyses', 'ai_analyses_source_workspace_fkey', 'source_asset_id', 'source_assets'),
      ('scheduled_posts', 'scheduled_posts_project_workspace_fkey', 'project_id', 'projects'),
      ('scheduled_posts', 'scheduled_posts_artifact_workspace_fkey', 'artifact_id', 'artifacts'),
      ('scheduled_posts', 'scheduled_posts_social_connection_workspace_fkey', 'social_connection_id', 'social_connections'),
      ('usage_events', 'usage_events_project_workspace_fkey', 'project_id', 'projects'),
      ('usage_reservations', 'usage_reservations_project_workspace_fkey', 'project_id', 'projects')
    ) as required(table_name, constraint_name, column_name, parent_table)
  loop
    if not exists (
      select 1
      from pg_constraint
      where conrelid = format('public.%I', relation.table_name)::regclass
        and conname = relation.constraint_name
    ) then
      execute format(
        'alter table public.%I add constraint %I foreign key (%I, workspace_id) references public.%I (id, workspace_id) not valid',
        relation.table_name,
        relation.constraint_name,
        relation.column_name,
        relation.parent_table
      );
    end if;

    execute format(
      'alter table public.%I validate constraint %I',
      relation.table_name,
      relation.constraint_name
    );
  end loop;
end $$;
