# DripCut Next-Generation Product Plan

**Plan date:** 2026-08-31

**Status:** Architecture proposal; no roadmap features implemented in this milestone.

**Foundation:** Existing DripCut React/FastAPI/Supabase/R2/FFmpeg architecture.

## Product Goal

Evolve DripCut from a video clipper into a creator-first content system without breaking the
simple clipping experience:

```text
Existing content
Upload / YouTube -> Standard or AI clip selection -> Render -> Captions/thumbnail/metadata
                 -> Download or approved schedule

New idea
Prompt / script -> Script -> Scenes -> Voice -> Visuals -> Music -> Captions -> Render
                -> Edit -> Metadata/thumbnail -> Download or approved schedule

Automation
Campaign -> Topic plan -> Approved items -> Generation -> Review -> Calendar -> Publishing
         -> Analytics -> Explainable recommendations
```

Standard clipping remains the default. AI viral moments remain optional. Both produce the same
`Segment` values and use the same downstream render path.

## Non-Negotiable Constraints

- Preserve Supabase auth, workspaces, RLS, tenant constraints, quotas, private storage, FFmpeg,
  Groq transcription, NVIDIA/Ollama AI, YouTube import, standard clipping, AI clipping,
  captions, ZIP export, admin, CI, and social-provider boundaries.
- Do not run a separate Node or Streamlit product inside DripCut.
- Do not make AI analysis mandatory for clipping.
- Do not publish generated content without explicit workspace configuration and approval.
- Do not expose provider keys, OAuth tokens, raw provider failures, filesystem paths, SQL, or
  stack traces to React.
- Do not enable a meaningful recurring-cost provider without user approval.
- Keep external provider claims separate from local/mocked verification.

## Reference Repository Comparison

### Summary

| Reference | Strongest value | What to adapt | What not to adopt |
|---|---|---|---|
| YouTube Automation Agent | Approval-oriented content lifecycle | Stage checkpoints, readiness probes, provenance, review gates, unknown-upload reconciliation, analytics recommendations | Monolithic Express/SQLite architecture, single-user credentials, YouTube-specific core |
| MoneyPrinterTurbo | Prompt/script-to-video stages | Script/TTS/assets/music/subtitle/assembly boundaries, presets, batch stages, validated materials | Streamlit UI, global configuration, giant task/service modules, provider sprawl, proxy publishing |
| Agency Agents | Review discipline | Evidence gates, specialist checklists, defect classification, three-attempt escalation, reality checks | Agent output as authority, stack-specific style mandates, unverified implementation suggestions |

### YouTube Automation Agent

Reusable concepts:

- Checkpoint each generation stage and support resume or downstream invalidation.
- Keep factual, media-rights, and editorial approval gates before publishing.
- Record media provenance and scene revisions.
- Distinguish a simulated fallback from provider-verified output.
- Reconcile an unknown upload outcome before retrying to avoid duplicate videos.
- Convert analytics into pending recommendations that a user accepts or rejects.
- Represent strategy, cadence, and safety guardrails as campaign configuration.

Rejected architecture:

- Large route/database modules and application-global SQLite state.
- A YouTube-only domain model.
- Provider credentials stored for a single local operator.
- A second job/auth/database architecture beside DripCut.

### MoneyPrinterTurbo

Reusable concepts:

- User-supplied script and AI-generated script are peers.
- Pipeline stages can stop after voice, captions, or final video.
- Materials are selected by aspect ratio and carry provider/source attribution.
- Voice, background music, caption style, language, output format, and batch count are explicit
  generation inputs.
- Task artifacts are written atomically and can be resumed.
- Provider-neutral orchestration is valuable even when only one provider is initially enabled.

Rejected architecture:

- A monolithic task function or a provider switch statement spread across services.
- Global mutable configuration and singleton providers.
- Streamlit as the product UI.
- Dozens of paid integrations in the first release.
- Generic proxy-based social publishing in place of official platform APIs.
- Any default that publishes a generated video publicly.

### Agency Agents methodology

Use the specialist roles as review lenses, not autonomous authorities:

1. Product/UX review of the journey and progressive disclosure.
2. UI/accessibility review against tokens, responsive states, reduced motion, and 44px targets.
3. Frontend review of component boundaries, state, errors, and reconnection.
4. Backend review of contracts, tenancy, jobs, and provider boundaries.
5. AI review of schemas, latency, cache, cost, and fallback behavior.
6. Security/AppSec review of actual trust boundaries and exploit tests.
7. DevOps review of health/readiness, rollback, observability, and secret delivery.
8. API contract/boundary/idempotency tests.
9. Performance baselines before optimization.
10. Evidence capture for real user journeys.
11. Reality check: without test or provider evidence, status is "needs work."

