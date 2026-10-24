"""Process-wide access to the single Hailo-backed ObjectDetector."""

import threading

import numpy as np

from rpi_surveillance.backend.inference.detection import Detection


class _DetectorInjector:
    """Lazily builds the ObjectDetector on first use (loads the Hailo model)."""

    def __init__(self):
        self._detector = None
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()

    def __call__(self):
        if self._detector is None:
            with self._lock:
                if self._detector is None:
                    # Imported here so modules depending on the injector stay
                    # importable on machines without the Hailo SDK.
                    from rpi_surveillance.backend.inference.detector import (
                        ObjectDetector,
                    )

                    self._detector = ObjectDetector()
        return self._detector

    def detect(self, frame: np.ndarray) -> np.ndarray:
        """Annotate a frame, serialising access to the single Hailo device.

        Concurrent streams and requests all share one accelerator, so inference
        is funnelled through a lock rather than interleaved on it.
        """
        detector = self()
        with self._infer_lock:
            return detector.detect(frame)

    def detect_objects(self, frame: np.ndarray) -> list[Detection]:
        """Return the objects detected in a frame (serialised like :meth:`detect`)."""
        detector = self()
        with self._infer_lock:
            return detector.detect_objects(frame)

    def annotate(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        """Draw already-computed detections; no inference, so no device lock."""
        return self().annotate(frame, detections)

    def close(self):
        with self._lock:
            if self._detector is not None:
                self._detector.close()
                self._detector = None


detector_injector = _DetectorInjector()
