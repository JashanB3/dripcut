# DripCut

DripCut turns one long video into ready-to-post Shorts and Reels. Creators can upload a
video or paste a YouTube URL, choose clip duration and count, optionally use AI to find
strong moments, render captions and portrait video, download a ZIP, and schedule posts.

Standard sequential clipping is the default and never requires AI.

## Product Flow

```text
Upload video / paste YouTube URL
              |
Choose duration and clip count
              |
Standard equal clips OR optional AI viral moments
              |
Shared render, captions and thumbnail pipeline
              |
Download private ZIP OR schedule through official APIs
```

## Current Foundation

- Email/password authentication and Google OAuth architecture
- Provider-neutral local and Supabase authentication
- Workspace ownership checks plus PostgreSQL row-level security
- Real project history, usage allowances, quota reservations and refunds
- Local development storage plus private S3/R2 object storage and signed URLs
- Durable local queue contract with idempotency, retries, progress and restart recovery
- Standard clipping, scene/silence/timestamp planning and optional AI recommendations
- Groq transcription with local Faster-Whisper fallback
- NVIDIA content analysis with Ollama fallback
- Real FFmpeg landscape, square and 1080x1920 portrait rendering
- Phone-safe burned captions, original templates, AI metadata and thumbnail ranking
- Official YouTube and Instagram OAuth/publishing provider boundaries
- Read-only internal admin operations area with a separate global admin role
- Structured request logs, normalized errors, rate limits, upload validation and CSRF checks
- Unit, integration and real-browser E2E checks in GitHub Actions

The classic local Gradio/CLI application remains available. The React/FastAPI product is the
multi-user SaaS path described below.

## Requirements

- Python 3.10 to 3.13
- Node.js 22+
- FFmpeg and FFprobe on `PATH`
- macOS or Linux
- Docker for container verification/deployment

Optional providers are configured entirely on the backend. No server secret may use a
`VITE_` prefix. See [`docs/credential-security.md`](docs/credential-security.md) for the rotation
runbook and [`docs/deployment-environment.md`](docs/deployment-environment.md) for the production
frontend/backend boundary.

## Local Setup

```bash
cd /Users/jashan/Documents/DripCut/dripcut
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Start the authenticated local API:

```bash
cd /Users/jashan/Documents/DripCut/dripcut
source .venv/bin/activate
python -m uvicorn dripcut.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Start the React app in a second terminal:

```bash
cd /Users/jashan/Documents/DripCut/dripcut/web
npm install
npm run dev
```

Open `http://127.0.0.1:5173/signup`. Local accounts, workspaces, projects, jobs and usage
persist under `DRIPCUT_HOME`. Local authentication is development-only and is rejected when
`DRIPCUT_ENV=production`.

If a port is already occupied:

