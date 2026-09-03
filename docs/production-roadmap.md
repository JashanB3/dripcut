# Production Roadmap Status

This file tracks the execution state of the 30-day production-readiness roadmap. Status values are
`pending`, `in_progress`, `blocked`, and `complete`.

| Day | Task | Priority | Status | Tests | Verification | Commit SHA | Remaining risk |
|---:|---|---|---|---|---|---|---|
| 0 | Repository safety and baseline | P0 | complete | 360 backend, 19 frontend, isolated E2E | Audit completed 2026-09-02; Day 1 branch created | pending Day 1 commit | Current product work predates a clean remote baseline |
| 1 | Credential security | P0 | blocked | 4 scanner tests, 364 backend, 19 frontend, isolated browser E2E, Docker build and health | Working tree, full Git history, compiled bundle, and exact ignored-value scans passed 2026-09-04 | `5395a05` | Externally shared provider credentials must be rotated and the previous values proven unusable |
| 2 | Clean Git baseline and CI | P0 | pending | Not started | Not started | pending | Current implementation is not remote/CI verified |
| 3 | Python and mypy alignment | P1 | pending | Not started | Not started | pending | Mypy/NumPy Python-target mismatch |
| 4-6 | Production deployment | P0 | pending | Not started | Not started | pending | No production frontend/API environment |
| 7-9 | Durable background execution | P1 | pending | Not started | Not started | pending | Process-local queue and scheduler state |
| 10-12 | Real email and OAuth | P1 | pending | Not started | Not started | pending | Email and social providers not fully live verified |
| 13-15 | Social publishing | P1 | pending | Not started | Not started | pending | No real YouTube/Instagram publishing proof |
| 16-18 | Storage lifecycle and recovery | P1 | pending | Not started | Not started | pending | Deletion and scheduler artifact recovery gaps |
| 19-21 | Security hardening | P1 | pending | Not started | Not started | pending | Headers, shared state, legacy grants |
| 22-24 | Observability and operations | P2 | pending | Not started | Not started | pending | No external monitoring or alerting |
| 25-27 | Browser and mobile E2E | P2 | pending | Not started | Not started | pending | Desktop Chromium is the only browser E2E |
| 28-30 | Load, release, and beta gate | P0 | pending | Not started | Not started | pending | Production gate not evaluated |

## Day 1 Evidence

- `.env` and its variants are ignored; only the placeholder-only `.env.example` is tracked.
- The scanner covers the current repository, every reachable Git blob, frontend secret references,
  service-role JWT claims, private-key material, and recognizable provider credentials.
- The production frontend bundle passed both pattern scanning and exact comparison against the
  ignored backend `.env` without disclosing any values.
- CI now performs full-history scanning and scans the production frontend bundle.
- The production Docker image was built without secrets and became healthy when the ignored
  backend environment was injected at runtime.
- The production image correctly failed closed when required encryption and Supabase runtime
  configuration were absent.

Day 1 cannot be marked complete until every previously exposed provider credential has been
rotated in its provider dashboard and the superseded value has been confirmed unusable. Repository
hardening is verified, but source-code changes cannot revoke an external credential.