Every finding is classified as `TRUE DEFECT`, `FALSE POSITIVE`, `IMPROVEMENT`, or
`NOT RELEVANT` before work is scheduled.

## Target Architecture

```text
React product
  |
  +-- route/page modules
  +-- shared API query state + workflow event stream
  +-- editor state + durable snapshots
  |
FastAPI application
  |
  +-- ContentSourceService
  +-- ContentItemService
  +-- ScriptService
  +-- AIVideoService
  +-- CampaignService
  +-- SchedulingService
  +-- AnalyticsService
  |
  +-- WorkflowOrchestrator
  |     +-- typed, serializable stage handlers
  |     +-- idempotency + retry policy + leases + checkpoints
  |     +-- local adapter for development
  |     +-- distributed adapter for production
  |
  +-- Existing services
  |     +-- YouTube import / media / split / transcription
  |     +-- AI / FFmpeg / captions / export / social
  |
  +-- Provider ports
        +-- AIProvider
        +-- TTSProvider
        +-- VisualAssetProvider
        +-- MusicProvider
        +-- VideoGenerationProvider
        +-- SocialProvider
        +-- AnalyticsProvider

Supabase/PostgreSQL: tenant metadata and workflow state
Private R2/S3: source media, stage artifacts, clips, thumbnails, archives
Shared queue/limiter: Redis-backed initially; SQS-compatible adapter if worker topology requires it
```

### Domain boundaries

#### Content source

`ContentSource` represents what the creator started with:

```text
id
workspace_id
project_id
kind: VIDEO_UPLOAD | YOUTUBE_URL | SCRIPT | AI_SCRIPT | AI_PROMPT
status: draft | importing | ready | failed
title
input_payload                 # sanitized, type-specific JSON
source_asset_id               # optional current media record
script_resource_id            # optional current script
rights_confirmation
provenance
created_by
created_at / updated_at
```

Existing upload and YouTube sources remain valid. A compatibility mapper can expose the current
`source_assets` rows through this aggregate until migration is complete.

#### Script resource

```text
id
workspace_id
project_id
source_id
version
origin: user | ai | imported_transcript
title
hook
sections[]
cta
estimated_duration
platform
language
status: draft | approved | superseded
provider_metadata             # no secrets or raw prompts
created_by
created_at / updated_at
```

Scripts are editable and versioned. Approval selects a version; it never destroys previous text.

#### Universal content item

`ContentItem` is the publishable creative, not the original upload:

```text
id
workspace_id
project_id
source_id
campaign_id                   # nullable
script_resource_id            # nullable
video_artifact_id             # nullable
thumbnail_artifact_id         # nullable
title
description
caption
hashtags[]
status: draft | generating | review | ready | scheduled | partially_published | published | failed | archived
version
created_by
created_at / updated_at
```

#### Platform target

Each target succeeds or fails independently:

```text
id
workspace_id
content_item_id
platform
social_connection_id
scheduled_at_utc
status: draft | ready | scheduled | queued | uploading | processing | published | failed | cancelled
provider_post_id
provider_metadata
idempotency_key
attempt_count
last_error_code
last_error_message            # customer-safe
published_at
created_at / updated_at
```

An Instagram failure must not change a successful YouTube target to failed.

#### Campaign

```text
id
workspace_id
name
topic
goal
platforms[]
frequency_rule
timezone
start_at / end_at
approval_mode: every_item | first_batch | configured_automation
status: draft | active | paused | completed | cancelled
created_by
created_at / updated_at
```

Campaigns propose content items. They do not grant publishing permission by themselves.

#### Workflow run and stage

```text
WorkflowRun
  id, workspace_id, kind, entity_type, entity_id, status, input_version,
  idempotency_key, requested_by, estimated_cost, actual_cost, created_at, updated_at

WorkflowStage
  id, workspace_id, workflow_run_id, stage_key, position, status,
  attempt, max_attempts, lease_owner, lease_expires_at, heartbeat_at,
  input_ref, output_ref, error_code, safe_error_message, retryable,
  started_at, finished_at
```

Stage inputs are immutable references or versioned JSON. A worker reconstructs work from the
record; it never depends on an in-memory callable. Completed outputs are idempotent artifacts.

