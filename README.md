# DripCut

**Local video toolkit with AI on board.**

A desktop video-processing suite that runs entirely on your machine. Split, trim, convert,
caption, and export video without uploading a single frame anywhere. Transcription runs on
Faster-Whisper; analysis runs on Ollama. No cloud APIs, no accounts, no per-minute billing.

AI is one module, not the point. Every video tool works with AI switched off.

---

## Status

> **Release candidate 1.0.0rc1.** Feature-complete, 222 tests passing, fully
> documented. See **[PROJECT_STATE.md](PROJECT_STATE.md)** for the inventory and
> **[CHANGELOG.md](CHANGELOG.md)** for what is and is not verified.

| | |
|---|---|
| Version | `1.0.0rc1` |
| Files written | 83 under `src/` (~11,600 lines Python, 863 CSS, 622 JS) |
| Compile | ✅ `python -m compileall src` clean |
| Imports | ✅ 78/78 modules, zero failures |
| Lint | ✅ `ruff check src` — all checks passed |
| Client script | ✅ `node --check app.js` clean |
| Packaging | ✅ builds `dripcut-1.0.0-py3-none-any.whl` |
| Launchable | ✅ `dripcut up` serves all ten pages |
| Pages | ✅ 10 of 10, every handler executed |
| Tests | ✅ 222 passing |

**The ten pages:** Dashboard, Workspace (9 tools), Split (6 modes), AI Studio,
Subtitle Studio, Batch, Exports (live queue), Projects, Plugins, Settings.

**Documentation:** [ARCHITECTURE](ARCHITECTURE.md) · [INSTALL](INSTALL.md) ·
[DEVELOPMENT](DEVELOPMENT.md) · [PLUGIN_GUIDE](PLUGIN_GUIDE.md) ·
[CHANGELOG](CHANGELOG.md)

**Not yet verified on real hardware:** Whisper transcription and Ollama analysis.
Both are written against the engine APIs and covered through their cache, guard and
fallback paths, but the build environment cannot download a Whisper model or run
Ollama. VideoToolbox detection is tested; the encode path is not.

## Requirements

