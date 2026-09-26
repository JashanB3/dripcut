-- Trusted worker jobs. Clients have no access; the API uses the service role.
create table if not exists public.acquisition_jobs (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid not null references public.projects(id) on delete cascade,
  source_url text not null,
  source_type text not null default 'youtube' check (source_type = 'youtube'),
  status text not null default 'queued' check (status in ('queued','claimed','running','uploading','completed','failed','cancelled')),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 2 check (max_attempts >= 1),
  lease_owner text,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  error_code text,
  error_message text,
  output_storage_key text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);
create index if not exists acquisition_jobs_claim_idx on public.acquisition_jobs(status, created_at) where status = 'queued';
alter table public.acquisition_jobs enable row level security;
revoke all on public.acquisition_jobs from anon, authenticated;

create table if not exists public.acquisition_workers (
  id text primary key,
  current_job_id uuid references public.acquisition_jobs(id) on delete set null,
  status text not null default 'idle',
  version text not null default 'unknown',
  last_seen_at timestamptz not null default now()
);
alter table public.acquisition_workers enable row level security;
revoke all on public.acquisition_workers from anon, authenticated;

create or replace function public.claim_acquisition_job(p_worker_id text, p_lease_seconds integer)
returns setof public.acquisition_jobs language plpgsql security definer set search_path = public as $$
declare claimed public.acquisition_jobs;
begin
  update acquisition_jobs set status='queued', lease_owner=null, lease_expires_at=null
    where status in ('claimed','running','uploading') and lease_expires_at < now();
  select * into claimed from acquisition_jobs where status='queued' and attempt_count < max_attempts
    order by created_at for update skip locked limit 1;
  if not found then return; end if;
  update acquisition_jobs set status='claimed', attempt_count=attempt_count+1, lease_owner=p_worker_id,
    lease_expires_at=now()+make_interval(secs => greatest(30,p_lease_seconds)), heartbeat_at=now(), started_at=coalesce(started_at,now())
    where id=claimed.id returning * into claimed;
  return next claimed;
end $$;

create or replace function public.heartbeat_acquisition_job(p_job_id uuid, p_worker_id text, p_lease_seconds integer, p_status text)
returns setof public.acquisition_jobs language plpgsql security definer set search_path = public as $$
declare result public.acquisition_jobs;
begin
 update acquisition_jobs set status=p_status, heartbeat_at=now(), lease_expires_at=now()+make_interval(secs => greatest(30,p_lease_seconds))
 where id=p_job_id and lease_owner=p_worker_id and lease_expires_at > now() returning * into result;
 if not found then raise exception 'invalid acquisition job lease'; end if; return next result;
end $$;

create or replace function public.complete_acquisition_job(p_job_id uuid, p_worker_id text, p_storage_key text, p_metadata jsonb)
returns setof public.acquisition_jobs language plpgsql security definer set search_path = public as $$
declare result public.acquisition_jobs;
begin
 update acquisition_jobs set status='completed', output_storage_key=p_storage_key, metadata=p_metadata, completed_at=now(), lease_expires_at=null
 where id=p_job_id and lease_owner=p_worker_id and lease_expires_at > now() returning * into result;
 if not found then raise exception 'invalid acquisition job lease'; end if; return next result;
end $$;

create or replace function public.fail_acquisition_job(p_job_id uuid, p_worker_id text, p_error_code text, p_error_message text, p_retryable boolean)
returns setof public.acquisition_jobs language plpgsql security definer set search_path = public as $$
declare result public.acquisition_jobs;
begin
 update acquisition_jobs set error_code=p_error_code, error_message=p_error_message, lease_owner=null, lease_expires_at=null,
  status=case when p_retryable and attempt_count < max_attempts then 'queued' else 'failed' end,
  completed_at=case when p_retryable and attempt_count < max_attempts then null else now() end
 where id=p_job_id and lease_owner=p_worker_id and lease_expires_at > now() returning * into result;
 if not found then raise exception 'invalid acquisition job lease'; end if; return next result;
end $$;

revoke all on function public.claim_acquisition_job(text, integer) from public;
revoke all on function public.heartbeat_acquisition_job(uuid, text, integer, text) from public;
revoke all on function public.complete_acquisition_job(uuid, text, text, jsonb) from public;
revoke all on function public.fail_acquisition_job(uuid, text, text, text, boolean) from public;
grant execute on function public.claim_acquisition_job(text, integer) to service_role;
grant execute on function public.heartbeat_acquisition_job(uuid, text, integer, text) to service_role;
grant execute on function public.complete_acquisition_job(uuid, text, text, jsonb) to service_role;
grant execute on function public.fail_acquisition_job(uuid, text, text, text, boolean) to service_role;
