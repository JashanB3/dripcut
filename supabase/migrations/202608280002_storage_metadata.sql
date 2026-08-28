-- DripCut Milestone 3: metadata required to restore private object-backed sources.

alter table public.source_assets
add column if not exists poster_storage_key text;
