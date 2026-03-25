"""
MillForge Quality Vision Agent

Implements a YOLOv8-style ONNX inference pipeline for defect detection.
Uses YOLOv8n general object detection weights as a placeholder — these can
be swapped for a fine-tuned metal defect detection model without changing
the interface.

Falls back to a deterministic heuristic when the model cannot be loaded
(CI / environments without internet access).

Pre-processing  : resize → 640×640, BGR→RGB, normalize [0,1], CHW, add batch dim
Post-processing : confidence filter → NMS → map class idx to defect category
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model availability check
# ---------------------------------------------------------------------------
MODEL_PATH = Path(__file__).parent.parent / "models" / "neu_det_yolov8n.onnx"
MODEL_AVAILABLE = MODEL_PATH.exists()

if not MODEL_AVAILABLE:
    logger.warning("NEU-DET model not found at %s — using heuristic defect simulation", MODEL_PATH)

# ---------------------------------------------------------------------------
# Model download config
# ---------------------------------------------------------------------------
_MODEL_URL = (
    "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.onnx"
)
_MODEL_DIR  = os.getenv("MILLFORGE_MODEL_DIR", "/tmp/millforge_models")
_MODEL_PATH = os.path.join(_MODEL_DIR, "yolov8n.onnx")

# NEU-DET fine-tuned model (steel surface defect detection, 6 classes)
# Train: yolo train model=yolov8n.pt data=neu_det.yaml epochs=50 imgsz=640
# Export: yolo export model=runs/detect/train/weights/best.pt format=onnx
NEU_DET_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "models", "neu_det_yolov8n.onnx"
)
NEU_DET_MODEL_MAP50 = 0.759  # published mAP@0.5 for YOLOv8n on NEU-DET

# NEU-DET class index → MillForge defect category
# Classes: 0=crazing, 1=inclusion, 2=patches, 3=pitted_surface, 4=rolled-in_scale, 5=scratches
NEU_DET_CLASS_MAP: dict[int, str] = {
    0: "surface_crack",        # crazing
    1: "inclusions",           # inclusion
    2: "surface_roughness",    # patches
    3: "porosity",             # pitted_surface
    4: "dimensional_deviation",# rolled-in_scale
    5: "surface_crack",        # scratches
}


def _try_download_model(path: str = _MODEL_PATH) -> bool:
    """Download YOLOv8n ONNX if not already cached. Returns True on success."""
    if os.path.exists(path):
        return True
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import urllib.request  # noqa: PLC0415
        logger.info("Downloading YOLOv8n ONNX model to %s …", path)
        urllib.request.urlretrieve(_MODEL_URL, path)  # noqa: S310
        logger.info("Model downloaded (%d KB)", os.path.getsize(path) // 1024)
        return True
    except Exception as exc:
        logger.warning("Model download failed (%s) — using heuristic fallback", exc)
        return False

# ---------------------------------------------------------------------------
# Defect taxonomy
# ---------------------------------------------------------------------------
DEFECT_TYPES = [
    "surface_crack",
    "porosity",
    "dimensional_deviation",
    "surface_roughness",
    "inclusions",
    "delamination",
]

# YOLO class index → MillForge defect category
YOLO_CLASS_MAP: dict[int, str] = {i: d for i, d in enumerate(DEFECT_TYPES)}

# ---------------------------------------------------------------------------
# Severity mapping for each defect type
# ---------------------------------------------------------------------------
DEFECT_SEVERITY: Dict[str, str] = {
    "surface_crack":         "critical",
    "delamination":          "critical",
    "inclusions":            "major",
    "porosity":              "major",
    "dimensional_deviation": "major",
    "surface_roughness":     "minor",
}

# ---------------------------------------------------------------------------
# Per-material confidence thresholds for pass/fail decision
# ---------------------------------------------------------------------------
MATERIAL_PASS_THRESHOLDS: dict[str, float] = {
    "steel":    0.82,
    "aluminum": 0.80,
    "titanium": 0.90,   # stricter — aerospace applications
    "copper":   0.78,
}
DEFAULT_PASS_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# ONNX / inference constants
# ---------------------------------------------------------------------------
INPUT_SIZE    = 640          # YOLOv8 standard input (square)
CONF_THRESHOLD = 0.25        # minimum detection confidence
IOU_THRESHOLD  = 0.45        # NMS IoU threshold


@dataclass
class InspectionResult:
    """Result of a quality inspection pass."""
    image_url: str
    passed: bool
    confidence: float
    defects_detected: List[str]
    defect_severities: Dict[str, str]  # defect_name → critical|major|minor
    recommendation: str
    inspector_version: str = "onnx-v1.0"
    model: str = "heuristic"           # "yolov8n-pretrained", "yolov8n-neu-det", or "heuristic"
    model_map50: Optional[float] = None  # published mAP@0.5 accuracy (None for heuristic)
    validation_failures: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "image_url": self.image_url,
            "passed": self.passed,
            "confidence": round(self.confidence, 3),
            "defects_detected": self.defects_detected,
            "defect_severities": self.defect_severities,
            "recommendation": self.recommendation,
            "inspector_version": self.inspector_version,
            "model": self.model,
            "validation_failures": self.validation_failures,
        }


class QualityVisionAgent:
    """
    Quality Vision Agent.

    When a model_path is provided and the file exists, loads an ONNX model and
    runs full YOLOv8-style inference:
      1. Pre-process: open/download image → resize 640×640 → RGB → normalize → NCHW
      2. Inference:   ONNX session run
      3. Post-process: confidence filter → NMS → map to defect taxonomy

    When no model file is available (CI / development), uses a deterministic
    hash-based heuristic that produces consistent results for the same input.
    """

    MAX_RETRIES = 3

    def __init__(self, model_path: Optional[str] = None):
        self._session = None
        self._input_name: Optional[str] = None
        self._model_name: str = "heuristic"
        self._model_map50: Optional[float] = None

        # Resolve model path: explicit arg → NEU-DET → env-var default → auto-download
        if model_path and os.path.exists(model_path):
            self._model_name = "yolov8n-pretrained"
            self._load_model(model_path)
        elif os.path.exists(NEU_DET_MODEL_PATH):
            self._model_name = "yolov8n-neu-det"
            self._model_map50 = NEU_DET_MODEL_MAP50
            self._load_model(NEU_DET_MODEL_PATH)
            logger.info("Loaded NEU-DET fine-tuned model (mAP@0.5=%.3f)", NEU_DET_MODEL_MAP50)
        else:
            fallback = model_path or os.getenv("MILLFORGE_MODEL_PATH", _MODEL_PATH)
            if os.path.exists(fallback):
                self._model_name = "yolov8n-pretrained"
                self._load_model(fallback)
            elif _try_download_model(fallback):
                self._model_name = "yolov8n-pretrained"
                self._load_model(fallback)
            else:
                logger.info("QualityVisionAgent initialized (heuristic mode)")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def inspect(
        self,
        image_url: str,
        material: Optional[str] = None,
    ) -> InspectionResult:
        """
        Inspect a part image and return a quality assessment.

        Retries up to MAX_RETRIES times if validation fails (ONNX mode only;
        heuristic is deterministic so a single attempt is sufficient).
        Returns the best result with validation_failures populated on hard failure.
        """
        spec = {"image_url": image_url, "material": material}
        failures: List[str] = []
        best_result: Optional[InspectionResult] = None

        max_attempts = self.MAX_RETRIES if self._session is not None else 1
        for attempt in range(max_attempts):
            result = self._do_inspect(image_url, material)
            errors = self._validate(result, spec)

            if not errors:
                return result

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best_result = result
            logger.warning("Vision validation failed on attempt %d: %s", attempt + 1, errors)

        assert best_result is not None
        best_result.validation_failures = failures
        return best_result

    # ------------------------------------------------------------------
    # Spec + validation
    # ------------------------------------------------------------------

    def _validate(self, result: InspectionResult, spec: dict) -> List[str]:
        errors: List[str] = []
        if not (0.0 <= result.confidence <= 1.0):
            errors.append(f"confidence {result.confidence} out of range [0, 1]")
        valid_severities = {"critical", "major", "minor"}
        for d in result.defects_detected:
            if d not in DEFECT_TYPES:
                errors.append(f"unknown defect category: {d!r}")
            sev = result.defect_severities.get(d)
            if sev not in valid_severities:
                errors.append(f"defect '{d}' has invalid severity '{sev}'")
        # Every severity entry should refer to a detected defect
        for d in result.defect_severities:
            if d not in result.defects_detected:
                errors.append(f"defect_severities references '{d}' not in defects_detected")
        if result.passed and result.defects_detected:
            errors.append("passed=True but defects_detected is non-empty")
        if not result.image_url:
            errors.append("image_url is empty")
        return errors

    # ------------------------------------------------------------------
    # Core inspection — ONNX path or heuristic fallback
    # ------------------------------------------------------------------

    def _do_inspect(
        self,
        image_url: str,
        material: Optional[str],
    ) -> InspectionResult:
        threshold = MATERIAL_PASS_THRESHOLDS.get(
            (material or "").lower(), DEFAULT_PASS_THRESHOLD
        )

        if self._session is not None:
            return self._onnx_inspect(image_url, material, threshold)
        return self._heuristic_inspect(image_url, material, threshold)

    # ------------------------------------------------------------------
    # ONNX inference path
    # ------------------------------------------------------------------

    def _load_model(self, path: str) -> None:
        try:
            import onnxruntime as ort  # noqa: PLC0415
            self._session = ort.InferenceSession(
                path,
                providers=["CPUExecutionProvider"],
            )
            self._input_name = self._session.get_inputs()[0].name
            logger.info("ONNX model loaded from %s", path)
        except Exception as exc:
            logger.error("Failed to load ONNX model: %s", exc)
            self._session = None

    def _onnx_inspect(
        self,
        image_url: str,
        material: Optional[str],
        threshold: float,
    ) -> InspectionResult:
        blob = self._preprocess(image_url)
        raw = self._run_inference(blob)
        detections = self._postprocess(raw)

        if not detections:
            return self._make_result(
                image_url=image_url,
                confidence=0.95,
                defects=[],
                threshold=threshold,
                model=self._model_name,
                model_map50=self._model_map50,
            )

        # Aggregate: overall confidence = max detection score
        confidence = max(conf for _, conf in detections)
        defects = list({cat for cat, conf in detections if conf >= CONF_THRESHOLD})

        return self._make_result(
            image_url=image_url,
            confidence=confidence,
            defects=defects,
            threshold=threshold,
            model=self._model_name,
            model_map50=self._model_map50,
        )

    def _preprocess(self, image_url: str) -> np.ndarray:
        """Load image, resize to INPUT_SIZE×INPUT_SIZE, normalize → NCHW float32."""
        from PIL import Image  # noqa: PLC0415

        if image_url.startswith("http://") or image_url.startswith("https://"):
            import io  # noqa: PLC0415
            import urllib.request  # noqa: PLC0415
            with urllib.request.urlopen(image_url, timeout=10) as resp:  # noqa: S310
                img = Image.open(io.BytesIO(resp.read())).convert("RGB")
        else:
            img = Image.open(image_url).convert("RGB")

        img = img.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
        arr = np.asarray(img, dtype=np.float32) / 255.0   # HWC [0,1]
        arr = arr.transpose(2, 0, 1)                        # CHW
        return arr[np.newaxis, ...]                         # NCHW

    def _run_inference(self, blob: np.ndarray) -> np.ndarray:
        """Run ONNX session and return raw output array."""
        assert self._session is not None
        outputs = self._session.run(None, {self._input_name: blob})
        return outputs[0]  # shape: (1, 4+nc, 8400) for YOLOv8

    def _postprocess(
        self,
        raw: np.ndarray,
    ) -> List[Tuple[str, float]]:
        """
        Parse YOLOv8 output → list of (defect_category, confidence).

        YOLOv8 output shape: (1, 4+nc, 8400)
          axis 1: [cx, cy, w, h, cls0_score, cls1_score, ...]
        """
        pred = raw[0].T  # (8400, 4+nc)
        num_classes = pred.shape[1] - 4

        box_scores = pred[:, 4:]           # (8400, nc)
        class_ids  = box_scores.argmax(axis=1)
        confidences = box_scores.max(axis=1)

        mask = confidences >= CONF_THRESHOLD
        class_ids   = class_ids[mask]
        confidences = confidences[mask]

        # Use NEU-DET class map when the fine-tuned model is loaded
        class_map = (
            NEU_DET_CLASS_MAP
            if self._model_name == "yolov8n-neu-det"
            else YOLO_CLASS_MAP
        )

        results: List[Tuple[str, float]] = []
        for cls_id, conf in zip(class_ids.tolist(), confidences.tolist()):
            category = class_map.get(int(cls_id) % num_classes)
            if category:
                results.append((category, float(conf)))

        return results

    # ------------------------------------------------------------------
    # Deterministic heuristic fallback (no model file)
    # ------------------------------------------------------------------

    # Per-material defect bias: most likely defect type for each material
    _MATERIAL_DEFECT_BIAS: Dict[str, str] = {
        "steel":    "surface_crack",
        "aluminum": "porosity",
        "titanium": "inclusions",
        "copper":   "surface_roughness",
    }

    def _heuristic_inspect(
        self,
        image_url: str,
        material: Optional[str],
        threshold: float,
    ) -> InspectionResult:
        """
        Produce a deterministic result based on a hash of the image_url.
        Different URLs → different, but repeatable outcomes.
        Confidence range 0.15–0.95 to reflect realistic inspection uncertainty.
        """
        digest = int(hashlib.sha256(image_url.encode()).hexdigest(), 16)
        # Map into [0.15, 0.95] — wider range reflects realistic model uncertainty
        confidence = 0.15 + (digest % 81) / 100.0

        passed = confidence >= threshold
        defects: List[str] = []
        if not passed:
            n = 1 + (digest // 100 % 2)
            # Bias toward material-specific defect type; fall back to hash selection
            mat_key = (material or "").lower()
            biased = self._MATERIAL_DEFECT_BIAS.get(mat_key)
            candidates = [biased] if biased else []
            for i in range(n):
                candidates.append(DEFECT_TYPES[(digest // (10 ** i)) % len(DEFECT_TYPES)])
            defects = list(dict.fromkeys(candidates))[:n]  # dedupe, cap at n

        return self._make_result(
            image_url=image_url,
            confidence=confidence,
            defects=defects,
            threshold=threshold,
            model="heuristic",
            model_map50=None,
        )

    # ------------------------------------------------------------------
    # Shared result builder
    # ------------------------------------------------------------------

    def _make_result(
        self,
        image_url: str,
        confidence: float,
        defects: List[str],
        threshold: float,
        model: str = "heuristic",
        model_map50: Optional[float] = None,
    ) -> InspectionResult:
        passed = confidence >= threshold and not defects

        if passed:
            recommendation = "Part meets quality specifications. Approve for shipment."
        elif confidence >= 0.70:
            recommendation = (
                f"Marginal quality. Detected: {', '.join(defects) or 'none'}. "
                "Flag for manual review before shipment."
            )
        else:
            recommendation = (
                f"Quality failure. Detected: {', '.join(defects) or 'none'}. "
                "Reject and rework required."
            )

        severities = {d: DEFECT_SEVERITY.get(d, "minor") for d in defects}

        return InspectionResult(
            image_url=image_url,
            passed=passed,
            confidence=confidence,
            defects_detected=defects,
            defect_severities=severities,
            recommendation=recommendation,
            model=model,
            model_map50=model_map50,
        )
