"""Host-aware video encoder selection behind a replaceable provider boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

__all__ = ["CapabilityEncoderProvider", "EncoderProvider", "EncoderSelection"]


@dataclass(frozen=True, slots=True)
class EncoderSelection:
    """Concrete FFmpeg encoder chosen for a logical video codec."""

    codec: str
    encoder: str
    provider: str
    hardware: bool


class EncoderProvider(Protocol):
    """Select a concrete encoder without coupling callers to one host type."""

    def select(self, codec: str, *, hardware: bool = True) -> EncoderSelection: ...


class CapabilityEncoderProvider:
    """Prefer host hardware encoders and fall back to portable software codecs."""

    _TABLE = {
        "h264": (("h264_videotoolbox", "h264_nvenc"), "libx264"),
        "hevc": (("hevc_videotoolbox", "hevc_nvenc"), "libx265"),
        "h265": (("hevc_videotoolbox", "hevc_nvenc"), "libx265"),
        "vp9": ((), "libvpx-vp9"),
        "av1": ((), "libsvtav1"),
        "prores": ((), "prores_ks"),
    }

    def __init__(self, available_encoders: Callable[[], frozenset[str]]) -> None:
        self._available_encoders = available_encoders

    def select(self, codec: str, *, hardware: bool = True) -> EncoderSelection:
        logical_codec = codec.lower()
        hardware_names, software_name = self._TABLE.get(logical_codec, ((), codec))
        available = self._available_encoders()

        if hardware:
            for name in hardware_names:
                if self._available(name, available):
                    return EncoderSelection(
                        codec=logical_codec,
                        encoder=name,
                        provider=self._provider_name(name),
                        hardware=True,
                    )

        selected = software_name if self._available(software_name, available) else "libx264"
        return EncoderSelection(
            codec=logical_codec,
            encoder=selected,
            provider="software",
            hardware=False,
        )

    @staticmethod
    def _available(name: str, available: frozenset[str]) -> bool:
        # Preserve the runner's optimistic behavior when FFmpeg cannot enumerate codecs.
        return not available or name in available

    @staticmethod
    def _provider_name(encoder: str) -> str:
        if encoder.endswith("_videotoolbox"):
            return "apple_videotoolbox"
        if encoder.endswith("_nvenc"):
            return "nvidia_nvenc"
        return "software"