## Provider Interfaces

Provider SDK calls stay behind small ports. Domain services receive typed input/output and a
request context containing workspace, usage reservation, deadline, and correlation ID.

```python
class AIProvider(Protocol):
    def analyze_transcript(...) -> Analysis: ...
    def find_viral_moments(...) -> list[ViralMoment]: ...
    def create_edit_plan(...) -> EditPlan: ...
    def generate_script(...) -> ScriptDraft: ...
    def rewrite_script(...) -> ScriptDraft: ...
    def create_social_metadata(...) -> SocialMetadata: ...
    def create_thumbnail_brief(...) -> ThumbnailBrief: ...

class TTSProvider(Protocol):
    def capabilities(self) -> TTSCapabilities: ...
    def synthesize(self, request: TTSRequest) -> AudioArtifact: ...

class VisualAssetProvider(Protocol):
    def search(self, request: AssetSearchRequest) -> list[LicensedAsset]: ...
    def generate(self, request: AssetGenerationRequest) -> GeneratedAsset: ...

class MusicProvider(Protocol):
    def search(self, request: MusicSearchRequest) -> list[LicensedTrack]: ...
    def generate(self, request: MusicGenerationRequest) -> AudioArtifact: ...

class VideoGenerationProvider(Protocol):
    def capabilities(self) -> VideoGenerationCapabilities: ...
    def generate_scene(self, request: SceneRequest) -> VideoArtifact: ...

class SocialProvider(Protocol):
    def capabilities(self) -> SocialCapabilities: ...
    def verify_account(self, credentials) -> SocialAccount: ...
    def publish(self, request: PublishRequest) -> PublishResult: ...
    def reconcile(self, idempotency_key) -> PublishResult | None: ...

class AnalyticsProvider(Protocol):
    def capabilities(self) -> AnalyticsCapabilities: ...
    def fetch_metrics(self, request: MetricsRequest) -> MetricsSnapshot: ...
```

Required capability fields include upload, shorts, scheduling, thumbnails, metadata updates,
analytics, supported aspect ratios, duration/size limits, and provider-side scheduling support.
React renders controls from capabilities rather than platform-name conditionals.

## AI Video Orchestration

```text
VALIDATE_INPUT
  -> GENERATE_OR_VALIDATE_SCRIPT
  -> PLAN_SCENES
  -> GENERATE_VOICE
  -> RESOLVE_VISUALS
  -> RESOLVE_MUSIC
  -> GENERATE_CAPTIONS
  -> ASSEMBLE_VIDEO
  -> CREATE_EDITABLE_PROJECT
  -> GENERATE_METADATA
  -> READY_FOR_REVIEW
```

Rules:

- Each stage has a typed schema, cost estimate, timeout, retry policy, and idempotency key.
- A failed stage can be retried without rerunning successful paid stages.
- Changing the script invalidates scene/voice/caption/video outputs but not the original source.
- Changing only metadata does not rerender the video.
- Stock/generated assets carry source URL, provider, license, retrieval time, and checksum.
- Provider failures return customer-safe codes while secure logs retain technical details.
- FFmpeg performs final assembly when practical; provider-specific media never bypasses probe and
  validation.
- Generation stops at review by default.

## Database Changes

All changes are additive migrations. Every tenant table has `workspace_id`, RLS, a tenant-scoped
foreign key, and indexes beginning with `workspace_id` where queries are tenant-filtered.

### Migration sequence

1. Add `content_sources` and `script_resources`.
2. Add `content_items` and `content_item_targets`.
3. Add `workflow_runs` and `workflow_stages` with unique workspace/idempotency indexes.
4. Add `campaigns` and `campaign_content_items`.
5. Add `analytics_snapshots` and `content_recommendations`.
6. Backfill current projects, sources, artifacts, and scheduled posts into compatibility views.
7. Switch production reads one domain at a time; retain rollback views until a full release passes.

### Reuse existing tables

- Keep `projects`, `source_assets`, `clips`, `render_jobs`, `artifacts`, `transcripts`,
  `ai_analyses`, `social_connections`, `scheduled_posts`, `usage_events`, `subscriptions`,
  `entitlements`, and `usage_reservations`.
- Link new records to existing project/artifact/social records rather than copying media metadata.
- Evolve `scheduled_posts` into or behind `content_item_targets`; do not maintain two permanent
  scheduling systems.
