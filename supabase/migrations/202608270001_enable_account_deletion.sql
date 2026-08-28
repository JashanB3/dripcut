-- Allow Supabase Auth account deletion to remove the user's tenant data.
--
-- profiles.id cascades from auth.users. Every row owned by that profile must
-- therefore cascade as well; ON DELETE RESTRICT creates a circular deadlock
-- with the existing workspace_id cascades.

do $$
declare
  table_name text;
  constraint_name text;
begin
  foreach table_name in array array[
    'workspaces', 'projects', 'source_assets', 'clips', 'render_jobs',
    'artifacts', 'transcripts', 'ai_analyses', 'social_connections',
    'scheduled_posts', 'usage_events', 'subscriptions', 'entitlements'
  ] loop
    constraint_name := table_name || '_owner_id_fkey';

    execute format(
      'alter table public.%I drop constraint if exists %I',
      table_name,
      constraint_name
    );
    execute format(
      'alter table public.%I add constraint %I foreign key (owner_id) references public.profiles(id) on delete cascade',
      table_name,
      constraint_name
    );
  end loop;
end $$;
