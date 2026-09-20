# DripCut Git regression audit

Audit date: 20 September 2026. Branch: `launch/production-ready`.

## Findings

### Clip-count explosion

- Good behavior: `5680c45` / `fe677a6`
  - displayed a number-of-clips stepper and MAX action;
  - defaulted long sources to at most five clips;
  - preserved the chosen count when duration changed.
- Regression: `b50ef22` (`Move MVP processing profile to GCE deployment`)
  - removed the count control;
  - changed maximum count from floor to ceiling;
  - automatically selected the entire source after import and every duration change.

For a 635-second source at 30 seconds this silently changed the default from five clips
to 22 clips. The recovery restores the count control and five-clip default while keeping
the useful partial final-clip behavior.

### Fast mode changed the promised output

- `8ddb79d` introduced a keyframe stream-copy path capable of near-instant clipping.
- That path only works when output format is `source`, captions are off, and requested
  boundaries are keyframes.
- `DRIPCUT_SUPER_FAST_CLIPS=1` forcibly changes portrait requests into source-framed
  clips. Production correctly had this disabled because the UI promises portrait output.

This optimization is retained for honest source-format jobs but is not used to fake a
fast portrait result. Portrait clips still receive the crop/reframe requested by the user.

### YouTube reliability accumulated slow fallbacks

- `bc2837d`, `d93ff57`, `6e1fa45`, `29d21ab`, `b3ffa74`, and `4fe997a` added useful
  extraction recovery paths, PoT support, and an operator cookie jar.
- In the current GCE region, the public paths are consistently bot-challenged while the
  configured cookie strategy succeeds.
- The cookie strategy remained last, so every successful import first paid for four
  predictable failures.
- The format selector allowed 1080p and 60-fps sources despite a 720p/30-fps production
  render profile.

The recovery tries the configured known-working strategy first, remembers the last
successful strategy in-process, and caps acquisition at 720p H.264/MP4 where available.
Surplus frames are discarded before the expensive portrait scale so a 60-fps-only source
does not double filter and encode work. All bounded public fallbacks remain available if
the cookie strategy fails.

### Progress polling became storage-bound

- The durable queue correctly persists accepted and terminal jobs.
- After the R2-backed state store was introduced, live FFmpeg progress also performed a
  synchronous object-store upload while holding the queue lock every two seconds.
- Job status requests waited behind that lock and measured 0.86–3.69 seconds during a
  single render, even though health checks stayed near 2 ms.
- The frontend then waited another 1.5 seconds after each completed request, producing a
  2.4–5.2 second effective refresh cadence.

The recovery keeps frequent progress checkpoints on the VM's persistent volume, uploads
remote queue state at lifecycle transitions, and uses a non-overlapping one-second UI
poll cadence.

### Restart status mismatch

- The queue already converts interrupted active jobs to retryable `WORKER_RESTARTED`
  failures.
- Project manifests could still say `processing`, so project cards appeared stuck after
  a worker restart.

Project responses now reconcile `processing`/`importing` cards with the latest terminal
job status, preventing a recovered failed job from being presented as still active.

## Preserved behavior

- Progressive per-clip registration and downloads.
- R2 durability for sources, artifacts, manifests, and queue lifecycle state.
- Exact portrait center crop and 720p/30-fps output.
- Captions-off fast path and captions-on single-pass rendering.
- Bounded YouTube fallbacks and normalized customer-safe errors.
- Existing tenant authorization, rights confirmation, and idempotency.
