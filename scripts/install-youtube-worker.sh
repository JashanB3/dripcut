#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${DRIPCUT_WORKER_PYTHON:-$ROOT/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"
for command in "$PYTHON_BIN" node ffmpeg ffprobe; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$node_major" -ge 20 ]] || { echo "Node 20 or later is required." >&2; exit 1; }
"$PYTHON_BIN" -c 'import yt_dlp, yt_dlp_plugins.extractor.getpot_bgutil, httpx' || { echo "Install the project Python dependencies first." >&2; exit 1; }
[[ -f "$ROOT/.env.worker" ]] || cp "$ROOT/.env.worker.example" "$ROOT/.env.worker"
mkdir -p "$ROOT/.worker-logs"
echo "Worker prerequisites checked. Fill .env.worker, then run scripts/start-youtube-worker.sh"
