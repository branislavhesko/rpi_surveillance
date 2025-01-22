from functools import partial
from nicegui import ui
import requests
import cv2
import numpy as np
from PIL import Image
from io import BytesIO

HOST = "http://localhost:5000"


def on_start_camera():
    requests.get(f"{HOST}/start")
    ui.notify("Camera started")


def on_stop_camera():
    requests.get(f"{HOST}/stop")
    ui.notify("Camera stopped")


# Create a NiceGUI page
@ui.page('/')
def main_page():
    ui.page_title("Raspberry Pi Surveillance")
    start_button = ui.button("Start Camera")
    stop_button = ui.button("Stop Camera")
    image_display = ui.interactive_image(size=(1024, 768))

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
        timer = ui.timer(1.0, update_image)


    def stop_timer():
        global timer
        timer.cancel()
        requests.get(f"{HOST}/stop")

    start_button.on_click(start_timer)
    stop_button.on_click(stop_timer)

# Start the NiceGUI app
ui.run(host='0.0.0.0', port=8080)