- Store large inputs/outputs in private object storage, not PostgreSQL JSON.

### Database invariants

- A content item, source, artifact, connection, target, and workflow referenced together must
  share a workspace.
- Only one active target may exist for `(content_item_id, platform, account)` unless explicitly
  versioned.
- Publish and generation idempotency keys are unique per workspace.
- Stage output references become immutable after successful completion.
- Service-role workers use explicit tenant filters; RLS remains defense in depth for user tokens.

## API Contract

### Normalized error envelope

```json
{
  "error": {
    "code": "AUTH_PROVIDER_UNAVAILABLE",
    "message": "We could not sign you in right now. Please try again.",
    "request_id": "abc123",
    "retryable": true,
    "hint": "Try again in a moment."
  }
}
```

Safe optional `details` are allowed only for field validation. Provider responses, stack traces,
SQL, paths, tokens, and SDK exception text remain in structured logs. A registry maps each code
to an HTTP status, retryability, customer message, and telemetry severity.

All mutating creation/retry APIs accept `Idempotency-Key`. Long-running responses return a
workflow/job resource, not a hanging request.

### Proposed endpoints

```text
POST   /api/content-sources
GET    /api/content-sources/{source_id}
POST   /api/content-sources/{source_id}/import

POST   /api/scripts/generate
POST   /api/scripts/{script_id}/rewrite
PATCH  /api/scripts/{script_id}
POST   /api/scripts/{script_id}/approve
GET    /api/scripts/{script_id}/versions

POST   /api/workflows/ai-video
GET    /api/workflows/{run_id}
GET    /api/workflows/{run_id}/events
POST   /api/workflows/{run_id}/stages/{stage_key}/retry
POST   /api/workflows/{run_id}/cancel

POST   /api/content-items
GET    /api/content-items
GET    /api/content-items/{content_item_id}
PATCH  /api/content-items/{content_item_id}
POST   /api/content-items/{content_item_id}/targets

GET    /api/social/providers/capabilities
POST   /api/content-targets/{target_id}/schedule
POST   /api/content-targets/{target_id}/publish
POST   /api/content-targets/{target_id}/cancel

POST   /api/campaigns
GET    /api/campaigns
GET    /api/campaigns/{campaign_id}
POST   /api/campaigns/{campaign_id}/propose
POST   /api/campaigns/{campaign_id}/approve
POST   /api/campaigns/{campaign_id}/pause

GET    /api/calendar?from=...&to=...&platform=...&status=...
GET    /api/analytics/content/{content_item_id}
GET    /api/recommendations
POST   /api/recommendations/{recommendation_id}/accept
POST   /api/recommendations/{recommendation_id}/reject
```

Existing upload, YouTube import, standard plan, viral moments, render, project, artifact, social,
usage, and admin endpoints remain during migration.

## Frontend Route Map

### Keep

```text
/home
/projects
/templates
/auto-clip
/ai-editor
/ai-thumbnail
/schedule
/usage
/admin
/settings
```

### Add by milestone

| Route | Milestone | Purpose |
|---|---|---|
| `/script` | C | Generate, edit, version, and approve scripts |
| `/ai-video` | D | Prompt/script-to-video staged workflow |
| `/content/:contentItemId` | B/D | Universal item review and editor entry |
| `/youtube` | E | Clip-or-create YouTube workflow |
| `/campaigns` | F | Campaign list and approval state |
| `/campaigns/:campaignId` | F | Plan, items, rules, and review |
| `/calendar` | H | Month/week/list scheduling |
| `/analytics` | H | Provider-neutral metrics and recommendations |
| `/workflows/:runId` | D | Durable stage status and retry view |

### Create launcher

Use progressive disclosure by creator goal:

- **From video:** upload, YouTube, standard auto clip, viral clips.
- **With AI:** AI video, AI script, AI editor, AI thumbnail.
- **For platform:** YouTube Short, Instagram Reel, standard short.
- **Automate:** schedule, bulk schedule, campaign, automated channel.
- **Utilities:** audio extraction, video extraction, captions, thumbnails.

Unavailable workflows are hidden from ordinary production users or clearly labeled beta. The
launcher reads a backend capability/configuration response, not mock data.

### Frontend state direction

- Retain local reducer state for immediate editor interactions and undo/redo.
- Introduce a server-state/query layer for projects, content items, connections, workflow runs,
  and schedules.
