#!/usr/bin/env python3
import os
import sys
import queue
import threading
from functools import partial
from types import SimpleNamespace
from pathlib import Path
import collections
import numpy as np
from picamera2 import Picamera2
import cv2
# -----------------------------------------------------------------------------
# Ensure repository root is available in sys.path
# -----------------------------------------------------------------------------
repo_root = None
for p in Path(__file__).resolve().parents:
    if (p / "hailo_apps" / "config" / "config_manager.py").exists():
        repo_root = p
        break

if repo_root is not None:
    sys.path.insert(0, str(repo_root))

from hailo_apps.python.core.tracker.byte_tracker import BYTETracker
from hailo_apps.python.core.common.hailo_inference import HailoInfer
from hailo_apps.python.core.common.camera_utils import PiCamera2CaptureAdapter
from hailo_apps.python.core.common.toolbox import (
    InputContext,
    VisualizationSettings,
    init_input_source,
    select_cap_processing_mode,
    get_labels,
    load_json_file,
    preprocess,
    visualize,
    FrameRateTracker,
    stop_after_timeout
)
from hailo_apps.python.core.common.defines import (
    MAX_INPUT_QUEUE_SIZE,
    MAX_OUTPUT_QUEUE_SIZE,
    MAX_ASYNC_INFER_JOBS,
)
from hailo_apps.python.core.common.parser import get_standalone_parser
from hailo_apps.python.core.common.hailo_logger import (
    get_logger,
    init_logging,
    level_from_args,
)
from hailo_apps.python.standalone_apps.object_detection.object_detection_post_process import (
    inference_result_handler,
)
from hailo_apps.python.core.common.core import handle_and_resolve_args

APP_NAME = Path(__file__).stem
logger = get_logger(__name__)

