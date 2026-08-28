-- Milestone 9: one official social connection per platform and worker-safe publishing.

alter table public.social_connections
  add column if not exists scopes text[] not null default '{}',
  add column if not exists token_expires_at timestamptz;

create unique index if not exists social_connections_workspace_platform_idx
  on public.social_connections(workspace_id, platform);

alter table public.scheduled_posts
  add column if not exists started_at timestamptz,
  add column if not exists published_at timestamptz,
  add column if not exists attempt integer not null default 0 check (attempt >= 0);

create index if not exists scheduled_posts_due_idx
  on public.scheduled_posts(status, publish_at)
  where status = 'scheduled';
