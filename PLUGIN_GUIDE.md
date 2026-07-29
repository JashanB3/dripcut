# Plugin guide

A DripCut plugin can add tools, split strategies and caption styles. Plugins are
ordinary Python — there is no manifest format and no build step.

## The shortest possible plugin

Save this as `~/Library/Application Support/DripCut/plugins/hello.py` (macOS) and
restart DripCut, or press **Rescan** on the Plugins page:

```python
from dripcut.plugins.api import Plugin, PluginContext, PluginMeta, ToolAction


class HelloPlugin(Plugin):
    meta = PluginMeta(
        id="hello",
        name="Hello",
        version="1.0.0",
        description="Prints the duration of the selected video.",
        author="You",
        tags=("demo",),
    )

    def tools(self, context: PluginContext) -> list[ToolAction]:
        return [
            ToolAction(
                id="hello.duration",
                label="Show duration",
                description="Log how long the selected video is.",
                group="Demo",
                needs_media=True,
                run=self._run,
            )
        ]

    def _run(self, media):
        print(f"{media.name} is {media.duration:.1f}s long")
        return []          # return a list of Paths to offer downloads
```

It will appear on the Plugins page, and its tool becomes runnable there.

## Discovery

Two mechanisms, both active at once:

1. **Loose files** — any `.py` in the plugins folder. Best for personal scripts.
   - macOS: `~/Library/Application Support/DripCut/plugins/`
   - Linux: `~/.local/share/DripCut/plugins/`
   - Windows: `%LOCALAPPDATA%\DripCut\plugins\`
   - Override the parent with `DRIPCUT_HOME`.

2. **Entry points** — for distributable plugins. In your `pyproject.toml`:

   ```toml
   [project.entry-points."dripcut.plugins"]
   my_plugin = "my_package.plugin:MyPlugin"
   ```

   `pip install` it into the same environment as DripCut and it is found
   automatically. This is how the three built-ins ship.

Run `dripcut plugins` to see what was discovered, where each came from, and any
load errors.

## `PluginMeta`

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique, stable, lowercase. Used in `settings.json` to disable it. |
| `name` | yes | Shown in the picker. |
| `version` | yes | Your own scheme. |
| `description` | yes | One sentence. A plugin without one is unusable in the picker. |
| `author` | no | |
| `api_version` | no | Defaults to `1`. Bump only when the host API changes. |
| `tags` | no | Tuple of strings, shown as chips. |

## Hook points

Override only what you need; every hook has a working default.

```python
def register(self, context: PluginContext) -> None:
    """Called once on activation. Keep the context if you need it later."""

def tools(self, context: PluginContext) -> list[ToolAction]:
    """Actions that appear on the Plugins page."""

def split_strategies(self, context: PluginContext) -> dict[str, SplitStrategy]:
    """Extra split modes, keyed by mode name."""

def caption_styles(self, context: PluginContext) -> dict[str, CaptionStyle]:
    """Extra caption presets, keyed by preset name."""

def on_event(self, event: Event) -> None:
    """Every event on the bus. Keep this fast and never raise."""

def shutdown(self) -> None:
    """Release anything you opened."""
```

## `PluginContext`

What your plugin is handed:

```python
context.container    # the full ServiceContainer
context.settings     # live Settings
context.events       # EventBus
context.output_dir   # where the user wants files written
context.data_dir     # your own scratch space (the plugins folder)
```

Go through services, not engines:

```python
def _run(self, media):
    video = self.context.container.video          # VideoEngine
    target = self.context.output_dir / f"{media.stem}-still.jpg"
    return [video.thumbnail(media.path, target, width=1280)]
```

## `ToolAction`

| Field | Notes |
|---|---|
| `id` | Unique across all plugins. Prefix with your plugin id. |
| `label` | Button text. |
| `description` | Shown in the tool table. |
| `run` | `Callable[[MediaInfo | None], list[Path]]`. Return the files you produced. |
| `icon` | Optional single glyph. |
| `group` | Optional grouping label. |
| `needs_media` | If true, the UI refuses to run it without a selected video. |
| `params` | Optional dict describing extra inputs. |

## Rules that keep plugins well-behaved

- **Never raise on import.** A plugin that explodes at import time is recorded with
  its error and skipped — the app still starts, but your plugin will not load. There
  is a test for exactly this.
- **Return real paths.** The UI offers whatever you return as downloads, so return
  `[]` rather than `None` when you produce nothing.
- **Respect cancellation.** If you accept a `CancelToken`, poll it.
- **Do not block the event bus.** `on_event` runs synchronously.
- **Stay offline.** DripCut's promise is that nothing leaves the machine. A plugin
  that makes network calls breaks that promise for the whole app.
- **Write to `output_dir` or `data_dir`.** Nowhere else.

## Testing your plugin

```python
from dripcut.core.bootstrap import build_container
from my_package.plugin import MyPlugin


def test_metadata():
    assert MyPlugin.meta.id and MyPlugin.meta.description


def test_tool_runs(tmp_path):
    container = build_container(load_plugins=False)
    plugin = MyPlugin()
    plugin.register(container.plugins.context)
    tool = plugin.tools(container.plugins.context)[0]
    assert callable(tool.run)
```

See `tests/test_plugins.py` for the patterns used against the built-ins.

## Disabling

Users can disable a plugin from the Plugins page or with
`dripcut plugins --disable <id>`. Disabled ids are stored in `disabled_plugins` in
`settings.json` and skipped at discovery.

## Worked examples

The three built-ins are deliberately small and readable:

- `plugins/builtin/thumbnail_grid.py` — a contact sheet; a tool that produces files
- `plugins/builtin/loudness.py` — LUFS measurement and normalisation
- `plugins/builtin/social_presets.py` — three caption styles; contributions without a tool
