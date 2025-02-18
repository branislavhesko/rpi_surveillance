import dataclasses
import json
import pathlib
import torch.utils.data as data

from rpi_surveillance.configuration import TrainingMode


BOUNDING_BOX_EXTENSION = "_bounding_boxes.json"


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
    path = config.dataset.path
    all_images = list(pathlib.Path(path).glob("**/*.jpg")) + list(pathlib.Path(path).glob("**/*.jpeg")) + list(pathlib.Path(path).glob("**/*.png"))
    all_images.sort()

    annotations = []
    for image_path in all_images:
        parent = image_path.parent
        basename = image_path.name
        bounding_boxes_path = parent / (basename.replace(".", BOUNDING_BOX_EXTENSION))
        if not bounding_boxes_path.exists():
            continue
        with open(bounding_boxes_path, "r") as f:
            bounding_boxes = json.load(f)
        annotations.append(BoundingBoxAnnotation(image_path, bounding_boxes))
    
    dataset = ObjectDetectionDataset(annotations)
    train_dataset, validation_dataset = data.random_split(dataset, [0.8, 0.2])
    return {
        TrainingMode.TRAIN: data.DataLoader(train_dataset, batch_size=config.dataset.batch_size, shuffle=True),
        TrainingMode.VALIDATION: data.DataLoader(validation_dataset, batch_size=config.dataset.batch_size, shuffle=True),
    }