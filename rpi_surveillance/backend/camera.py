from datetime import datetime
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np
from pydantic import BaseModel
try:
    from picamera2 import Picamera2
except Exception:  # pragma: no cover - only present on a Raspberry Pi
    Picamera2 = None


JPEG_QUALITY = 80
JPEG_ENCODE_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
TARGET_RESOLUTION = (1920, 1080)
DEFAULT_RTSP_URL = "rtsp://192.168.1.100:8554/stream"
RECORDINGS_DIR = Path("/home/brani/recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _redact_url(url: str) -> str:
    """Mask the password in an RTSP URL so it is safe to log."""
    try:
        parts = urlsplit(url)
        if parts.password:
            netloc = parts.netloc.replace(f":{parts.password}@", ":****@", 1)
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        pass
    return url


def _fit_resolution(frame: np.ndarray, size: tuple[int, int] = TARGET_RESOLUTION) -> np.ndarray:
    """Resize ``frame`` to ``size`` (Full HD by default) if it differs."""
    h, w = frame.shape[:2]
    if (w, h) == size:
        return frame
    interp = cv2.INTER_AREA if (w * h) > (size[0] * size[1]) else cv2.INTER_LINEAR
    return cv2.resize(frame, size, interpolation=interp)

# libcamera allows only one Picamera2 object per camera per process. Constructing
# a fresh Picamera2() on every start double-acquires the device and fails with
# "Camera in Configured state trying acquire() requiring state Available", so we
# keep a single shared instance and reuse it.
_PICAM2 = None
_PICAM2_LOCK = threading.Lock()


def _get_picam2():
    """Return the process-wide Picamera2 singleton, creating it on first use."""
    global _PICAM2
    if Picamera2 is None:
        raise RuntimeError("PiCamera2 is not available on this machine")
    with _PICAM2_LOCK:
        if _PICAM2 is None:
            _PICAM2 = Picamera2()
        return _PICAM2


def _transform_image(image: np.ndarray) -> np.ndarray:
    return np.flip(image, axis=0)


class Settings(BaseModel):
    resolution: tuple[int, int] = TARGET_RESOLUTION
    framerate: int = 30
    format: str = "RGB888"

    def to_dict(self):
        return {"size": self.resolution, "format": self.format}



class PiCameraHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing camera")
        self.picam2 = _get_picam2()
        self._settings = Settings()
        # Make sure the shared instance is stopped before reconfiguring it.
        try:
            self.picam2.stop()
        except Exception:
            pass
        self.picam2.configure(self.picam2.create_preview_configuration(self._settings.to_dict()))
        self.streaming_active = False
        self._recording = False
        self._recording_proc: subprocess.Popen | None = None
        self._recording_thread: threading.Thread | None = None
        self._recording_path: str | None = None
        self._capture_lock = threading.Lock()

    def start(self):
        self.logger.info("Starting camera")
        self.picam2.start()
        return self

    def stop(self):
        self.logger.info("Stopping camera")
        try:
            self.picam2.stop()
        except Exception as e:
            self.logger.error(f"Error stopping camera: {e}")
        return self

    def close(self):
        """Stop the shared camera instance (kept alive for reuse across handlers)."""
        self.logger.info("Stopping camera and releasing pipeline")
        self.stop_recording()
        try:
            self.picam2.stop()
        except Exception as e:
            self.logger.warning(f"Error stopping camera during close: {e}")
        return self

    def capture_image(self):
        with self._capture_lock:
            np_array = self.picam2.capture_array()
            np_array = np.ascontiguousarray(np_array)
        return np_array

    def next_frame(self, last_seq: int = 0, timeout: float = 5.0) -> tuple[np.ndarray, int]:
        """Grab a frame, mirroring :meth:`RTSPCameraHandler.next_frame`.

        PiCamera2 hands back a fresh capture on every call, so there is no
        already-seen frame to skip and the sequence number merely counts up.
        """
        return self.capture_image(), last_seq + 1

    def save_image(self) -> str:
        """Capture and save a single frame as JPEG."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = str(RECORDINGS_DIR / f"capture_{timestamp}.jpg")
        frame = self.capture_image()
        cv2.imwrite(filename, frame, JPEG_ENCODE_PARAMS)
        self.logger.info(f"Saved image to {filename}")
        return filename

    def start_recording(self) -> str:
        """Start recording video to an MP4 file (H.264 via ffmpeg)."""
        if self._recording:
            return self._recording_path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._recording_path = str(RECORDINGS_DIR / f"video_{timestamp}.mp4")
        frame = self.capture_image()
        h, w = frame.shape[:2]
        self._recording_proc = subprocess.Popen(
            ['ffmpeg', '-y',
             '-f', 'rawvideo', '-pix_fmt', 'bgr24',
             '-s', f'{w}x{h}', '-r', '15',
             '-i', '-',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
             '-pix_fmt', 'yuv420p',
             self._recording_path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._recording = True
        self._recording_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._recording_thread.start()
        self.logger.info(f"Started recording to {self._recording_path}")
        return self._recording_path
    
    def start_gatekeeper(self):
        self.logger.info("Starting gatekeeper")
        self._gatekeeper_thread = threading.Thread(target=self._gatekeeper_loop, daemon=True)
        self._gatekeeper_thread.start()
        return self
            

    def _record_loop(self):
        """Background thread: capture frames and pipe to ffmpeg."""
        while self._recording:
            try:
                frame = self.capture_image()
                self._recording_proc.stdin.write(frame.tobytes())
            except Exception as e:
                self.logger.error(f"Error recording frame: {e}")
                break
            time.sleep(1 / 15)

    def stop_recording(self) -> str | None:
        """Stop recording and finalise the video file."""
        if not self._recording:
            return None
        self._recording = False
        if self._recording_thread:
            self._recording_thread.join(timeout=5)
            self._recording_thread = None
        if self._recording_proc:
            try:
                self._recording_proc.stdin.close()
                self._recording_proc.wait(timeout=30)
            except Exception as e:
                self.logger.error(f"Error finalizing recording: {e}")
                self._recording_proc.kill()
            self._recording_proc = None
        path = self._recording_path
        self._recording_path = None
        self.logger.info(f"Stopped recording, saved to {path}")
        return path

    def restart_camera(self):
        """Restart the camera by stopping and starting it"""
        self.logger.info("Restarting camera")
        try:
            self.picam2.stop()
            self.picam2.start()
            self.logger.info("Camera restarted successfully")
        except Exception as e:
            self.logger.error(f"Error restarting camera: {e}")
            raise
        return self

    def reset_camera(self):
        self.close()
        self.picam2 = _get_picam2()
        self.picam2.configure(self.picam2.create_preview_configuration(Settings().to_dict()))
        return self

    def update_settings(self, settings: Settings):
        self.picam2.configure(self.picam2.create_preview_configuration(settings.to_dict()))
        self.picam2.start()
        return self


class RTSPCameraHandler:
    """Camera handler backed by an RTSP stream via OpenCV.

    Exposes the same interface as :class:`PiCameraHandler` (``start``/``stop``/
    ``capture_image``/recording helpers), so the REST endpoints work unchanged.
    A background thread continuously grabs frames and keeps only the latest one,
    which avoids the growing latency you get when reading an RTSP stream on
    demand. Frames are returned in BGR order (OpenCV's native layout), which is
    exactly what ``cv2.imencode`` and the detector's ``BGR2RGB`` step expect.
    """

    def __init__(self, url: str = DEFAULT_RTSP_URL):
        self.logger = logging.getLogger(__name__)
        self.url = url
        self.logger.info(f"Initializing RTSP camera: {_redact_url(url)}")
        self.cap: cv2.VideoCapture | None = None
        self.streaming_active = False
        self._recording = False
        self._recording_proc: subprocess.Popen | None = None
        self._recording_thread: threading.Thread | None = None
        self._recording_path: str | None = None
        # A Condition (rather than a plain Lock) lets consumers block until the
        # reader thread publishes a frame, instead of polling for one.
        self._frame_lock = threading.Condition()
        self._latest_frame: np.ndarray | None = None
        self._frame_seq = 0
        self._reader_thread: threading.Thread | None = None
        self._running = False

    def _open_capture(self) -> cv2.VideoCapture:
        # Force TCP transport and a connection timeout (5s, in microseconds).
        # Many IP cameras refuse the default UDP transport or hang silently.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        # Keep only the newest frame buffered to minimise latency.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def start(self):
        self.logger.info(f"Opening RTSP stream {_redact_url(self.url)}")
        self.cap = self._open_capture()
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            raise RuntimeError(f"Could not open RTSP stream: {_redact_url(self.url)}")
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        return self

    def _reader_loop(self):
        """Continuously pull frames, reconnecting on failure."""
        while self._running:
            if self.cap is None:
                self.cap = self._open_capture()
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.logger.warning("RTSP read failed; attempting to reconnect")
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(0.5)
                continue
            # Normalise to Full HD so all consumers see a consistent size.
            frame = _fit_resolution(frame)
            with self._frame_lock:
                self._latest_frame = frame
                self._frame_seq += 1
                self._frame_lock.notify_all()

    def stop(self):
        self.logger.info("Stopping RTSP camera")
        self._running = False
        if self._reader_thread:
            self._reader_thread.join(timeout=5)
            self._reader_thread = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as e:
                self.logger.error(f"Error releasing RTSP capture: {e}")
            self.cap = None
        with self._frame_lock:
            self._latest_frame = None
            # Reset so a stream reconnecting after a restart isn't waiting on a
            # sequence number the fresh reader will never reach.
            self._frame_seq = 0
            self._frame_lock.notify_all()
        return self

    def close(self):
        """Stop recording, tear down the reader thread and release the stream."""
        self.logger.info("Closing RTSP camera and releasing resources")
        self.stop_recording()
        self.stop()
        return self

    def capture_image(self, timeout: float = 10.0):
        """Return the most recent frame, waiting briefly for the stream to warm up."""
        deadline = time.monotonic() + timeout
        with self._frame_lock:
            while self._latest_frame is None:
                if not self._frame_lock.wait(max(0.0, deadline - time.monotonic())):
                    raise RuntimeError(
                        f"No frame available from RTSP stream: {_redact_url(self.url)}")
            return np.ascontiguousarray(self._latest_frame)

    def next_frame(self, last_seq: int = 0, timeout: float = 5.0) -> tuple[np.ndarray, int]:
        """Block until a frame newer than ``last_seq`` arrives.

        Returning the sequence number lets a stream skip re-encoding a frame it
        has already sent, which matters when the source delivers fewer frames
        per second than the consumer asks for.

        Raises:
            TimeoutError: If no new frame arrives within ``timeout`` seconds.
        """
        deadline = time.monotonic() + timeout
        with self._frame_lock:
            while self._latest_frame is None or self._frame_seq <= last_seq:
                if not self._frame_lock.wait(max(0.0, deadline - time.monotonic())):
                    raise TimeoutError(
                        f"No new frame within {timeout}s from {_redact_url(self.url)}")
            return np.ascontiguousarray(self._latest_frame), self._frame_seq

    def save_image(self) -> str:
        """Capture and save a single frame as JPEG."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = str(RECORDINGS_DIR / f"capture_{timestamp}.jpg")
        frame = self.capture_image()
        cv2.imwrite(filename, frame, JPEG_ENCODE_PARAMS)
        self.logger.info(f"Saved image to {filename}")
        return filename

    def start_recording(self) -> str:
        """Start recording video to an MP4 file (H.264 via ffmpeg)."""
        if self._recording:
            return self._recording_path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._recording_path = str(RECORDINGS_DIR / f"video_{timestamp}.mp4")
        frame = self.capture_image()
        h, w = frame.shape[:2]
        self._recording_proc = subprocess.Popen(
            ['ffmpeg', '-y',
             '-f', 'rawvideo', '-pix_fmt', 'bgr24',
             '-s', f'{w}x{h}', '-r', '15',
             '-i', '-',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
             '-pix_fmt', 'yuv420p',
             self._recording_path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._recording = True
        self._recording_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._recording_thread.start()
        self.logger.info(f"Started recording to {self._recording_path}")
        return self._recording_path

    def _record_loop(self):
        """Background thread: capture frames and pipe to ffmpeg."""
        while self._recording:
            try:
                frame = self.capture_image()
                self._recording_proc.stdin.write(frame.tobytes())
            except Exception as e:
                self.logger.error(f"Error recording frame: {e}")
                break
            time.sleep(1 / 15)

    def stop_recording(self) -> str | None:
        """Stop recording and finalise the video file."""
        if not self._recording:
            return None
        self._recording = False
        if self._recording_thread:
            self._recording_thread.join(timeout=5)
            self._recording_thread = None
        if self._recording_proc:
            try:
                self._recording_proc.stdin.close()
                self._recording_proc.wait(timeout=30)
            except Exception as e:
                self.logger.error(f"Error finalizing recording: {e}")
                self._recording_proc.kill()
            self._recording_proc = None
        path = self._recording_path
        self._recording_path = None
        self.logger.info(f"Stopped recording, saved to {path}")
        return path

    def restart_camera(self):
        """Reconnect to the RTSP stream."""
        self.logger.info("Restarting RTSP camera")
        self.stop()
        self.start()
        return self

    def reset_camera(self):
        self.close()
        return self

    def update_settings(self, settings: Settings):
        """Resolution is dictated by the RTSP source, so this is a no-op."""
        return self
