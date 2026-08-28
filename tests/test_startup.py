"""Launcher and logging regressions."""

from __future__ import annotations

from types import SimpleNamespace

import gradio as gr

from dripcut.core.network import pick_server_port
from dripcut.ui.pages.exports import ExportsPage
from dripcut.ui.pages.plugins import PluginsPage
from dripcut.ui.pages.split import SplitPage
from dripcut.ui.pages.subtitles import SubtitlesPage


def test_pick_server_port_falls_back_when_busy(monkeypatch) -> None:
    import dripcut.core.network as network

    class FakeSocket:
        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def setsockopt(self, *args, **kwargs) -> None:
            return None

        def bind(self, address) -> None:
            self.address = address

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 54321)

    monkeypatch.setattr(network, "is_port_available", lambda host, port: False)
    monkeypatch.setattr(network.socket, "socket", lambda *args, **kwargs: FakeSocket())

    assert pick_server_port("127.0.0.1", 7999) == 54321


def test_setup_logging_falls_back_when_file_handler_fails(monkeypatch) -> None:
    import dripcut.core.logging as logging_mod

    monkeypatch.setattr(logging_mod, "_CONFIGURED", False, raising=False)

    def boom(*args, **kwargs):
        raise OSError("cannot open log file")

    monkeypatch.setattr(logging_mod.logging.handlers, "RotatingFileHandler", boom)

    logger = logging_mod.setup_logging("INFO")

    assert logger.name == "dripcut"
    assert logger.handlers


def test_launch_uses_a_resolved_port(monkeypatch) -> None:
    import dripcut.ui.app as ui_app

    captured: dict[str, object] = {}

    class FakeApp:
        def launch(
            self,
            server_name: str | None = None,
            server_port: int | None = None,
            share: bool | None = None,
            inbrowser: bool | None = None,
            show_api: bool | None = None,
            quiet: bool | None = None,
            favicon_path: str | None = None,
            **kwargs,
        ) -> None:
            captured.update(
                {
                    "server_name": server_name,
                    "server_port": server_port,
                    "share": share,
                    "inbrowser": inbrowser,
                    "show_api": show_api,
                    "quiet": quiet,
                    "favicon_path": favicon_path,
                    "kwargs": kwargs,
                }
            )

    container = SimpleNamespace(
        settings=SimpleNamespace(
            server=SimpleNamespace(host="127.0.0.1", port=7999),
            ui=SimpleNamespace(theme="dark"),
        )
    )

    monkeypatch.setattr(ui_app, "build_app", lambda _container: FakeApp())
    monkeypatch.setattr(ui_app, "pick_server_port", lambda host, port: 4321)

    real_accepts = ui_app._accepts

    def fake_accepts(callable_obj, name: str) -> bool:
        if callable_obj is gr.Blocks.__init__ and name == "theme":
            return True
        return real_accepts(callable_obj, name)

    monkeypatch.setattr(ui_app, "_accepts", fake_accepts)
    monkeypatch.setattr(ui_app, "_package_logo", lambda: None)
    monkeypatch.setattr(ui_app, "presentation_options", lambda settings: {})

    ui_app.launch(container)

    assert captured["server_name"] == "127.0.0.1"
    assert captured["server_port"] == 4321
    assert captured["share"] is False
    assert captured["inbrowser"] is False
    assert captured["show_api"] is False
    assert captured["quiet"] is True


def test_file_output_widgets_allow_multiple_files(monkeypatch, container) -> None:
    page_specs = [
        (SplitPage(), "Rendered clips"),
        (ExportsPage(), "Finished files"),
        (PluginsPage(), "Tool output"),
        (SubtitlesPage(), "Subtitle file"),
        (SubtitlesPage(), "Burned video"),
        (SubtitlesPage(), "Video with a subtitle track"),
    ]

    captured: list[dict[str, object]] = []
    original_files = gr.Files

    def fake_files(*args, **kwargs):
        captured.append(dict(kwargs))
        return original_files(*args, **kwargs)

    monkeypatch.setattr(gr, "Files", fake_files)

    from dripcut.ui.pages.base import PageContext

    ctx = PageContext(container=container)
    with gr.Blocks():
        for page, _label in page_specs:
            page.build(ctx, visible=False)

    assert captured and all(item.get("file_count") == "multiple" for item in captured)
