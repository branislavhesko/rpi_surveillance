import dataclasses
import pathlib
import torch.utils.data as data


@dataclasses.dataclass
class BoundingBox:
    xmin: int
    ymin: int
    xmax: int
    ymax: int
    class_name: str


@dataclasses.dataclass
class BoundingBoxAnnotation:
    image_path: pathlib.Path
    bounding_boxes: list[BoundingBox]


class ObjectDetectionDataset(data.Dataset):
    def __init__(self, annotations: list[BoundingBoxAnnotation]):
        self.annotations = annotations
    
    def __len__(self):
        return len(self.annotations)
    
    def __getitem__(self, index):
        return self.annotations[index]
    
    
def get_dataloaders(config):
    pass
