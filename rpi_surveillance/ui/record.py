from functools import partial
from nicegui import ui
import requests
import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel
from io import BytesIO

HOST = "http://localhost:5000"


def drawer(record):
    with ui.left_drawer().props('behavior="desktop"') as drawer:
        ui.label("Settings")
        ui.label("Host")
        ui.input(value=record.host, on_change=lambda e: setattr(record, "host", e.value))
        ui.label("Port")
        ui.input(value=record.port, on_change=lambda e: setattr(record, "port", e.value))
        ui.label("Interval")
        ui.input(value=record.interval, on_change=lambda e: setattr(record, "interval", e.value))
        ui.label("Width")
        ui.select([1024, 1920], value=record.width, on_change=lambda e: setattr(record, "width", int(e.value)))
        ui.label("Height")
        ui.select([768, 1080], value=record.height, on_change=lambda e: setattr(record, "height", int(e.value)))
    return drawer

def on_start_camera():
    requests.get(f"{HOST}/start")
    ui.notify("Camera started")


def on_stop_camera():
    requests.get(f"{HOST}/stop")
    ui.notify("Camera stopped")

class Record(BaseModel):
    host: str = "localhost"
    port: int = 5000
    interval: int = 1.0
    width: int = 1024
    height: int = 768
    
    @property
    def url(self):
        return f"http://{self.host}:{self.port}"


# Create a NiceGUI page
@ui.page('/record')
def main_page(record):
    ui.page_title("Raspberry Pi Surveillance")
    start_button = ui.button("Start Camera")
    stop_button = ui.button("Stop Camera")
    image_display = ui.interactive_image(size=(record.width, record.height))

    def update_image():
        response = requests.get(f"{HOST}/capture")
        if response.status_code == 200:
            image_display.set_source(Image.open(BytesIO(response.content)))
        else:
            ui.notify(f"Error: {response.status_code} - {response.text}")

    # Run the update_image function in a loop
    timer = None
    def start_timer():
        global timer
        requests.get(f"{HOST}/start")
        timer = ui.timer(record.interval, update_image)


    def stop_timer():
        global timer
        timer.cancel()
        requests.get(f"{HOST}/stop")

    start_button.on_click(start_timer)
    stop_button.on_click(stop_timer)

