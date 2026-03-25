"""
Train YOLOv8n on NEU Surface Defect Database for real metal defect detection.

Prerequisites:
    pip install ultralytics "kaggle<2.0"
    # Kaggle credentials in project root .env: KAGGLE_USERNAME, KAGGLE_KEY

Classes (6): crazing, inclusion, patches, pitted_surface, rolled-in_scale, scratches

Usage:
    cd backend
    python scripts/train_vision_model.py

Output:
    backend/models/neu_det_yolov8n.onnx  (replaces the current heuristic mock)
"""

import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent  # backend/
load_dotenv(ROOT / ".env")          # backend/.env
load_dotenv(ROOT.parent / ".env")  # project root .env

# Raw download lands here (Kaggle unzips to NEU-DET/)
RAW_DATA_DIR  = ROOT.parent / "data" / "NEU-DET"
# Converted YOLO-format dataset lives here
NEU_DATA_DIR  = ROOT.parent / "data" / "neu_det_yolo"
OUTPUT_MODEL  = ROOT / "models" / "neu_det_yolov8n.onnx"
YAML_PATH     = ROOT.parent / "neu_det.yaml"

NEU_CLASSES = [
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
]
CLASS_INDEX = {name: i for i, name in enumerate(NEU_CLASSES)}

YAML_CONTENT = f"""path: {NEU_DATA_DIR}
train: images/train
val: images/val

nc: {len(NEU_CLASSES)}
names: {NEU_CLASSES}
"""


def download_dataset() -> bool:
    """Download NEU-DET from Kaggle using credentials from .env."""
    kaggle_user = os.getenv("KAGGLE_USERNAME", "").strip()
    kaggle_key  = os.getenv("KAGGLE_KEY", "").strip()

    if kaggle_user and kaggle_key:
        kaggle_dir = Path.home() / ".kaggle"
        kaggle_dir.mkdir(exist_ok=True)
        creds_file = kaggle_dir / "kaggle.json"
        creds_file.write_text(json.dumps({"username": kaggle_user, "key": kaggle_key}))
        creds_file.chmod(0o600)
        print(f"Kaggle credentials written to {creds_file}")
    else:
        print("WARNING: KAGGLE_USERNAME or KAGGLE_KEY not set in .env")

    try:
        import kaggle  # noqa: F401
        kaggle.api.authenticate()
        kaggle.api.dataset_download_files(
            "kaustubhdikshit/neu-surface-defect-database",
            path=str(RAW_DATA_DIR.parent),
            unzip=True,
        )
        print(f"Dataset downloaded to {RAW_DATA_DIR}")
        return True
    except Exception as exc:
        print(f"Download failed: {exc}")
        print("Manual: https://www.kaggle.com/datasets/kaustubhdikshit/neu-surface-defect-database")
        return False


def xml_to_yolo(xml_path: Path, img_w: int, img_h: int) -> list[str]:
    """Convert a Pascal VOC XML annotation to YOLO label lines."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    lines = []
    for obj in root.findall("object"):
        name = obj.find("name").text.strip()
        cls  = CLASS_INDEX.get(name)
        if cls is None:
            continue
        bb   = obj.find("bndbox")
        xmin = float(bb.find("xmin").text)
        ymin = float(bb.find("ymin").text)
        xmax = float(bb.find("xmax").text)
        ymax = float(bb.find("ymax").text)
        cx   = ((xmin + xmax) / 2) / img_w
        cy   = ((ymin + ymax) / 2) / img_h
        w    = (xmax - xmin) / img_w
        h    = (ymax - ymin) / img_h
        lines.append(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines


def prepare_dataset():
    """
    Convert the raw NEU-DET Pascal VOC layout to YOLO format.

    Raw layout:
        NEU-DET/train/images/       + train/annotations/
        NEU-DET/validation/images/  + validation/annotations/

    Output layout (NEU_DATA_DIR):
        images/train/   images/val/
        labels/train/   labels/val/
    """
    if NEU_DATA_DIR.exists():
        print(f"YOLO dataset already prepared at {NEU_DATA_DIR}, skipping conversion.")
        return

    splits = [("train", "train"), ("validation", "val")]
    for raw_split, yolo_split in splits:
        src_img_dir = RAW_DATA_DIR / raw_split / "images"
        src_ann_dir = RAW_DATA_DIR / raw_split / "annotations"
        dst_img_dir = NEU_DATA_DIR / "images" / yolo_split
        dst_lbl_dir = NEU_DATA_DIR / "labels" / yolo_split
        dst_img_dir.mkdir(parents=True, exist_ok=True)
        dst_lbl_dir.mkdir(parents=True, exist_ok=True)

        img_files = [p for p in src_img_dir.rglob("*") if p.is_file()]
        print(f"Converting {len(img_files)} {raw_split} images…")
        for img_path in img_files:
            # Copy image (flatten into single dir — YOLO doesn't need class subdirs)
            shutil.copy2(img_path, dst_img_dir / img_path.name)
            # Find matching XML (annotations may also be nested by class)
            xml_path = src_ann_dir / img_path.parent.name / (img_path.stem + ".xml")
            if not xml_path.exists():
                xml_path = src_ann_dir / (img_path.stem + ".xml")
            if not xml_path.exists():
                continue
            # Parse image size from XML
            tree = ET.parse(xml_path)
            size = tree.getroot().find("size")
            img_w = int(size.find("width").text)
            img_h = int(size.find("height").text)
            # Write YOLO label
            label_lines = xml_to_yolo(xml_path, img_w, img_h)
            lbl_path = dst_lbl_dir / (img_path.stem + ".txt")
            lbl_path.write_text("\n".join(label_lines))

    print(f"Dataset prepared at {NEU_DATA_DIR}")


def check_prerequisites():
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print("ERROR: ultralytics not installed.  pip install ultralytics")
        sys.exit(1)

    if not RAW_DATA_DIR.exists():
        print(f"Raw dataset not found at {RAW_DATA_DIR}")
        print("Attempting to download via Kaggle API…")
        if not download_dataset():
            print("ERROR: Dataset download failed.")
            print("  Manual: https://www.kaggle.com/datasets/kaustubhdikshit/neu-surface-defect-database")
            print("  Unzip so that data/NEU-DET/train/images/ exists.")
            sys.exit(1)

    prepare_dataset()


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
    # YOLO auto-increments the name (neu_det_train, neu_det_train2, …) if dir exists.
    # Find the most recently modified matching directory.
    runs_dir = ROOT.parent / "runs"
    candidates = sorted(
        runs_dir.glob("neu_det_train*/weights/best.pt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        print(f"ERROR: No best.pt found under {runs_dir}/neu_det_train*/weights/")
        sys.exit(1)
    best_weights = candidates[0]
    print(f"Using best weights: {best_weights}")
    return best_weights


def export_onnx(weights_path: Path):
    from ultralytics import YOLO

    OUTPUT_MODEL.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(weights_path))
    model.export(format="onnx", imgsz=640)
    exported = weights_path.with_suffix(".onnx")
    exported.rename(OUTPUT_MODEL)
    print(f"\nModel exported to: {OUTPUT_MODEL}")
    print("Restart the backend — quality_inspection will switch to onnx_inference automatically.")


if __name__ == "__main__":
    check_prerequisites()
    write_yaml()
    weights = train()
    export_onnx(weights)
