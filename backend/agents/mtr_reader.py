"""
MTR Reader Agent — OCR extraction and spec verification for Mill Test Reports.

Extracts chemical composition and mechanical properties from MTR PDFs,
verifies them against ASTM/AMS/SAE spec requirements, and auto-matches
to jobs for AS9100 traceability.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("millforge.mtr_reader")

# Load spec databases
_SPEC_DIR = Path(__file__).parent.parent / "data" / "material_specs"

_SPECS: dict[str, dict] = {}


def _load_specs() -> None:
    """Lazily load all spec JSON files."""
    global _SPECS
    if _SPECS:
        return
    for spec_file in _SPEC_DIR.glob("*.json"):
        try:
            with open(spec_file) as f:
                data = json.load(f)
            _SPECS.update(data)
        except Exception as exc:
            logger.error("Failed to load spec file %s: %s", spec_file, exc)


@dataclass
class MTRExtraction:
    """Structured data extracted from an MTR PDF."""
    heat_number: Optional[str] = None
    material_spec: Optional[str] = None
    spec_standard: Optional[str] = None
    spec_grade: Optional[str] = None
    chemistry: dict[str, float] = field(default_factory=dict)
    mechanicals: dict[str, float] = field(default_factory=dict)
    raw_text: str = ""
    extraction_method: str = "pdfplumber"


@dataclass
class PropertyCheck:
    property_name: str
    actual_value: float
    spec_min: Optional[float] = None
    spec_max: Optional[float] = None
    unit: str = ""
    passed: bool = True


@dataclass
class VerificationResult:
    status: str  # pass | fail | review
    spec_used: str = ""
    overall_pass: bool = True
    details: list[PropertyCheck] = field(default_factory=list)


# Chemical element patterns — matches "C 0.03" or "Carbon: 0.030%" etc.
_ELEMENT_PATTERNS = {
    "C":  r"(?:Carbon|C)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Mn": r"(?:Manganese|Mn)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "P":  r"(?:Phosphorus|P)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "S":  r"(?:Sulfur|Sulphur|S)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Si": r"(?:Silicon|Si)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Cr": r"(?:Chromium|Cr)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Ni": r"(?:Nickel|Ni)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Mo": r"(?:Molybdenum|Mo)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Cu": r"(?:Copper|Cu)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "V":  r"(?:Vanadium|V)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Nb": r"(?:Niobium|Columbium|Nb|Cb)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Ti": r"(?:Titanium|Ti)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Al": r"(?:Aluminum|Aluminium|Al)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "N":  r"(?:Nitrogen|N)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Fe": r"(?:Iron|Fe)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Co": r"(?:Cobalt|Co)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "W":  r"(?:Tungsten|W)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Zn": r"(?:Zinc|Zn)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
    "Mg": r"(?:Magnesium|Mg)\s*[:=]?\s*(\d+\.?\d*)\s*%?",
}

# Mechanical property patterns
_MECH_PATTERNS = {
    "tensile_ksi": r"(?:Tensile|Ultimate\s+Tensile|UTS)\s*(?:Strength)?\s*[:=]?\s*(\d+\.?\d*)\s*(?:ksi|KSI)",
    "yield_ksi": r"(?:Yield|0\.2%?\s*(?:Offset)?)\s*(?:Strength)?\s*[:=]?\s*(\d+\.?\d*)\s*(?:ksi|KSI)",
    "elongation_pct": r"(?:Elongation|Elong\.?)\s*(?:in\s+\d+[\"D])?\s*[:=]?\s*(\d+\.?\d*)\s*%",
    "reduction_of_area_pct": r"(?:Reduction\s+of\s+Area|R\.?A\.?|ROA)\s*[:=]?\s*(\d+\.?\d*)\s*%",
    "hardness_hb": r"(?:Brinell|HB|BHN)\s*(?:Hardness)?\s*[:=]?\s*(\d+\.?\d*)",
    "hardness_hrc": r"(?:Rockwell\s+C|HRC)\s*(?:Hardness)?\s*[:=]?\s*(\d+\.?\d*)",
}

_HEAT_PATTERN = re.compile(r"(?:Heat|Melt|Lot)\s*(?:No\.?|Number|#)\s*[:=]?\s*([A-Z0-9\-]+)", re.IGNORECASE)

_SPEC_PATTERN = re.compile(
    r"((?:ASTM|AMS|SAE|AISI|MIL)\s*[-\s]?\s*[A-Z]?\d+(?:[-/]\d+)?(?:\s*(?:Type|Grade|Condition|Class)\s*\w+)?)",
    re.IGNORECASE,
)


class MTRReaderAgent:
    """OCR extraction and spec verification for Mill Test Reports."""

    def __init__(self) -> None:
        _load_specs()
        from services.pdf_processor import PDFProcessor
        self._pdf = PDFProcessor()

    def extract_from_pdf(self, pdf_bytes: bytes) -> MTRExtraction:
        """Extract structured data from an MTR PDF."""
        result = self._pdf.extract(pdf_bytes)
        text = result.text
        extraction = MTRExtraction(
            raw_text=text,
            extraction_method=result.method,
        )

        # Extract heat number
        heat_match = _HEAT_PATTERN.search(text)
        if heat_match:
            extraction.heat_number = heat_match.group(1).strip()

        # Extract material specification
        spec_match = _SPEC_PATTERN.search(text)
        if spec_match:
            extraction.material_spec = spec_match.group(1).strip()
            parts = extraction.material_spec.split()
            if parts:
                extraction.spec_standard = parts[0].upper()

        # Extract chemistry from tables first, then regex fallback
        extraction.chemistry = self._extract_chemistry(text, result.tables)

        # Extract mechanical properties
        extraction.mechanicals = self._extract_mechanicals(text, result.tables)

        return extraction

    def _extract_chemistry(self, text: str, tables: list) -> dict[str, float]:
        """Extract chemical composition from text and/or tables."""
        chemistry = {}

        # Try table extraction first — more reliable
        for table in tables:
            if not table:
                continue
            # Look for rows with element names/symbols
            for row in table:
                if not row or len(row) < 2:
                    continue
                for i, cell in enumerate(row):
                    if not cell:
                        continue
                    cell_clean = cell.strip().upper()
                    if cell_clean in _ELEMENT_PATTERNS and i + 1 < len(row):
                        try:
                            val = float(row[i + 1].strip().replace("%", ""))
                            chemistry[cell_clean] = val
                        except (ValueError, TypeError, AttributeError):
                            pass

        # Regex fallback for any elements not found in tables
        for element, pattern in _ELEMENT_PATTERNS.items():
            if element not in chemistry:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    try:
                        chemistry[element] = float(match.group(1))
                    except ValueError:
                        pass

        return chemistry

    def _extract_mechanicals(self, text: str, tables: list) -> dict[str, float]:
        """Extract mechanical properties."""
        mechanicals = {}
        for prop_name, pattern in _MECH_PATTERNS.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    mechanicals[prop_name] = float(match.group(1))
                except ValueError:
                    pass
        return mechanicals

    def verify_against_spec(self, extraction: MTRExtraction,
                            spec_key: Optional[str] = None) -> VerificationResult:
        """Verify extracted MTR data against ASTM/AMS spec limits.

        If spec_key is None, attempts to auto-detect from the extraction.
        """
        _load_specs()

        if spec_key is None:
            spec_key = self._auto_detect_spec(extraction)

        if spec_key is None or spec_key not in _SPECS:
            return VerificationResult(
                status="review",
                spec_used=spec_key or "unknown",
                overall_pass=False,
                details=[],
            )

        spec = _SPECS[spec_key]
        checks: list[PropertyCheck] = []
        all_pass = True

        # Check chemistry
        spec_chem = spec.get("chemistry", {})
        for element, limits in spec_chem.items():
            if isinstance(limits, dict) and "note" in limits:
                continue  # skip "balance" entries
            actual = extraction.chemistry.get(element)
            if actual is None:
                continue
            check = PropertyCheck(
                property_name=f"Chemistry {element}",
                actual_value=actual,
                spec_min=limits.get("min") if isinstance(limits, dict) else None,
                spec_max=limits.get("max") if isinstance(limits, dict) else None,
                unit="%",
                passed=True,
            )
            if check.spec_min is not None and actual < check.spec_min:
                check.passed = False
                all_pass = False
            if check.spec_max is not None and actual > check.spec_max:
                check.passed = False
                all_pass = False
            checks.append(check)

        # Check mechanicals
        spec_mech = spec.get("mechanicals", {})
        for prop, limits in spec_mech.items():
            actual = extraction.mechanicals.get(prop)
            if actual is None:
                continue
            unit = "ksi" if "ksi" in prop else "%" if "pct" in prop else ""
            check = PropertyCheck(
                property_name=prop,
                actual_value=actual,
                spec_min=limits.get("min") if isinstance(limits, dict) else None,
                spec_max=limits.get("max") if isinstance(limits, dict) else None,
                unit=unit,
                passed=True,
            )
            if check.spec_min is not None and actual < check.spec_min:
                check.passed = False
                all_pass = False
            if check.spec_max is not None and actual > check.spec_max:
                check.passed = False
                all_pass = False
            checks.append(check)

        return VerificationResult(
            status="pass" if all_pass else "fail",
            spec_used=spec_key,
            overall_pass=all_pass,
            details=checks,
        )

    def _auto_detect_spec(self, extraction: MTRExtraction) -> Optional[str]:
        """Try to match extracted spec string to a known spec key."""
        if not extraction.material_spec:
            return None

        spec_text = extraction.material_spec.upper()

        # Collect all matching keys, return the most specific (longest)
        candidates = []

        # Direct key-as-substring matching
        for key in _SPECS:
            key_parts = key.replace("_", " ").upper()
            if key_parts in spec_text:
                candidates.append(key)

        # Fuzzy matching — spec number + grade both present
        if not candidates:
            for key in _SPECS:
                parts = key.split("_")
                if len(parts) >= 2:
                    spec_num = parts[0]
                    grade = "_".join(parts[1:])
                    if spec_num.upper() in spec_text and grade.upper() in spec_text:
                        candidates.append(key)

        if candidates:
            # Return longest match (most specific — "A276_316L" over "A276_316")
            candidates.sort(key=len, reverse=True)
            return candidates[0]

        return None

    def auto_match_job(self, extraction: MTRExtraction, jobs: list[dict]) -> Optional[int]:
        """Try to match an MTR to a job by material or heat number.

        Args:
            extraction: The MTR extraction result.
            jobs: List of job dicts with 'id', 'material', 'title' keys.

        Returns:
            Job ID if matched, None otherwise.
        """
        if not jobs:
            return None

        # Match by material similarity
        mtr_spec = (extraction.material_spec or "").lower()
        for job in jobs:
            job_material = (job.get("material") or "").lower()
            if job_material and job_material in mtr_spec:
                return job["id"]
            if mtr_spec and mtr_spec in job_material:
                return job["id"]

        return None

    def supported_specs(self) -> list[dict]:
        """List all supported material specifications."""
        _load_specs()
        return [
            {"key": key, "name": spec.get("name", key)}
            for key, spec in _SPECS.items()
        ]

    def file_hash(self, pdf_bytes: bytes) -> str:
        """SHA-256 hash for deduplication."""
        return self._pdf.file_hash(pdf_bytes)
