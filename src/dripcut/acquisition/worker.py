"""Polling worker for a DripCut-owned Mac; it never accepts inbound connections."""

from __future__ import annotations

import os
import re
import shutil
import signal
import threading
from typing import Any

import httpx

from dripcut.acquisition.models import AcquisitionStatus
from dripcut.core.bootstrap import build_container
from dripcut.storage.provider import build_storage_provider


class YouTubeWorker:
    def __init__(self) -> None:
        self.api_url = os.environ["DRIPCUT_WORKER_API_URL"].rstrip("/")
        self.token = os.environ["DRIPCUT_WORKER_TOKEN"]
        self.worker_id = os.environ.get("DRIPCUT_WORKER_ID", "mac-youtube-worker")
        self.poll_seconds = max(2, int(os.environ.get("DRIPCUT_WORKER_POLL_SECONDS", "8")))
        self.max_size = int(os.environ.get("DRIPCUT_WORKER_MAX_SOURCE_MB", "2048")) * 1024 * 1024
        self.stop = threading.Event()
        self.client = httpx.Client(timeout=httpx.Timeout(30, read=30))
        self.container = build_container(load_plugins=False)
        self.storage = build_storage_provider(self.container.paths.projects / "web" / "objects")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-DripCut-Worker-Id": self.worker_id}

    def run(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: self.stop.set())
        while not self.stop.is_set():
            try:
                self.client.post(f"{self.api_url}/api/worker/heartbeat", headers=self.headers, json={"status": "idle", "version": "1"}).raise_for_status()
                response = self.client.get(f"{self.api_url}/api/worker/jobs/next", headers=self.headers)
                if response.status_code == 204:
                    self.stop.wait(self.poll_seconds)
                    continue
                response.raise_for_status()
                self.process(dict(response.json()["job"]))
            except Exception:
                # A network outage is not a failed acquisition. The lease expiry
                # makes the job recoverable without leaking credentials in logs.
                self.stop.wait(self.poll_seconds)

    def process(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        self.client.post(f"{self.api_url}/api/worker/heartbeat", headers=self.headers, json={"status": "running", "current_job_id": job_id, "version": "1"}).raise_for_status()
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat_loop, args=(job_id, heartbeat_stop), daemon=True)
        heartbeat.start()
        downloaded_parent = None
        try:
            self._post(job_id, "heartbeat", {"status": AcquisitionStatus.RUNNING.value})
            result = self.container.youtube.import_video(str(job["source_url"]))
            downloaded_parent = result.path.parent
            if result.path.stat().st_size > self.max_size:
                raise RuntimeError("UPLOAD_TOO_LARGE: The source is larger than the worker limit.")
            self._post(job_id, "heartbeat", {"status": AcquisitionStatus.UPLOADING.value})
            key = f"acquisitions/{job_id}/source{result.path.suffix.lower() or '.mp4'}"
            self.storage.put_file(key, result.path, content_type="video/mp4")
            self._post(job_id, "complete", {"storage_key": key, "metadata": {
                "title": result.metadata.title, "channel": result.metadata.channel,
                "youtube_strategy": result.strategy, "youtube_format": result.format_id,
                "size_bytes": result.path.stat().st_size,
            }})
        except Exception as error:  # Service normalizes known yt-dlp failures itself.
            text = self._safe_error(str(error))
            code = text.split(":", 1)[0] if ":" in text else "UNKNOWN"
            self._post(job_id, "fail", {"error_code": code, "error_message": text, "retryable": code not in {"PRIVATE_VIDEO", "AGE_RESTRICTED", "UPLOAD_TOO_LARGE"}})
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            if downloaded_parent is not None:
                shutil.rmtree(downloaded_parent, ignore_errors=True)

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(30):
            try:
                self._post(job_id, "heartbeat", {"status": AcquisitionStatus.RUNNING.value})
            except Exception:
                return

    def _post(self, job_id: str, action: str, payload: dict[str, object]) -> None:
        response = self.client.post(f"{self.api_url}/api/worker/jobs/{job_id}/{action}", headers=self.headers, json=payload)
        response.raise_for_status()

    def _safe_error(self, value: str) -> str:
        value = value.replace(self.token, "[redacted]")
        value = re.sub(r"(?i)(authorization|token|secret|cookie|password)=[^\s&]+", r"\1=[redacted]", value)
        value = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [redacted]", value)
        return value[:500]


def main() -> None:
    YouTubeWorker().run()


if __name__ == "__main__":
    main()
