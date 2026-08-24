"""Portrait reframing helpers.

The split page uses these helpers when the user chooses a 9:16 export. The
goal is to keep the main subject in frame with the least surprising amount of
zoom, while falling back cleanly to a centered crop when detection is weak.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "TrackedCrop",
    "PortraitAnalysis",
    "build_tracked_crop",
    "build_blur_background_filters",
]

ProgressFn = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class TrackedCrop:
    """A crop rectangle expressed as FFmpeg expressions."""

    width: str
    height: str
    x: str
    y: str


@dataclass(frozen=True, slots=True)
class PortraitAnalysis:
    """A sampled crop path used for smooth reframing."""

    crop: TrackedCrop
    has_tracking: bool


@dataclass(frozen=True, slots=True)
class _TrackPoint:
    time: float
    center_x: float
    center_y: float
    crop_width: float
    crop_height: float


def build_tracked_crop(
    source: Path,
    duration: float,
    *,
    target_aspect: float = 9 / 16,
    samples: int = 12,
    source_offset: float = 0.0,
    on_progress: ProgressFn | None = None,
) -> PortraitAnalysis:
    """Return a tracked portrait crop, or a centered fallback if detection fails."""
    points = _analyse(
        source,
        duration,
        target_aspect=target_aspect,
        samples=samples,
        source_offset=source_offset,
        on_progress=on_progress,
    )
    if not points:
        return PortraitAnalysis(
            crop=TrackedCrop(
                width="trunc(min(iw\\,ih*9/16)/2)*2",
                height="trunc(ih/2)*2",
                x="trunc((iw-min(iw\\,ih*9/16))/2/2)*2",
                y="0",
            ),
            has_tracking=False,
        )

    return PortraitAnalysis(
        crop=TrackedCrop(
            width=_piecewise_expression([point.time for point in points], [point.crop_width for point in points]),
            height=_piecewise_expression([point.time for point in points], [point.crop_height for point in points]),
            x=_piecewise_expression([point.time for point in points], [point.center_x for point in points]),
            y=_piecewise_expression([point.time for point in points], [point.center_y for point in points]),
        ),
        has_tracking=True,
    )


def build_blur_background_filters(width: int, height: int, *, sigma: float = 24.0) -> list[str]:
    """Background-blur portrait filters that avoid bars."""
    return [
        "[0:v]split[bg][fg]",
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={sigma:g}[bg]",
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]",
    ]


def _analyse(
    source: Path,
    duration: float,
    *,
    target_aspect: float,
    samples: int,
    source_offset: float,
    on_progress: ProgressFn | None,
) -> list[_TrackPoint]:
    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001 - detection is a best-effort enhancement
        return []
    required = (
        "VideoCapture",
        "CAP_PROP_POS_MSEC",
        "COLOR_BGR2GRAY",
        "cvtColor",
        "resize",
    )
    if any(not hasattr(cv2, name) for name in required):
        return []

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        return []

    face_cascade = None
    try:
        cascade_root = getattr(getattr(cv2, "data", None), "haarcascades", "")
        if hasattr(cv2, "CascadeClassifier") and cascade_root:
            face_cascade = cv2.CascadeClassifier(
                cascade_root + "haarcascade_frontalface_default.xml"
            )
            if hasattr(face_cascade, "empty") and face_cascade.empty():
                face_cascade = None
    except Exception:  # noqa: BLE001 - center crop is safer than failing export
        face_cascade = None

    hog = None
    try:
        if hasattr(cv2, "HOGDescriptor") and hasattr(cv2, "HOGDescriptor_getDefaultPeopleDetector"):
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    except Exception:  # noqa: BLE001 - person detection is optional
        hog = None
    if face_cascade is None and hog is None:
        capture.release()
        return []

    sample_times = _sample_times(duration, samples)
    points: list[_TrackPoint] = []
    previous = None
    had_detection = False
    try:
        for index, time in enumerate(sample_times, start=1):
            if on_progress is not None:
                on_progress(min(0.85, index / max(1, len(sample_times) + 1)), "Tracking subject")
            capture.set(
                cv2.CAP_PROP_POS_MSEC,
                max(0.0, source_offset + time) * 1000.0,
            )
            ok, frame = capture.read()
            if not ok or frame is None:
                continue

            height, width = frame.shape[:2]
            try:
                box = _detect_focus_box(cv2, face_cascade, hog, frame)
            except Exception:  # noqa: BLE001 - a bad frame should not abort rendering
                box = None
            if box is None:
                if previous is None:
                    center_x = width / 2
                    center_y = height / 2
                    crop_height = min(height, max(2.0, width / target_aspect))
                else:
                    center_x, center_y, crop_height = previous
                crop_width = min(width, crop_height * target_aspect)
            else:
                x, y, box_w, box_h = box
                had_detection = True
                center_x = x + box_w / 2
                center_y = y + box_h / 2
                crop_height = _choose_crop_height(
                    frame_width=width,
                    frame_height=height,
                    target_aspect=target_aspect,
                    subject_width=box_w,
                    subject_height=box_h,
                )
                crop_width = min(width, crop_height * target_aspect)
                previous = (center_x, center_y, crop_height)

            crop_width = max(2.0, min(width, crop_width))
            crop_height = max(2.0, min(height, crop_height))
            x = max(0.0, min(width - crop_width, center_x - crop_width / 2))
            y = max(0.0, min(height - crop_height, center_y - crop_height / 2))
            points.append(
                _TrackPoint(
                    time=time,
                    center_x=x,
                    center_y=y,
                    crop_width=_even(crop_width),
                    crop_height=_even(crop_height),
                )
            )
    finally:
        capture.release()

    return points if had_detection else []


def _sample_times(duration: float, samples: int) -> list[float]:
    duration = max(0.1, float(duration))
    count = max(4, int(samples))
    start = max(0.0, duration * 0.08)
    end = max(start, duration - max(0.05, duration * 0.08))
    if end <= start:
        mid = duration / 2
        return [mid]
    if count == 1:
        return [(start + end) / 2]
    step = (end - start) / max(1, count - 1)
    return [start + step * index for index in range(count)]


def _detect_focus_box(cv2, face_cascade, hog, frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = 1.0
    small = gray
    if gray.shape[1] > 720:
        scale = 720 / gray.shape[1]
        small = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    if face_cascade is not None:
        faces = face_cascade.detectMultiScale(
            small,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(24, 24),
        )
        if len(faces):
            x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
            inv = 1 / max(1e-6, scale)
            return int(x * inv), int(y * inv), int(w * inv), int(h * inv)

    if hog is not None:
        people, _ = hog.detectMultiScale(
            small,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.04,
            finalThreshold=2,
        )
        if len(people):
            x, y, w, h = max(people, key=lambda box: box[2] * box[3])
            inv = 1 / max(1e-6, scale)
            return int(x * inv), int(y * inv), int(w * inv), int(h * inv)
    return None


def _choose_crop_height(
    *,
    frame_width: int,
    frame_height: int,
    target_aspect: float,
    subject_width: float,
    subject_height: float,
) -> float:
    """Pick a crop height that keeps the subject prominent without over-zooming."""
    max_height = min(float(frame_height), float(frame_width) / target_aspect)
    min_height = max(2.0, max_height * 0.68)
    occupied = max(subject_width / max(1.0, frame_width), subject_height / max(1.0, frame_height))
    zoom = max(1.0, min(1.24, 1.02 + (0.26 - occupied) * 0.85))
    crop_height = max_height / zoom
    return max(min_height, min(max_height, crop_height))


def _piecewise_expression(times: Sequence[float], values: Sequence[float]) -> str:
    """Render a sequence of keyframes as a nested FFmpeg expression."""
    if not times:
        return "0"
    points = list(zip(times, values, strict=False))
    if len(points) == 1:
        return _fmt(points[0][1])

    terms: list[str] = []
    for (start_t, start_v), (end_t, end_v) in zip(points, points[1:], strict=False):
        span = max(0.001, end_t - start_t)
        slope = f"(({_fmt(end_v)}-{_fmt(start_v)})*((t-{_fmt(start_t)})/{span:.3f}))"
        terms.append(f"if(lt(t\\,{_fmt(end_t)}),{_fmt(start_v)}+{slope},")
    terms.append(_fmt(points[-1][1]))
    return "".join(terms) + ")" * (len(points) - 1)


def _fmt(value: float) -> str:
    return f"{float(value):.3f}"


def _even(value: float) -> float:
    rounded = max(2.0, round(float(value)))
    return rounded - (rounded % 2)
