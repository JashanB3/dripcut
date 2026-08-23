"""Run the DripCut API with ``python -m dripcut.api``."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "dripcut.api.app:create_app",
        host=os.environ.get("DRIPCUT_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("DRIPCUT_API_PORT", "8000")),
        reload=os.environ.get("DRIPCUT_API_RELOAD", "0") == "1",
        factory=True,
    )


if __name__ == "__main__":
    main()
