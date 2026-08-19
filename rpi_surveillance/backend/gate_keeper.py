import abc
import threading
import time


from rpi_surveillance.backend.inference.detector_injector import detector_injector


class GateKeeper(abc.ABC):
    
    def __init__(self, conditions_dict: dict[str, bool], fps: int = 5):
        self._conditions_dict = conditions_dict
        self._gatekeeper_thread = None
        self._gatekeeper_running_event = threading.Event()
        self._detector_injector = detector_injector()
        
    def verify_conditions(self) -> bool:
        pass
    
    def start_gatekeeper(self):
        self.logger.info("Starting gatekeeper")
        self._gatekeeper_thread = threading.Thread(target=self._gatekeeper_loop, daemon=True)
        self._gatekeeper_thread.start()
        return self
    
    def trigger_recording(self):
        pass

    def _gatekeeper_loop(self):
        """Background thread: capture frames and pipe to ffmpeg."""
        while self._gatekeeper_running_event.is_set():
            try:
                frame = self.capture_image()
                detections = self._detector_injector.detect(frame)
                if not self.verify_conditions(detections):
                    self.logger.info("Conditions verified")
                    self.trigger_recording()
            except Exception as e:
                self.logger.error(f"Error recording frame: {e}")
                break
            time.sleep(1 / self._fps)
