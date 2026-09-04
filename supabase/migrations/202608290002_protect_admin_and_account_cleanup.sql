-- Close two production security/lifecycle gaps discovered by live verification.

-- Authenticated users may edit their public profile, but privileged fields are
-- server-managed. Column grants prevent PostgREST clients from self-promoting.
revoke update on public.profiles from authenticated;
grant update (display_name, avatar_url) on public.profiles to authenticated;

-- This table was introduced after the original account-deletion migration.
-- Keep its ownership foreign key aligned with every other tenant-owned table.
alter table public.usage_reservations
  drop constraint if exists usage_reservations_owner_id_fkey;
alter table public.usage_reservations
  add constraint usage_reservations_owner_id_fkey
  foreign key (owner_id) references public.profiles(id) on delete cascade;