- Use event streaming or bounded polling for stage progress with reconnect/backoff.
- Put entity IDs and selected tabs in typed URLs, not local storage alone.
- Add one application error boundary plus shared `ErrorState`, `EmptyState`, `LoadingState`,
  `SuccessState`, and `RetryAction` components.
- Save editor snapshots with version checks; resolve conflicts rather than silently overwriting.

## Milestone Plan

Complexity is a relative engineering estimate for one experienced full-stack engineer with
review support, excluding provider-verification wait time.

### Milestone A - current-product trust stabilization

**Complexity:** Medium, approximately 1-2 engineer-weeks.

- Add error code/status/retryability registry.
- Remove raw worker exception hints.
- Add React error boundary and shared state components.
- Audit signup/login/recovery/upload/import/transcription/AI/render/download/OAuth/scheduling/
  publishing/quota/storage errors.
- Replace duplicate social/account placeholder truth with API-backed state.
- Remove or hide obsolete `ScheduleModal`; make settings deployment-aware.
- Add focused backend, frontend, and browser tests for every changed failure path.

Gate: no major journey displays raw HTTP/provider/internal errors; every async click has visible
loading, success, disabled, empty, and retry behavior.

### Milestone B - universal content foundation

**Complexity:** High, approximately 3-5 engineer-weeks.

- Add new schema and RLS policies.
- Add content/source/script/target/workflow domain models and repositories.
- Add compatibility adapters for current projects and schedules.
- Implement serializable workflow stages and DB-first production job state.
- Introduce shared production rate limiting and worker leases.

Gate: current clipping E2E remains green and a content item survives API/worker restarts.

### Milestone C - AI Script Studio

**Complexity:** Medium, approximately 2-3 engineer-weeks.

- Extend the current `AIProvider` with structured script generation and rewrite.
- Add script versions, edits, approval, and route.
- Meter/cache calls and make provider/model configurable.
- Add schema, security, UX, and E2E tests.

Gate: a creator can use a custom or AI script, edit it, approve it, and resume later.

### Milestone D - AI Video pipeline

**Complexity:** Very high, approximately 6-10 engineer-weeks for an MVP.

- Add TTS, visual, music, and video-generation ports.
- Implement stage orchestration, partial retry, invalidation, and cost estimates.
- Start with one low-cost/free option per stage and existing FFmpeg assembly.
- Add editable project output, provenance, caption, and download flow.

Gate: script-to-video and prompt-to-video complete with one supported provider set, survive a
restart, and retry one failed stage without duplicating paid work.

### Milestone E - YouTube workspace

**Complexity:** High, approximately 3-5 engineer-weeks plus Google approval time.

- Combine clip-existing and create-new paths.
- Connect editor, thumbnail, metadata, target scheduling, and official publishing.
- Add unknown-outcome reconciliation and duplicate-safe upload.
- Complete real unlisted upload verification with a test channel.

Gate: official OAuth and an unlisted real upload are live verified; otherwise mark blocked.

### Milestone F - campaigns and automation

**Complexity:** Very high, approximately 5-8 engineer-weeks.

- Add campaigns, proposals, approvals, triggers/actions/conditions, and audit log.
- Default to approval for every item.
- Add per-workspace automation enablement, pause, and cost ceilings.

Gate: a campaign can propose, approve, generate, and schedule without unapproved publishing.

### Milestone G - provider capabilities

**Complexity:** Medium, approximately 2-3 engineer-weeks.

- Add capability metadata and provider-aware validation/UI.
- Remove platform-name assumptions from shared scheduler controls.
- Define future Facebook/TikTok/Bilibili/LinkedIn adapters without implementing them.

### Milestone H - calendar and analytics

**Complexity:** High, approximately 4-6 engineer-weeks plus platform review.

- Add month/week/list calendar, confirmed drag rescheduling, and target status.
- Add YouTube analytics first behind a separate least-privilege consent expansion.
- Store snapshots and create explainable, opt-in recommendations.

### Milestone I - specialist review and hardening

**Complexity:** Medium, approximately 2-4 engineer-weeks.

- UX/accessibility, frontend, backend, AI, security, AppSec, DevOps, API, evidence, performance,
  and reality-check reviews.
- Fix true defects and record false positives/not-relevant findings.

### Milestone J - release verification

**Complexity:** Medium/high, approximately 3-5 engineer-weeks plus provider approval time.

- Full CI, migration rehearsal, rollback, worker recovery, load and soak testing.
- Real-provider smoke suite separated from deterministic CI.
- Cross-browser and mobile visual QA with evidence.

