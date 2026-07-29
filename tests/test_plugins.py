"""Plugin system: discovery, lifecycle, and the three built-ins."""

from __future__ import annotations

import pytest

from dripcut.core.bootstrap import build_container
from dripcut.plugins.api import Plugin, PluginMeta
from dripcut.plugins.builtin.loudness import LoudnessPlugin
from dripcut.plugins.builtin.social_presets import SocialPresetsPlugin
from dripcut.plugins.builtin.thumbnail_grid import ThumbnailGridPlugin

BUILTINS = (ThumbnailGridPlugin, LoudnessPlugin, SocialPresetsPlugin)


@pytest.fixture
def loaded(settings, paths):
    """A container with plugin discovery switched on."""
    built = build_container(settings, paths=paths, load_plugins=True)
    yield built
    built.plugins.shutdown()
    queue = built.try_resolve("queue")
    if queue is not None:
        queue.shutdown()


@pytest.mark.parametrize("plugin", BUILTINS)
def test_builtins_declare_metadata(plugin: type[Plugin]) -> None:
    meta = plugin.meta
    assert isinstance(meta, PluginMeta)
    assert meta.id and meta.name and meta.version
    assert meta.description, "a plugin without a description is unusable in the picker"
    assert meta.api_version == 1


def test_builtin_ids_are_unique() -> None:
    assert len({plugin.meta.id for plugin in BUILTINS}) == len(BUILTINS)


def test_discovery_finds_the_builtins(loaded) -> None:
    found = {record.meta.id for record in loaded.plugins.records()}
    assert {"thumbnail_grid", "loudness", "social_presets"} <= found


def test_discovered_plugins_are_active(loaded) -> None:
    assert all(record.status == "active" for record in loaded.plugins.records())


def test_tools_are_contributed(loaded) -> None:
    tools = loaded.plugins.tools()
    assert tools
    for tool in tools:
        assert tool.id and tool.label and callable(tool.run)


def test_tool_lookup_by_id(loaded) -> None:
    first = loaded.plugins.tools()[0]
    assert loaded.plugins.tool(first.id) is first
    assert loaded.plugins.tool("not-a-tool") is None


def test_disable_then_enable(loaded) -> None:
    record = loaded.plugins.set_enabled("loudness", False)
    assert record.enabled is False
    assert loaded.plugins.set_enabled("loudness", True).enabled is True


def test_disabled_plugins_are_skipped_at_discovery(settings, paths) -> None:
    settings.disabled_plugins = ["loudness"]
    built = build_container(settings, paths=paths, load_plugins=True)
    try:
        states = {r.meta.id: r.status for r in built.plugins.records()}
        assert states.get("loudness") == "disabled"
    finally:
        built.plugins.shutdown()
        built.resolve("queue").shutdown()


def test_caption_styles_are_contributed(loaded) -> None:
    """The social pack adds presets; they must be real CaptionStyle objects."""
    from dripcut.models.subtitle import CaptionStyle

    styles = SocialPresetsPlugin().caption_styles(loaded.plugins.context)
    assert styles
    assert all(isinstance(style, CaptionStyle) for style in styles.values())


def test_a_broken_plugin_does_not_break_discovery(loaded, paths) -> None:
    """One bad file must never stop the healthy plugins from loading."""
    (paths.plugins / "broken_plugin.py").write_text(
        "raise RuntimeError('boom')\n", encoding="utf-8"
    )
    loaded.plugins.discover(disabled=[])
    survivors = {r.meta.id for r in loaded.plugins.records() if r.status == "active"}
    assert {"thumbnail_grid", "loudness", "social_presets"} <= survivors


def test_table_rows_render(loaded) -> None:
    rows = loaded.plugins.table_rows()
    assert rows and all(isinstance(row, list) for row in rows)
