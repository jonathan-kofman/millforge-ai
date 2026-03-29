"""
QC inference service — isolated ONNX defect detection for Job QC stage.

Loads `backend/models/yolov8n_surface_defect.onnx` when present.
Falls back gracefully when the model file is missing so the endpoint
always returns a structured result (status="model_not_deployed").

Defect taxonomy inherited from NEU-DET:
  crazing, inclusion, patches, pitted_surface, rolled-in_scale, scratches
"""

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "models", "yolov8n_surface_defect.onnx"
)

# NEU-DET 6-class taxonomy
DEFECT_CLASSES = [
    "crazing",
    "inclusion",
    "patches",
    "pitted_surface",
    "rolled-in_scale",
    "scratches",
]

CONFIDENCE_THRESHOLD = 0.45

# Module-level session — loaded once on first call
_session = None
_session_attempted = False


def _load_session():
    global _session, _session_attempted
    if _session_attempted:
        return _session
    _session_attempted = True
    model_path = os.path.abspath(_MODEL_PATH)
    if not os.path.isfile(model_path):
        logger.info("QC model not found at %s — running in fallback mode.", model_path)
        return None
    try:
        import onnxruntime as ort  # type: ignore
        _session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        logger.info("QC ONNX model loaded from %s", model_path)
    except Exception as exc:
        logger.warning("Failed to load QC ONNX model: %s", exc)
    return _session


def _preprocess(image_bytes: bytes) -> Optional[np.ndarray]:
    """Decode image bytes → CHW float32 tensor, 640×640."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((640, 640))
        arr = np.array(img, dtype=np.float32) / 255.0  # HWC
        arr = arr.transpose(2, 0, 1)[np.newaxis, ...]   # NCHW
        return arr
    except Exception as exc:
        logger.warning("Image preprocessing failed: %s", exc)
        return None


def run_inference(image_bytes: bytes) -> dict:
    """
    Run defect detection on image_bytes.

    Returns:
        {
            "status": "ok" | "model_not_deployed" | "inference_error",
            "defects_found": [...],
            "confidence_scores": [...],
            "passed": bool,
        }
    """
    session = _load_session()

    if session is None:
        return {
            "status": "model_not_deployed",
            "defects_found": [],
            "confidence_scores": [],
            "passed": True,  # optimistic pass when no model
        }

    tensor = _preprocess(image_bytes)
    if tensor is None:
        return {
            "status": "inference_error",
            "defects_found": [],
            "confidence_scores": [],
            "passed": False,
        }

    try:
        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: tensor})
        # YOLOv8n output: [1, 84, 8400] — first 4 = bbox, next 80 = classes
        # NEU-DET export has 6 classes: shape [1, 10, 8400]
        raw = outputs[0]  # (1, num_attrs, num_anchors)
        if raw.ndim == 3:
            raw = raw[0]  # (num_attrs, num_anchors)
        if raw.shape[0] > 4:
            class_scores = raw[4:]  # (num_classes, num_anchors)
        else:
            class_scores = raw

        max_scores = class_scores.max(axis=1)  # (num_classes,)
        detected_indices = np.where(max_scores >= CONFIDENCE_THRESHOLD)[0]

        defects_found = [DEFECT_CLASSES[i] for i in detected_indices if i < len(DEFECT_CLASSES)]
        confidence_scores = [float(round(max_scores[i], 3)) for i in detected_indices if i < len(DEFECT_CLASSES)]
        passed = len(defects_found) == 0

        return {
            "status": "ok",
            "defects_found": defects_found,
            "confidence_scores": confidence_scores,
            "passed": passed,
        }
    except Exception as exc:
        logger.warning("QC inference failed: %s", exc)
        return {
            "status": "inference_error",
            "defects_found": [],
            "confidence_scores": [],
            "passed": False,
        }