```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Stop only the displayed DripCut process, or start Vite on another port with
`npm run dev -- --port 5174`.

## Standard and AI Clipping

The Auto Clip screen starts in standard mode. A ten-minute source with 60-second duration
offers ten complete clips through `MAX`; incomplete tail segments are not silently rendered.
The timeline shows clip boundaries and previews before processing.

“Find Viral Moments with AI” is an optional selection strategy. It overlays scored moments
on the same source timeline and feeds accepted segments into the same rendering pipeline as
standard clips. AI output is schema-validated and cannot execute shell commands or arbitrary
FFmpeg arguments.

## SaaS Providers

Production startup fails closed unless Supabase is configured:

```dotenv
DRIPCUT_ENV=production
DRIPCUT_AUTH_PROVIDER=supabase
DRIPCUT_TENANT_PROVIDER=supabase
DRIPCUT_USAGE_PROVIDER=supabase
DRIPCUT_SOCIAL_STORE=supabase
DRIPCUT_AUTH_REQUIRED=1
DRIPCUT_COOKIE_SECURE=1
DRIPCUT_FRONTEND_URL=https://app.example.com
DRIPCUT_ALLOWED_ORIGINS=https://app.example.com
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-public-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-server-only-service-role-key
```

Run every file in [`supabase/migrations`](supabase/migrations) in filename order. Full setup,
redirect URLs and security notes are in
[`docs/saas-foundation.md`](docs/saas-foundation.md).

### Private Media Storage

```dotenv
DRIPCUT_STORAGE_PROVIDER=s3
DRIPCUT_STORAGE_BUCKET=dripcut-production
DRIPCUT_STORAGE_PREFIX=media
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=server-only-access-key
AWS_SECRET_ACCESS_KEY=server-only-secret
```

Use `r2` and set `DRIPCUT_STORAGE_ENDPOINT_URL` for Cloudflare R2. Buckets remain private;
the API returns short-lived signed URLs after ownership checks. PostgreSQL stores metadata,
not video binaries.

### AI and Transcription

```dotenv
GROQ_API_KEY=server-secret
DRIPCUT_TRANSCRIPTION_PROVIDER=groq
DRIPCUT_AI_PROVIDER=auto
NVIDIA_API_KEY=server-secret
DRIPCUT_NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
DRIPCUT_OLLAMA_HOST=http://127.0.0.1:11434
DRIPCUT_OLLAMA_MODEL=qwen2.5:3b
```

Groq `whisper-large-v3-turbo` is the primary hosted transcription provider. Cached normalized
transcripts prevent repeated provider work. NVIDIA is the primary configured content-analysis
provider; Ollama is the local fallback. Basic clipping remains operational when both are absent.

### Social Publishing

Official Google and Meta application credentials are required. Register these backend callback
URLs and never ask users for platform passwords:

```text
https://api.example.com/api/social/youtube/callback
https://api.example.com/api/social/instagram/callback
```

Credentials and refresh tokens are encrypted server-side. Publishing runs through the durable
scheduler and records `scheduled`, `uploading`, `published`, and `failed` states.

### Internal Admin

`/admin` is not granted to ordinary workspace owners. For local development, list explicit
emails in the backend environment:

```dotenv
DRIPCUT_ADMIN_EMAILS=admin@example.com
```

For production, promote a verified profile in the Supabase SQL editor:

```sql
update public.profiles
set is_dripcut_admin = true, updated_at = now()
where email = 'admin@example.com';
```

Log out and back in after promotion. The read-only admin area shows aggregate users, projects,
processing, jobs, failures, usage and publishing status. It never exposes credentials, cookies,
prompts or private media and does not support impersonation.

## Performance

Local development defaults to two workers. The production image defaults to one safe worker;
increase concurrency only after measuring CPU, memory and storage throughput. FFmpeg selects
Apple VideoToolbox, NVIDIA NVENC or software encoding by capability and falls back safely.

Benchmark the pipeline by stage:

```bash
source .venv/bin/activate
python scripts/benchmark_pipeline.py /absolute/path/to/spoken-video.mp4 \
  --clip-duration 30 --count 3 --output-format portrait --runs 2
```

The operations API reports privacy-safe p50/p95 stage timings. Provider API and video encoding
are separate concerns; configuring an AI API does not accelerate FFmpeg.

## Validation

Backend:

```bash
source .venv/bin/activate
ruff check src tests scripts
pytest
python scripts/check_secrets.py --history
```

Frontend:

```bash
cd web
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e
```

After the frontend build, verify that no ignored backend value reached browser assets:

```bash
cd ..
python scripts/check_secrets.py --bundle web/dist --env-file .env
```

The Playwright flow creates an account, uploads real generated media, renders a standard clip,
downloads the ZIP, logs out, logs back in and verifies persisted project recovery.

## Docker

```bash
docker build -t dripcut-api .
docker run --rm -p 10000:10000 --env-file .env -e PORT=10000 dripcut-api
curl http://127.0.0.1:10000/api/health
```

The image runs as a non-root user, includes FFmpeg and Node for yt-dlp EJS, binds to `PORT`,
forces production Supabase providers and uses one render worker by default. Deploy the React
`web/dist` output separately and configure the static host to rewrite routes to `index.html`.

Render and YouTube import diagnostics are documented in
[`docs/web-processing-api.md`](docs/web-processing-api.md).

## Security Model

- HttpOnly, Secure, SameSite cookies in production
- strict allowed-origin CORS and cookie-auth mutation Origin checks
- workspace ownership checks before processing or download
- Supabase RLS as a second authorization boundary
- private object storage and short-lived signed URLs
- upload size/MIME/container/duration validation through FFprobe
- constrained YouTube URL validation and no arbitrary downloader sites
- endpoint rate limits plus atomic quota reservations
- OAuth state validation and encrypted social credentials
- normalized user errors with technical diagnostics retained in logs
- CI credential scanning and no frontend server secrets

The included process-local rate limiter is appropriate for a single API instance. Replace it
with a shared Redis-backed limiter before horizontally scaling.

## Classic CLI

The existing local toolkit is preserved:

```bash
dripcut doctor
dripcut info video.mp4
dripcut split video.mp4 --length 30 --dry-run
dripcut transcribe video.mp4 --format srt
dripcut export video.mp4 --preset "Vertical 1080x1920"
```

## License

MIT. See [`LICENSE`](LICENSE).
