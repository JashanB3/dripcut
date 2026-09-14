# DripCut launch checklist

Updated 2026-09-12. This launch checkpoint supersedes the feature-expansion roadmap.
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

368 backend tests, 21 frontend tests, 4 Playwright scenarios pass. Ruff, ESLint,
TypeScript, production build and credential/history/bundle scans pass. Mobile
390px/412px and tablet 768px signup, launcher, deep link and session-refresh checks
pass; captured screenshots were inspected. Real Safari remains unverified.

The September 4 roadmap records credential rotation as incomplete. On 2026-09-09 the owner reported rotation was not completed or was uncertain.
Required Supabase, R2, Groq and NVIDIA replacements are now verified and staged.
All 28 backend setting names are now persisted on Render. A subsequent screenshot
exposed the replacement Supabase secret, which must be replaced again before launch. Do not infer
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
- [x] Final GitHub CI for release commit `0efae48`: all five jobs passed.
- [ ] Deploy both services to the release commit after secrets are saved.
- [ ] Verify live Supabase signup/login, refresh and persistence in clean browser.
- [ ] Verify production upload/import, captions, render and download.
- [ ] Verify production tenant isolation with controlled accounts.
- [ ] Verify production worker memory and restart recovery.

## Additional release evidence

- GitHub CI on `0efae48`, including the Supabase key-header compatibility fix,
  passed all five jobs: https://github.com/JashanB3/dripcut/actions/runs/34303439288.
- Docker with a 512 MiB hard memory limit and one CPU completed signup, a generated
  1080p upload and a 15-second portrait render in 10.53 seconds. No OOM kills.
  The memory ceiling was reached, so this tiny low-frame-rate fixture is not proof
  of sufficient production capacity. Test representative footage on the host.
- New `sb_secret_` keys are supported by the social background store via `apikey`;
  user calls retain their public API key + user JWT/RLS boundary. Three regression
  cases pass. Existing environment variable names remain compatible.

## JASHAN MUST DO

### NEXT ACTION: replace Supabase key exposed in September 12 screenshot

- Supabase replacement `dripcut_production_20260909` is saved locally and staged
  privately in `.env.render`; both files have owner-only permissions.
- Owner disabled legacy API keys. Dashboard now offers **Re-enable JWT-based
  API keys**, confirming they are disabled.
- After deactivation, replacement backend REST and publishable-key auth-settings
  probes both returned HTTP 200. No secret values were displayed.
- Owner created an R2 replacement user token scoped to Object Read & Write on
  `dripcut-production` and saved both S3 credential values locally. List, write,
  and read checks passed; the unique temporary verification object was removed.
- Superseded `R2 User Token` was deleted; dashboard lists only the replacement.
- Initial saved credentials were rejected after old-token deletion. Owner rolled
  the remaining token and saved its regenerated S3 credentials on September 12.
  Fresh list/write/read/delete verification now passes. Verified values were
  staged privately in `.env.render`; the verification object was removed.
- Owner created and saved the Groq replacement `dripcut_production_20260912`.
  Authentication returned HTTP 200 and real sample transcription produced four
  segments. Verified key staged privately in `.env.render`. Old `Dripcut` key
  (August 24) is absent after owner revocation; replacement still returns HTTP 200.
- NVIDIA replacement `dripcut_production_20260912` passed a real, schema-valid
  Viral Moments request with the configured model. Its displayed suffix matches
  the saved local key. Verified credential staged privately in `.env.render`.
  Old `Dripcut` key is absent after owner deletion; replacement inference returns
  HTTP 200. Publishing is deferred.

Required provider rotation is complete; import the prepared backend-only Render
file next. Do not replace the encryption key without handling existing encrypted
social records. Publishing remains unconfigured for this release.

References: https://supabase.com/docs/guides/getting-started/api-keys and
https://developers.cloudflare.com/r2/api/tokens/

### A. Sign in to Render — completed

1. Open https://dashboard.render.com/login.
2. Click your existing sign-in option and complete sign-in.
3. Return to Codex and say “done”.

### B. Import prepared server settings — READY FOR OWNER IMPORT

The root `.env.render` is an ignored, owner-readable file containing the existing
server credentials plus exact production URLs. Never paste its contents into chat,
commit it, or upload it to the frontend service.

1. Open https://dashboard.render.com/web/srv-da61o6jl550s73864hkg/env.
2. Click Edit, then the small More options button beside Add variable.
3. Click Import from .env, then Choose a file.
4. Press Command+Shift+G; enter `/Users/jashan/Documents/DripCut/dripcut/.env.render`.
5. Press Return, click Open, then Add variables. Replace duplicate keys with the
   prepared values if prompted.
6. After Add variables, use the arrow beside the save button and choose Save only.
7. Keep the backend page open and return to Codex saying “done”. Codex will verify
   persisted key names and deploy the release. On September 12 the first import
   did not persist (API still had three settings); frontend had only VITE_API_BASE_URL.

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

## September 12 deployment checkpoint

- All 28 expected backend setting names are persisted, with no duplicates observed.
- User-triggered API deployment of `main` commit `9abbca8` failed with
  `Expected 3 parts in JWT; got 1` during social worker recovery. This matches the
  already-fixed opaque Supabase key header bug in launch commit `0efae48`.
- Re-ran `tests/test_social_service.py`: 14 tests passed.
- API Render branch is now `launch/production-ready`; Auto-Deploy was set Off
  to control release timing. No launch-branch deployment has been started.
- Frontend was independently redeployed to `9abbca8` on main; it still needs the
  launch release and same-origin API configuration verification.
- Screenshot exposed `dripcut_production_20260909` Supabase secret. Do not launch
  using it. Fresh key form prepared as `dripcut_production_20260912`; owner must
  create/save it locally and on Render, then revoke the screenshot-exposed key.

## September 15 signup repair

- Supabase Site URL was still `http://127.0.0.1:5173`; confirmation mail consequently
  returned users to an unavailable local server. Changed the default auth destination
  to `https://dripcut.onrender.com/auth/callback` and added that exact URL plus
  `https://dripcut.onrender.com/reset-password` to the allowlist. Saved state verified.
- Signup adapter now explicitly supplies the configured frontend callback. Callback
  page handles expired/used links with recovery navigation, uses provider-neutral
  language, and removes tokens/errors from the address bar before exchanging them.
- Auth provider tests: 7 passed; Ruff, frontend lint/typecheck and the new expired-link
  Playwright scenario passed. These source changes still require deployment.
- Supabase Emails UI explicitly says custom SMTP is required to edit subject/body.
  Default sender remains active. Owner reports no email domain/sending service.
  Prepared branded HTML in `docs/email-templates/`; not yet installed in Supabase.
- For the current early-access launch, email confirmation is deliberately disabled in
  Supabase. New email/password users can reach their workspace immediately, so the
  default Supabase delivery limits and generic template cannot block sign-up. Re-enable
  confirmation before broad public marketing after configuring a verified sending domain
  and custom SMTP; then test with a fresh email, since old links may be used or expired.
- Owner reports replacement Supabase key saved on Render. Screenshot-exposed
  September 9 key revocation remains unverified; finish this before release.

## September 15 production deployment

- Render backend and frontend were both deployed from `launch/production-ready` at
  commit `2408fe7`. GitHub Actions completed successfully for that commit.
- Render health endpoint returned `{"status":"ok","ffmpeg":true,"ffprobe":true}` and
  the public frontend returned HTTP 200.
- Browser QA created a synthetic email/password account and reached `/home` directly;
  no confirmation email, local redirect, or expired-link error was involved.
