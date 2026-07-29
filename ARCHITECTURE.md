# Architecture

DripCut is a local video toolkit. It runs as a Gradio app on `127.0.0.1`, shells out
to FFmpeg for media work, and talks to Whisper and Ollama on the same machine. There
is no server component and no network dependency after install.

## The one rule

Layers are ordered, and no inner layer imports an outer one:

```
utils → core → models → engines → services → plugins → ui → cli
```

Read that as "things that know less" on the left. `utils` knows nothing about
DripCut; `cli` knows everything. If you find yourself wanting `engines` to import
from `services`, the logic belongs in the service.

| Layer | Owns | Never does |
|---|---|---|
| `utils/` | Timecodes, filesystem helpers, text wrapping, cancel tokens | Import anything from DripCut |
| `core/` | Settings, paths, errors, logging, events, DI container, bootstrap | Touch media |
| `models/` | `MediaInfo`, `Segment`, `SplitPlan`, `Transcript`, `CaptionStyle`, `Job`, `Project` | Do I/O beyond its own JSON |
| `engines/` | FFmpeg invocation, encoding, split strategies, Whisper, Ollama, subtitles, the queue | Know that a UI exists |
| `services/` | Use cases: import media, plan a split, transcribe, queue an export | Build FFmpeg arguments by hand |
| `plugins/` | Third-party extension points | Reach into engines directly |
| `ui/` | Gradio composition, pages, components, theme | Contain business logic |
| `cli/` | Argument parsing, terminal rendering, exit codes | Contain business logic |

## Dependency injection

There is exactly one composition root: `core/bootstrap.py`. It constructs every
object once, in dependency order, and registers it in a `ServiceContainer`.

```python
from dripcut.core.bootstrap import build_container

container = build_container()          # loads settings, wires everything
plan = container.split.plan(media, "scene")
```

The container is a keyed registry with typed properties for the common services:

```python
container.settings   container.events    container.paths
container.media      container.video     container.split
container.ai         container.subtitles container.export
container.projects   container.notifications  container.plugins
container.resolve("queue")   # engine-level objects use string keys
```

Why a container rather than module-level singletons: tests build a container
against a temporary home in one line, and nothing has to be monkeypatched. Every
test in `tests/` does exactly that.

Adding a service means editing one function. If you have to hunt for import sites,
something has gone wrong.

## Engines

Engines are stateless-ish workers that know how to do one thing well.

**`engines/ffmpeg/`** — `FFmpegRunner` is the only place a subprocess is spawned. It
parses `-progress pipe:1` for real progress, drains stderr into a bounded buffer,
honours a `CancelToken` with SIGTERM then SIGKILL, deletes partial outputs on
failure, and maps common stderr patterns to actionable hints. `MediaProbe` wraps
`ffprobe` with a cache keyed on path, mtime and size. `filters.py` builds filter
graphs as string lists.

**`engines/video/`** — `VideoEngine` composes runner and probe into the operations the
app offers: trim, cut, merge, transform, compress, convert, extract, GIF, thumbnail,
proxy, watermark, burn, attach, loudness, normalise. `encode.py` turns a `Quality`
into concrete encoder arguments, including the VideoToolbox path (`-q:v`, not
`-crf`) and the stream-copy fast path.

**`engines/split/`** — Six strategies behind one `SplitStrategy` interface, selected
through `SplitRegistry`. Each returns a `SplitPlan`; none of them render anything.
Shared post-processing (`enforce_bounds`) clamps to the source duration, merges
slivers, applies `max_clips` and renumbers from 1, so every mode produces
consistent output.

**`engines/ai/`** — `OllamaClient` uses stdlib `urllib` only. `TranscriptionEngine`
lazy-loads Faster-Whisper. `AnalysisEngine` asks for strict JSON and falls back to
heuristics when no model is reachable, so a missing Ollama degrades quality rather
than breaking the feature.

**`engines/subtitle/`** — Six presets, cue re-flow from word timings, and writers for
SRT, VTT, ASS and TXT.

**`engines/export/`** — Ten presets and `JobQueue`, a bounded thread pool (two workers
by default) that publishes lifecycle events and persists history.

## Services

Services are the use-case layer. They own the "and then" logic: import the file,
*and then* probe it, *and then* publish an event, *and then* cache the thumbnail.

