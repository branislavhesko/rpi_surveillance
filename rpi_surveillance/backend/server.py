import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from fastapi import FastAPI
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from picamera2 import Picamera2
import numpy as np
import cv2


class Settings(BaseModel):
    resolution: tuple[int, int] = (1024, 768)
    framerate: int = 30
    format: str = "RGB888"
    
    def to_dict(self):
        return {"size": self.resolution, "format": self.format}


class PiCameraHandler:
    def __init__(self):
        self.picam2 = Picamera2()
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing camera")
        self.picam2.configure(self.picam2.create_preview_configuration(Settings().to_dict()))

    def start(self):
        self.logger.info("Starting camera")
        self.picam2.start()

    def stop(self):
        self.logger.info("Stopping camera")
        self.picam2.stop()

    def capture_image(self):
        np_array = self.picam2.capture_array()
        np_array = np.ascontiguousarray(np_array[::-1, :, :])
        self.logger.info(f"Captured image of size {np_array.shape}")
        return np_array
    
    def restart_camera(self):
        self.logger.info("Restarting camera")
        self.picam2.stop()
        self.picam2.start()
        
    def update_settings(self, settings: Settings):
        self.picam2.configure(self.picam2.create_preview_configuration(settings.to_dict()))
        self.picam2.start()


app = FastAPI()
_camera_handler = None


@app.get("/")
def read_root():
    return {"message": "Hello, World!"}


@app.get("/start")
def start_camera():
    global _camera_handler
    if _camera_handler is None:
        _camera_handler = PiCameraHandler()
        _camera_handler.start()
    return {"message": "Camera started"}


@app.get("/stop")
def stop_camera():
    global _camera_handler
    if _camera_handler is not None:
        _camera_handler.stop()
    _camera_handler = None
    return {"message": "Camera stopped"}    


@app.get("/capture")
def capture_image():
    if _camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})
    image = _camera_handler.capture_image()
    logging.info(f"Captured image of size {image.shape}")
    return Response(content=cv2.imencode('.jpg', image)[1].tobytes(), media_type="image/jpeg")

    
@app.get("/restart")
def restart_camera():
    if _camera_handler is None:
        return JSONResponse(status_code=400, content={"message": "Camera not started"})
    _camera_handler.restart_camera()
    return JSONResponse(status_code=200, content={"message": "Camera restarted"})


@app.post("/update_settings")
def update_settings(settings: Settings):
    _camera_handler.update_settings(settings)
    return {"message": "Settings updated"}


def run_server():
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=True, workers=1)


if __name__ == "__main__":
    run_server()