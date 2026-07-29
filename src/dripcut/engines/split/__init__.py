"""Split planning: turn a source file into a reviewable list of segments.

Every mode implements :class:`~dripcut.engines.split.base.SplitStrategy` and is
registered in :mod:`dripcut.engines.split.registry`. Adding a seventh mode means
adding one file and one registry line - no changes to the service or the UI.
"""

from __future__ import annotations

from dripcut.engines.split.base import SplitContext, SplitStrategy
from dripcut.engines.split.registry import SplitRegistry, build_default_registry

__all__ = ["SplitContext", "SplitRegistry", "SplitStrategy", "build_default_registry"]
