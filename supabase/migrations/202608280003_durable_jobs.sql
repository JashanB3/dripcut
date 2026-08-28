alter table public.render_jobs
  add column if not exists attempt integer not null default 0 check (attempt >= 0),
  add column if not exists max_attempts integer not null default 1 check (max_attempts >= 1),
  add column if not exists idempotency_key text;

create unique index if not exists render_jobs_workspace_idempotency_idx
  on public.render_jobs(workspace_id, idempotency_key)
  where idempotency_key is not null;
