# DripCut GCP migration audit

Audit date: 2026-09-19. Target: existing `instance-20260915-154845`, project
`dripcut`, zone `asia-south1-a`. No new compute resources are part of this plan.

## Current production truth

The repository and live checks show that the current frontend is a **Render
static site**, not Vercel: `https://dripcut.onrender.com`. It uses same-origin
`/api` requests and a Render rewrite to `https://dripcut-api.onrender.com` so
HttpOnly authentication cookies remain first-party. There is no tracked Vercel
configuration. This differs from the requested target description and must be
handled as a Render-static-site cutover unless a separate Vercel project is
identified.

The backend is a Render Docker web service. The verified deployed commit before
this migration was `29d21ab`. The image starts one Uvicorn process on port 10000.
Render currently executes all backend work:

| Responsibility | Current execution |
|---|---|
| YouTube validation, metadata and download | Render API/worker via yt-dlp |
| ffprobe and source validation | Render container |
| FFmpeg clipping/reframing | Render container |
| Groq transcription | Requested by Render; inference runs at Groq |
| Local Whisper | Code exists; excluded from the GCP MVP profile |
| Caption preparation/encoding | Render container when enabled |
| Clip/ZIP/thumbnail artifact creation | Render container |
| Artifact/source persistence | Render uploads to Cloudflare R2 |
| Job execution/state | In-process queue; snapshots persisted in R2 |
| YouTube scheduler/publisher | Render process; schedule/OAuth rows in Supabase |
| OAuth callbacks | Render API under `/api/social/{platform}/callback` |

Render's free worker has 512 MB RAM. Previous production runs hit both memory
termination and health timeout during FFmpeg. Public YouTube URLs also ended in
`BOT_CHALLENGE` from Render after the configured acquisition strategies were
exhausted. Those failures are the reason processing is moving to GCE.

## External services

### Supabase

Project ref: `amywdqifpomydyumuzgo`. It is on the Free plan. Dashboard evidence
captured during the launch audit showed database disk 14%, RAM 51%, and 7/60
connections. Current-cycle allowance usage shown by the dashboard was:

| Meter | Used / included |
|---|---:|
| Database | 0.029 / 0.5 GB |
| Uncached egress | 0.065 / 5 GB |
| Cached egress | 0 / 5 GB |
| Storage | 0 / 1 GB |
| MAU | 21 / 50,000 |
| Realtime / Edge Functions | 0 |

Supabase provides authentication, tenancy/ownership, plans and usage,
content/platform-target metadata, and social connection/schedule persistence.
The current `ProjectService` manifests and queue snapshots are object-backed in
R2; this is intentional existing design, not a claim that every project field is
a Supabase row.

### Cloudflare R2

R2 is configured through the S3-compatible provider and holds durable sources,
posters, clips, archives, project manifests and job state. Live Cloudflare usage
could not be inspected because the dashboard session was not authenticated.
The production cutover does not create a new bucket or paid service.

### Groq and optional AI

`GROQ_API_KEY` is configured in the production secret set and the default remote
transcription model is `whisper-large-v3-turbo`. Groq transcription/captions stay
off until the basic import→clip→R2 path passes on GCE. NVIDIA/editorial AI and
local Whisper are disabled in the MVP profile.

### Google/YouTube OAuth

The local ignored environment has YouTube OAuth client variables, but the
Render-specific ignored environment does not. It does contain credential
encryption and OAuth-state secrets. Consequently, production YouTube publishing
must be reported unconfigured until client credentials and the new callback URL
are verified on the GCE deployment. The required callback form is:
`https://api.dripcut.in/api/social/youtube/callback`.

## Secret inventory (names only)

Both `.env` and `.env.render` are ignored by Git; neither is tracked. The current
production secret/config inventory contains:

- Supabase: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- R2: `DRIPCUT_STORAGE_PROVIDER`, `DRIPCUT_STORAGE_BUCKET`,
  `DRIPCUT_STORAGE_ENDPOINT_URL`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`
- AI: `GROQ_API_KEY`, `NVIDIA_API_KEY`, `DRIPCUT_NVIDIA_MODEL`
- Security/OAuth: `DRIPCUT_CREDENTIAL_ENCRYPTION_KEY`,
  `DRIPCUT_OAUTH_STATE_SECRET`
- Deployment/provider selection: `DRIPCUT_ENV`, `DRIPCUT_AUTH_PROVIDER`,
  `DRIPCUT_TENANT_PROVIDER`, `DRIPCUT_USAGE_PROVIDER`,
  `DRIPCUT_CONTENT_STORE`, `DRIPCUT_SOCIAL_STORE`,
  `DRIPCUT_AUTH_REQUIRED`, `DRIPCUT_COOKIE_SECURE`, `DRIPCUT_MAX_WORKERS`
- URLs/CORS: `DRIPCUT_FRONTEND_URL`, `DRIPCUT_PUBLIC_API_URL`,
  `DRIPCUT_ALLOWED_ORIGINS`
- Feature providers: `DRIPCUT_TRANSCRIPTION_PROVIDER`, `DRIPCUT_AI_PROVIDER`

The GCE copy belongs at `/opt/dripcut/.env.production` with mode `0600`. Secret
values must never be copied into Git, Docker build arguments, logs or this audit.

## Target GCE shape

`deploy/gcp/docker-compose.yml` builds the API from the approved commit and runs
it behind Caddy. Only Caddy publishes 80/443. The API receives a 3 GB container
memory ceiling, 1.75 CPU ceiling, one processing worker, bounded JSON logs and an
automatic restart policy. Durable local metadata is a Docker volume; transient
acquisition/render work is `/tmp/dripcut`; durable media remains in R2.

The production image deliberately omits Gradio, OpenCV, local faster-whisper and
PySceneDetect. These remain in the desktop/development dependency set. The MVP
defaults are 720p, at most 30 fps, H.264/AAC, one FFmpeg thread, sequential clip
render/upload/delete, no ZIP, and no AI/thumbnail/caption/Instagram work.

## Cutover constraints

1. Inspect the existing VM and firewall before changing it.
2. Deploy and pass GCE health, YouTube acquisition, clipping, R2 and persistence
   checks before changing frontend routing.
3. Point `api.dripcut.in` at the existing VM and verify HTTPS.
4. Preserve same-site authentication. If the frontend remains on
   `dripcut.onrender.com`, update its same-origin `/api` rewrite to GCE rather
   than sending browser cookies cross-site. A frontend on `dripcut.in` may call
   `api.dripcut.in` with explicit credentialed CORS.
5. Leave Render intact as rollback, but stop it from consuming production jobs.

## Pending external verification

- Google account verification is required before VM inspection/deployment.
- DNS ownership is required to create the API A record once the existing VM's
  external IPv4 address is confirmed.
- Google OAuth console access/consent may be required to add the new YouTube
  callback and complete an actual private upload test.
- Cloudflare authentication is required only to report live R2 usage; it does not
  block deploying with the already-configured bucket.
