#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${DRIPCUT_WORKER_ENV_FILE:-$ROOT/.env.worker}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Create $ROOT/.env.worker from .env.worker.example first." >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
PYTHON_BIN="${DRIPCUT_WORKER_PYTHON:-$ROOT/.venv/bin/python}"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"
exec "$PYTHON_BIN" -m dripcut.acquisition.worker
