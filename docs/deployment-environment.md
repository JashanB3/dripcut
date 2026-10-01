# Deployment Environment

DripCut uses separate frontend and backend environments. Build the React application with public
configuration only. Inject all provider credentials into the API and worker runtime through the
hosting platform's encrypted secret manager.

## Frontend

| Variable | Required | Secret | Purpose |
|---|---:|---:|---|
| `VITE_API_BASE_URL` | Empty with the Render proxy | No | Same-origin `/api`; use a separate URL only with a compatible cookie/domain deployment |

The frontend must not receive Supabase service-role, R2/S3, Groq, NVIDIA, Google client-secret,
Meta app-secret, OAuth-state, encryption, cookie, or database credentials.

## Backend Identity and Security

| Variable | Production requirement |
|---|---|
| `DRIPCUT_ENV` | `production` |
| `DRIPCUT_AUTH_PROVIDER` | `supabase` |
| `DRIPCUT_TENANT_PROVIDER` | `supabase` |
| `DRIPCUT_USAGE_PROVIDER` | `supabase` |
| `DRIPCUT_CONTENT_STORE` | `supabase` |
| `DRIPCUT_SOCIAL_STORE` | `supabase` |
| `DRIPCUT_AUTH_REQUIRED` | `1` |
| `DRIPCUT_COOKIE_SECURE` | `1` |
| `DRIPCUT_FRONTEND_URL` | Public HTTPS frontend origin |
| `DRIPCUT_PUBLIC_API_URL` | Public HTTPS API origin |
| `DRIPCUT_ALLOWED_ORIGINS` | Explicit HTTPS frontend origins only |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Project anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret manager only |

## Backend Media and Providers

Store the following only in the API/worker secret manager when the corresponding provider is
enabled:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `GROQ_API_KEY`
- `NVIDIA_API_KEY`
- `DRIPCUT_YOUTUBE_CLIENT_SECRET`
- `DRIPCUT_META_APP_SECRET` (legacy Facebook Login)
- `DRIPCUT_INSTAGRAM_APP_SECRET` (direct Instagram Login)
- `DRIPCUT_CREDENTIAL_ENCRYPTION_KEY`
- `DRIPCUT_OAUTH_STATE_SECRET`

Provider identifiers, model names, bucket names, endpoint URLs, regions, privacy defaults, and
OAuth client IDs are configuration rather than credentials, but should still remain server-side
unless the browser needs them.

## Deployment Procedure

1. Create isolated development, staging, and production secret sets.
2. Rotate any credential previously shared outside its approved secret manager.
3. Configure the backend first and confirm `/api/health` over HTTPS.
4. Build the frontend with only `VITE_API_BASE_URL`.
5. Run `python scripts/check_secrets.py --bundle web/dist` before publishing static assets.
6. Configure Supabase and provider callback URLs using the exact production origins.
7. Perform controlled auth, upload, render, download, and provider smoke tests.
8. Revoke superseded credentials and record the rotation result without recording values.

Do not pass secrets as Docker build arguments. Runtime environment injection prevents credentials
from being stored in image layers. Limit secret-manager access to the API and worker service
identities, and require review for secret changes.

## Current launch deployment

See [launch-checklist.md](launch-checklist.md) for the existing Render service IDs,
verified routing rules, public URLs, release evidence and remaining manual actions.
