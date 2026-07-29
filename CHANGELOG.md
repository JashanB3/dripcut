# Changelog

All notable changes to DripCut. Format follows [Keep a Changelog](https://keepachangelog.com);
versions follow [PEP 440](https://peps.python.org/pep-0440/).

## [1.0.0rc1] — 2026-07-27

First release candidate. Feature-complete, tested, and documented.

### Added

**Video tools** — trim, cut, split, merge, crop, resize, rotate, flip, compress,
convert container, change FPS, change resolution, adjust speed, extract audio,
extract frames, create GIF, image and text watermarks, proxy generation, thumbnails,
and batch processing across a folder.

**Six split modes** — fixed length, custom timestamps, embedded chapters, scene
detection, silence detection, and AI highlight. Planning is always separate from
rendering, so you see the clip list before anything is written.

**Local AI** — Faster-Whisper transcription with a disk cache, plus highlight
detection, hook detection, title suggestions, summaries and chapter markers through
Ollama. Every LLM call falls back to a heuristic, so a missing model degrades
quality rather than breaking the feature.

**Subtitles** — six caption presets, cue re-flow from word-level timings, SRT/VTT/
ASS/TXT output, karaoke timing, burn-in, and soft-attach.

**Export queue** — ten presets, a two-worker thread pool, live progress, cancellation
of one job or all, and persisted history.

**Ten-page interface** — Dashboard, Workspace, Split, AI Studio, Subtitle Studio,
Batch, Exports, Projects, Plugins, Settings. Custom dark and light themes, a command
palette, keyboard shortcuts, a resizable sidebar, and a status bar.

**CLI** — `dripcut` launches the app; `doctor`, `info`, `split`, `transcribe`,
`export`, `plugins`, `config` and `version` cover the rest. `dripcut doctor` runs 20
environment checks and every problem it reports comes with the command that fixes it.

**Plugin system** — entry-point and loose-file discovery, three built-in plugins, and
hooks for tools, split strategies and caption styles.

**Test suite** — 222 tests across engines, services, CLI, plugins and UI pages.

**Documentation** — ARCHITECTURE, INSTALL, DEVELOPMENT and PLUGIN_GUIDE.

### Fixed

Found while building and running the application:

- `cli/doctor.py` used PEP 701 nested-quote f-strings, which crash on Python 3.10
  and 3.11 despite `requires-python = ">=3.10"`.
- `cli/commands.py` treated `Segment.display_title` as a property; it is a method.
- `cli/commands.py` printed error hints twice, because `DripCutError.__str__`
  already folds the hint into the message.
- `ui/components/widgets.py` closed over a loop variable in `notes_list`.
- `ui/app.py` passed `theme`, `css` and `head` to `Blocks()`, which Gradio 6 moved to
  `launch()`. The module now asks each signature what it accepts, so 4.x, 5.x and
  6.x all work.
- The theme toggle returned a `<script>` from a `gr.HTML` component, which browsers
  never execute. The DOM swap is now a client-side handler on the click event.
- The command palette loaded zero commands: its JSON `<script>` block did not
  survive as a standalone DOM node. Commands now travel as `window.__dripcutCommands`
  inside the same script that carries `app.js`.
- ⌘↵ resolved on only eight of ten pages. All pages now use the `dc-primary-<page>`
  id convention.
- `ui/pages/ai_studio.py` passed `show_copy_button` to `gr.Textbox`, which does not
  exist in Gradio 6.
- `ui/pages/subtitles.py` read `CaptionStyle.font`, `.size` and `.outline`; the real
  fields are `font_name`, `font_size` and `outline_width`.

### Removed

- An unreachable empty-folder branch in the Batch page: `import_folder` raises
  rather than returning an empty list.
- Three unused CSS rules (`dc-field`, `dc-player`, `dc-scroll`).
- A function written only to justify an unused import in `ui/pages/split.py`.

### Known limitations

- **Transcription and Ollama analysis are unverified end to end.** The build
  environment cannot download Whisper weights or run an Ollama server. Both paths
  are covered through their cache, guard and fallback branches only.
- **Browser behaviour is unverified.** No headless browser was available, so the
  command palette, keyboard shortcuts, sidebar resize and theme flip are confirmed
  as far as payload delivery, not execution.
- **Hardware encoding is untested.** VideoToolbox detection works, but no Apple
  Silicon machine was available to exercise the encode path.
- Windows support is implemented but has not been run on Windows.
