-- Auth-user deletion cascades through profiles. Universal content must follow
-- the existing account-cleanup contract instead of blocking profile deletion.

do $$
declare
  relation record;
begin
  for relation in
    select *
    from (values
      ('content_sources', 'content_sources_owner_id_fkey'),
      ('content_items', 'content_items_owner_id_fkey'),
      ('platform_targets', 'platform_targets_owner_id_fkey')
    ) as required(table_name, constraint_name)
  loop
    if exists (
      select 1
      from pg_constraint
      where conrelid = format('public.%I', relation.table_name)::regclass
        and conname = relation.constraint_name
        and confdeltype <> 'c'
    ) then
      execute format(
        'alter table public.%I drop constraint %I',
        relation.table_name,
        relation.constraint_name
      );
    end if;

    if not exists (
      select 1
      from pg_constraint
      where conrelid = format('public.%I', relation.table_name)::regclass
        and conname = relation.constraint_name
    ) then
      execute format(
        'alter table public.%I add constraint %I foreign key (owner_id) references public.profiles(id) on delete cascade not valid',
        relation.table_name,
        relation.constraint_name
      );
    end if;

    execute format(
      'alter table public.%I validate constraint %I',
      relation.table_name,
      relation.constraint_name
    );
  end loop;
end $$;
