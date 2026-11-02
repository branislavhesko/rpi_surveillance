"""Small cached JPEG previews for recorded videos and captured images."""

import logging
from pathlib import Path

import cv2
import numpy as np

THUMB_DIR_NAME = "thumbnails"
THUMB_WIDTH = 320
THUMB_JPEG_PARAMS = [cv2.IMWRITE_JPEG_QUALITY, 75]

logger = logging.getLogger(__name__)


def thumbnail_path(media_path: Path) -> Path:
    return media_path.parent / THUMB_DIR_NAME / f"{media_path.name}.jpg"


def _read_video_frame(path: Path) -> np.ndarray | None:
    """Return a frame from ~1/3 into the clip, falling back to the first frame."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if count > 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, count // 3)
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def _read_source_frame(path: Path) -> np.ndarray | None:
    if path.suffix.lower() == ".mp4":
        return _read_video_frame(path)
    return cv2.imread(str(path))


def _scale(frame: np.ndarray, width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    size = (width, max(1, round(h * width / w)))
    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def ensure_thumbnail(media_path: Path, width: int = THUMB_WIDTH) -> Path | None:
    """Create or reuse an up-to-date thumbnail; None if the source is unreadable."""
    thumb = thumbnail_path(media_path)
    try:
        if thumb.exists() and thumb.stat().st_mtime >= media_path.stat().st_mtime:
            return thumb
        frame = _read_source_frame(media_path)
        if frame is None or frame.size == 0:
            return None
        thumb.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(thumb), _scale(frame, width), THUMB_JPEG_PARAMS):
            return None
        return thumb
    except Exception as e:
        logger.warning(f"Could not create thumbnail for {media_path}: {e}")
        return None


def remove_thumbnail(media_path: Path) -> None:
    thumbnail_path(media_path).unlink(missing_ok=True)
