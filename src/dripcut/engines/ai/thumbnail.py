"""Objective frame-quality signals used before editorial AI ranking."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class FrameQuality:
    path: Path
    timestamp: float
    sharpness: float
    brightness: float
    contrast: float
    face_count: int
    face_center_score: float
    quality_score: float

    def prompt_payload(self, *, frame_id: str, nearby_text: str = "") -> dict[str, object]:
        payload = asdict(self)
        payload.pop("path")
        payload["id"] = frame_id
        payload["nearby_transcript"] = nearby_text[:500]
        return payload


def inspect_frame(path: Path, timestamp: float) -> FrameQuality | None:
    """Return inexpensive composition and image-quality signals for one frame."""
    image = cv2.imread(str(path))
    if image is None or image.size == 0:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    faces = _faces(gray)
    height, width = gray.shape[:2]
    center_score = 0.0
    if faces:
        frame_center_x = width / 2
        frame_center_y = height / 2
        distances = []
        for x, y, face_width, face_height in faces:
            face_x = x + face_width / 2
            face_y = y + face_height / 2
            normalized = abs(face_x - frame_center_x) / max(width / 2, 1)
            normalized += abs(face_y - frame_center_y) / max(height / 2, 1)
            distances.append(normalized / 2)
        center_score = max(0.0, 1.0 - min(distances))
    exposure = max(0.0, 1.0 - abs(brightness - 128) / 128)
    score = (
        min(1.0, sharpness / 800) * 0.38
        + exposure * 0.20
        + min(1.0, contrast / 64) * 0.14
        + min(1.0, len(faces) / 2) * 0.16
        + center_score * 0.12
    )
    return FrameQuality(
        path=path,
        timestamp=round(timestamp, 3),
        sharpness=round(sharpness, 3),
        brightness=round(brightness, 3),
        contrast=round(contrast, 3),
        face_count=len(faces),
        face_center_score=round(center_score, 3),
        quality_score=round(score * 100, 2),
    )


def usable_frames(frames: list[FrameQuality], *, limit: int = 8) -> list[FrameQuality]:
    """Drop objectively unusable frames while retaining a deterministic fallback."""
    filtered = [
        frame
        for frame in frames
        if 18 <= frame.brightness <= 238 and frame.sharpness >= 8
    ]
    candidates = filtered or frames
    return sorted(candidates, key=lambda frame: frame.quality_score, reverse=True)[:limit]


def _faces(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    classifier = getattr(cv2, "CascadeClassifier", None)
    data = getattr(cv2, "data", None)
    cascades = getattr(data, "haarcascades", None)
    if classifier is None or not cascades:
        return []
    try:
        cascade = classifier(str(Path(cascades) / "haarcascade_frontalface_default.xml"))
        if cascade.empty():
            return []
        found = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(42, 42))
        return [tuple(int(value) for value in face) for face in found]
    except (AttributeError, cv2.error):
        return []
