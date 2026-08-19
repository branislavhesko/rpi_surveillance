#!/usr/bin/env python3
"""Camera backend for rpi_surveillance.

Contains the PiCamera2 handler and the FastAPI ``APIRouter`` exposing the camera
REST endpoints. The router is mounted onto the NiceGUI/FastAPI application in
``rpi_surveillance.app`` under the ``/api`` prefix, so this module does not run a
server of its own.
"""

import asyncio
import logging
import os
import time
from urllib.parse import quote, urlsplit, urlunsplit

import cv2
import numpy as np
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
try:
    from picamera2 import Picamera2
except Exception:  # pragma: no cover - only present on a Raspberry Pi
    Picamera2 = None


from rpi_surveillance.backend.camera import (
    DEFAULT_RTSP_URL,
    JPEG_QUALITY,
    RTSPCameraHandler,
    PiCameraHandler,
    Settings,
)
from rpi_surveillance.backend.inference.detector_injector import detector_injector
from rpi_surveillance.config import load_env

logger = logging.getLogger(__name__)

# Camera REST API is mounted under this prefix on the main app.
API_PREFIX = "/api"
STREAM_WIDTH = 1280
STREAM_QUALITY = 75
STREAM_MAX_FPS = 15.0

# Ensure .env (RTSP credentials etc.) is loaded before reading env vars below.
load_env()

# Default RTSP source; overridable via the ``RTSP_URL`` env var or the ``/start``
# endpoint's ``url`` query parameter. ``RTSP_CREDENTIALS`` (``user:pass``) is
# injected server-side so credentials never travel through the browser.
DEFAULT_RTSP_URL = os.environ.get("RTSP_URL", "rtsp://192.168.50.5:554/stream1")


def _resolve_rtsp_url(url: str | None) -> str:
    """Return the RTSP URL to connect to, injecting server-side credentials.

    If ``RTSP_CREDENTIALS`` (``user:pass``) is set and the URL has no embedded
    credentials, they are added here on the server. A URL that already carries
    credentials is left untouched.
    """
    url = url or DEFAULT_RTSP_URL
    creds = os.environ.get("RTSP_CREDENTIALS", "").strip()
    if not creds:
        return url
    parts = urlsplit(url)
    if '@' in parts.netloc:  # credentials already present
        return url
    user, _, password = creds.partition(':')
    userinfo = quote(user, safe='')
    if password:
        userinfo += ':' + quote(password, safe='')
    netloc = f"{userinfo}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _scale_to_width(frame: np.ndarray, width: int | None) -> np.ndarray:
    """Downscale ``frame`` to ``width`` px wide, preserving aspect ratio."""
    if not width or width >= frame.shape[1]:
        return frame
    height = int(round(frame.shape[0] * width / frame.shape[1]))
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def _encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    """Encode a frame as JPEG bytes at the given quality."""
    return cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])[1].tobytes()


class _DependencyInjector:
    def __init__(self):
        self.camera_handler: RTSPCameraHandler | None = None

    def __call__(self):
        return self.camera_handler

    def set_camera_handler(self, camera_handler: RTSPCameraHandler | None):
        self.camera_handler = camera_handler
        return self


camera_injector = _DependencyInjector()


def _build_camera_handler(source: str, url: str | None):
    """Create a camera handler for the requested source ('rtsp' or 'rpi')."""
    source = (source or "rtsp").lower()
    if source == "rpi":
        if Picamera2 is None:
            raise RuntimeError("PiCamera2 is not available on this machine")
        return PiCameraHandler()
    return RTSPCameraHandler(_resolve_rtsp_url(url))


def _start_camera_internal(
    _camera_handler: None | RTSPCameraHandler | PiCameraHandler,
    url: str | None = None,
    source: str = "rtsp",
):
    if _camera_handler is not None:
        logging.info("Cleaning up existing camera handler")
        try:
            _camera_handler.close()
        except Exception as e:
            logging.error(f"Error closing existing camera: {e}")
    _camera_handler = _build_camera_handler(source, url)
    try:
        _camera_handler.start()
    except Exception:
        # Release the just-built handler so a failed start doesn't leave the
        # camera acquired (which would break every subsequent attempt).
        try:
            _camera_handler.close()
        except Exception as e:
            logging.error(f"Error cleaning up failed camera handler: {e}")
        raise
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
def start_camera(
    source: str = "rtsp",
    url: str | None = None,
    camera_handler: RTSPCameraHandler | PiCameraHandler = Depends(camera_injector),
):
    try:
        _start_camera_internal(camera_handler, url, source)
    except Exception as e:
        logging.error(f"Failed to start {source} camera: {e}")
        camera_injector.set_camera_handler(None)
        return JSONResponse(status_code=502, content={"message": str(e)})
    return {"message": "Camera started", "source": source}


