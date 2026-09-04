# DripCut Next Platform Audit

**Audit date:** 2026-08-31

**Repository:** `/Users/jashan/Documents/DripCut/dripcut`

**Scope:** Current architecture, customer-visible behavior, risks, and readiness for the
next-generation content platform. This is an evidence document, not an implementation.

## Executive Summary

DripCut already has a credible SaaS and media-processing foundation. It should not be
replaced by either of the reference applications. The current strengths are tenant-aware
authentication, Supabase row-level security, private object storage, FFmpeg rendering,
standard and AI-assisted clip selection, transcription, structured AI output, usage quotas,
official social-provider boundaries, and a tested React/FastAPI product path.

The next product should be built additively on those boundaries. Before adding script-to-video,
campaigns, or analytics, DripCut needs one trust-focused stabilization milestone. The largest
confirmed issues are:

1. The public error contract has no consistent `retryable` field or status-code taxonomy.
2. Unexpected worker exception text is copied into a job hint and may reach the customer.
3. React has no application-level error boundary or reusable recovery state.
4. Social connection status has two competing UI implementations; one is real and one is a
   disabled placeholder.
5. Render execution is process-local. Active renders become explicit failures after restart
   because callable work cannot be reconstructed.
6. The editor foundation has local undo/redo state but is not yet connected to durable project
   persistence or export.
7. Google has blocked the current YouTube OAuth test account at the provider boundary. That is
   an external app/test-user configuration blocker, not evidence that publishing is live.

The correct sequence is: stabilize trust and errors, add universal content records, add script
creation, then add an independently retryable AI-video workflow. Campaigns, automation,
calendar, and analytics should follow only after the content and workflow models are durable.

## Evidence Collected

### Current verification

The following checks were run against the current working tree during this audit:

| Check | Result |
|---|---:|
| Backend tests | 336 passed |
| Backend test collection | 336 tests collected |
| Frontend unit tests | 16 passed |
| TypeScript | passed |

The existing CI workflow separately defines backend Ruff/tests, frontend ESLint/TypeScript/
tests/build, credential scanning, Playwright E2E, and a Docker build. Those CI definitions were
inspected but not represented as a fresh remote GitHub Actions run by this audit.

### Reference evidence

The three reference repositories were shallow-cloned outside the DripCut tree and inspected at:

| Repository | Audited commit | License |
|---|---|---|
| `darkzOGx/youtube-automation-agent` | `260d7a9` | MIT |
| `msitarzewski/agency-agents` | `3c95888` | MIT |
| `harry0703/MoneyPrinterTurbo` | `d7d4a13` | MIT |

No source code from those repositories was copied during this audit.

## Current Architecture

```text
React 19 / Vite
    |
    | JSON + HttpOnly session cookies
    v
FastAPI API
    |
    +-- AuthProvider -------- local / Supabase
    +-- TenantProvider ------ local / Supabase + PostgreSQL RLS
    +-- UsageProvider ------- local / Supabase reservations and events
    +-- StorageProvider ----- local / private S3 or R2
    +-- SocialStore --------- local / Supabase
    +-- Source/Project/Artifact manifest stores
    +-- LocalJobQueue ------- persisted history, process-local execution
    |
    +-- Media / Split / AI / Subtitle / Export / Project / Social services
            |
            +-- FFmpeg + FFprobe
            +-- yt-dlp YouTube import
            +-- Groq transcription / Faster-Whisper fallback
            +-- NVIDIA AI / Ollama fallback
            +-- official YouTube and Instagram provider boundaries

Classic Gradio UI and CLI remain alongside the SaaS path.
```

### Composition and layering

`src/dripcut/core/bootstrap.py` is the classic application's composition root and preserves the
documented dependency direction:

```text
utils -> core -> models -> engines -> services -> plugins -> ui -> cli
```

The FastAPI application adds provider-neutral auth, tenancy, usage, storage, social, and API
contracts around that foundation. The separation is directionally sound. New product features
should enter through services and provider ports rather than importing provider SDKs into route
handlers or React.

