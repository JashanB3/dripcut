-- Milestone B: provider-neutral content sources, content items, and platform targets.
--
-- This migration is forward-only. Existing project, source_asset, artifact, and
-- scheduled_post rows remain authoritative for their current responsibilities.

create table if not exists public.content_sources (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null,
  source_type text not null check (
    source_type in ('video_upload', 'youtube_url', 'script', 'ai_script', 'ai_prompt')
  ),
  title text not null check (char_length(title) between 1 and 180),
  text_content text check (text_content is null or char_length(text_content) <= 100000),
  source_asset_id uuid,
  external_url text check (external_url is null or char_length(external_url) <= 2048),
  metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 16384
  ),
  status text not null default 'draft' check (
    status in ('draft', 'importing', 'ready', 'failed')
  ),
  rights_confirmed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint content_sources_type_payload_check check (
    (source_type = 'video_upload' and source_asset_id is not null)
    or (source_type = 'youtube_url' and (source_asset_id is not null or external_url is not null))
    or (source_type in ('script', 'ai_script', 'ai_prompt') and nullif(btrim(text_content), '') is not null)
  )
);

create table if not exists public.content_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null,
  source_id uuid,
  content_type text not null check (
    content_type in ('video_clip', 'script', 'ai_script', 'ai_video')
  ),
  title text not null check (char_length(title) between 1 and 180),
  script text check (script is null or char_length(script) <= 100000),
  hook text check (hook is null or char_length(hook) <= 2000),
  body text check (body is null or char_length(body) <= 100000),
  description text check (description is null or char_length(description) <= 10000),
  caption text check (caption is null or char_length(caption) <= 10000),
  hashtags text[] not null default '{}'::text[] check (cardinality(hashtags) <= 50),
  thumbnail_artifact_id uuid,
  video_artifact_id uuid,
  audio_artifact_id uuid,
  duration_seconds numeric check (duration_seconds is null or duration_seconds >= 0),
  aspect_ratio text check (aspect_ratio is null or char_length(aspect_ratio) <= 20),
  language text check (language is null or char_length(language) <= 40),
  status text not null default 'draft' check (
    status in (
      'draft', 'generating', 'review', 'ready', 'scheduled',
      'partially_published', 'published', 'failed', 'archived'
    )
  ),
  metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 16384
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.platform_targets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  content_item_id uuid not null,
  platform text not null check (
    platform in ('youtube', 'instagram', 'facebook', 'tiktok', 'bilibili', 'linkedin')
  ),
  social_connection_id uuid,
  scheduled_at timestamptz,
  source_timezone text check (
    source_timezone is null or char_length(source_timezone) <= 80
  ),
  publish_status text not null default 'draft' check (
    publish_status in (
      'draft', 'ready', 'scheduled', 'queued', 'uploading',
      'processing', 'published', 'failed', 'cancelled'
    )
  ),
  provider_post_id text,
  provider_metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(provider_metadata) = 'object'
    and octet_length(provider_metadata::text) <= 16384
  ),
  idempotency_key text check (
    idempotency_key is null or char_length(idempotency_key) <= 200
  ),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  last_error_code text,
  last_error_message text check (
    last_error_message is null or char_length(last_error_message) <= 2000
  ),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists content_sources_id_workspace_idx
  on public.content_sources(id, workspace_id);
create unique index if not exists content_items_id_workspace_idx
  on public.content_items(id, workspace_id);
create unique index if not exists platform_targets_id_workspace_idx
  on public.platform_targets(id, workspace_id);

create index if not exists content_sources_project_created_idx
  on public.content_sources(workspace_id, project_id, created_at);
create index if not exists content_sources_asset_idx
  on public.content_sources(workspace_id, source_asset_id)
  where source_asset_id is not null;
create index if not exists content_items_project_created_idx
  on public.content_items(workspace_id, project_id, created_at);
create index if not exists content_items_source_idx
  on public.content_items(workspace_id, source_id)
  where source_id is not null;
create index if not exists platform_targets_content_status_idx
  on public.platform_targets(workspace_id, content_item_id, publish_status);
create index if not exists platform_targets_schedule_idx
  on public.platform_targets(workspace_id, publish_status, scheduled_at)
  where scheduled_at is not null;
create unique index if not exists platform_targets_idempotency_idx
  on public.platform_targets(workspace_id, idempotency_key)
  where idempotency_key is not null;

do $$
declare
  relation record;