def parse_args():
    """
    Parse command-line arguments for the detection application.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    parser = get_standalone_parser()
    parser.description = "Run object detection with optional tracking and performance measurement."

    parser.add_argument(
        "--track",
        action="store_true",
        help=(
            "Enable object tracking for detections. "
            "When enabled, detected objects will be tracked across frames using a tracking algorithm "
            "(e.g., ByteTrack). This assigns consistent IDs to objects over time, enabling temporal analysis, "
            "trajectory visualization, and multi-frame association. Useful for video processing applications."
        ),
    )
    
    parser.add_argument(
        "--config-path",
        type=str,
        default=None,
        help=(
            "Path to the config file. "
            "If not specified, the default config file will be used (e.g., config.json)."
            "The config file should be in the assets directory."
        ),
    )

    parser.add_argument(
        "--labels",
        "-l",
        type=str,
        default=None,
        help=(
            "Path to a text file containing class labels, one per line. "
            "Used for mapping model output indices to human-readable class names. "
            "If not specified, default labels for the model will be used (e.g., COCO labels for detection models)."
        ),
    )

    parser.add_argument(
        "--draw-trail",
        action="store_true",
        help=(
            "[Tracking only] Draw motion trails of tracked objects.\n"
            "Uses the last 30 positions from the tracker history."
        )
    )

    args = parser.parse_args()
    return args


class PiCamera2CaptureAdapter:
    """
    Adapter that makes Picamera2 behave like cv2.VideoCapture.
    """

    def __init__(self, picam2):
        self.picam2 = picam2
        self._opened = True
        self._io_lock = threading.Lock()

    def isOpened(self):
        return self._opened

    def read(self):
        if not self._opened:
            return False, None

        # prevent stop/close while capturing
        with self._io_lock:
            if not self._opened: # re-check after taking lock
                return False, None
            frame = self.picam2.capture_array()

        if frame is None:
            return False, None
        return True, frame

    def get(self, prop_id: int) -> float:
        if prop_id in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT):
            try:
                cfg = self.picam2.camera_configuration()
                size = cfg.get("main", {}).get("size", None)
                if size and len(size) == 2:
                    w, h = int(size[0]), int(size[1])
                    return float(w if prop_id == cv2.CAP_PROP_FRAME_WIDTH else h)
            except Exception:
                pass
            return 0.0
        if prop_id == cv2.CAP_PROP_FPS:
            return 30.0
        return None

    def release(self):
        # stop new reads ASAP
        self._opened = False

        # wait if a read() is currently inside capture_array()
        with self._io_lock:
            try:
                self.picam2.stop()
            except Exception:
                pass
            try:
                self.picam2.close()
            except Exception:
                pass


class InferenceThread(threading.Thread):
    """
    Thread that wraps and manages the Hailo object detection inference pipeline.
    """
    def __init__(
        self,
        net,
        input_context: InputContext,
        visualization_settings: VisualizationSettings,
        config_path: str | Path | None = None,
        labels=None,
        enable_tracking: bool = False,
        show_fps: bool = False,
        draw_trail: bool = False,
        time_to_run: int | None = None,
        name: str = "InferenceThread",
    ):
        super().__init__(name=name)
        self.net = net
        self.input_context = input_context
        self.visualization_settings = visualization_settings
        self.config_path = config_path
        self.labels = labels
        self.enable_tracking = enable_tracking
        self.show_fps = show_fps
        self.draw_trail = draw_trail
        self.time_to_run = time_to_run

        self.stop_event = threading.Event()
        self.fps_tracker = None
        self.tracker = None
        self.preprocess_thread = None
        self.infer_thread = None
        self.timer_thread = None
        self.hailo_inference = None
        self.input_queue = None
        self.output_queue = None

    def run(self) -> None:
        labels = get_labels(self.labels)
        app_dir = Path(__file__).resolve().parent
        config_path = self.config_path
        if config_path is None:
            config_path = app_dir / "config.json"
        config_data = load_json_file(str(config_path))

        self.fps_tracker = FrameRateTracker() if self.show_fps else None
        self.tracker = None

        if self.enable_tracking:
            tracker_config = config_data.get("visualization_params", {}).get("tracker", {})
            self.tracker = BYTETracker(SimpleNamespace(**tracker_config))

        self.input_queue = queue.Queue(MAX_INPUT_QUEUE_SIZE)
        self.output_queue = queue.Queue(MAX_OUTPUT_QUEUE_SIZE)

        post_process_callback_fn = partial(
            inference_result_handler,
            labels=labels,
            config_data=config_data,
            tracker=self.tracker,
            draw_trail=self.draw_trail,
        )

        self.hailo_inference = HailoInfer(self.net, self.input_context.batch_size)
        height, width, _ = self.hailo_inference.get_input_shape()

        self.preprocess_thread = threading.Thread(
            target=preprocess,
            args=(
                self.input_context,
                self.input_queue,
                width,
                height,
                None,  # Use default preprocess from toolbox
                self.stop_event,
            ),
            name="preprocess-thread",
        )

        self.infer_thread = threading.Thread(
            target=infer,
            args=(
                self.hailo_inference,
                self.input_queue,
                self.output_queue,
                self.stop_event,
            ),
            name="infer-thread",
        )

        self.preprocess_thread.start()
        self.infer_thread.start()

        if self.show_fps and self.fps_tracker is not None:
            self.fps_tracker.start()

        if self.time_to_run is not None:
            self.timer_thread = threading.Thread(
                target=stop_after_timeout,
                args=(self.stop_event, self.time_to_run),
                name="timer-thread",
                daemon=True,
            )
            self.timer_thread.start()

        try:
            visualize(
                self.input_context,
                self.visualization_settings,
                self.output_queue,
                post_process_callback_fn,
                self.fps_tracker,
                self.stop_event,
            )
        finally:
            self.stop_event.set()
            if self.preprocess_thread is not None:
                self.preprocess_thread.join()
            if self.infer_thread is not None:
                self.infer_thread.join()

        if self.show_fps and self.fps_tracker is not None:
            logger.info(self.fps_tracker.frame_rate_summary())

        logger.success("Processing completed successfully.")

        if self.visualization_settings.save_stream_output or self.input_context.has_images:
            logger.info(f"Saved outputs to '{self.visualization_settings.output_dir}'.")

    def stop(self) -> None:
        self.stop_event.set()


def open_rpi_camera():
    """
    Open Raspberry Pi camera using Picamera2.

    Returns:
        PiCamera2CaptureAdapter | None:
            Camera adapter if successful, otherwise None.
    """
    try:
        from picamera2 import Picamera2
    except Exception as e:
        return None

    try:
        picam2 = Picamera2()
        width, height = 800, 600
        fps = 30
        main = {"size": (width, height), "format": "RGB888"}
        config = picam2.create_video_configuration(main=main, controls={"FrameRate": fps})

        picam2.configure(config)
        picam2.start()

        return PiCamera2CaptureAdapter(picam2)
    except Exception as e:
        logger.error(f"Failed to open RPi camera: {e}")
        return None

def run_inference_pipeline(
    net,
    labels,
    input_context: InputContext,
    visualization_settings: VisualizationSettings,
    config_path: str | Path | None = None,
    enable_tracking: bool = False,
    show_fps: bool = False,
    draw_trail: bool = False,
    time_to_run: int | None = None,
) -> None:
    """
    Initialize queues, inference instance, and run the pipeline thread.
    """
    pipeline = InferenceThread(
        net=net,
        input_context=input_context,
        visualization_settings=visualization_settings,
        config_path=config_path,
        labels=labels,
        enable_tracking=enable_tracking,
        show_fps=show_fps,
        draw_trail=draw_trail,
        time_to_run=time_to_run,
    )
    pipeline.start()
    pipeline.join()



def infer(hailo_inference, input_queue, output_queue, stop_event):
    """
    Main inference loop that pulls data from the input queue, runs asynchronous
    inference, and pushes results to the output queue.

    Each item in the input queue is expected to be a tuple:
        (input_batch, preprocessed_batch)
        - input_batch: Original frames (used for visualization or tracking)
        - preprocessed_batch: Model-ready frames (e.g., resized, normalized)

    Args:
        hailo_inference (HailoInfer): The inference engine to run model predictions.
        input_queue (queue.Queue): Provides (input_batch, preprocessed_batch) tuples.
        output_queue (queue.Queue): Collects (input_frame, result) tuples for visualization.

    Returns:
        None
    """
    # Limit number of concurrent async inferences
    pending_jobs = collections.deque()

    while True:
        next_batch = input_queue.get()
        if not next_batch:
            break  # Stop signal received

        if stop_event.is_set():
            continue  # Skip processing if stop signal is set

        input_batch, preprocessed_batch = next_batch

        # Prepare the callback for handling the inference result
        inference_callback_fn = partial(
            inference_callback,
            input_batch=input_batch,
            output_queue=output_queue
        )


        while len(pending_jobs) >= MAX_ASYNC_INFER_JOBS:
            pending_jobs.popleft().wait(10000)

        # Run async inference
        job = hailo_inference.run(preprocessed_batch, inference_callback_fn)
        pending_jobs.append(job)

    # Release resources and context
    hailo_inference.close()
    output_queue.put(None)


def inference_callback(
    completion_info,
    bindings_list: list,
    input_batch: list,
    output_queue: queue.Queue
) -> None:
    """
    infernce callback to handle inference results and push them to a queue.

    Args:
        completion_info: Hailo inference completion info.
        bindings_list (list): Output bindings for each inference.
        input_batch (list): Original input frames.
        output_queue (queue.Queue): Queue to push output results to.
    """
    if completion_info.exception:
        logger.error(f'Inference error: {completion_info.exception}')
    else:
        for i, bindings in enumerate(bindings_list):
            if len(bindings._output_names) == 1:
                result = bindings.output().get_buffer()
            else:
                result = {
                    name: np.expand_dims(
                        bindings.output(name).get_buffer(), axis=0
                    )
                    for name in bindings._output_names
                }
            output_queue.put((input_batch[i], result))

def main() -> None:
    args = parse_args()
    init_logging(level=level_from_args(args))
    handle_and_resolve_args(args, APP_NAME)

    config_path = args.config_path
    if config_path is None:
        config_path = Path(os.getcwd()).resolve() / "assets" / "config.json"

    input_context = InputContext(
        input_src="rpi",
        cap=open_rpi_camera(),
        batch_size=args.batch_size,
        resolution=args.camera_resolution,
        frame_rate=args.frame_rate,
        video_unpaced=args.video_unpaced,
    )
    
    if input_context.cap is not None:
        input_context.width = int(input_context.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        input_context.height = int(input_context.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        input_context.cap_processing_mode = select_cap_processing_mode(
            input_type="rpi_camera",
            frame_rate=input_context.frame_rate,
            source_fps=input_context.source_fps,
            video_unpaced=input_context.video_unpaced,
        )
        logger.info(f"Capture processing mode: {input_context.cap_processing_mode.value}")


    # input_context = init_input_source(input_context)

    visualization_settings = VisualizationSettings(
        output_dir=args.output_dir,
        save_stream_output=True,
        output_resolution=args.output_resolution,
        no_display=True,
    )

    run_inference_pipeline(
        net=args.hef_path,
        labels=args.labels,
        input_context=input_context,
        config_path=config_path,
        visualization_settings=visualization_settings,
        enable_tracking=args.track,
        show_fps=args.show_fps,
        draw_trail=args.draw_trail,
        time_to_run=args.time_to_run
    )

if __name__ == "__main__":
    main()