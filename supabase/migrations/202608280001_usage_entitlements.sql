-- DripCut Milestone 2: atomic usage reservations and quota-safe accounting.

create table if not exists public.usage_reservations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete restrict,
  project_id uuid references public.projects(id) on delete set null,
  metric text not null,
  quantity numeric not null check (quantity >= 0),
  unit text not null,
  status text not null default 'reserved' check (status in ('reserved', 'committed', 'released')),
  period_start timestamptz not null,
  period_end timestamptz not null,
  expires_at timestamptz not null default (now() + interval '24 hours'),
  committed_at timestamptz,
  released_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists usage_reservations_active_idx
  on public.usage_reservations(workspace_id, metric, status, period_start, period_end);

drop trigger if exists set_usage_reservations_updated_at on public.usage_reservations;
create trigger set_usage_reservations_updated_at
before update on public.usage_reservations
for each row execute function public.set_updated_at();

alter table public.usage_reservations enable row level security;

create policy "usage_reservations_select_workspace"
on public.usage_reservations for select
using (public.is_workspace_member(workspace_id));

create or replace function public.reserve_workspace_usage(
  p_workspace_id uuid,
  p_project_id uuid,
  p_metric text,
  p_quantity numeric,
  p_unit text,
  p_limit numeric,
  p_period_start timestamptz,
  p_period_end timestamptz
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  consumed numeric := 0;
  pending numeric := 0;
  reservation_id uuid := gen_random_uuid();
begin
  if auth.uid() is null or not public.is_workspace_member(p_workspace_id) then
    raise exception 'WORKSPACE_ACCESS_DENIED' using errcode = '42501';
  end if;
  if p_quantity < 0 or p_period_end <= p_period_start then
    raise exception 'INVALID_USAGE_RESERVATION' using errcode = '22023';
  end if;

  -- Serialize each workspace/metric pair so concurrent requests cannot bypass a limit.
  perform pg_advisory_xact_lock(hashtextextended(p_workspace_id::text || ':' || p_metric, 0));

  select coalesce(sum(quantity), 0)
  into consumed
  from public.usage_events
  where workspace_id = p_workspace_id
    and event_type = p_metric
    and created_at >= p_period_start
    and created_at < p_period_end;

  select coalesce(sum(quantity), 0)
  into pending
  from public.usage_reservations
  where workspace_id = p_workspace_id
    and metric = p_metric
    and status = 'reserved'
    and expires_at > now()
    and created_at >= p_period_start
    and created_at < p_period_end;

  if p_limit is not null and consumed + pending + p_quantity > p_limit then
    raise exception 'QUOTA_EXCEEDED:%', p_metric using errcode = 'P0001';
  end if;

  insert into public.usage_reservations (
    id, workspace_id, owner_id, project_id, metric, quantity, unit,
    period_start, period_end
  ) values (
    reservation_id, p_workspace_id, auth.uid(), p_project_id, p_metric, p_quantity,
    p_unit, p_period_start, p_period_end
  );
  return reservation_id;
end;
$$;

create or replace function public.commit_workspace_usage(
  p_reservation_id uuid,
  p_actual_quantity numeric default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  reservation public.usage_reservations%rowtype;
  actual numeric;
begin
  select * into reservation
  from public.usage_reservations
  where id = p_reservation_id
  for update;

  if not found or auth.uid() is null or not public.is_workspace_member(reservation.workspace_id) then
    raise exception 'USAGE_RESERVATION_NOT_FOUND' using errcode = '42501';
  end if;
  if reservation.status <> 'reserved' then
    return;
  end if;

  actual := coalesce(p_actual_quantity, reservation.quantity);
  if actual < 0 or actual > reservation.quantity then
    raise exception 'INVALID_ACTUAL_USAGE' using errcode = '22023';
  end if;

  update public.usage_reservations
  set status = 'committed', committed_at = now()
  where id = reservation.id;

  insert into public.usage_events (
    workspace_id, owner_id, project_id, event_type, quantity, unit, metadata
  ) values (
    reservation.workspace_id,
    auth.uid(),
    reservation.project_id,
    reservation.metric,
    actual,
    reservation.unit,
    jsonb_build_object('reservation_id', reservation.id)
  );
end;
$$;

create or replace function public.release_workspace_usage(p_reservation_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  reservation public.usage_reservations%rowtype;
begin
  select * into reservation
  from public.usage_reservations
  where id = p_reservation_id
  for update;

  if not found or auth.uid() is null or not public.is_workspace_member(reservation.workspace_id) then
    return;
  end if;
  if reservation.status = 'reserved' then
    update public.usage_reservations
    set status = 'released', released_at = now()
    where id = reservation.id;
  end if;
end;
$$;

revoke all on function public.reserve_workspace_usage(uuid, uuid, text, numeric, text, numeric, timestamptz, timestamptz) from public;
revoke all on function public.commit_workspace_usage(uuid, numeric) from public;
revoke all on function public.release_workspace_usage(uuid) from public;
grant execute on function public.reserve_workspace_usage(uuid, uuid, text, numeric, text, numeric, timestamptz, timestamptz) to authenticated;
grant execute on function public.commit_workspace_usage(uuid, numeric) to authenticated;
grant execute on function public.release_workspace_usage(uuid) to authenticated;
