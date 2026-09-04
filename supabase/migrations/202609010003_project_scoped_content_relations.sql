-- Content relationships must stay inside both the workspace and the project.
-- The Milestone B workspace keys prevent cross-tenant references; these keys
-- also prevent references between two projects owned by the same workspace.

create unique index if not exists source_assets_id_workspace_project_idx
  on public.source_assets(id, workspace_id, project_id);
create unique index if not exists artifacts_id_workspace_project_idx
  on public.artifacts(id, workspace_id, project_id);
create unique index if not exists content_sources_id_workspace_project_idx
  on public.content_sources(id, workspace_id, project_id);

do $$
declare
  relation record;
begin
  for relation in
    select *
    from (values
      (
        'content_sources',
        'content_sources_source_asset_project_workspace_fkey',
        'source_asset_id',
        'source_assets'
      ),
      (
        'content_items',
        'content_items_source_project_workspace_fkey',
        'source_id',
        'content_sources'
      ),
      (
        'content_items',
        'content_items_thumbnail_project_workspace_fkey',
        'thumbnail_artifact_id',
        'artifacts'
      ),
      (
        'content_items',
        'content_items_video_project_workspace_fkey',
        'video_artifact_id',
        'artifacts'
      ),
      (
        'content_items',
        'content_items_audio_project_workspace_fkey',
        'audio_artifact_id',
        'artifacts'
      )
    ) as required(table_name, constraint_name, column_name, parent_table)
  loop
    if not exists (
      select 1
      from pg_constraint
      where conrelid = format('public.%I', relation.table_name)::regclass
        and conname = relation.constraint_name
    ) then
      execute format(
        'alter table public.%I add constraint %I foreign key (%I, workspace_id, project_id) references public.%I (id, workspace_id, project_id) on delete restrict not valid',
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
