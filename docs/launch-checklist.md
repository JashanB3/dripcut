# DripCut launch checklist

Updated 2026-09-09. This launch checkpoint supersedes the feature-expansion roadmap.
Do not start payments, campaigns, AI Video, Recreate/Dissect, or new social providers.

## Recovered baseline

- Starting commit: `352349b`, clean `codex/production-readiness-day1` branch.
- Launch branch: `launch/production-ready`.
- Fresh initial baseline: 364 backend tests, 19 frontend tests; Ruff, ESLint,
  TypeScript, credential/history scan passed.
- React/Vite frontend, FastAPI API with in-process render workers, Supabase
  identity/tenant/content/usage stores, private R2/S3 media, FFmpeg, Groq and NVIDIA.
- Milestones A and B are present. Script Studio also exists; it is deferred for launch.
- Supabase read-only probes confirm profiles, workspaces, projects, content_sources,
  content_items and platform_targets exist. This does NOT verify all constraints/RLS
  or prove every migration was applied. No production migration was changed here.

## Current release checks

365 backend tests, 21 frontend tests, 4 Playwright scenarios pass. Ruff, ESLint,
TypeScript, production build and credential/history/bundle scans pass. Mobile
390px/412px and tablet 768px signup, launcher, deep link and session-refresh checks
pass; captured screenshots were inspected. Real Safari remains unverified.

The September 4 roadmap records credential rotation as incomplete. On 2026-09-09 the owner reported rotation was not completed or was uncertain.
Pause importing `.env.render` until the required credentials are replaced. Do not infer
that an authenticating key is safe or that a clean Git scan proves rotation.

## Existing deployment

- Frontend: https://dripcut.onrender.com
- API: https://dripcut-api.onrender.com
- Render project: `prj-da5k98bl550s73d4is1g`.
- Frontend service: `srv-da61ktm417fc739279k0`, static site.
- API service: `srv-da61o6jl550s73864hkg`, Docker, Oregon, free instance.
- At audit: frontend ran `fe677a6`; API ran `bc2837d`. API deployments of
  `fe677a6` and `9abbca8` failed at startup; their logs expired.
- API had only three environment keys: origins, transcription provider, Groq key.
  Supabase and object-storage credentials were absent. This explains a likely startup
  failure of the newer fail-closed production configuration; fresh deploy logs must confirm.
- No separate worker service exists. Keep one API replica and one render worker.
  In-flight renders cannot survive process termination; restart marks local jobs failed.
  A persistent disk/always-on instance must be evaluated before production reliability
  is claimed. Do not purchase upgrades without owner approval.

## Production routing

Render static-site rules, in order (added and HTTP-verified during this sprint):

| Source | Destination | Action |
|---|---|---|
| `/api/*` | `https://dripcut-api.onrender.com/api/*` | Rewrite |
| `/*` | `/index.html` | Rewrite |

Build frontend with `VITE_API_BASE_URL` empty, using same-origin `/api` URLs.
Do not point browser cookie-auth traffic directly at a different onrender.com origin.
API responses set `Cache-Control: private, no-store` to protect tenant responses
behind the proxy. Verify POST bodies, Set-Cookie, refresh and downloads after deployment.
Render reference: https://render.com/docs/redirects-rewrites

## Launch feature policy

- Core: Landing, email auth, Home, Projects, Upload/YouTube import, sequential clips,
  optional viral moments, captions, render, download, templates and usage.
- `VITE_EXPERIMENTAL_TOOLS=false` (default): hides Script Studio, AI Editor, thumbnails.
- `VITE_YOUTUBE_PUBLISHING_BETA=false` (default): hides schedule navigation and actions.
- These are UI visibility flags, not backend authorization controls. Existing API
  authorization still applies. Do not provision publishing credentials until approved.
- YouTube beta UI, when enabled, selects YouTube only. Instagram stays coming soon.
- Paid tier advertisements, unfinished utilities and false search prompt are hidden.
- Existing implementations and database tables are preserved.

## CODEX CAN DO

- [x] Protect working tree, create launch branch, check ignored secrets.
- [x] Audit source, tests, migrations, documentation and actual Render services.
- [x] Simplify launch navigation, landing claims and customer-facing settings.
- [x] Add `/create` entry point; guard hidden routes.
- [x] Isolate E2E from developer API and cloud credentials.
- [x] Prevent unexpected frontend Error messages leaking implementation details;
  display API support references; prevent shared caching of API responses.
- [x] Local browser signup/upload/render/download/logout/login/persistence.
- [x] Public YouTube import: `jNQXAC9IVRw` imported, 19 seconds.
  `BaW_jenozKc` is unavailable and returns a safe VIDEO_UNAVAILABLE response.
- [x] Real Groq transcription: 4 segments, 38 timed words.
- [x] Real configured NVIDIA viral-moment response passed schema validation.
- [x] Captioned render of imported video: 15 seconds in 1080x1920, 1080x1080,
  1920x1080. Frames visually inspected; captions readable with no truncation.
- [x] Generated 1080p/65-second upload; MAX plans 15/30/45/60 seconds returned
  4/2/1/1 complete clips. Nine actual HTTP render submissions in batches of 1/3/5
  all succeeded; observed queue peaks 0/1/3. This is local hardware evidence only.
- [x] Docker build, startup, health 200, FFmpeg/FFprobe, non-root UID 10001.
- [ ] Final GitHub CI for release commit.
- [ ] Deploy both services to the release commit after secrets are saved.
- [ ] Verify live Supabase signup/login, refresh and persistence in clean browser.
- [ ] Verify production upload/import, captions, render and download.
- [ ] Verify production tenant isolation with controlled accounts.
- [ ] Verify production worker memory and restart recovery.

## JASHAN MUST DO

### A. Sign in to Render — completed

1. Open https://dashboard.render.com/login.
2. Click your existing sign-in option and complete sign-in.
3. Return to Codex and say “done”.

### B. Import prepared server settings — PAUSED FOR CREDENTIAL ROTATION

The root `.env.render` is an ignored, owner-readable file containing the existing
server credentials plus exact production URLs. Never paste its contents into chat,
commit it, or upload it to the frontend service.

1. Open https://dashboard.render.com/web/srv-da61o6jl550s73864hkg/env.
2. Click Edit, then the small More options button beside Add variable.
3. Click Import from .env, then Choose a file.
4. Press Command+Shift+G; enter `/Users/jashan/Documents/DripCut/dripcut/.env.render`.
5. Press Return, click Open, then Add variables. Replace duplicate keys with the
   prepared values if prompted.
6. Leave the form open without deploying; return to Codex and say “done”.
7. Codex will verify key names only, save the configuration, and deploy the release.

### C. Supabase callback settings — after deployment targets are verified

1. Open https://supabase.com/dashboard/project/amywdqifpomydyumuzgo/auth/url-configuration.
2. Set Site URL to `https://dripcut.onrender.com` and click Save changes.
3. Under Redirect URLs, click Add URL and add
   `https://dripcut.onrender.com/auth/callback`.
4. Repeat for `https://dripcut.onrender.com/reset-password`.
5. Return to Codex and say “done”. Do not disable email verification merely to pass QA.

### D. YouTube publishing — deferred, not a core launch blocker

Do not enable public publishing yet. After core production QA, Codex will inspect
Google's exact app/project configuration and give the corresponding account-specific
Audience/Test users/publishing instructions. A real private upload and official
scheduled video ID are required before claiming YouTube publishing works.

## Release decision

NOT READY TO LAUNCH until the production journey and release CI are verified.
Local green tests alone are insufficient. Optional AI failures must not block standard
clipping. Payments and Instagram are not launch gates.