- macOS (tuned for Apple Silicon; VideoToolbox is used when present) or Linux
- Python 3.10+ — developed against 3.13
- FFmpeg and FFprobe on `PATH`
- [Ollama](https://ollama.com) with a small local model, for AI features only:
  ```bash
  ollama pull qwen2.5:3b
  ```

Ollama is optional. Without it, AI features report themselves unavailable and everything
else keeps working.

## Install

```bash
git clone <repo> dripcut && cd dripcut
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This registers a global `dripcut` command via `[project.scripts]`.

## Usage

```bash
dripcut                                   # launch the app at http://127.0.0.1:7999
dripcut up --port 8080 --no-browser       # launch elsewhere, don't open a browser
dripcut doctor                            # 20 environment checks with fixes
dripcut info video.mp4                    # probe a file, or omit it for paths
dripcut split video.mp4 --mode scene      # plan and render clips
dripcut split video.mp4 --length 30 --dry-run
dripcut transcribe video.mp4 --format srt --show 12
dripcut export video.mp4 --preset "Vertical 1080x1920"
dripcut plugins --disable loudness
dripcut config --set server.port=8080
```

Start with `dripcut doctor`. It checks Python, FFmpeg, FFprobe, VideoToolbox,
Faster Whisper, Ollama, folders, write permissions and free space, and every failure
comes with the command that fixes it.

## Keyboard

| Key | Action |
|---|---|
| `⌘K` | Command palette |
| `⌘\` | Collapse or show the sidebar |
| `⌘⇧T` | Switch theme |
| `⌘↵` | Run the current page's primary action |
| `J` `K` `L` | Previous · play · next |
| `?` | Shortcut list |
| `esc` | Close overlays |

Click any timecode to copy it. Drag the sidebar's trailing edge to resize it;
double-click to reset.

## Features

**Video tools** — upload, preview, trim, cut, split, merge, crop, resize, rotate, flip,
compress, convert container, change FPS, change resolution, speed adjust, extract audio,
extract frames, create GIF, image and text watermarks, proxy generation, thumbnails, batch
processing.

**Split modes** — fixed length · custom length (15/30/45/60s, 2min, 5min) · scene detection ·
silence detection · explicit timestamps · embedded chapters · AI highlight. Switching modes
re-plans without re-rendering.

**AI module** — Whisper transcription with disk caching, transcript viewer and editor,
highlight detection, hook detection, funny / educational / story-peak focus rubrics, best-clip
finder, title suggestions, summaries, chapter suggestions. Every LLM call has a heuristic
fallback, so a missing model degrades quality rather than breaking the feature.

**Subtitles** — 6 caption presets (Clean, Punch, Plate, Signal, Documentary, Karaoke), cue
re-flow from word-level timings, SRT / VTT / ASS / TXT output, soft-attach or burn-in.

**Export** — 10 presets including vertical 1080×1920, square, landscape, ProRes master, WebM
VP9, MKV passthrough, GIF, and audio-only. Threaded queue with live progress, cancellation,
and persisted history.

**Plugins** — drop a Python file in `~/Library/Application Support/DripCut/plugins/` or ship
an entry point in the `dripcut.plugins` group. Plugins can add tools, split strategies, and
caption styles. Three ship built in: contact sheet, loudness tools, social caption pack.

## Architecture

Clean layering, enforced by convention and documented in `src/dripcut/__init__.py`:

```
utils → core → models → engines → services → plugins → ui → cli
```

No inner layer imports an outer one. Everything is resolved through a DI container built in
`core/bootstrap.py`. Long operations become `Job` objects on a two-worker queue and report
progress over an event bus, so the UI never blocks and never owns business logic.

```
src/dripcut/
├── core/       settings · paths · errors · logging · events · container · bootstrap
├── models/     media · clip · transcript · subtitle · job · project
├── engines/    ffmpeg · video · split · ai · subtitle · export
├── services/   media · project · ai · split · subtitle · export · notifications
├── plugins/    api · loader · builtin/
├── ui/         theme · assets · components/ · pages/  (10 pages)
└── cli/        launcher · doctor · subcommands
```

Third-party media and AI libraries are imported lazily inside functions. Startup stays fast,
and a missing optional dependency surfaces as a friendly message instead of an import crash.

## Design

Not the default Gradio look. Midnight-ink slate-blue base (`#111524`) with electric-blue to
violet accents (`#5B8CFF` → `#7A5BFF`), mint for success, amber for warnings, plus a full
light theme. System font stacks only — no web fonts, because the app has to work offline.

The signature element is the **sprocket rail**: a filmstrip-notched progress and segment strip
that carries monospaced timecodes as a recurring typographic motif. Keyboard focus is always
visible and `prefers-reduced-motion` is respected.

## Development

```bash
make install     # pip install -e .
make dev         # pip install -e ".[dev]"
make lint        # ruff check src
make fmt         # ruff format
make type        # mypy
make test        # pytest              (suite not written yet)
make run         # dripcut up
make clean
```

## Configuration

Settings live at `~/Library/Application Support/DripCut/settings.json` (macOS) and can be
overridden by environment variables:

### Hosted transcription

The web processing backend uses Groq `whisper-large-v3-turbo` as its primary speech
provider when `GROQ_API_KEY` is configured. Credentials are read only by Python on the
backend; never prefix the key with `VITE_`. If Groq is unavailable, the existing local
Faster-Whisper provider remains the fallback.

```bash
cp .env.example .env
# Set GROQ_API_KEY in .env, then restart the backend.
```

Transcripts are normalized and cached by source-content SHA-256, language, provider,
model, and provider version. Re-importing the same bytes under a different filename still
reuses the transcript.

Run the repeatable pipeline benchmark with an approximately ten-minute spoken video:

```bash
source .venv/bin/activate
python scripts/benchmark_pipeline.py /absolute/path/to/spoken-video.mp4 \
  --clip-duration 30 --count 3 --output-format portrait --runs 2
```

The command reports source import, audio extraction, provider API, clip render, subtitle
preparation, caption encoding, ZIP, and total times. The second run reports whether the
transcript cache was hit. It exits with `CONFIGURATION REQUIRED` rather than presenting a
local run as a Groq benchmark when the backend credential is missing.

| Variable | Default |
|---|---|
| `DRIPCUT_HOME` | `~/Library/Application Support/DripCut` |
| `DRIPCUT_OUTPUT` | `~/Movies/DripCut` |
| `DRIPCUT_PORT` | `7999` |
| `DRIPCUT_HOST` | `127.0.0.1` |
| `DRIPCUT_THEME` | `dark` |
| `DRIPCUT_TRANSCRIPTION_PROVIDER` | `groq` |
| `DRIPCUT_GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` |
| `DRIPCUT_WHISPER_MODEL` | `small` |
| `DRIPCUT_OLLAMA_MODEL` | `qwen2.5:3b` |
| `DRIPCUT_OLLAMA_HOST` | `http://127.0.0.1:11434` |
| `DRIPCUT_MAX_WORKERS` | `2` |
| `DRIPCUT_LOG_LEVEL` | `INFO` |

Logs are written to `<DRIPCUT_HOME>/logs/dripcut.log` with rotation.

## Render deployment

The repository includes a production `Dockerfile` for the Python processing API. It
installs FFmpeg/FFprobe, yt-dlp with EJS support, and Node 22, runs as a non-root user,
and binds Uvicorn to Render's `PORT`. The React frontend is deployed separately as a
static site.

Build and run the same image locally:

```bash
docker build -t dripcut-api .
docker run --rm -p 10000:10000 --env-file .env -e PORT=10000 dripcut-api
curl http://127.0.0.1:10000/api/health
```

Create a Render **Web Service** with these settings:

| Setting | Value |
|---|---|
| Runtime | Docker |
| Branch | `main` |
| Root directory | repository root (leave blank) |
| Dockerfile path | `./Dockerfile` |
| Health check path | `/api/health` |

Configure these backend environment variables in Render, not in the image or repository:

| Variable | Recommended value |
|---|---|
| `GROQ_API_KEY` | Render secret containing the Groq key |
| `DRIPCUT_TRANSCRIPTION_PROVIDER` | `groq` |
| `DRIPCUT_ALLOWED_ORIGINS` | exact deployed frontend origin, such as `https://dripcut.example` |
| `DRIPCUT_MAX_WORKERS` | `1` for a 512 MB instance |
| `DRIPCUT_HOME` | `/var/lib/dripcut` |

Set `VITE_API_BASE_URL=https://<your-backend>.onrender.com` on the frontend static site
before building it. Do not expose `GROQ_API_KEY` through a `VITE_` variable.

Render instances without a persistent disk have ephemeral storage. Uploaded/imported
sources, rendered clips, transcript caches, ZIP archives, projects, job history, and
schedules stored under `DRIPCUT_HOME` can disappear after a restart or redeploy. This is
acceptable for a download-first beta, but durable multi-user deployment requires object
storage and a persistent database. The 512 MB tier should run one render job at a time;
Groq transcription is strongly recommended because local Faster-Whisper can exceed that
memory budget.

## Privacy

Verified against Gradio 6.20.0; the UI asks each Gradio signature what it accepts, so
4.x and 5.x work too.

DripCut sends extracted speech audio to Groq only when hosted transcription is configured
and captions/transcription are requested. It may also contact YouTube during an explicitly
requested import and Ollama for enabled local analysis. Backend credentials are never sent
to the React application or returned by diagnostics. Telemetry remains disabled.

## Licence

MIT — see [LICENSE](LICENSE).
