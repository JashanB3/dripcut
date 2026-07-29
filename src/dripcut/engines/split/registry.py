"""Registry mapping :class:`SplitMode` values to strategy instances."""

from __future__ import annotations

from dripcut.core.errors import ValidationError
from dripcut.engines.split.ai_highlight import AIHighlightSplit
from dripcut.engines.split.base import SplitStrategy
from dripcut.engines.split.chapters import ChapterSplit
from dripcut.engines.split.fixed import FixedLengthSplit
from dripcut.engines.split.scene import SceneSplit
from dripcut.engines.split.silence import SilenceSplit
from dripcut.engines.split.timestamps import TimestampSplit
from dripcut.models.clip import SplitMode

__all__ = ["SplitRegistry", "build_default_registry"]


class SplitRegistry:
    """Look-up table for split strategies, extensible by plugins."""

    def __init__(self) -> None:
        self._strategies: dict[SplitMode, SplitStrategy] = {}

    def register(self, strategy: SplitStrategy, *, replace: bool = False) -> None:
        """Add a strategy.

        Args:
            strategy: Instance to register.
            replace: Allow overwriting an existing mode (used by plugins that
                improve on a built-in strategy).

        Raises:
            ValidationError: If the mode is taken and ``replace`` is false.
        """
        if strategy.mode in self._strategies and not replace:
            raise ValidationError(f"Split mode {strategy.mode.value!r} is already registered.")
        self._strategies[strategy.mode] = strategy

    def get(self, mode: SplitMode | str) -> SplitStrategy:
        """Resolve a strategy by mode.

        Raises:
            ValidationError: For an unknown mode.
        """
        key = SplitMode(str(mode))
        strategy = self._strategies.get(key)
        if strategy is None:
            raise ValidationError(f"Split mode {key.value!r} is not available.")
        return strategy

    def modes(self) -> list[SplitMode]:
        """Registered modes in menu order."""
        order = list(SplitMode)
        return sorted(self._strategies, key=lambda mode: order.index(mode))

    def choices(self, *, include_ai: bool = True) -> list[tuple[str, str]]:
        """``(label, value)`` pairs for the mode selector."""
        return [
            (mode.label, mode.value)
            for mode in self.modes()
            if include_ai or not self._strategies[mode].requires_ai
        ]


def build_default_registry() -> SplitRegistry:
    """Registry containing every built-in split mode."""
    registry = SplitRegistry()
    for strategy in (
        FixedLengthSplit(),
        SceneSplit(),
        SilenceSplit(),
        TimestampSplit(),
        ChapterSplit(),
        AIHighlightSplit(),
    ):
        registry.register(strategy)
    return registry
