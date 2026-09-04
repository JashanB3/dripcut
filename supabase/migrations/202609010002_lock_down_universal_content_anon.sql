-- Supabase grants table privileges to API roles through default privileges.
-- Universal content is authenticated-only, so keep anon from reaching these
-- tables even before row-level policies are evaluated.

revoke all on table public.content_sources from anon;
revoke all on table public.content_items from anon;
revoke all on table public.platform_targets from anon;
