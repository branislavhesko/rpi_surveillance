#!/usr/bin/env python3
"""Camera backend for rpi_surveillance.

Contains the PiCamera2 handler and the FastAPI ``APIRouter`` exposing the camera
REST endpoints. The router is mounted onto the NiceGUI/FastAPI application in
``rpi_surveillance.app`` under the ``/api`` prefix, so this module does not run a
server of its own.
"""

import asyncio
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse
from picamera2 import Picamera2
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Camera REST API is mounted under this prefix on the main app.
API_PREFIX = "/api"

RECORDINGS_DIR = Path("/home/raspberry/recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _transform_image(image: np.ndarray) -> np.ndarray:
    return np.flip(image, axis=0)


class Settings(BaseModel):
    resolution: tuple[int, int] = (1024, 768)
    framerate: int = 30
    format: str = "RGB888"

    def to_dict(self):
        return {"size": self.resolution, "format": self.format}


class PiCameraHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing camera")
        self.picam2 = Picamera2()
        self._settings = Settings()
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
        """Properly close and release camera resources"""
        self.logger.info("Closing camera and releasing resources")
        self.stop_recording()
        try:
            self.picam2.stop()
        except Exception as e:
            self.logger.warning(f"Error stopping camera during close: {e}")
        try:
            self.picam2.close()
        except Exception as e:
            self.logger.error(f"Error closing camera: {e}")
        return self

    def capture_image(self):
        with self._capture_lock:
            np_array = self.picam2.capture_array()
            np_array = np.ascontiguousarray(np_array)
        self.logger.info(f"Captured image of size {np_array.shape}")
        return np_array

    def save_image(self) -> str:
        """Capture and save a single frame as JPEG."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = str(RECORDINGS_DIR / f"capture_{timestamp}.jpg")
        frame = self.capture_image()
        cv2.imwrite(filename, frame)
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
        self.picam2 = Picamera2()
        self.picam2.configure(self.picam2.create_preview_configuration(Settings().to_dict()))
        return self

    def update_settings(self, settings: Settings):
        self.picam2.configure(self.picam2.create_preview_configuration(settings.to_dict()))
        self.picam2.start()
        return self


class _DependencyInjector:
    def __init__(self):
        self.camera_handler: PiCameraHandler | None = None

    def __call__(self):
        return self.camera_handler

    def set_camera_handler(self, camera_handler: PiCameraHandler | None):
        self.camera_handler = camera_handler
        return self


camera_injector = _DependencyInjector()


def _start_camera_internal(_camera_handler: None | PiCameraHandler):
    if _camera_handler is not None:
        logging.info("Cleaning up existing camera handler")
        try:
            _camera_handler.close()
        except Exception as e:
            logging.error(f"Error closing existing camera: {e}")
    _camera_handler = PiCameraHandler()
    _camera_handler.start()
    camera_injector.set_camera_handler(_camera_handler)
    return _camera_handler


# ===========================================================================
# Camera REST endpoints
# ===========================================================================
camera_api = APIRouter(prefix=API_PREFIX, tags=["camera"])


@camera_api.get("/")
def read_root():
    return {"message": "Hello, World!"}


@camera_api.get("/start")
def start_camera(camera_handler: PiCameraHandler = Depends(camera_injector)):
    _start_camera_internal(camera_handler)
    return {"message": "Camera started"}


@camera_api.get("/stop")
def stop_camera(camera_handler: PiCameraHandler = Depends(camera_injector)):
    if camera_handler is not None:
        camera_handler.reset_camera()
    return {"message": "Camera stopped"}


@camera_api.get("/capture")
def capture_image(camera_handler: PiCameraHandler = Depends(camera_injector)):
    if camera_handler is None:
        camera_handler = _start_camera_internal(None)
    image = camera_handler.capture_image()
    logging.info(f"Captured image of size {image.shape}")
    return Response(content=cv2.imencode('.jpg', image)[1].tobytes(), media_type="image/jpeg")


@camera_api.get("/restart")
def restart_camera(camera_handler: PiCameraHandler = Depends(camera_injector)):
    if camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})

    try:
        # Try simple restart first
        camera_handler.restart_camera()
        return JSONResponse(status_code=200, content={"message": "Camera restarted"})
    except Exception as e:
        # If restart fails, try full reinitialize
        logging.error(f"Simple restart failed: {e}. Attempting full reinitialization.")
        try:
            camera_handler.close()
            camera_handler = PiCameraHandler().start()
            camera_injector.set_camera_handler(camera_handler)
            return JSONResponse(status_code=200, content={"message": "Camera reinitialized"})
        except Exception as e2:
            logging.error(f"Full reinitialization failed: {e2}")
            camera_injector.set_camera_handler(None)
            return JSONResponse(status_code=500, content={"message": f"Restart failed: {str(e2)}"})


@camera_api.post("/update_settings")
def update_settings(settings: Settings, camera_handler: PiCameraHandler = Depends(camera_injector)):
    camera_handler.update_settings(settings)
    return {"message": "Settings updated"}


@camera_api.get("/stream")
async def stream_video(camera_handler: PiCameraHandler | None = Depends(camera_injector)):
    """Stream live video as MJPEG"""
    if camera_handler is None:
        camera_handler = _start_camera_internal(None)

    camera_handler.streaming_active = True

    async def generate_frames():
        try:
            while camera_handler.streaming_active:
                try:
                    # Capture frame from camera
                    frame = camera_handler.capture_image()

                    # Encode frame as JPEG
                    _, buffer = cv2.imencode('.jpg', frame)
                    frame_bytes = buffer.tobytes()

                    # Yield frame in multipart format
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

                    # Small delay to control frame rate
                    await asyncio.sleep(0.033)  # ~30 fps
                except Exception as e:
                    logging.error(f"Error generating frame: {e}")
                    break
        finally:
            camera_handler.streaming_active = False
            logging.info("Streaming stopped")
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@camera_api.get("/stream/stop")
def stop_stream(camera_handler: PiCameraHandler = Depends(camera_injector)):
    """Stop the video stream"""
    if camera_handler:
        camera_handler.streaming_active = False
    return {"message": "Stream stopped"}


@camera_api.get("/save")
def save_image(camera_handler: PiCameraHandler = Depends(camera_injector)):
    """Capture and save the current frame as a JPEG file."""
    if camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})
    try:
        filename = camera_handler.save_image()
        return {"message": "Image saved", "filename": filename}
    except Exception as e:
        logging.error(f"Error saving image: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})


@camera_api.get("/record/start")
def start_recording(camera_handler: PiCameraHandler = Depends(camera_injector)):
    """Start recording video to an MP4 file."""
    if camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})
    try:
        filename = camera_handler.start_recording()
        return {"message": "Recording started", "filename": filename}
    except Exception as e:
        logging.error(f"Error starting recording: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})


@camera_api.get("/record/stop")
def stop_recording(camera_handler: PiCameraHandler = Depends(camera_injector)):
    """Stop recording and finalise the video file."""
    if camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})
    try:
        filename = camera_handler.stop_recording()
        if filename:
            return {"message": "Recording saved", "filename": filename}
        return {"message": "Not recording"}
    except Exception as e:
        logging.error(f"Error stopping recording: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})
