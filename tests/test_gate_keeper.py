import threading
import time

import numpy as np

from rpi_surveillance.backend.gate_keeper import (
    ANIMAL_LABELS,
    GateKeeper,
    GateKeeperConfig,
    resolve_classes,
)
from rpi_surveillance.backend.inference.detection import Detection

FRAME = np.zeros((90, 160, 3), dtype=np.uint8)


def det(label, score=0.9):
    return Detection(class_id=0, label=label, score=score, box=(10, 10, 50, 50))


class FakeCamera:
    def __init__(self):
        self.recording = False
        self.started = 0
        self.stopped = 0

    def capture_image(self):
        return FRAME

    def start_recording(self):
        self.recording = True
        self.started += 1
        return f"/rec/video_{self.started}.mp4"

    def stop_recording(self):
        self.recording = False
        self.stopped += 1
        return f"/rec/video_{self.started}.mp4"


class FakeDetector:
    def __init__(self):
        self.next = []
        self.annotated = []

    def detect_objects(self, frame):
        return list(self.next)

    def annotate(self, frame, detections):
        self.annotated.append(frame)
        return frame.copy()


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_async(self, text, image_jpeg=None):
        self.sent.append((text, image_jpeg))


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(**config):
    camera, detector, notifier, clock = (
        FakeCamera(),
        FakeDetector(),
        FakeNotifier(),
        Clock(),
    )
    gk = GateKeeper(camera, detector, notifier, GateKeeperConfig(**config), clock=clock)
    return gk, camera, detector, notifier, clock


def test_resolve_classes_expands_groups():
    assert resolve_classes("human, animal") == {"person"} | ANIMAL_LABELS
    assert resolve_classes("Car,dog") == {"car", "dog"}


def test_ignores_unwatched_and_low_score_objects():
    gk, camera, detector, notifier, _ = make()
    detector.next = [det("car"), det("person", score=0.2)]
    assert gk.process_frame(FRAME) == []
    assert camera.started == 0 and notifier.sent == []


def test_detection_starts_recording_and_notifies_with_snapshot():
    gk, camera, detector, notifier, _ = make(snapshot_delay_seconds=0)
    detector.next = [det("person", 0.91), det("dog", 0.7)]
    gk.process_frame(FRAME)
    assert camera.recording and camera.started == 1
    assert len(notifier.sent) == 1
    text, image = notifier.sent[0]
    assert "person 91%" in text and "dog 70%" in text and "video_1.mp4" in text
    assert image[:2] == b"\xff\xd8"  # JPEG


def test_alert_snapshot_is_middle_frame_after_delay():
    gk, camera, detector, notifier, clock = make(snapshot_delay_seconds=3)
    detector.next = [det("person")]
    for t in range(4):
        clock.t = t
        gk.process_frame(np.full_like(FRAME, t * 10))
        if t < 3:
            assert camera.recording and notifier.sent == []
    assert len(notifier.sent) == 1
    assert detector.annotated[-1][0, 0, 0] == 20
    assert "video_1.mp4" in notifier.sent[0][0]


def test_alert_sent_when_event_ends_before_delay():
    gk, camera, detector, notifier, clock = make(
        snapshot_delay_seconds=30, hold_seconds=2
    )
    detector.next = [det("dog")]
    for t in range(3):
        clock.t = t
        gk.process_frame(np.full_like(FRAME, t * 10))
    detector.next = []
    clock.t = 5
    gk.process_frame(FRAME)
    assert not camera.recording
    assert len(notifier.sent) == 1
    assert detector.annotated[-1][0, 0, 0] == 10


def test_recording_continues_while_seen_and_stops_after_hold():
    gk, camera, detector, notifier, clock = make(hold_seconds=10)
    detector.next = [det("cat")]
    gk.process_frame(FRAME)
    clock.t = 8
    gk.process_frame(FRAME)
    detector.next = []
    clock.t = 17
    gk.process_frame(FRAME)
    assert camera.recording and camera.started == 1
    clock.t = 18
    gk.process_frame(FRAME)
    assert not camera.recording and camera.stopped == 1
    assert len(notifier.sent) == 1


def test_notification_cooldown_between_events():
    gk, camera, detector, notifier, clock = make(
        hold_seconds=1, notify_cooldown_seconds=60, snapshot_delay_seconds=0
    )
    for t, seen in [(0, True), (2, False), (10, True), (12, False), (70, True)]:
        clock.t = t
        detector.next = [det("person")] if seen else []
        gk.process_frame(FRAME)
    assert camera.started == 3
    assert len(notifier.sent) == 2


def test_max_duration_splits_recording():
    gk, camera, detector, _, clock = make(max_recording_seconds=30)
    detector.next = [det("person")]
    for t in range(0, 35, 5):
        clock.t = t
        gk.process_frame(FRAME)
    assert camera.stopped == 1 and camera.started == 2 and camera.recording


def test_does_not_touch_manual_recording():
    gk, camera, detector, notifier, clock = make(hold_seconds=1)
    camera.recording = True
    detector.next = [det("person")]
    gk.process_frame(FRAME)
    detector.next = []
    clock.t = 5
    gk.process_frame(FRAME)
    assert camera.started == 0 and camera.stopped == 0 and camera.recording
    assert len(notifier.sent) == 1


def test_works_without_notifier():
    camera, detector = FakeCamera(), FakeDetector()
    gk = GateKeeper(camera, detector, None, GateKeeperConfig())
    detector.next = [det("person")]
    gk.process_frame(FRAME)
    assert camera.recording


def test_thread_lifecycle_finalises_recording_on_stop():
    camera, detector = FakeCamera(), FakeDetector()
    detector.next = [det("person")]
    gk = GateKeeper(camera, detector, None, GateKeeperConfig(fps=50)).start()
    deadline = time.monotonic() + 2
    while not camera.recording and time.monotonic() < deadline:
        time.sleep(0.01)
    assert gk.running and camera.recording
    gk.stop()
    assert not gk.running and not camera.recording
    assert gk.status()["running"] is False


def test_loop_survives_capture_errors():
    camera, detector = FakeCamera(), FakeDetector()
    calls = threading.Event()

    def failing_capture():
        calls.set()
        raise RuntimeError("no frame")

    camera.capture_image = failing_capture
    gk = GateKeeper(camera, detector, None, GateKeeperConfig(fps=50)).start()
    assert calls.wait(2)
    time.sleep(0.1)
    assert gk.running
    assert gk.status()["last_error"] == "no frame"
    gk.stop()


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("GATEKEEPER_CLASSES", "animal")
    monkeypatch.setenv("GATEKEEPER_MIN_SCORE", "0.7")
    monkeypatch.setenv("GATEKEEPER_HOLD_SECONDS", "oops")
    monkeypatch.setenv("GATEKEEPER_SNAPSHOT_DELAY_SECONDS", "5")
    cfg = GateKeeperConfig.from_env()
    assert cfg.snapshot_delay_seconds == 5.0
    assert cfg.classes == ANIMAL_LABELS
    assert cfg.min_score == 0.7
    assert cfg.hold_seconds == 5.0
    assert cfg.max_recording_seconds == 60.0
    assert cfg.notify_cooldown_seconds == 30.0