### Backend domains

| Domain | Current behavior | Assessment |
|---|---|---|
| Authentication | Local development and Supabase production providers | Keep |
| Tenancy | Workspace membership checks plus RLS | Keep and extend |
| Projects | Source-centric local manifests and Supabase metadata | Extend additively |
| Sources | Upload and YouTube URL | Extend to script and prompt sources |
| Clip selection | Sequential standard plans and optional AI recommendations | Keep shared segment contract |
| Rendering | FFmpeg, hardware capability selection, caption and format pipelines | Keep |
| Transcription | Groq primary, Faster-Whisper fallback and cache | Keep |
| AI | Structured NVIDIA/Ollama provider abstraction | Extend with script operations |
| Storage | Local or private S3/R2 with signed URLs | Keep |
| Usage | Reservations, commit/refund, entitlements | Keep; meter new stages |
| Social | Official provider interfaces and encrypted tokens | Keep and add capabilities |
| Jobs | Idempotent local thread pool with persisted history | Replace execution, not contract |
| Admin | Separate global-admin role and read-only operations | Keep |

### Frontend routes

Current authenticated routes are:

| Route | Purpose |
|---|---|
| `/home` | Recent activity, launch actions, usage summary |
| `/projects` | Project history and recovery |
| `/templates` | Workflow/template launcher |
| `/auto-clip` | Upload/YouTube, standard or AI selection, render and download |
| `/ai-editor` | Structured AI edit planning |
| `/ai-thumbnail` | Frame candidates, ranking, and thumbnail brief |
| `/schedule` | Real connection, metadata, schedule and publish state |
| `/usage` | Entitlement and usage display |
| `/admin` | Global-admin operations |
| `/settings` | Product settings summary |

Unauthenticated routes cover landing, signup, login, recovery/reset, OAuth callback, and logout.

The custom route hook supports both paths and legacy hashes. It is adequate for the current
route count but lacks entity routes, nested layouts, route loaders, and typed URL parameters.
A mature router can be introduced when content-item and workflow-run routes require it; changing
routing before that would add churn without product value.

### Frontend state

- Authentication is centralized in an `AuthProvider`.
- Most product pages own request, loading, error, and success state independently.
- Auto Clip uses a reducer for source/segment selection and keeps standard and AI selection on
  the same timeline.
- The editor uses an `EditorProvider` reducer with serializable state and up to 50 undo/redo
  snapshots.
- Template/project handoff still uses local storage in places.
- There is no server-state cache or normalized content entity store.

This is sufficient for a clipper, but long-running stage workflows need shared query state,
reconnection, and a durable workflow-run model. Introduce those only with the universal content
milestone.

## Current Working Features

The following capabilities exist in code and have local automated coverage:

- Email/password auth and Google-login architecture.
- Workspace isolation and tenant-aware persistence.
- Upload and rights-confirmed YouTube import.
- Standard sequential clipping without AI.
- Optional AI viral-moment recommendations over the same source timeline.
- Shared segment-to-render pipeline for standard and AI selections.
- Landscape, portrait, square, and source-format rendering.
- Caption generation/burn-in, thumbnail candidates, AI metadata, and ZIP downloads.
- Private artifact access through API ownership checks and signed object URLs.
- Usage reservations, quota enforcement, commit, and refund.
- Schedule drafts and official YouTube/Instagram provider boundaries.
- Structured logs, request IDs, rate limits, CORS/origin checks, and normalized API errors.
- Local restart recovery that marks interrupted work explicitly rather than losing it silently.
- Admin operations and CI quality gates.

External provider success must remain a separate claim. Local tests and mocks do not prove a
real social upload, email delivery, or provider token refresh.

## Broken or Incomplete Customer Functionality

### P0 - Trust and security defects

1. **Unexpected worker detail can reach the user.**
   `LocalJobQueue._apply_failure()` uses `str(exc)[:200]` as a public job hint for unexpected
   exceptions. This can reveal paths, dependency details, or provider internals. Log the original
   exception with a request/job correlation ID and return a fixed customer-safe hint.

