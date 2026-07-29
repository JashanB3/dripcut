"""Ollama client built on the standard library.

Why ``urllib`` and not an SDK: DripCut talks to ``127.0.0.1`` only, needs three
endpoints, and every dependency is a thing that can break an offline install. The
whole client is under 200 lines and has no third-party imports.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from dripcut.core.errors import ModelUnavailableError
from dripcut.core.logging import get_logger
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.text import extract_json

__all__ = ["OllamaClient"]

_log = get_logger("engines.ai.llm")


class OllamaClient:
    """Minimal Ollama HTTP client: health, model list, generate, chat, JSON."""

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        *,
        model: str = "qwen2.5:3b",
        timeout: int = 180,
        num_ctx: int = 4096,
        temperature: float = 0.25,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.temperature = temperature

    # ------------------------------------------------------------------- health

    @property
    def endpoint_host(self) -> tuple[str, int]:
        """``(hostname, port)`` parsed from the configured base URL."""
        parsed = urlparse(self.host)
        return parsed.hostname or "127.0.0.1", parsed.port or 11434

    def is_up(self, timeout: float = 1.0) -> bool:
        """True when something is listening on the Ollama port."""
        host, port = self.endpoint_host
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def ensure_server(self, *, wait_seconds: float = 12.0, autostart: bool = True) -> bool:
        """Make sure the Ollama server is running, starting it if allowed.

        ``ollama serve`` is launched detached so quitting DripCut does not kill a
        server the user may have started themselves.

        Returns:
            True when the server is reachable.
        """
        if self.is_up():
            return True
        if not autostart or not shutil.which("ollama"):
            return False
        _log.info("starting ollama serve")
        try:
            subprocess.Popen(  # noqa: S603,S607 - fixed argv, no shell
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:  # pragma: no cover - host dependent
            _log.warning("could not start ollama: %s", exc)
            return False
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if self.is_up():
                return True
            time.sleep(0.4)
        return False

    def list_models(self) -> list[str]:
        """Names of every locally installed model (empty when unreachable)."""
        try:
            payload = self._get("/api/tags")
        except ModelUnavailableError:
            return []
        return sorted(str(entry.get("name", "")) for entry in payload.get("models", []) if entry)

    def has_model(self, name: str | None = None) -> bool:
        """True when ``name`` (default: configured model) is installed.

        Ollama reports ``qwen2.5:3b`` but users type ``qwen2.5``, so a bare name
        matches any tag of that model.
        """
        wanted = (name or self.model).strip()
        installed = self.list_models()
        if wanted in installed:
            return True
        base = wanted.split(":")[0]
        return any(entry.split(":")[0] == base for entry in installed)

    def pull(self, name: str | None = None) -> Iterator[str]:
        """Stream ``ollama pull`` status lines for the launcher's progress display."""
        target = name or self.model
        if not shutil.which("ollama"):
            raise ModelUnavailableError(
                "The ollama command was not found.",
                hint="Install Ollama from ollama.com, then run `dripcut doctor`.",
            )
        process = subprocess.Popen(  # noqa: S603,S607 - fixed argv, no shell
            ["ollama", "pull", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout is not None:
            for line in process.stdout:
                text = line.strip()
                if text:
                    yield text
        process.wait()

    # --------------------------------------------------------------- generation

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
        cancel_token: CancelToken | None = None,
    ) -> str:
        """Run a single-turn completion and return the text.

        Raises:
            ModelUnavailableError: If the server or model cannot be reached.
        """
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        body: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_ctx": self.num_ctx,
                "num_predict": max_tokens,
            },
        }
        if system:
            body["system"] = system
        if json_mode:
            body["format"] = "json"
        started = time.monotonic()
        payload = self._post("/api/generate", body)
        _log.debug("ollama generate in %.1fs", time.monotonic() - started)
        return str(payload.get("response", "")).strip()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> str:
        """Multi-turn chat completion (used by the future assistant panel)."""
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_ctx": self.num_ctx,
            },
        }
        if json_mode:
            body["format"] = "json"
        payload = self._post("/api/chat", body)
        return str((payload.get("message") or {}).get("content", "")).strip()

    def generate_json(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str | None = None,
        temperature: float = 0.15,
        max_tokens: int = 1536,
        retries: int = 1,
        cancel_token: CancelToken | None = None,
    ) -> Any:
        """Completion parsed as JSON, with one strict-format retry.

        Small quantised models drift out of JSON now and then; a single retry with
        a blunt reminder recovers almost every case, and callers still get a clean
        exception when it does not.
        """
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            suffix = "" if attempt == 0 else "\n\nReturn ONLY valid JSON. No prose, no code fences."
            raw = self.generate(
                prompt + suffix,
                system=system,
                model=model,
                temperature=temperature if attempt == 0 else 0.0,
                max_tokens=max_tokens,
                json_mode=True,
                cancel_token=cancel_token,
            )
            try:
                return extract_json(raw)
            except ValueError as exc:
                last_error = exc
                _log.debug("model returned non-JSON on attempt %d", attempt + 1)
        raise ModelUnavailableError(
            "The local model did not return usable JSON.",
            hint="Try a larger model in Settings, or run the step again.",
        ) from last_error

    # ----------------------------------------------------------------- internals

    def _get(self, path: str) -> dict[str, Any]:
        """GET a JSON endpoint."""
        request = urllib.request.Request(f"{self.host}{path}", method="GET")
        return self._send(request)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON body to an endpoint."""
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        """Execute a request and map transport failures onto DripCut errors."""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                data = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            if exc.code == 404 and "model" in detail.lower():
                raise ModelUnavailableError(
                    f"Model {self.model!r} is not installed.",
                    hint=f"Run `ollama pull {self.model}`.",
                ) from exc
            raise ModelUnavailableError(
                f"Ollama replied with HTTP {exc.code}.", hint=detail or None
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelUnavailableError(
                "Ollama is not responding.",
                hint="Start it with `ollama serve`, or switch AI features off in Settings.",
            ) from exc
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ModelUnavailableError("Ollama returned an unreadable response.") from exc
        return parsed if isinstance(parsed, dict) else {"response": parsed}
