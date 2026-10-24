"""Gatekeeper: watch the camera and react when a person or animal shows up.

A background thread samples frames at a low rate and runs object detection.
When an object of a watched class appears, recording starts and a Telegram
alert with an annotated snapshot is sent. Recording stops once nothing watched
has been seen for ``hold_seconds`` (or ``max_recording_seconds`` is reached).
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from rpi_surveillance.backend.inference.detection import Detection
from rpi_surveillance.config import load_env

logger = logging.getLogger(__name__)

# COCO animal classes, as named in the detector's label file.
ANIMAL_LABELS = frozenset(
    {
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
    }
)
HUMAN_LABELS = frozenset({"person"})

# Aliases accepted in ``GATEKEEPER_CLASSES``; anything else is a literal label.
CLASS_GROUPS: dict[str, frozenset[str]] = {
    "human": HUMAN_LABELS,
    "humans": HUMAN_LABELS,
    "people": HUMAN_LABELS,
    "animal": ANIMAL_LABELS,
    "animals": ANIMAL_LABELS,
}

DEFAULT_CLASSES = "human,animal"


def resolve_classes(spec: str) -> frozenset[str]:
    """Expand a comma-separated class spec (e.g. ``"human,animal,car"``) to labels."""
    labels: set[str] = set()
    for name in spec.split(","):
        name = name.strip().lower()
        if name:
            labels |= CLASS_GROUPS.get(name, {name})
    return frozenset(labels)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"Invalid {name}={raw!r}; using {default}")
        return default


@dataclass
class GateKeeperConfig:
    classes: frozenset[str] = field(
        default_factory=lambda: resolve_classes(DEFAULT_CLASSES)
    )
    min_score: float = 0.5
    fps: float = 2.0
    hold_seconds: float = 10.0
    max_recording_seconds: float = 300.0
    notify_cooldown_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "GateKeeperConfig":
        load_env()
        return cls(
            classes=resolve_classes(
                os.environ.get("GATEKEEPER_CLASSES", DEFAULT_CLASSES)
            ),
            min_score=_env_float("GATEKEEPER_MIN_SCORE", cls.min_score),
            fps=_env_float("GATEKEEPER_FPS", cls.fps),
            hold_seconds=_env_float("GATEKEEPER_HOLD_SECONDS", cls.hold_seconds),
            max_recording_seconds=_env_float(
                "GATEKEEPER_MAX_RECORDING_SECONDS", cls.max_recording_seconds
            ),
            notify_cooldown_seconds=_env_float(
                "GATEKEEPER_NOTIFY_COOLDOWN_SECONDS", cls.notify_cooldown_seconds
            ),
        )

    def matches(self, detection: Detection) -> bool:
        return (
            detection.score >= self.min_score
            and detection.label.lower() in self.classes
        )


class Camera(Protocol):
    @property
    def recording(self) -> bool: ...
    def capture_image(self) -> np.ndarray: ...
    def start_recording(self) -> str: ...
    def stop_recording(self) -> str | None: ...


class Detector(Protocol):
    def detect_objects(self, frame: np.ndarray) -> list[Detection]: ...
    def annotate(
        self, frame: np.ndarray, detections: list[Detection]
    ) -> np.ndarray: ...


class Notifier(Protocol):
    def send_async(self, text: str, image_jpeg: bytes | None = None): ...


def _summarize(detections: list[Detection]) -> str:
    """``"person 91%, dog 78%"`` — best score per label, highest first."""
    best: dict[str, float] = {}
    for d in detections:
        best[d.label] = max(best.get(d.label, 0.0), d.score)
    return ", ".join(
        f"{label} {score:.0%}"
        for label, score in sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    )


class GateKeeper:
    def __init__(
        self,
        camera: Camera,
        detector: Detector,
        notifier: Notifier | None = None,
        config: GateKeeperConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.camera = camera
        self.detector = detector
        self.notifier = notifier
        self.config = config or GateKeeperConfig()
        self._clock = clock
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

        self._event_started: float | None = None
        self._last_seen: float | None = None
        self._last_notified: float | None = None
        self._owns_recording = False
        self._recording_path: str | None = None
        self._last_labels = ""
        self._last_error: str | None = None
        self.events = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def event_active(self) -> bool:
        return self._event_started is not None

    def start(self) -> "GateKeeper":
        if self.running:
            return self
        watched = ", ".join(sorted(self.config.classes))
        logger.info(f"Starting gatekeeper (watching: {watched})")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="gatekeeper", daemon=True
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 15.0) -> None:
        if self._thread is None:
            return
        logger.info("Stopping gatekeeper")
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        self._thread = None

    def status(self) -> dict:
        return {
            "running": self.running,
            "event_active": self.event_active,
            "recording": Path(self._recording_path).name
            if self._recording_path
            else None,
            "last_detection": self._last_labels or None,
            "events": self.events,
            "classes": sorted(self.config.classes),
            "notifications": self.notifier is not None,
            "last_error": self._last_error,
        }

    def _loop(self) -> None:
        interval = 1.0 / self.config.fps if self.config.fps > 0 else 0.0
        try:
            while not self._stop_event.is_set():
                started = self._clock()
                try:
                    self.process_frame(self.camera.capture_image())
                    self._last_error = None
                except Exception as e:
                    if str(e) != self._last_error:
                        logger.error(f"Gatekeeper iteration failed: {e}")
                    self._last_error = str(e)
                self._stop_event.wait(max(0.0, interval - (self._clock() - started)))
        finally:
            self._end_event()

    # ── Detection handling ────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray) -> list[Detection]:
        """Run one gatekeeper step on ``frame``; returns the matching detections."""
        matches = [
            d for d in self.detector.detect_objects(frame) if self.config.matches(d)
        ]
        now = self._clock()
        with self._state_lock:
            if matches:
                self._last_seen = now
                self._last_labels = _summarize(matches)
                if not self.event_active:
                    self._begin_event(frame, matches, now)
            if self.event_active:
                idle = now - self._last_seen
                duration = now - self._event_started
                if idle >= self.config.hold_seconds:
                    self._end_event()
                elif duration >= self.config.max_recording_seconds:
                    logger.info("Gatekeeper recording hit max duration; splitting")
                    self._end_event()
                    if matches:
                        self._begin_event(frame, matches, now)
        return matches

    def _begin_event(
        self, frame: np.ndarray, matches: list[Detection], now: float
    ) -> None:
        self.events += 1
        self._event_started = now
        summary = _summarize(matches)
        logger.info(f"Gatekeeper triggered: {summary}")

        # Never hijack a recording someone started by hand: only stop what we start.
        if not self.camera.recording:
            try:
                self._recording_path = self.camera.start_recording()
                self._owns_recording = True
            except Exception as e:
                logger.error(f"Gatekeeper could not start recording: {e}")

        self._notify(frame, matches, summary, now)

    def _end_event(self) -> None:
        if self._owns_recording:
            try:
                path = self.camera.stop_recording()
                logger.info(f"Gatekeeper recording saved: {path}")
            except Exception as e:
                logger.error(f"Gatekeeper could not stop recording: {e}")
        self._owns_recording = False
        self._recording_path = None
        self._event_started = None

    def _notify(
        self, frame: np.ndarray, matches: list[Detection], summary: str, now: float
    ) -> None:
        if self.notifier is None:
            return
        cooldown = self.config.notify_cooldown_seconds
        if self._last_notified is not None and now - self._last_notified < cooldown:
            return
        self._last_notified = now

        text = f"Gatekeeper: detected {summary} at {datetime.now():%Y-%m-%d %H:%M:%S}"
        if self._recording_path:
            text += f"\nRecording: {Path(self._recording_path).name}"
        image = None
        try:
            annotated = self.detector.annotate(frame, matches)
            ok, buf = cv2.imencode(
                ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            )
            image = buf.tobytes() if ok else None
        except Exception as e:
            logger.warning(f"Could not render gatekeeper snapshot: {e}")
        self.notifier.send_async(text, image)