2. **Error semantics are incomplete.**
   `ErrorDetail` has message, hint, code, details, and request ID, but no `retryable` flag. The
   base `DripCutError` also lacks a status contract, so provider unavailability can default to a
   generic 400 response rather than a safe 502/503 mapping.

3. **No React error boundary.**
   An unexpected component error can replace the application with an unhelpful blank or browser
   error rather than a recoverable customer state with a support reference.

### P1 - Conflicting product state

1. `SchedulePage` reads real connection state and performs real connection actions, while the
   account drawer hard-codes YouTube and Instagram as "Not connected" with disabled buttons.
2. `ScheduleModal` is an older disconnected placeholder even though `SchedulePage` contains the
   real flow.
3. `SettingsPage` always says filesystem manifests are enabled, which is misleading in an S3/R2
   and Supabase production deployment.
4. The create launcher advertises development workflows alongside real workflows. Disabled
   controls are acceptable during development, but normal customers should not have to discover
   which product promises are placeholders.

### P1 - Durability and scale gaps

1. Render callables live in a process-local thread pool. After a restart, active work becomes a
   retryable failure because the operation cannot be reconstructed from persisted data.
2. The API constructs local manifest stores even when blobs are placed in S3/R2. Object manifests
   support recovery, but production metadata is not uniformly database-native.
3. The process-local rate limiter cannot enforce limits across multiple API instances.
4. Video generation will require stage-level jobs, leases, heartbeats, retry policies, and
   idempotent output records before horizontal workers can be safe.

### P2 - Editor and workflow gaps

1. Editor undo/redo is local only; project persistence and export are explicitly deferred.
2. Canvas crop/rotate/adjust, editor export, and account controls remain disabled.
3. There is no durable AI script resource or script editor.
4. There is no AI-video workflow, TTS, visual asset, music, campaign, calendar, or analytics
   provider boundary yet.
5. Current project/source types support upload and YouTube only.

## Duplicate Systems and Technical Debt

| Area | Duplication/debt | Direction |
|---|---|---|
| UI | Classic Gradio plus React product | Preserve classic; new SaaS work is React only |
| Social UI | Real schedule connections plus placeholder account drawer/modal | One API-backed connection source |
| Persistence | Local manifests plus Supabase tables/object manifests | Define DB as production source of truth |
| Jobs | Generic classic export queue plus SaaS job records | Keep job model; add serializable stage handlers |
| Routing | Path and legacy hash routing | Retain compatibility, migrate when nested routes arrive |
| Error handling | Page-specific banners plus API normalization | Add shared error/retry components and boundary |
| Project handoff | API data plus local-storage selection | Use content/project IDs in URLs and server state |
| Mock catalog | Development workflows and sample recommendations | Keep catalog metadata, remove demo truth from live paths |

`PROJECT_STATE.md` is an older RC1 snapshot and no longer reflects the current React/Supabase
foundation or test count. It should be updated or explicitly archived once implementation work
resumes, but it was not changed in this planning-only milestone.

## Security Review

### Existing strengths

- HttpOnly session cookies, Secure in production, and SameSite controls.
- Cookie-auth mutation origin checks and explicit CORS allowlists.
- Workspace ownership checks before media and artifact operations.
- PostgreSQL RLS plus tenant-scoped relationship constraints.
- Private S3/R2 objects with short-lived signed URLs.
- Upload, media, duration, MIME/container, and YouTube URL validation.
- OAuth state validation and encrypted social credentials.
- Backend-only provider credentials and CI credential scanning.
- FFmpeg argument arrays rather than shell command strings.
- Structured AI models that cannot inject arbitrary FFmpeg arguments.

### Required hardening

1. Move Supabase browser OAuth to authorization-code/PKCE where supported. The current callback
   reads access and refresh tokens from the URL fragment before exchanging them into HttpOnly
   cookies. Tokens are not sent to the server by the browser automatically, but they are briefly
   available to React and browser extensions.
