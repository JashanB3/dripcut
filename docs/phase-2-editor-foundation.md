# Phase 2: Editor Foundation

## Decision

DripCut will migrate incrementally to a React and TypeScript editor backed by a
Python API. The existing Python services and FFmpeg engines remain the rendering
core. Gradio remains available during migration, but it is not a dependency of the
new editor.

This split is appropriate because the current dependency-injection boundary already
separates services from most UI construction. React provides the interaction model
needed for synchronized playback, timeline editing, selection and history. FastAPI
is already present through the current runtime and provides a small typed HTTP and
WebSocket boundary without introducing another backend language.

The Phase 2 prototype intentionally uses browser-local object URLs. It proves the
editor interaction model without inventing a temporary upload API that would later
need to be replaced by the asset store.

## Target Architecture

```text
React editor
  |-- serializable editor project state
  |-- browser-only playback runtime
  |-- typed API client
  |
FastAPI boundary
  |-- project API
  |-- asset API
  |-- render/job API and progress stream
  |
Application services
  |-- project application service
  |-- asset application service
  |-- render orchestrator
  |
Existing DripCut services and engines
  |-- split, subtitles, AI and exports
  |-- FFmpeg, probe and video engines
  |
Ports                         Adapters
  |-- ProjectStore             |-- local JSON / database
  |-- AssetStore               |-- local filesystem / S3
  |-- ArtifactStore            |-- local filesystem / S3
  |-- JobStore                 |-- local queue / Redis queue
  |-- IdentityProvider         |-- local user / hosted auth
```

Local Mac mode can run the API, worker and local adapters in one process. Hosted
mode can use the same ports with S3, a database and distributed workers.

## Repository Structure

```text
web/                         React/TypeScript editor
  src/
    components/
      editor/                editor compositions
      primitives/            shared UI controls
    editor/                   serializable schema and reducer
    styles/                   tokens, global rules and editor layout
    App.tsx
    main.tsx
src/dripcut/
  api/                        future FastAPI routes and DTO mapping
  application/                future project/render orchestration
  ports/                      future persistence/storage interfaces
  adapters/                   future local and hosted implementations
  engines/                    existing processing engines
  services/                   existing use cases during migration
  ui/                         legacy Gradio UI until feature parity
```

## Editor State Schema

The project document is JSON-serializable and contains no DOM nodes, `File`
objects, media elements or browser object URLs.

```text
EditorProject
  version, id, name, createdAt, updatedAt
  assets[]
    id, name, kind, mimeType, duration, width, height, source
  canvas
    aspectRatio, width, height, background, zoom
  timeline
    duration, zoom, tracks[]
      id, kind, name, muted, locked, clips[]
        id, assetId, start, end, sourceStart, sourceEnd, label
        transform, text?, captionStyle?
  renderSettings
    format, width, height, fps, quality, captions

EditorSession (not persisted)
  selectedTool, selectedElement, playback, panel state
  undo stack, redo stack, dirty/saved state

PlaybackRuntime (not in reducer)
  HTMLVideoElement ref
  object URL map
  requestAnimationFrame handle
```

Document actions are recorded in undo history. High-frequency playback events are
session actions and never pollute undo history.

## Design Tokens

Tokens live in `web/src/styles/tokens.css` and are the only source for foundational
visual values.

```text
Color: canvas, surface 1-3, elevated, text 1-3, border, accent, positive, warning
Typography: display, heading, body and mono families; 12-28px scale
Spacing: 4, 6, 8, 12, 16, 20, 24, 32
Radius: 6, 8, 10, 14 and pill
Border: subtle, default and focus
Shadow: floating controls and menus only
Icons: 16, 18, 20 and 24
Motion: 120ms immediate, 180ms standard, 240ms panel
States: hover, selected, focus-visible, disabled and loading
```

The editor defaults to a focused dark workspace. Accent gradients are limited to
brand and primary-action moments; operational surfaces remain solid and dense.

## Component Hierarchy

```text
AppShell
  TopBar
    ProjectTitle, HistoryControls, ExportAction, ProfileAction
  EditorBody
    ToolRail
    ToolPanel
      SearchField, AssetGrid, AssetCard, EmptyState
    Workspace
      ContextToolbar
      CanvasArea
        VideoPlayer
        EmptyState
      TransportControls
    PropertyPanel
  Timeline
    TimelineToolbar, ZoomControl
    TimelineRuler
    TimelineTrack
      TimelineClip
    Playhead
  ToastRegion
```

Primitives own visual states. Editor components compose primitives and do not
create page-specific button or input variants.

## Migration Strategy

1. Ship the editor as a separate development entry point while Gradio remains the
   default application.
2. Add read-only project and asset API endpoints with DTO mappers.
3. Add asset ingestion and persistent project saves behind ports.
4. Route render requests through a durable orchestrator and expose job progress.
5. Move one workflow at a time from Gradio, starting with Make Clips.
6. Switch the default entry point only after feature parity and migration tests.
7. Remove legacy Gradio CSS only when no remaining view imports it.

## Modules That Remain Unchanged

- `engines/ffmpeg/*`
- `engines/video/*`
- `engines/split/*`
- `engines/subtitle/*`
- `engines/ai/*`
- `models/media.py`, `models/clip.py`, `models/transcript.py`
- FFmpeg-facing service behavior that already has passing tests
- CLI commands during the UI migration

## Modules Requiring Adapters Or Refactoring

- `models/project.py`: migrate absolute paths to asset/artifact identifiers.
- `services/project_service.py`: implement a `ProjectStore` port.
- `services/media_service.py`: ingest through an `AssetStore` port.
- `services/export_service.py`: submit typed render requests to an orchestrator.
- `engines/export/queue.py`: separate job persistence from in-process execution.
- `core/bootstrap.py`: choose local or hosted adapters by deployment mode.
- `ui/*`: remain legacy and are replaced page by page, not restyled again.

## Risks

- Two UIs temporarily increase testing and documentation cost.
- Browser object URLs disappear on reload; this is deliberate for the prototype.
- Project model migration needs versioned manifests and a compatibility reader.
- Frame-accurate timeline previews require proxy generation in a later phase.
- Cross-origin media and byte-range responses must be correct before remote assets.
- Undo history can become memory-heavy unless actions store compact document deltas.

## Exact Implementation Sequence

1. Establish the `web/` package, TypeScript strictness and design tokens.
2. Define serializable editor types, initial project and reducer history semantics.
3. Build shared primitives and the editor shell.
4. Add browser-local media import and metadata capture.
5. Implement the video player and transport synchronization.
6. Implement tracks, ruler, playhead dragging and timeline zoom.
7. Add contextual tool and property panels.
8. Verify build, lint, browser behavior and target desktop sizes.
9. Add the FastAPI DTO boundary in the next phase, after the client contract is
   exercised and stable.

## Intentionally Deferred

Authentication, cloud persistence, social publishing, AI tools, templates,
multi-track rendering, overlay manipulation, keyframes and production export are
not represented as functional controls in this prototype.