begin
  for relation in
    select *
    from (values
      ('content_sources', 'content_sources_project_workspace_fkey', 'project_id', 'projects', 'cascade'),
      ('content_sources', 'content_sources_source_asset_workspace_fkey', 'source_asset_id', 'source_assets', 'restrict'),
      ('content_items', 'content_items_project_workspace_fkey', 'project_id', 'projects', 'cascade'),
      ('content_items', 'content_items_source_workspace_fkey', 'source_id', 'content_sources', 'restrict'),
      ('content_items', 'content_items_thumbnail_workspace_fkey', 'thumbnail_artifact_id', 'artifacts', 'restrict'),
      ('content_items', 'content_items_video_workspace_fkey', 'video_artifact_id', 'artifacts', 'restrict'),
      ('content_items', 'content_items_audio_workspace_fkey', 'audio_artifact_id', 'artifacts', 'restrict'),
      ('platform_targets', 'platform_targets_content_item_workspace_fkey', 'content_item_id', 'content_items', 'cascade'),
      ('platform_targets', 'platform_targets_social_connection_workspace_fkey', 'social_connection_id', 'social_connections', 'restrict')
    ) as required(table_name, constraint_name, column_name, parent_table, delete_action)
  loop
    if not exists (
      select 1
      from pg_constraint
      where conrelid = format('public.%I', relation.table_name)::regclass
        and conname = relation.constraint_name
    ) then
      execute format(
        'alter table public.%I add constraint %I foreign key (%I, workspace_id) references public.%I (id, workspace_id) on delete %s not valid',
        relation.table_name,
        relation.constraint_name,
        relation.column_name,
        relation.parent_table,
        relation.delete_action
      );
    end if;

    execute format(
      'alter table public.%I validate constraint %I',
      relation.table_name,
      relation.constraint_name
    );
  end loop;
end $$;

drop trigger if exists set_content_sources_updated_at on public.content_sources;
create trigger set_content_sources_updated_at
before update on public.content_sources
for each row execute function public.set_updated_at();

drop trigger if exists set_content_items_updated_at on public.content_items;
create trigger set_content_items_updated_at
before update on public.content_items
for each row execute function public.set_updated_at();

drop trigger if exists set_platform_targets_updated_at on public.platform_targets;
create trigger set_platform_targets_updated_at
before update on public.platform_targets
for each row execute function public.set_updated_at();

alter table public.content_sources enable row level security;
alter table public.content_items enable row level security;
alter table public.platform_targets enable row level security;

create policy "content_sources_select_workspace" on public.content_sources
for select using (public.is_workspace_member(workspace_id));
create policy "content_sources_insert_workspace" on public.content_sources
for insert with check (public.is_workspace_member(workspace_id) and owner_id = auth.uid());
create policy "content_sources_update_workspace" on public.content_sources
for update using (public.is_workspace_member(workspace_id))
with check (public.is_workspace_member(workspace_id));
create policy "content_sources_delete_workspace" on public.content_sources
for delete using (owner_id = auth.uid() or public.can_manage_workspace(workspace_id));

create policy "content_items_select_workspace" on public.content_items
for select using (public.is_workspace_member(workspace_id));
create policy "content_items_insert_workspace" on public.content_items
for insert with check (public.is_workspace_member(workspace_id) and owner_id = auth.uid());
create policy "content_items_update_workspace" on public.content_items
for update using (public.is_workspace_member(workspace_id))
with check (public.is_workspace_member(workspace_id));
create policy "content_items_delete_workspace" on public.content_items
for delete using (owner_id = auth.uid() or public.can_manage_workspace(workspace_id));

create policy "platform_targets_select_workspace" on public.platform_targets
for select using (public.is_workspace_member(workspace_id));
create policy "platform_targets_insert_workspace" on public.platform_targets
for insert with check (public.is_workspace_member(workspace_id) and owner_id = auth.uid());
create policy "platform_targets_update_workspace" on public.platform_targets
for update using (public.is_workspace_member(workspace_id))
with check (public.is_workspace_member(workspace_id));
create policy "platform_targets_delete_workspace" on public.platform_targets
for delete using (owner_id = auth.uid() or public.can_manage_workspace(workspace_id));

revoke update on public.content_sources from authenticated;
grant select, insert, delete on public.content_sources to authenticated;
grant update (title, text_content, metadata, status, rights_confirmed)
  on public.content_sources to authenticated;

revoke update on public.content_items from authenticated;
grant select, insert, delete on public.content_items to authenticated;
grant update (
  title, script, hook, body, description, caption, hashtags, duration_seconds,
  aspect_ratio, language, status, metadata
) on public.content_items to authenticated;

revoke update on public.platform_targets from authenticated;
grant select, insert, delete on public.platform_targets to authenticated;
grant update (
  social_connection_id, scheduled_at, source_timezone, publish_status,
  provider_post_id, provider_metadata, idempotency_key, attempt_count,
  last_error_code, last_error_message, published_at
) on public.platform_targets to authenticated;

revoke update (id, workspace_id, owner_id, project_id, source_type, source_asset_id, external_url)
  on public.content_sources from authenticated;
revoke update (
  id, workspace_id, owner_id, project_id, source_id, content_type,
  thumbnail_artifact_id, video_artifact_id, audio_artifact_id
) on public.content_items from authenticated;
revoke update (id, workspace_id, owner_id, content_item_id, platform)
  on public.platform_targets from authenticated;
