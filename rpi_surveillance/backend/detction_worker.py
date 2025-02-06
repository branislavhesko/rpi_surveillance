import cv2
import numpy as np
import torch
import torchvision


class DetectionWorker:
    def __init__(self, model, device):
        self.model = model
        self.device = device
