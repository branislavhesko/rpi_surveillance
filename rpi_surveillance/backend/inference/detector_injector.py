import threading
import numpy as np

from rpi_surveillance.backend.inference.detector import ObjectDetector


class _DetectorInjector:
    """Lazily builds the ObjectDetector on first use (loads the Hailo model)."""

    def __init__(self):
        self._detector: ObjectDetector | None = None
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()

    def __call__(self) -> ObjectDetector:
        if self._detector is None:
            with self._lock:
                if self._detector is None:
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
        
    def close(self):
        with self._lock:    
            if self._detector is not None:
                self._detector.close()
                self._detector = None


detector_injector = _DetectorInjector()