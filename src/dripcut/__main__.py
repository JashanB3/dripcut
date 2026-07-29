"""Allow ``python -m dripcut`` as an alias for the ``dripcut`` command."""

from __future__ import annotations

from dripcut.cli.main import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