## Test Strategy

### Deterministic CI

- Contract tests for every provider and stage.
- Tenant/IDOR/RLS tests for every new table and endpoint.
- Idempotency and duplicate-publish tests.
- Worker lease, restart, retry, cancellation, and partial-stage recovery tests.
- Upload/URL/asset SSRF and validation tests.
- Structured AI response, malformed response, timeout, and fallback tests.
- React accessibility, failure-state, reconnect, and route tests.
- Browser E2E for email signup, upload, standard clip, AI recommendation, script, AI video with
  controlled adapters, thumbnail, download, schedule, calendar, and campaign approval.

### Real-provider smoke tests

Run separately with controlled accounts and budgets:

- Supabase auth and password email delivery.
- YouTube import.
- NVIDIA/Groq structured output.
- Private R2 upload/download/expiration/restart recovery.
- YouTube OAuth, refresh, unlisted upload, reconciliation, and disconnect.
- Instagram OAuth and test publishing.
- Any enabled TTS/stock/generation provider.

A provider is `LIVE VERIFIED` only after its official API returned success and the resulting
resource was inspected in the provider account.

## Security Plan

Threat-model these boundaries before each milestone:

- Browser session, Supabase callback, and refresh-token exchange.
- OAuth state, scopes, refresh tokens, revocation, and reconnect.
- Workspace IDs and object ownership.
- Uploads, remote URLs, DNS rebinding, decompression and media bombs.
- FFmpeg arguments, paths, and generated filter expressions.
- AI prompt/reference injection and unsafe model-selected actions.
- Worker leases, idempotency, quota bypass, and race conditions.
- Provider webhooks, replay, and unknown outcomes.
- Campaign permissions and automatic publishing.
- Admin/service-role access and logs.

Required controls include PKCE where available, encrypted tokens, no secrets in React, CSP,
strict origins, signed webhooks, immutable audit records, scoped providers, safe structured
errors, tenant composite foreign keys, RLS tests, signed URLs, and explicit automation approval.

## Provider and API-Key Requirements

| Capability | Preferred starting provider | New secret | Free/low-cost path | Replaceability |
|---|---|---|---|---|
| Text intelligence/script | Existing NVIDIA; Ollama local fallback | No new secret | NVIDIA development endpoint or local Ollama | High through `AIProvider` |
| Transcription | Existing Groq; Faster-Whisper local | No new secret | Local fallback and transcript cache | High |
| Final assembly | Existing local FFmpeg | None | Local CPU/GPU | High at worker layer |
| TTS | Local Piper/approved local engine first | None | Local compute | High through `TTSProvider` |
| Stock visuals | Pexels/Pixabay-style provider after legal review | Provider key | Usually limited free API | High through `VisualAssetProvider` |
| Generated visuals/video | Disabled by default until selected | Provider key | Development credits may exist | High through provider ports |
| Music | User upload/license-safe library first | None | User-owned/local tracks | High through `MusicProvider` |
| Database/auth | Existing Supabase | Existing secrets | Free development plan | Moderate behind existing ports |
| Media storage | Existing private R2/S3 | Existing secrets | R2 free allowance | High through `StorageProvider` |
| YouTube publish | Official Google app | Existing client credentials | API quota, no proxy | Provider-specific adapter |
| Instagram publish | Official Meta app | Meta app credentials | API access subject to Meta review | Provider-specific adapter |
| Analytics | Official YouTube first | Consent scope expansion | API quota | High through `AnalyticsProvider` |

Do not add a paid LLM solely because a reference repository supports it. Ask before enabling a
provider that can create material recurring cost.

## Expected Operating Costs

These are planning estimates checked against official pricing pages on 2026-08-31. Provider
pricing and free allowances can change; re-check before production enablement.

### Fixed foundation

- **Supabase:** development can remain on the free plan. A production baseline is currently
  approximately **$25/month** for Pro with the included default compute credit. Database,
  bandwidth, MAU, backup, and log overages are usage-based.
- **R2:** Standard storage currently includes 10 GB-month, 1 million Class A operations, and
  10 million Class B operations monthly. Beyond that, storage is approximately **$0.015 per
  GB-month**, with operation charges and no direct R2 egress fee.
- **API/worker compute:** not fixed by this architecture. Video rendering is the dominant cost.
  Start with one API instance and one separately scalable render worker; benchmark CPU versus GPU
  cost per completed minute before selecting instance size.

