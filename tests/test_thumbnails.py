import cv2
import numpy as np

from rpi_surveillance.backend.thumbnails import (
    ensure_thumbnail,
    remove_thumbnail,
    thumbnail_path,
)


def _write_video(path, frames=9, size=(640, 360)):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, size)
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), i * 20, dtype=np.uint8))
    writer.release()


def test_image_thumbnail_is_scaled_and_cached(tmp_path):
    src = tmp_path / "capture_1.jpg"
    cv2.imwrite(str(src), np.zeros((480, 1280, 3), dtype=np.uint8))

    thumb = ensure_thumbnail(src, width=320)

    assert thumb == thumbnail_path(src)
    assert thumb.parent.name == "thumbnails"
    assert cv2.imread(str(thumb)).shape[:2] == (120, 320)
    mtime = thumb.stat().st_mtime_ns
    assert ensure_thumbnail(src, width=320) == thumb
    assert thumb.stat().st_mtime_ns == mtime


def test_video_thumbnail(tmp_path):
    src = tmp_path / "recording_1.mp4"
    _write_video(src)

    thumb = ensure_thumbnail(src, width=160)

    assert thumb is not None
    assert cv2.imread(str(thumb)).shape[:2] == (90, 160)


def test_unreadable_source_returns_none(tmp_path):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"not a video")
    assert ensure_thumbnail(src) is None
    assert not thumbnail_path(src).exists()


def test_remove_thumbnail(tmp_path):
    src = tmp_path / "capture_2.jpg"
    cv2.imwrite(str(src), np.zeros((10, 10, 3), dtype=np.uint8))
    thumb = ensure_thumbnail(src)
    remove_thumbnail(src)
    remove_thumbnail(src)
    assert not thumb.exists()
