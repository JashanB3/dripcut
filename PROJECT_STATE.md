# DripCut — Historical Project State

This July snapshot is historical. For the current launch state use
[docs/launch-checklist.md](docs/launch-checklist.md).

**Version:** 1.0.0rc1 (release candidate)
**Checkpoint date:** 2026-07-27 (session 5)
**Status:** Feature-complete. All planned modules exist, are wired, and are covered by tests.

## Build gate

```
python -m compileall -q src   → clean
ruff check src tests          → All checks passed
node --check app.js           → clean
pytest                        → 222 passed
python -m build --wheel       → dripcut-1.0.0rc1-py3-none-any.whl
dripcut doctor                → 20 checks, correct verdict
dripcut up                    → serves all 10 pages
```

## 1. Complete

| Layer | Path | Notes |
|---|---|---|
| Packaging | `pyproject.toml`, `Makefile`, `LICENSE`, `.gitignore` | src-layout, console script, plugin entry points |
| Utilities | `utils/` | timecode, fs, text, concurrency |
| Core | `core/` | settings, paths, errors, logging, events, container, bootstrap |
| Models | `models/` | media, clip, transcript, subtitle, job, project |
| FFmpeg engine | `engines/ffmpeg/` | runner with progress + cancellation, cached probe, filters |
| Video engine | `engines/video/` | 15 operations, quality presets, stream-copy fast path |
| Split engine | `engines/split/` | 6 modes behind one interface |
| AI engine | `engines/ai/` | Ollama client, Whisper wrapper, prompts, analysis with fallback |
| Subtitle engine | `engines/subtitle/` | 6 presets, 4 formats, karaoke |
| Export engine | `engines/export/` | 10 presets, 2-worker queue, persisted history |
| Services | `services/` | 7 services |
| Plugins | `plugins/` | api, loader, 3 built-ins |
| CLI | `cli/` | 9 subcommands, 20-check doctor |
| UI shell | `ui/app.py`, `theme.py`, `assets/`, `components/` | theme, router, palette, shortcuts |
| UI pages | `ui/pages/` | all 10 |
| **Tests** | `tests/` | **222 tests, 11 files** |
| **Docs** | `ARCHITECTURE`, `INSTALL`, `DEVELOPMENT`, `PLUGIN_GUIDE`, `CHANGELOG` | |

### Test coverage by file

| File | Tests | Covers |
|---|---:|---|
| `test_ai.py` | 27 | transcript model, caching, prompts, degradation |
| `test_cli.py` | 28 | parser, doctor, config commands |
| `test_export.py` | 25 | presets, queue lifecycle, worker limit, real renders |
| `test_ffmpeg.py` | 23 | filters, encoder args, probe |
| `test_split.py` | 21 | split maths, parsing, real rendering |
| `test_subtitles.py` | 25 | presets, cues, all four formats |
| `test_workspace.py` | 21 | all 9 tools, guards, end-to-end trim |
| `test_batch.py` | 14 | scanning, validation, batch job |
| `test_plugins.py` | 13 | discovery, lifecycle, broken-plugin resilience |
| `test_projects.py` | 13 | full CRUD on disk |
| `test_settings.py` | 12 | defaults, hydration, env overrides, persistence |

## 2. Remaining

| Item | Status |
|---|---|
| `scripts/install.sh` | ⬜ optional convenience wrapper; the documented pip flow works |
| Signed macOS bundle | ⬜ out of scope for RC1 |

## 3. Verified in this environment

Executed, not assumed:

- 222 tests pass, including real FFmpeg renders against a generated sample.
- All 10 pages built in a live Blocks tree; every handler on every page invoked
  through both its guard path and its success path. Zero failures.
- Server launched: 599,108 bytes served, nav 10/10, primary buttons 10/10,
  51 palette commands, queued jobs completed and wrote files to disk.
- `pip install -e .` → `dripcut doctor` → `dripcut up` all work from a clean shell.

## 4. NOT verified — stated plainly

- **Whisper transcription end to end.** Model weights need `huggingface.co`, which
  is outside this container's allowed domains. Covered only through cache, guard and
  error paths.
- **Ollama analysis end to end.** No server can run here. Highlights, hooks, titles,
  summaries and chapters are covered through their fallback and guard paths; the
  heuristic fallback *is* tested against a dead endpoint.
- **Browser behaviour.** No headless browser. The palette, shortcuts, sidebar resize
  and theme flip are verified as far as payload delivery, not execution.
- **VideoToolbox encoding.** Detection is tested; the Apple Silicon encode path is not.
- **Windows.** Implemented and pathed, never run.

## 5. Contracts for future work

- Layering: `utils → core → models → engines → services → plugins → ui → cli`.
- Pages never import engines; everything arrives via `PageContext`.
- Handlers never raise: wrap service calls in `safe_call`.
- A page is one `gr.Column`; register it in `build_pages()` and nothing else.
- Primary button id is `dc-primary-<page>` so ⌘↵ finds it.
- Long work goes on the queue (2 workers), progress over the event bus.
- No browser storage; durable preferences in `settings.json`.
- Offline: the only socket is Ollama on `127.0.0.1:11434`.
- Class names come from `styles.css`; add the rule before using it.