Official references:

- Supabase: `https://supabase.com/pricing`
- Cloudflare R2: `https://developers.cloudflare.com/r2/pricing/`

### Variable AI/media cost

- NVIDIA currently advertises free serverless endpoints for development. Production terms and
  limits must be confirmed before relying on that path.
- Groq transcription is usage-priced; retain cache and local fallback. The current public pricing
  page should be checked from the provider console at implementation time because a stable rate
  was not available in the audited page content.
- Local TTS, FFmpeg, and user-owned music avoid per-call API charges but consume worker compute.
- Stock media can start with a reviewed free API, but provenance and terms are mandatory.
- AI image/video generation can dominate per-video cost. Keep it disabled until a provider,
  budget ceiling, quality benchmark, and explicit approval are selected.

### Cost controls

- Estimate cost before every workflow and show it before a paid run.
- Reserve usage atomically before work; commit actual usage or refund on failure.
- Cache transcripts, scripts, assets, and completed stage outputs by content hash.
- Retry only the failed stage.
- Set workspace monthly caps and per-run maximums.
- Record provider/model, unit quantity, estimated cost, and actual cost without storing secrets.
- Do not auto-fallback from a free/local provider to a paid provider without explicit policy.

## Operational Requirements

- API health checks dependency reachability without making paid calls.
- Worker readiness verifies FFmpeg/FFprobe, storage, DB, and queue connectivity.
- Provider readiness reports configured/unconfigured/degraded without exposing values.
- Structured logs use request, workflow, stage, job, workspace, and provider correlation IDs.
- Metrics include queue age, p50/p95 stage duration, success/error rate, retry count, render
  throughput, signed-URL failures, and cost per completed content minute.
- Deployments drain workers, expire leases safely, and reconcile unknown publish outcomes.
- Every migration has a rollback/compatibility plan and is rehearsed on a production-like copy.

## Principal Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Roadmap breadth | Unfinished product surfaces | Milestone gates; hide unavailable workflows |
| Provider approval delays | Social/analytics blocked | Separate local completion from live verification |
| Video compute cost | Poor margins and latency | Stage benchmark, hardware profiles, quotas, cache |
| Duplicate publishing | Public trust incident | Idempotency, reconciliation, target state machine |
| AI quality variability | Low-value content | Structured schemas, editable output, approval, evals |
| Asset licensing | Legal exposure | Provenance, allowlisted providers, terms review |
| Queue restart/races | Lost or duplicate work | DB jobs, leases, heartbeats, immutable stage output |
| Tenant leakage | Critical security incident | RLS, composite FKs, IDOR tests, service-role filters |
| Provider sprawl | Maintenance/cost explosion | One provider per stage initially, strict ports |
| UI complexity | Creator confusion | Goal-based launcher and progressive disclosure |

## Release Definition

A milestone is complete only when:

1. Its API and data contracts are documented and migration-safe.
2. Focused backend, frontend, type, lint, build, and browser checks pass.
3. Error, loading, empty, success, disabled, retry, and cancellation states are visible.
4. Tenant isolation, authorization, idempotency, and secret boundaries are tested.
5. Performance and cost are measured for the new path.
6. Real-provider functionality is marked live only after a controlled provider smoke test.
7. User-facing behavior has evidence from a normal browser journey.

## Milestone B Implementation: Universal Content Architecture

**Implementation status:** complete locally on 2026-09-01. The forward-only migration is
validated statically and by automated tests but has not been applied to live Supabase by this
milestone.

### Actual domain relationships

```text
Project (workflow aggregate)
  |
  +-- SourceAsset (media metadata + private storage key)
  |      |
  |      +-- ContentSource (video_upload or youtube_url origin)
  |
  +-- ContentSource (script, ai_script, or ai_prompt origin)
         |
         +-- ContentItem (provider-neutral publishable creative)
                |
                +-- Artifact references (video, thumbnail, audio)
                |
                +-- PlatformTarget (independent platform intent/state)

ScheduledPost remains the current durable publishing runtime.
```

The new content domain is implemented behind `ContentRepository` and `ContentService`. Local
development uses an atomic workspace-scoped JSON repository. Supabase mode uses PostgREST with
the caller's access token, explicit workspace filters, row-level security, and composite tenant
foreign keys.

### Canonical source of truth