@camera_api.get("/stop")
def stop_camera(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
    if camera_handler is not None:
        camera_handler.reset_camera()
        camera_injector.set_camera_handler(None)
    return {"message": "Camera stopped"}


@camera_api.get("/capture")
def capture_image(
    width: int = 0,
    quality: int = JPEG_QUALITY,
    camera_handler: RTSPCameraHandler = Depends(camera_injector),
):
    """Return a single frame as JPEG, full resolution unless ``width`` is given."""
    if camera_handler is None:
        camera_handler = _start_camera_internal(None)
    image = _scale_to_width(camera_handler.capture_image(), width)
    return Response(content=_encode_jpeg(image, quality), media_type="image/jpeg")


@camera_api.get("/detect")
def detect_objects(
    width: int = 0,
    quality: int = JPEG_QUALITY,
    camera_handler: RTSPCameraHandler = Depends(camera_injector),
):
    """Capture the current frame and return it annotated with detected objects."""
    if camera_handler is None:
        camera_handler = _start_camera_internal(None)
    frame = _scale_to_width(camera_handler.capture_image(), width)
    annotated = detector_injector.detect(frame)
    return Response(content=_encode_jpeg(annotated, quality), media_type="image/jpeg")


@camera_api.get("/restart")
def restart_camera(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
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
            camera_handler = RTSPCameraHandler().start()
            camera_injector.set_camera_handler(camera_handler)
            return JSONResponse(status_code=200, content={"message": "Camera reinitialized"})
        except Exception as e2:
            logging.error(f"Full reinitialization failed: {e2}")
            camera_injector.set_camera_handler(None)
            return JSONResponse(status_code=500, content={"message": f"Restart failed: {str(e2)}"})


@camera_api.post("/update_settings")
def update_settings(settings: Settings, camera_handler: RTSPCameraHandler = Depends(camera_injector)):
    camera_handler.update_settings(settings)
    return {"message": "Settings updated"}


@camera_api.get("/stream")
async def stream_video(
    detect: bool = False,
    width: int = STREAM_WIDTH,
    quality: int = STREAM_QUALITY,
    max_fps: float = STREAM_MAX_FPS,
    camera_handler: RTSPCameraHandler | None = Depends(camera_injector),
):
    """Stream live video as MJPEG, optionally annotated with detections.

    The browser consumes this directly through an ``<img>`` tag, so frames travel
    over plain HTTP and back-pressure is handled by TCP: a slow client simply
    receives fewer frames. Pushing frames to the page over the websocket instead
    lets a slow client build an unbounded queue, and latency grows without bound.
    """
    if camera_handler is None:
        camera_handler = _start_camera_internal(None)

    camera_handler.streaming_active = True
    min_interval = 1.0 / max_fps if max_fps > 0 else 0.0

    def _render(last_seq: int) -> tuple[bytes, int]:
        """Blocking part of the pipeline; runs off the event loop."""
        frame, seq = camera_handler.next_frame(last_seq, timeout=5.0)
        # Downscale before inference and drawing so every later stage works on
        # the smaller frame the browser is actually going to display.
        frame = _scale_to_width(frame, width)
        if detect:
            frame = detector_injector.detect(frame)
        return _encode_jpeg(frame, quality), seq

    async def generate_frames():
        last_seq = 0
        try:
            while camera_handler.streaming_active:
                started = time.monotonic()
                try:
                    payload, last_seq = await asyncio.to_thread(_render, last_seq)
                except TimeoutError:
                    continue  # Source stalled; hold the connection open and retry.
                except Exception as e:
                    logging.error(f"Error generating frame: {e}")
                    break
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(payload)).encode() + b'\r\n\r\n'
                       + payload + b'\r\n')
                remaining = min_interval - (time.monotonic() - started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
        finally:
            logging.info("Streaming stopped")

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@camera_api.get("/stream/stop")
def stop_stream(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
    """Stop the video stream"""
    if camera_handler:
        camera_handler.streaming_active = False
    return {"message": "Stream stopped"}


@camera_api.get("/save")
def save_image(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
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
def start_recording(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
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
def stop_recording(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
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

@camera_api.get("/start_gatekeeper")
def start_gatekeeper(camera_handler: RTSPCameraHandler = Depends(camera_injector)):
    """Start the gatekeeper"""
    if camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})
    try:
        camera_handler.start_gatekeeper()
        return {"message": "Gatekeeper started"}
    except Exception as e:
        logging.error(f"Error starting gatekeeper: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})