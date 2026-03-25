from pathlib import Path
from ultralytics import YOLO

weights = Path("../runs/neu_det_train2/weights/best.pt")
model = YOLO(str(weights))
model.export(format="onnx", imgsz=640)
exported = weights.with_suffix(".onnx")
dest = Path("models/neu_det_yolov8n.onnx")
dest.parent.mkdir(exist_ok=True)
exported.rename(dest)
print(f"Exported to {dest}")
