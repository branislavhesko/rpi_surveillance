#!/usr/bin/env python3
"""Synchronous, single-frame object detection for request/response code paths.

Unlike ``object_detection.py`` (a continuous-stream CLI pipeline built on
threads and queues), this module is meant to be called like a function: hand
it one camera frame, get one annotated frame back. Suitable for use from a
FastAPI endpoint or any other synchronous handler.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

# -----------------------------------------------------------------------------
# Ensure repository root is available in sys.path (same lookup as object_detection.py)
# -----------------------------------------------------------------------------
_repo_root = None
for _p in Path(__file__).resolve().parents:
    if (_p / "hailo_apps" / "config" / "config_manager.py").exists():
        _repo_root = _p
        break

if _repo_root is not None:
    sys.path.insert(0, str(_repo_root))

from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.toolbox import get_labels, load_json_file, default_preprocess
from hailo_apps.python.core.common.core import resolve_hef_path

from rpi_surveillance.backend.inference.object_detection_postprocess import (
    extract_detections,
    draw_detections,
)

APP_NAME = "object_detection"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


class HailoModel:
    """Thin synchronous wrapper around ``HailoInfer`` for one frame at a time."""

    def __init__(self, hef_path: str | Path, batch_size: int = 1):
        self._hailo = HailoInfer(str(hef_path), batch_size)
        self.input_height, self.input_width, _ = self._hailo.get_input_shape()

    def infer(self, preprocessed_frame: np.ndarray, timeout_ms: int = 10000):
        """Run inference on one preprocessed frame and block until the result is ready."""
        result_box: dict = {}

        def _on_done(completion_info, bindings_list):
            if completion_info.exception:
                result_box["error"] = completion_info.exception
                return
            bindings = bindings_list[0]
            if len(bindings._output_names) == 1:
                result_box["result"] = bindings.output().get_buffer()
            else:
                result_box["result"] = {
                    name: np.expand_dims(bindings.output(name).get_buffer(), axis=0)
                    for name in bindings._output_names
                }

        job = self._hailo.run([preprocessed_frame], _on_done)
        job.wait(timeout_ms)

        if "error" in result_box:
            raise RuntimeError(f"Hailo inference failed: {result_box['error']}")
        return result_box.get("result")

    def close(self) -> None:
        self._hailo.close()


def frame_to_model_input(frame_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Convert a BGR camera frame into the letterboxed RGB tensor the model expects."""
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return default_preprocess(frame_rgb, width, height)


class ObjectDetector:
    """Detect objects in individual camera frames and draw the results.

    Usage::

        detector = ObjectDetector()          # auto-resolves/downloads the default HEF
        annotated = detector.detect(frame)   # frame: BGR np.ndarray from a camera
        detector.close()

    or as a context manager: ``with ObjectDetector() as detector: ...``
    """

    def __init__(
        self,
        hef_path: str | Path | None = None,
        labels_path: str | Path | None = None,
        config_path: str | Path | None = None,
    ):
        if hef_path is None:
            hef_path = resolve_hef_path(None, APP_NAME, app_type="standalone")
        if hef_path is None:
            raise RuntimeError(f"Could not resolve a default HEF model for '{APP_NAME}'.")

        self.labels = get_labels(str(labels_path) if labels_path else None)
        self.config_data = load_json_file(str(config_path or DEFAULT_CONFIG_PATH))
        self.model = HailoModel(hef_path)

    def detect(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Run detection on one BGR frame and return it annotated with boxes and labels."""
        detections = self._infer(frame_bgr)
        return draw_detections(detections, frame_bgr.copy(), self.labels)

    def _infer(self, frame_bgr: np.ndarray) -> dict:
        model_input = frame_to_model_input(frame_bgr, self.model.input_width, self.model.input_height)
        raw_result = self.model.infer(model_input)
        return extract_detections(frame_bgr, raw_result, self.config_data)

    def close(self) -> None:
        self.model.close()

    def __enter__(self) -> "ObjectDetector":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
