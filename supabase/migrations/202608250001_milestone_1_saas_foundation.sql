-- DripCut Milestone 1: identity, workspaces, tenant-owned product metadata and RLS.
-- Large video binaries remain outside PostgreSQL; only metadata/storage keys belong here.

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null default '',
  avatar_url text,
  is_dripcut_admin boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete restrict,
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.workspace_members (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role text not null default 'user' check (role in ('owner', 'admin', 'member', 'user')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create or replace function public.is_workspace_member(target_workspace uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.workspace_members
    where workspace_id = target_workspace and user_id = auth.uid()
  );
$$;

create or replace function public.can_manage_workspace(target_workspace uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.workspace_members
    where workspace_id = target_workspace
      and user_id = auth.uid()
      and role in ('owner', 'admin')
  );
$$;

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  title text not null,
  project_type text not null default 'auto_clip',
  status text not null default 'draft',
  platform text not null default 'both',
  output_format text not null default 'portrait',
  captions_enabled boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.source_assets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid references public.projects(id) on delete cascade,
  kind text not null check (kind in ('upload', 'youtube')),
  name text not null,
  status text not null default 'ready',
  storage_key text,
  source_url text,
  mime_type text,
  size_bytes bigint not null default 0 check (size_bytes >= 0),
  duration_seconds numeric not null default 0 check (duration_seconds >= 0),
  width integer not null default 0,
  height integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.clips (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete cascade,
  source_asset_id uuid not null references public.source_assets(id) on delete cascade,
  position integer not null,
  start_seconds numeric not null check (start_seconds >= 0),
  end_seconds numeric not null check (end_seconds > start_seconds),
  selection_strategy text not null default 'standard',
  status text not null default 'planned',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.render_jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid references public.projects(id) on delete cascade,
  source_asset_id uuid references public.source_assets(id) on delete cascade,
  status text not null default 'queued' check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  progress numeric not null default 0 check (progress >= 0 and progress <= 1),
  stage text not null default '',
  error_code text,
  error_message text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.artifacts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid references public.projects(id) on delete cascade,
  render_job_id uuid not null references public.render_jobs(id) on delete cascade,
  kind text not null check (kind in ('clip', 'zip', 'thumbnail', 'subtitle', 'transcript')),
  name text not null,
  storage_key text,
  mime_type text,
  size_bytes bigint not null default 0 check (size_bytes >= 0),
  status text not null default 'ready',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.transcripts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete cascade,
  source_asset_id uuid not null references public.source_assets(id) on delete cascade,
  provider text not null,
  language text,
  status text not null default 'queued',
  storage_key text,
  duration_seconds numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_analyses (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete cascade,
  source_asset_id uuid references public.source_assets(id) on delete cascade,
  analysis_type text not null,
  provider text,
  model text,
  status text not null default 'queued',
  input_hash text,
  result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.social_connections (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  platform text not null check (platform in ('youtube', 'instagram')),
  external_account_id text,
  display_name text,
  encrypted_credentials text,
  status text not null default 'disconnected',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, platform, external_account_id)
);

create table if not exists public.scheduled_posts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete cascade,
  artifact_id uuid references public.artifacts(id) on delete restrict,
  social_connection_id uuid references public.social_connections(id) on delete restrict,
  platform text not null check (platform in ('youtube', 'instagram')),
  publish_at timestamptz not null,
  status text not null default 'scheduled',
  metadata jsonb not null default '{}'::jsonb,
  external_post_id text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid references public.projects(id) on delete set null,
  event_type text not null,
  quantity numeric not null default 0,
  unit text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null unique references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  provider text,
  provider_customer_id text,
  provider_subscription_id text,
  plan text not null default 'free',
  status text not null default 'active',
  current_period_start timestamptz,
  current_period_end timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.entitlements (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  key text not null,
  value jsonb not null,
  source text not null default 'plan',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, key)
);

create index if not exists workspace_members_user_idx on public.workspace_members(user_id);
create index if not exists projects_workspace_updated_idx on public.projects(workspace_id, updated_at desc);
create index if not exists source_assets_workspace_idx on public.source_assets(workspace_id, project_id);
create index if not exists clips_project_idx on public.clips(project_id, position);
create index if not exists render_jobs_workspace_status_idx on public.render_jobs(workspace_id, status);
create index if not exists artifacts_project_idx on public.artifacts(project_id, created_at desc);
create index if not exists transcripts_source_idx on public.transcripts(source_asset_id);
create index if not exists ai_analyses_project_idx on public.ai_analyses(project_id, analysis_type);
create index if not exists scheduled_posts_publish_idx on public.scheduled_posts(workspace_id, status, publish_at);
create index if not exists usage_events_workspace_created_idx on public.usage_events(workspace_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'profiles', 'workspaces', 'workspace_members', 'projects', 'source_assets',
    'clips', 'render_jobs', 'artifacts', 'transcripts', 'ai_analyses',
    'social_connections', 'scheduled_posts', 'usage_events', 'subscriptions', 'entitlements'
  ] loop
    execute format('drop trigger if exists set_%I_updated_at on public.%I', table_name, table_name);
    execute format(
      'create trigger set_%I_updated_at before update on public.%I for each row execute function public.set_updated_at()',
      table_name, table_name
    );
  end loop;
end $$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  workspace_id uuid := gen_random_uuid();
  display_name text := coalesce(new.raw_user_meta_data->>'name', split_part(new.email, '@', 1));
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, coalesce(new.email, ''), display_name);
  insert into public.workspaces (id, owner_id, name, slug)
  values (
    workspace_id,
    new.id,
    display_name || '''s workspace',
    lower(regexp_replace(display_name, '[^a-zA-Z0-9]+', '-', 'g')) || '-' || left(new.id::text, 8)
  );
  insert into public.workspace_members (workspace_id, user_id, role)
  values (workspace_id, new.id, 'owner');
  insert into public.subscriptions (workspace_id, owner_id, plan, status)
  values (workspace_id, new.id, 'free', 'active');
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.projects enable row level security;
alter table public.source_assets enable row level security;
alter table public.clips enable row level security;
alter table public.render_jobs enable row level security;
alter table public.artifacts enable row level security;
alter table public.transcripts enable row level security;
alter table public.ai_analyses enable row level security;
alter table public.social_connections enable row level security;
alter table public.scheduled_posts enable row level security;
alter table public.usage_events enable row level security;
alter table public.subscriptions enable row level security;
alter table public.entitlements enable row level security;

create policy "profiles_select_self" on public.profiles for select using (id = auth.uid());
create policy "profiles_update_self" on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());
create policy "workspaces_select_members" on public.workspaces for select using (public.is_workspace_member(id));
create policy "workspaces_update_admins" on public.workspaces for update using (public.can_manage_workspace(id)) with check (public.can_manage_workspace(id));
create policy "memberships_select_members" on public.workspace_members for select using (public.is_workspace_member(workspace_id));
create policy "memberships_manage_admins" on public.workspace_members for all using (public.can_manage_workspace(workspace_id)) with check (public.can_manage_workspace(workspace_id));

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'projects', 'source_assets', 'clips', 'render_jobs', 'artifacts', 'transcripts',
    'ai_analyses', 'social_connections', 'scheduled_posts', 'usage_events',
    'subscriptions', 'entitlements'
  ] loop
    execute format(
      'create policy %I on public.%I for select using (public.is_workspace_member(workspace_id))',
      table_name || '_select_workspace', table_name
    );
    execute format(
      'create policy %I on public.%I for insert with check (public.is_workspace_member(workspace_id) and owner_id = auth.uid())',
      table_name || '_insert_workspace', table_name
    );
    execute format(
      'create policy %I on public.%I for update using (public.is_workspace_member(workspace_id)) with check (public.is_workspace_member(workspace_id))',
      table_name || '_update_workspace', table_name
    );
    execute format(
      'create policy %I on public.%I for delete using (owner_id = auth.uid() or public.can_manage_workspace(workspace_id))',
      table_name || '_delete_workspace', table_name
    );
  end loop;
end $$;

revoke all on function public.is_workspace_member(uuid) from public;
revoke all on function public.can_manage_workspace(uuid) from public;
grant execute on function public.is_workspace_member(uuid) to authenticated;
grant execute on function public.can_manage_workspace(uuid) to authenticated;
