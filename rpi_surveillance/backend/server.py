import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from fastapi import FastAPI, Depends
from fastapi.responses import Response, JSONResponse, StreamingResponse
from pydantic import BaseModel
from picamera2 import Picamera2
import numpy as np
import cv2
import asyncio


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
        self.picam2.configure(self.picam2.create_preview_configuration(Settings().to_dict()))
        self.streaming_active = False

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
        np_array = self.picam2.capture_array()
        np_array = np.ascontiguousarray(np_array[::-1, :, :])
        self.logger.info(f"Captured image of size {np_array.shape}")
        return np_array

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

app = FastAPI()

class _DependencyInjector:
    def __init__(self):
        self.camera_handler: PiCameraHandler | None = None
        
    def __call__(self):
        return self.camera_handler
    
    def set_camera_handler(self, camera_handler: PiCameraHandler | None):
        self.camera_handler = camera_handler
        return self
    
    
camera_injector = _DependencyInjector()
    

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}


@app.get("/start")
def start_camera(camera_handler: PiCameraHandler = Depends(camera_injector)):
    camera_handler = _start_camera_internal(camera_handler)
    return {"message": "Camera started"}


def _start_camera_internal(_camera_handler: None | PiCameraHandler):
    # Clean up existing handler if it exists
    if _camera_handler is not None:
        logging.info("Cleaning up existing camera handler")
        try:
            _camera_handler.close()
        except Exception as e:
            logging.error(f"Error closing existing camera: {e}")
        _camera_handler.reset_camera()

    else:
        # Create and start new camera handler
        _camera_handler = PiCameraHandler()
    _camera_handler.start()
    camera_injector.set_camera_handler(_camera_handler)
    return _camera_handler


@app.get("/stop")
def stop_camera(camera_handler: PiCameraHandler = Depends(camera_injector)):
    if camera_handler is not None:
        camera_handler.reset_camera()
    return {"message": "Camera stopped"}    


@app.get("/capture")
def capture_image(camera_handler: PiCameraHandler = Depends(camera_injector)):
    if camera_handler is None:
        _start_camera_internal(None)
    image = camera_handler.capture_image()
    logging.info(f"Captured image of size {image.shape}")
    return Response(content=cv2.imencode('.jpg', image)[1].tobytes(), media_type="image/jpeg")

    
@app.get("/restart")
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


@app.post("/update_settings")
def update_settings(settings: Settings, camera_handler: PiCameraHandler = Depends(camera_injector)):
    camera_handler.update_settings(settings)
    return {"message": "Settings updated"}


@app.get("/stream")
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


@app.get("/stream/stop")
def stop_stream(camera_handler: PiCameraHandler = Depends(camera_injector)):
    """Stop the video stream"""
    if camera_handler:
        camera_handler.streaming_active = False
    return {"message": "Stream stopped"}


def run_server():
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=True, workers=1)


if __name__ == "__main__":
    run_server()