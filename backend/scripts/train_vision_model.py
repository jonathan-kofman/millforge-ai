"""
Train YOLOv8n on NEU Surface Defect Database for real metal defect detection.

Prerequisites:
    pip install ultralytics kaggle
    kaggle datasets download -d kaustubhdikshit/neu-surface-defect-database
    # Unzip to data/neu_det/

Classes (6): crazing, inclusion, patches, pitted_surface, rolled-in_scale, scratches

Usage:
    cd backend
    python scripts/train_vision_model.py

Output:
    backend/models/neu_det_yolov8n.onnx  (replaces the current heuristic mock)
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent  # backend/

NEU_DATA_DIR = ROOT.parent / "data" / "neu_det"
OUTPUT_MODEL = ROOT / "models" / "neu_det_yolov8n.onnx"
YAML_PATH = ROOT.parent / "neu_det.yaml"

NEU_CLASSES = [
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
]

YAML_CONTENT = f"""path: {NEU_DATA_DIR}
train: images/train
val: images/val

nc: {len(NEU_CLASSES)}
names: {NEU_CLASSES}
"""


def download_dataset() -> bool:
    """
    Download the NEU Surface Defect Database from Kaggle using credentials from env vars.
    Returns True on success, False on failure.
    """
    # Set Kaggle credentials from env vars if available
    kaggle_user = os.getenv("KAGGLE_USERNAME", "").strip()
    kaggle_key = os.getenv("KAGGLE_KEY", "").strip()
    if kaggle_user:
        os.environ["KAGGLE_USERNAME"] = kaggle_user
    if kaggle_key:
        os.environ["KAGGLE_KEY"] = kaggle_key

    try:
        import kaggle  # noqa: F401, PLC0415
        kaggle.api.authenticate()
        kaggle.api.dataset_download_files(
            "kaustubhdikshit/neu-surface-defect-database",
            path=str(NEU_DATA_DIR.parent),
            unzip=True,
        )
        print(f"Dataset downloaded to {NEU_DATA_DIR}")
        return True
    except Exception as exc:
        print(f"Download failed: {exc}")
        print("Manual: https://www.kaggle.com/datasets/kaustubhdikshit/neu-surface-defect-database")
        return False


def check_prerequisites():
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print("ERROR: ultralytics not installed.")
        print("  pip install ultralytics")
        sys.exit(1)

    if not NEU_DATA_DIR.exists():
        print(f"Dataset not found at {NEU_DATA_DIR}")
        print("Attempting to download via Kaggle API…")
        if not download_dataset():
            print("ERROR: Dataset download failed and dataset not found.")
            print("  Manual download: https://www.kaggle.com/datasets/kaustubhdikshit/neu-surface-defect-database")
            print("  Unzip into data/neu_det/ with images/train and images/val subdirs")
            sys.exit(1)


def write_yaml():
    YAML_PATH.write_text(YAML_CONTENT)
    print(f"Wrote {YAML_PATH}")


def train():
    from ultralytics import YOLO

    model = YOLO("yolov8n.pt")
    model.train(
        data=str(YAML_PATH),
        epochs=50,
        imgsz=640,
        project=str(ROOT.parent / "runs"),
        name="neu_det_train",
    )
    best_weights = ROOT.parent / "runs" / "neu_det_train" / "weights" / "best.pt"
    if not best_weights.exists():
        print(f"ERROR: Training output not found at {best_weights}")
        sys.exit(1)
    return best_weights


def export_onnx(weights_path: Path):
    from ultralytics import YOLO

    OUTPUT_MODEL.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(weights_path))
    model.export(format="onnx", imgsz=640)
    exported = weights_path.with_suffix(".onnx")
    exported.rename(OUTPUT_MODEL)
    print(f"\nModel exported to: {OUTPUT_MODEL}")
    print("Replace backend/agents/quality_vision.py heuristic with this ONNX for real inference.")


if __name__ == "__main__":
    check_prerequisites()
    write_yaml()
    weights = train()
    export_onnx(weights)
