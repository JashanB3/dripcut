# Development

## Getting set up

```bash
git clone <repo> dripcut && cd dripcut
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

make lint    # ruff check
make fmt     # ruff format
make type    # mypy
make test    # pytest
make run     # dripcut up
```

The dev extra adds pytest, pytest-cov, ruff and mypy. FFmpeg must be on `PATH` for
most of the test suite; tests that need it are marked and skip cleanly without it.

## Coding style

Ruff enforces the mechanical parts (line length 100, import order, the usual bug
classes). What it cannot enforce:

- **Type hints on everything public.** `from __future__ import annotations` at the
  top of every module.
- **Docstrings say why, not what.** `"""Return the duration."""` on a method called
  `duration` is noise. `"""Two workers: three FFmpeg processes thrash on 8 GB."""`
  earns its place.
- **Errors carry hints.** Raise `DripCutError` subclasses with a `hint=` describing
  the fix. A message with no remedy is not finished.
- **No bare `except`.** Catch what you can handle. Where a broad catch is genuinely
  right — a status panel that must never blank the page — add `# noqa: BLE001` and
  a comment saying why.
- **Comments explain decisions.** If a line looks wrong but is right, say why.
- **No dead code.** Not commented out, not "might need it later". Git remembers.

Heavy imports (`gradio`, `faster_whisper`, `scenedetect`, `cv2`) go inside the
functions that need them, marked `# noqa: PLC0415`. This keeps `dripcut --version`
fast and lets the app degrade gracefully when an optional dependency is missing.

## Folder structure

```
src/dripcut/
├── cli/       argument parsing, terminal output, exit codes
├── core/      settings, paths, errors, logging, events, container, bootstrap
├── models/    dataclasses passed between layers
├── engines/   ffmpeg · video · split · ai · subtitle · export
├── services/  use cases; the only thing UI and CLI call
├── plugins/   api, loader, builtin/
├── ui/        theme, assets, components, pages
└── utils/     timecode, fs, text, concurrency
```

The layering rule is in [ARCHITECTURE.md](ARCHITECTURE.md) and is not negotiable:
`utils → core → models → engines → services → plugins → ui → cli`.

## Adding a page

1. Create `ui/pages/my_page.py`:

```python
from dripcut.ui.pages.base import Page, PageContext, safe_call


class MyPage(Page):
    key = "my_page"
    label = "My Page"
    icon = "\u25c6"
    group = "Workspace"          # sidebar section
    title = "My Page"
    subtitle = "What this page is for."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()
            run = gr.Button("Do it", elem_id="dc-primary-my_page",
                            elem_classes=["dc-btn", "dc-btn-primary"])
            run.click(self._run, outputs=message)
        return column

    def _run(self) -> str:
        result, error = safe_call(self._ctx.media.recent)
        return error or ""

    def commands(self) -> list[dict[str, str]]:
        return [*super().commands(),
                {"label": "Do it", "group": "My Page", "target": "dc-primary-my_page"}]
```

2. Append it to `build_pages()` in `ui/pages/__init__.py`. That is the whole
   registration — sidebar, router and command palette all derive from that list.

Conventions that matter:

- The primary button's `elem_id` must be `dc-primary-<key>` so ⌘↵ finds it.
- Wrap every service call in `safe_call`. Handlers must never raise.
- Use classes from `styles.css`. If you need a new look, add the rule to the
  stylesheet first — do not invent class names in Python.
- Long work goes on the queue via `ExportService`, not inline.
- Add a smoke test in `tests/`, following `test_workspace.py`.

## Adding an engine

Engines do one thing and know nothing about services or UI.

1. Create `engines/<area>/<thing>.py`.
2. Take collaborators through the constructor — never reach for globals.
3. Accept `on_progress: ProgressCallback | None` and `cancel_token: CancelToken | None`
   for anything slow.
4. Raise `DripCutError` subclasses with hints.
5. Register it in `core/bootstrap.py`.
6. Test it directly; engines are the easiest layer to cover.

If you are spawning a subprocess anywhere other than `FFmpegRunner`, stop and
reconsider.

## Adding a service

1. Create `services/my_service.py`; take engines through the constructor.
2. Publish events for anything the UI should react to.
3. Construct it in `build_container()` and register it under a `KEY_*` constant.
4. Add a typed property on `ServiceContainer` if pages will use it often.

Services are where "and then" logic lives. If a page is doing three service calls in
a row and stitching the results, that sequence probably belongs in a service.

## Adding a plugin

See [PLUGIN_GUIDE.md](PLUGIN_GUIDE.md). For plugins that should ship with DripCut,
put them in `plugins/builtin/` and add an entry point in `pyproject.toml`.

## Testing

```bash
pytest                          # everything
pytest tests/test_split.py -v   # one file
pytest -k "silence"             # by name
pytest --cov=dripcut            # coverage
```

The suite mirrors the layers. Conventions:

- `conftest.py` gives every test its own `DRIPCUT_HOME`, so nothing touches your
  real config. `app_paths()` is `lru_cache`d and the fixture clears it.
- The `container` fixture builds a real wired container against that temporary home.
  Prefer it to mocks — the wiring is what breaks.
- The `sample_video` fixture generates a six-second clip with FFmpeg once per
  session. Real media beats a fake.
- Mark FFmpeg-dependent tests with `@needs_ffmpeg`.
- Guard UI tests with `pytest.importorskip("gradio")`.
- Test names are sentences: `test_silence_at_the_start_is_dropped`.

Not covered, and honestly so: Whisper model downloads and Ollama round trips cannot
run in CI. `test_ai.py` covers everything that decides whether those calls happen
and what occurs when they cannot.

## Building a release

```bash
make clean
make lint && make test
python -m build --wheel
```

The wheel bundles `ui/assets/*` and `py.typed` — check `pyproject.toml`'s
`package-data` if you add a new asset type.

Before tagging:

1. `make lint`, `make test`, `python -m build --wheel` all clean.
2. `pip install dist/*.whl` into a fresh venv; run `dripcut doctor` and `dripcut up`.
3. Click through every page.
4. Update `CHANGELOG.md` and the version in `pyproject.toml` and `__init__.py`.
5. Refresh `PROJECT_STATE.md`.

## Debugging

```bash
dripcut --log-level DEBUG up
tail -f ~/Library/Application\ Support/DripCut/logs/dripcut.log
dripcut doctor --json | jq
dripcut info                    # resolved paths and settings
```

Every FFmpeg failure logs the command and the tail of stderr. If a render fails,
that log line is the first place to look.