| Concern | Canonical record | Compatibility relationship |
|---|---|---|
| Workflow/project lifecycle | Existing `projects` / project manifest | `ContentSource` and `ContentItem` reference the project; they do not replace it |
| Uploaded/downloaded media | Existing `source_assets` plus private object storage | A media `ContentSource` reuses the source asset UUID and references `source_asset_id` |
| Clip boundaries | Existing `ClipSegment` request and render job | Standard and viral selection continue to feed the same renderer |
| Rendered binary files | Existing `artifacts` plus private object storage | A rendered clip `ContentItem` reuses the clip artifact UUID and references `video_artifact_id` |
| Creative copy and publishable identity | New `content_items` | Does not duplicate video bytes or ZIP files |
| Future per-platform intent | New `platform_targets` | One content item can have independently retryable targets |
| Current publishing execution | Existing `scheduled_posts` | Remains authoritative until a later scheduling migration explicitly links target execution |
| Social credentials | Existing `social_connections` | Targets may reference a same-workspace connection; credentials remain encrypted and server-only |

No existing production rows are rewritten or deleted. Existing upload and YouTube import paths
create a compatibility `ContentSource` after their current source registration succeeds. Render
job polling creates one `ContentItem` per clip artifact after artifact ownership is registered.
Reusing current UUIDs makes synchronization idempotent and avoids mapping tables or duplicate
media metadata.

### Migration and rollout strategy

1. Apply `202609010001_universal_content_architecture.sql` after all earlier migrations on a
   production-like database and inspect every constraint validation result.
2. Deploy the compatible API after the migration. Existing routes remain unchanged.
3. Existing historical records can be populated lazily when a source/job is opened, or by a
   future idempotent backfill using the same source/artifact UUID rule.
4. Keep `scheduled_posts` authoritative until a later migration can preserve queued/published
   state and provider idempotency evidence.
5. Do not remove `source_assets`, `artifacts`, project manifests, or `ClipSegment`; each still
   owns a distinct concern.

The migration creates only new tables and indexes. It includes workspace ownership, RLS,
composite tenant foreign keys, safe cascade/restrict behavior, JSON size/type checks, immutable
relationship-column grants, and indexes for project, source, target-status, and scheduling
lookups. It performs no destructive update, delete, or backfill.

### Capability contract

`SocialProvider.capabilities()` now reports video upload, short-form publishing, scheduling,
thumbnail publishing, metadata editing, analytics, supported aspect ratios, optional configured
duration limits, and supported content types. YouTube and Instagram expose only behavior the
current adapters implement. The Schedule page reads this endpoint before enabling a platform;
Facebook, TikTok, Bilibili, and LinkedIn are valid future target values but have no provider
adapter and cannot reference a social connection yet.

### Security review

| Classification | Finding | Resolution |
|---|---|---|
| TRUE DEFECT | Local inserts were initially evaluated as updates and rejected | Fixed by separating new inserts from guarded tenant updates; regression tested |
| TRUE DEFECT | Generic upsert could update ownership or relationship columns in hosted mode | Replaced with insert-or-safe-PATCH behavior; migration revokes table updates and grants named mutable columns only |
| TRUE DEFECT | Unknown request fields could be silently ignored | New content and target mutation contracts use `extra="forbid"`; mass-assignment regression test added |
| TRUE DEFECT | Cross-workspace UUID knowledge could create hidden relationships | Service checks, explicit workspace queries, RLS, and composite `(id, workspace_id)` foreign keys enforce isolation |
| TRUE DEFECT | Unbounded arbitrary metadata could exhaust storage or complicate provider state | API/service depth, entry, string, type, and 16 KB limits plus PostgreSQL JSON type/size checks |
| IMPROVEMENT | Future targets are representable before providers exist | Allowed only without provider credentials; actual publishing remains unavailable until an official adapter exists |
| NOT RELEVANT | Remote URL fetching through the content API | `external_url` is stored as origin metadata only; this service never fetches it |
| FALSE POSITIVE | New content models create a second renderer | They do not execute rendering; both standard and AI selections retain the existing render pipeline |

IDOR tests cover cross-workspace reads and references. API clients cannot set workspace, owner,
project, source relationship, artifact relationship, provider post ID, retry count, or error
fields through public patch contracts. Provider publishing remains outside `ContentService`.

## Immediate Next Work

Begin Milestone C, AI Script Studio, only after the Milestone B migration has been rehearsed and
the complete backend/frontend/build/browser gates remain green. Continue using `ContentSource`
and `ContentItem`; do not create a separate script-only project or rendering engine.
