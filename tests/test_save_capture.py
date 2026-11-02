import cv2
import numpy as np
import pytest

from rpi_surveillance.backend.camera import save_capture


def test_save_capture_writes_readable_jpeg(tmp_path):
    frame = np.full((72, 128, 3), 200, dtype=np.uint8)

    path = save_capture(frame, tmp_path)

    assert path.startswith(str(tmp_path / "capture_"))
    assert path.endswith(".jpg")
    assert cv2.imread(path).shape == (72, 128, 3)


def test_quick_successive_captures_do_not_overwrite(tmp_path):
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    paths = {save_capture(frame, tmp_path) for _ in range(5)}
    assert len(list(tmp_path.glob("capture_*.jpg"))) == len(paths)


def test_save_capture_raises_when_write_fails(tmp_path):
    with pytest.raises(RuntimeError):
        save_capture(np.zeros((10, 10, 3), dtype=np.uint8), tmp_path / "missing")


def test_save_capture_rejects_empty_frame(tmp_path):
    with pytest.raises(RuntimeError):
        save_capture(np.zeros((0, 0, 3), dtype=np.uint8), tmp_path)
