"""
Drawing Reader Agent — Extract GD&T callouts from engineering drawings
and generate inspection plans.

Reads engineering drawing PDFs, extracts dimensions, tolerances, datum
references, and surface finish callouts. Generates a complete inspection
plan: which features to measure, in what order, with what instruments,
and pass/fail criteria.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("millforge.drawing_reader")


@dataclass
class GDTCallout:
    """A single GD&T callout extracted from a drawing."""
    feature_id: str
    dimension_type: str  # diameter | length | depth | flatness | position | ...
    nominal: float
    tolerance_plus: float
    tolerance_minus: float
    datum_refs: list[str] = field(default_factory=list)
    surface_finish: Optional[str] = None
    gdt_symbol: Optional[str] = None
    units: str = "mm"


@dataclass
class InspectionStep:
    """A single step in an inspection plan."""
    sequence: int
    feature_id: str
    measurement_method: str
    instrument: str
    acceptance_criteria: str
    notes: Optional[str] = None


@dataclass
class InspectionPlan:
    """Complete inspection plan generated from GD&T callouts."""
    steps: list[InspectionStep] = field(default_factory=list)
    total_estimated_time_minutes: float = 0.0
    instruments_required: list[str] = field(default_factory=list)


# Instrument selection based on tolerance band
_INSTRUMENT_MAP = [
    # (max_tolerance_mm, instrument, method, time_per_feature_min)
    (0.005, "CMM", "CMM touch probe", 5.0),
    (0.01,  "CMM", "CMM touch probe", 4.0),
    (0.025, "Bore gauge / Pin gauge", "Precision bore gauge", 3.0),
    (0.05,  "Micrometer", "Outside micrometer", 2.0),
    (0.1,   "Micrometer", "Digital micrometer", 1.5),
    (0.25,  "Caliper", "Digital caliper", 1.0),
    (1.0,   "Caliper", "Digital caliper", 0.5),
    (999,   "Scale / Tape", "Steel rule measurement", 0.3),
]

# GD&T symbol patterns
_GDT_SYMBOLS = {
    "position": "Position",
    "flatness": "Flatness",
    "perpendicularity": "Perpendicularity",
    "parallelism": "Parallelism",
    "concentricity": "Concentricity",
    "runout": "Circular Runout",
    "total_runout": "Total Runout",
    "profile_surface": "Profile of a Surface",
    "profile_line": "Profile of a Line",
    "circularity": "Circularity",
    "cylindricity": "Cylindricity",
    "straightness": "Straightness",
    "angularity": "Angularity",
    "symmetry": "Symmetry",
}

# Dimension patterns in drawing text
_DIM_PATTERNS = [
    # Diameter with tolerance: ⌀25.00 +0.01/-0.02
    (r"[⌀∅Ø]\s*(\d+\.?\d*)\s*[+±]\s*(\d+\.?\d*)\s*/?\s*-\s*(\d+\.?\d*)",
     "diameter"),
    # Linear dimension with bilateral tolerance: 50.00 ±0.05
    (r"(\d+\.?\d*)\s*±\s*(\d+\.?\d*)",
     "linear_bilateral"),
    # Linear dimension with unilateral tolerance: 50.00 +0.05/-0.02
    (r"(\d+\.?\d*)\s*[+]\s*(\d+\.?\d*)\s*/?\s*-\s*(\d+\.?\d*)",
     "linear_unilateral"),
    # Surface finish: Ra 1.6, Ra0.8
    (r"Ra\s*(\d+\.?\d*)",
     "surface_finish"),
    # GD&T frame: position 0.05 A B
    (r"(?:position|flatness|perpendicularity|parallelism|concentricity|runout|circularity|cylindricity|straightness|angularity|symmetry)\s+(\d+\.?\d*)\s*([A-Z](?:\s+[A-Z])*)?",
     "gdt_frame"),
]


class DrawingReaderAgent:
    """Extract GD&T callouts from engineering drawings, generate inspection plans."""

    def __init__(self) -> None:
        from services.pdf_processor import PDFProcessor
        self._pdf = PDFProcessor()

    def extract_callouts(self, pdf_bytes: bytes) -> list[GDTCallout]:
        """Extract GD&T callouts from a drawing PDF."""
        result = self._pdf.extract(pdf_bytes)
        text = result.text
        callouts = []
        feature_counter = 0

        # Extract diameter dimensions with tolerances
        for match in re.finditer(
            r"[⌀∅Ø]\s*(\d+\.?\d*)\s*[+±]\s*(\d+\.?\d*)\s*/?\s*-?\s*(\d+\.?\d*)?",
            text, re.IGNORECASE
        ):
            feature_counter += 1
            nominal = float(match.group(1))
            tol_plus = float(match.group(2))
            tol_minus = float(match.group(3)) if match.group(3) else tol_plus
            callouts.append(GDTCallout(
                feature_id=f"F{feature_counter}",
                dimension_type="diameter",
                nominal=nominal,
                tolerance_plus=tol_plus,
                tolerance_minus=tol_minus,
            ))

        # Extract bilateral tolerances
        for match in re.finditer(
            r"(?<![⌀∅Ø])\b(\d+\.?\d*)\s*±\s*(\d+\.?\d*)",
            text
        ):
            feature_counter += 1
            nominal = float(match.group(1))
            tol = float(match.group(2))
            callouts.append(GDTCallout(
                feature_id=f"F{feature_counter}",
                dimension_type="length",
                nominal=nominal,
                tolerance_plus=tol,
                tolerance_minus=tol,
            ))

        # Extract GD&T frames
        for gdt_type in _GDT_SYMBOLS:
            for match in re.finditer(
                rf"\b{gdt_type}\s+(\d+\.?\d*)\s*([A-Z](?:\s+[A-Z])*)?",
                text, re.IGNORECASE
            ):
                feature_counter += 1
                tolerance = float(match.group(1))
                datums = match.group(2).split() if match.group(2) else []
                callouts.append(GDTCallout(
                    feature_id=f"F{feature_counter}",
                    dimension_type=gdt_type,
                    nominal=0.0,
                    tolerance_plus=tolerance,
                    tolerance_minus=tolerance,
                    datum_refs=datums,
                    gdt_symbol=_GDT_SYMBOLS[gdt_type],
                ))

        # Extract surface finish callouts
        for match in re.finditer(r"Ra\s*(\d+\.?\d*)", text, re.IGNORECASE):
            # Attach surface finish to the most recent feature
            if callouts:
                callouts[-1].surface_finish = f"Ra {match.group(1)}"

        return callouts

    def generate_inspection_plan(self, callouts: list[GDTCallout]) -> InspectionPlan:
        """Generate an ordered inspection plan from callouts.

        Ordering strategy:
        1. Datum features first (referenced by other features)
        2. Tightest tolerances next (most critical)
        3. Looser tolerances last
        """
        if not callouts:
            return InspectionPlan()

        # Identify datum features
        all_datums = set()
        for c in callouts:
            all_datums.update(c.datum_refs)

        # Sort: datum features first, then by tolerance (tightest first)
        def sort_key(c: GDTCallout):
            is_datum = 0 if c.feature_id in all_datums else 1
            total_tol = c.tolerance_plus + c.tolerance_minus
            return (is_datum, total_tol)

        sorted_callouts = sorted(callouts, key=sort_key)

        steps = []
        instruments_used = set()
        total_time = 0.0

        for i, callout in enumerate(sorted_callouts):
            total_tol = callout.tolerance_plus + callout.tolerance_minus
            instrument, method, time_min = self._select_instrument(total_tol)
            instruments_used.add(instrument)
            total_time += time_min

            acceptance = self._format_acceptance(callout)

            steps.append(InspectionStep(
                sequence=i + 1,
                feature_id=callout.feature_id,
                measurement_method=method,
                instrument=instrument,
                acceptance_criteria=acceptance,
                notes=self._step_notes(callout),
            ))

        return InspectionPlan(
            steps=steps,
            total_estimated_time_minutes=round(total_time, 1),
            instruments_required=sorted(instruments_used),
        )

    def _select_instrument(self, total_tolerance_mm: float) -> tuple[str, str, float]:
        """Select measurement instrument based on tolerance band."""
        for max_tol, instrument, method, time in _INSTRUMENT_MAP:
            if total_tolerance_mm <= max_tol:
                return instrument, method, time
        return "Scale / Tape", "Steel rule measurement", 0.3

    def _format_acceptance(self, callout: GDTCallout) -> str:
        """Format pass/fail acceptance criteria string."""
        if callout.dimension_type in _GDT_SYMBOLS:
            return f"{callout.gdt_symbol or callout.dimension_type}: {callout.tolerance_plus} mm max"

        low = callout.nominal - callout.tolerance_minus
        high = callout.nominal + callout.tolerance_plus
        dim_label = "DIA" if callout.dimension_type == "diameter" else ""
        return f"{dim_label} {low:.3f} — {high:.3f} {callout.units}".strip()

    def _step_notes(self, callout: GDTCallout) -> Optional[str]:
        """Generate notes for an inspection step."""
        notes = []
        if callout.datum_refs:
            notes.append(f"Datum refs: {', '.join(callout.datum_refs)}")
        if callout.surface_finish:
            notes.append(f"Surface finish: {callout.surface_finish}")
        return "; ".join(notes) if notes else None
