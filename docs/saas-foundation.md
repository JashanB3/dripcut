# Milestone 1 SaaS foundation

DripCut uses provider boundaries for authentication and tenant metadata:

- `AuthProvider`: local development or Supabase Auth
- `TenantRepository`: local atomic JSON or Supabase/PostgREST with PostgreSQL RLS
- `UsageService`: centralized FREE/CREATOR/PRO entitlements and atomic reservations
- `StorageProvider`: local private objects for development or private S3/R2 objects
- `SocialStore`: encrypted account credentials and durable publishing schedules

Production never uses the local provider. `DRIPCUT_ENV=production`, Render, or
AWS startup fails unless Supabase is configured.

## Local development

Copy `.env.example` to `.env`, retain the local provider values, then run:

```bash
source .venv/bin/activate
make api-dev
```

In another terminal:

```bash
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173/signup`. Local passwords are hashed with `scrypt`,
sessions are HMAC-signed, and local users/workspaces persist beneath
`<DRIPCUT_HOME>/projects/web/`. This provider is for development only and does
not send recovery email or support Google.

## Supabase setup

1. Create a Supabase project.
2. Open SQL Editor and run every migration in filename order:
   `202608250001_milestone_1_saas_foundation.sql`,
   `202608270001_enable_account_deletion.sql`,
   `202608280001_usage_entitlements.sql`,
   `202608280002_storage_metadata.sql`,
   `202608280003_durable_jobs.sql`, and
   `202608280004_social_oauth_publishing.sql`.
3. In Authentication > URL Configuration, set the production Site URL.
4. Add `https://your-frontend.example/auth/callback` and
   `https://your-frontend.example/reset-password` to Redirect URLs.
5. Enable Email authentication. Decide whether email confirmation is required.
6. Enable Google and configure the Google client ID/secret in Supabase. Add the
   Supabase callback URL shown by Supabase to the Google OAuth client.
7. Configure the backend variables below. User-facing API requests use the
   caller's access token. Only the background publishing scheduler uses the
   service-role key to find due posts. Never expose that key to the browser and
   never create `VITE_SUPABASE_SERVICE_ROLE_KEY`.

```dotenv
DRIPCUT_ENV=production
DRIPCUT_AUTH_PROVIDER=supabase
DRIPCUT_TENANT_PROVIDER=supabase
DRIPCUT_USAGE_PROVIDER=supabase
DRIPCUT_AUTH_REQUIRED=1
DRIPCUT_FRONTEND_URL=https://your-frontend.example
DRIPCUT_ALLOWED_ORIGINS=https://your-frontend.example
DRIPCUT_COOKIE_SECURE=1
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=server-worker-key
```

The backend exchanges credentials and OAuth tokens with Supabase, validates the
access token against `/auth/v1/user`, and stores access/refresh tokens only in
`HttpOnly`, `SameSite=Lax` cookies. CORS accepts only configured origins.

## Internal admin access

The global DripCut administrator role is separate from workspace `owner` and
`admin` roles. Only profiles with `is_dripcut_admin = true` may open `/admin` or
call `GET /api/admin/overview`. Promote a verified operator explicitly:

```sql
update public.profiles
set is_dripcut_admin = true, updated_at = now()
where email = 'admin@example.com';
```

The operator must log out and back in after promotion. Production admin
analytics use the service-role key on the backend to aggregate users, jobs,
failures, usage, storage and publishing state. Responses never include OAuth
credentials, API keys, cookies, prompts or private media, and the admin area
does not provide impersonation.

Local development may set `DRIPCUT_ADMIN_EMAILS` to a comma-separated list of
test emails. This setting does not grant production access.

## Tenant authorization

Every product route resolves the authenticated user to a workspace membership.
The API registers and checks ownership for projects, sources, render jobs, and
artifacts before media services are called. Unauthorized IDs return `404` to
avoid confirming whether another workspace owns them. PostgreSQL RLS provides a
second independent boundary.

## Usage and quotas

`GET /api/usage` returns the authenticated workspace plan, monthly reset date,
committed usage, and active reservations. Uploads, YouTube imports, renders,
transcription, AI Editor actions, thumbnail generations, and scheduling reserve
their allowance before work starts. Successful work commits usage; failures
release the reservation. PostgreSQL advisory locks serialize each
workspace/metric pair so concurrent requests cannot bypass a quota.

Defaults live in `src/dripcut/usage/entitlements.py`. Deployments may override
individual limits with `DRIPCUT_PLAN_ENTITLEMENTS_JSON`; the frontend never
owns plan limits.

The migration creates metadata tables for profiles, workspaces,
workspace_members, projects, source_assets, clips, render_jobs, artifacts,
transcripts, ai_analyses, social_connections, scheduled_posts, usage_events,
subscriptions, and entitlements. Large media is not stored in PostgreSQL.

## Private object storage

Production should use a private S3 or R2 bucket. DripCut stores sources,
posters, rendered artifacts, ZIPs, and deterministic metadata manifests as
private objects. Downloads use short-lived signed URLs. The metadata manifests
allow a fresh API instance to reconstruct source and artifact records without a
persistent local disk.

```dotenv
DRIPCUT_STORAGE_PROVIDER=s3
DRIPCUT_STORAGE_BUCKET=dripcut-production
DRIPCUT_STORAGE_PREFIX=media
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=server-only-access-key
AWS_SECRET_ACCESS_KEY=server-only-secret
```

For R2, set `DRIPCUT_STORAGE_PROVIDER=r2` and
`DRIPCUT_STORAGE_ENDPOINT_URL` to the account endpoint.

## AI and social providers

NVIDIA-backed analysis is enabled only on the server. Without a configured
NVIDIA key, DripCut falls back to Ollama when available; standard sequential
clipping never requires either provider.

Official YouTube and Instagram publishing requires provider application
credentials, a public HTTPS API URL, encrypted credential storage, and the
server-side Supabase worker key. Register these callbacks with Google and Meta:

```text
https://api.example.com/api/social/youtube/callback
https://api.example.com/api/social/instagram/callback
```

Set `DRIPCUT_PUBLIC_API_URL=https://api.example.com`. In production, provide
`DRIPCUT_CREDENTIAL_ENCRYPTION_KEY` and `DRIPCUT_OAUTH_STATE_SECRET` through the
host's secret manager. YouTube defaults to private uploads. Instagram automatic
publishing also requires S3/R2 so Meta can retrieve a temporary HTTPS media URL.

## Static frontend routes

The React app uses real paths such as `/login`, `/signup`, and `/home`. Configure
the static host to rewrite unknown paths to `/index.html`. A `_redirects` file is
included for hosts that support the Netlify/Render convention.