2. Remove raw unexpected-exception text from job/API customer fields.
3. Add explicit error-code, HTTP-status, and retryability mappings.
4. Add a restrictive Content Security Policy and review other response security headers.
5. Use a shared rate limiter before adding API replicas.
6. Require signatures, timestamp windows, and replay protection for future provider webhooks.
7. Treat reference text, scripts, URLs, and provider metadata as untrusted AI input. Keep system
   instructions isolated, validate structured output, and never allow model output to select
   arbitrary files, commands, URLs, or credentials.
8. Add provider-domain allowlists, DNS/IP revalidation, byte limits, MIME/magic-byte checks, and
   provenance records for stock or generated visual assets.
9. Keep campaign generation approval-first. No AI-created item should publish automatically
   unless the workspace owner has explicitly configured and enabled that automation.

## External Provider Blockers

| Provider | Current evidence | Status/action |
|---|---|---|
| Supabase | Auth/RLS architecture and migrations exist | Keep; production migrations remain an operational gate |
| R2/S3 | Private storage provider and signed URLs exist | Keep; monitor lifecycle and cost |
| NVIDIA | Structured provider adapter exists | Keep configurable; do not bind domain models to one model |
| Groq | Hosted transcription adapter exists | Keep with cache and local fallback |
| Google login | Supabase provider flow exists | Provider configuration must be verified per environment |
| YouTube publishing | OAuth reaches Google, but current account is denied access to the test app | **Blocked:** add the account as an OAuth test user or complete Google verification |
| Instagram publishing | Official provider boundary exists | **Blocked until:** Meta app credentials, test account, and permissions are configured |

The current Google denial must be shown to customers as a safe connection-availability message
with a request ID. It must not be called a live-verified YouTube integration.

## Missing Product Capabilities

- Provider-neutral `SCRIPT`, `AI_SCRIPT`, and `AI_PROMPT` sources.
- Editable, versioned scripts as project resources.
- Script generation and rewrite operations on `AIProvider`.
- TTS, visual asset, music, video-generation, and analytics provider ports.
- Stage-level AI-video orchestration with partial retry.
- Universal content items and per-platform targets.
- Campaigns, campaign approval, content calendar, and automation rules.
- Platform capability metadata.
- Provider analytics snapshots and explainable recommendations.
- Cost estimation and stage-level usage metering.
- Full E2E coverage for external-provider journeys.

## Architectural Decision

Do not rewrite DripCut and do not embed either reference application. Preserve the current
auth, tenancy, RLS, storage, usage, FFmpeg, source import, clipping, AI, and social-provider
boundaries. Add a universal content layer and a serializable workflow orchestrator above the
existing services. Migrate current projects and schedules through compatibility adapters rather
than a flag-day schema change.

## Prioritized Refactor Order

1. **Milestone A - trust stabilization:** normalized errors, safe worker failures, error boundary,
   reusable retry/empty/loading/success states, remove conflicting UI truth.
2. **Milestone B - universal content:** additive sources, content items, platform targets, workflow
   runs/stages, DB-first production metadata, compatibility adapters.
3. **Milestone C - script studio:** structured script generation and editing using current AI.
4. **Milestone D - AI video:** provider-neutral, stage-based pipeline; no mandatory paid provider.
5. **Milestone E - YouTube workspace:** end-to-end content preparation and approved scheduling.
6. **Milestone F - campaigns/automation:** approval-first generation and scheduling.
7. **Milestone G - capabilities:** provider-driven UI and future platform readiness.
8. **Milestone H - calendar/analytics:** durable calendar and read-only recommendation loop.
9. **Milestone I - specialist review:** UX, accessibility, security, performance, evidence.
10. **Milestone J - release verification:** full CI/E2E, real-provider smoke tests, load and recovery.

Implementation details, API contracts, schema proposals, cost controls, and milestone gates are
defined in `docs/next-gen-product-plan.md`.
