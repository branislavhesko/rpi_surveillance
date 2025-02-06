import dataclasses

import mlflow
import torch
from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor


from rpi_surveillance.detector.dataset import ObjectDetectionDataset, get_dataloaders

@dataclasses.dataclass
class TrainingConfig:
    mlflow_experiment_name: str
    
    num_classes: int
    num_epochs: int
    batch_size: int
    learning_rate: float


class ObjectDetectorTrainer:
    
    def __init__(self, config: TrainingConfig):
        self.config = config
        self.model = self.build_model()
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.config.learning_rate, weight_decay=1e-4)
        self.train_loader, self.val_loader = get_dataloaders(self.config)
        self.train_step = 0
        self.val_step = 0
    
    def build_model(self):
        model = fasterrcnn_mobilenet_v3_large_fpn(pretrained=True)
        in_features = model.roi_heads.box_predictor.cls_score.in_features
        model.roi_heads.box_predictor = FastRCNNPredictor(in_features, self.config.num_classes)
        return model
    
    def train(self):
        self.train_step = 0
        self.val_step = 0
        with mlflow.start_run(experiment_id=self.config.mlflow_experiment_name):
            for epoch in range(self.config.num_epochs):
                self.train_one_epoch(epoch)
                self.validate(epoch)

    def train_one_epoch(self, epoch):
        self.model.train()
        for images, targets in self.train_loader:
            self.optimizer.zero_grad()
            images = list(image.to(self.device) for image in images)
            targets = [{k: v.to(self.device) for k, v in t.items()} for t in targets]
            loss_dict = self.model(images, targets)
            losses = sum(loss for loss in loss_dict.values())
            losses.backward()
            self.optimizer.step()
            self.train_step += 1
            
    def validate(self, epoch):
        self.model.eval()
        with torch.no_grad():
            for images, targets in self.val_loader:
                images = list(image.to(self.device) for image in images)
                targets = [{k: v.to(self.device) for k, v in t.items()} for t in targets]
                loss_dict = self.model(images, targets)
                losses = sum(loss for loss in loss_dict.values())
                self.val_step += 1
                
    def deploy(self):
        pass
    
    
if __name__ == '__main__':
    trainer = ObjectDetectorTrainer()
    model = trainer.build_model(num_classes=2)
    print(model)