- `MediaService` — import, probe, thumbnails, proxies, waveforms
- `SplitService` — plan via the registry, render segments sequentially with per-clip progress
- `AIService` — transcription with a disk cache and a single-flight lock, plus analysis
- `SubtitleService` — cues, files, burn-in, soft-attach
- `ExportService` — builds a `Job` for every tool and submits it
- `ProjectService` — manifest CRUD, atomic writes
- `NotificationService` — subscribes to the event bus, keeps a readable log

Services never build FFmpeg arguments. If a service is assembling a `-vf` string,
that belongs in `filters.py`.

## The rendering pipeline

A split from click to file:

```
UI page collects parameters
  → SplitService.plan()  → SplitRegistry → strategy.plan() → SplitPlan
                                            (no files touched yet)
  → user reviews the plan in the filmstrip
  → SplitService.render() → for each Segment:
        VideoEngine.trim() → EncodeSettings.build_args() → FFmpegRunner.run()
        progress mapped from per-clip to whole-plan
  → list[Path]
```

Planning is always separate from rendering. It is fast, reversible and free, so the
UI can show what you are about to get before anything is written.

Anything long-running goes on the queue instead of blocking:

```
ExportService.queue_*() → Job(kind, title, run=callable)
  → JobQueue.submit() → worker thread → job.set_progress()
  → EventBus: job.started / job.progress / job.succeeded | job.failed
  → NotificationService records it; the Exports page shows it
```

Two workers is deliberate. On an 8 GB machine, three concurrent FFmpeg processes
thrash rather than finish sooner.

## Errors and cancellation

Every deliberate failure is a `DripCutError` subclass carrying a `hint`:

```python
raise ValidationError("The end time must be after the start.",
                      hint="Check the range and try again.")
```

The UI renders the message and the hint; it never shows a traceback. UI handlers
wrap service calls in `safe_call`, which converts `DripCutError` into a banner and
re-raises anything unexpected so it reaches the log.

Cancellation is cooperative. A `CancelToken` is passed down to the engine; FFmpeg
gets SIGTERM, then SIGKILL, and partial outputs are removed.

## Events

`EventBus` is a small synchronous pub/sub with a wildcard subscription. Handler
failures are logged, never raised — a broken listener cannot take down a render.
Events are how the queue, the notification centre and the status bar stay in sync
without knowing about each other.

## UI

```
ui/app.py            composition root: Blocks tree, theme, assets, router
ui/theme.py          dark and light palettes, Gradio theme object
ui/assets/           styles.css, app.js, logo.svg
ui/components/
    widgets.py       pure HTML builders, no Gradio import, unit-testable
    shell.py         sidebar, top bar, status bar
ui/pages/
    base.py          Page ABC and PageContext
    __init__.py      build_pages() — the site map
    <ten pages>
```

The router is deliberately dumb: one `gr.Column` per page, exactly one visible,
switched by real button clicks. No client-side routing means no state to drift.

`PageContext` is a typed view onto the container. Pages never import engines.

The command palette is data, not code: each page returns entries from
`Page.commands()` pointing at real `elem_id`s, and `app.js` clicks the underlying
button. Navigation therefore goes through the same path whether you use the mouse,
the keyboard or the palette.

There is no browser storage anywhere. Durable preferences live in `settings.json`
and are written by the server; session state lives in `gr.State`.

## Plugin system

See [PLUGIN_GUIDE.md](PLUGIN_GUIDE.md). In short: `PluginRegistry` discovers plugins
from the `dripcut.plugins` entry-point group and from loose `.py` files in the
plugins folder, activates them with a `PluginContext`, and collects their
contributions. A plugin that raises on import is recorded with its error and
skipped; it never stops the app from starting.

## Project layout

```
dripcut/
├── src/dripcut/
│   ├── cli/          launcher, doctor, subcommands
│   ├── core/         settings, paths, errors, logging, events, container, bootstrap
│   ├── models/       the data the app passes around
│   ├── engines/      ffmpeg, video, split, ai, subtitle, export
│   ├── services/     use cases
│   ├── plugins/      api, loader, builtin/
│   ├── ui/           theme, assets, components, pages
│   └── utils/        timecode, fs, text, concurrency
├── tests/            pytest suite, mirrors the layers
└── docs/
```

## Deliberate constraints

- **Offline.** The only socket opened is Ollama on `127.0.0.1:11434`. No web fonts —
  system stacks only, so typography works with no network.
- **`share=False`, always.** Not a setting. DripCut never exposes a public URL.
- **No telemetry.** There is no code to enable.
- **Two workers.** Tuned for 8 GB of unified memory.
- **AI is optional.** Every video tool works with Whisper and Ollama absent.
