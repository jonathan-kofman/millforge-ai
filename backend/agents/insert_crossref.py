"""
Insert Cross-Reference Agent — ISO 1832 parser and cost optimizer.

Parses tooling insert designations (ISO 1832 / ANSI B212.4), finds
cross-manufacturer equivalents, and validates equivalence using tool
wear sensor data from the existing ToolWearAgent.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("millforge.insert_crossref")

# ISO 1832 shape codes → full name
ISO_SHAPES = {
    "C": "Rhombic 80°",
    "D": "Rhombic 55°",
    "H": "Hexagonal",
    "K": "Rhombic 55° (alt)",
    "O": "Octagonal",
    "P": "Pentagonal",
    "R": "Round",
    "S": "Square",
    "T": "Triangular",
    "V": "Rhombic 35°",
    "W": "Trigon 80°",
}

# ISO 1832 clearance angle codes
ISO_CLEARANCE = {
    "A": "3°", "B": "5°", "C": "7°", "D": "15°", "E": "20°",
    "F": "25°", "G": "30°", "N": "0°", "P": "11°",
}

# ISO 1832 tolerance class codes
ISO_TOLERANCE = {
    "A": "±0.025mm", "C": "±0.025mm", "E": "±0.025mm",
    "G": "±0.025mm", "H": "±0.013mm", "J": "±0.005mm",
    "K": "±0.025mm", "L": "±0.025mm", "M": "±0.05-0.13mm",
    "N": "±0.025mm", "U": "±0.08-0.18mm",
}

# ISO 1832 IC (inscribed circle) size codes → mm
ISO_IC_MAP = {
    "04": 4.76, "05": 5.56, "06": 6.35, "08": 8.0,
    "09": 9.525, "11": 11.0, "12": 12.7, "16": 15.875,
    "19": 19.05, "22": 22.0, "25": 25.4, "32": 31.75,
}

# ISO 1832 thickness codes → mm
ISO_THICKNESS_MAP = {
    "01": 1.59, "02": 2.38, "03": 3.18, "04": 4.76,
    "05": 5.56, "06": 6.35, "07": 7.94, "09": 9.525,
    "T3": 3.97,
}

# ISO 1832 nose radius codes → mm
ISO_NOSE_RADIUS_MAP = {
    "00": 0.0, "01": 0.1, "02": 0.2, "04": 0.4,
    "08": 0.8, "12": 1.2, "16": 1.6, "20": 2.0,
    "24": 2.4, "28": 2.8, "32": 3.2,
}


@dataclass
class InsertSpec:
    """Parsed ISO 1832 / ANSI designation."""
    shape: Optional[str] = None
    shape_name: Optional[str] = None
    clearance_angle: Optional[str] = None
    tolerance_class: Optional[str] = None
    insert_type: Optional[str] = None
    ic_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    nose_radius_mm: Optional[float] = None
    chipbreaker: Optional[str] = None
    grade: Optional[str] = None
    raw_designation: str = ""


# ISO 1832 pattern: SHAPE CLEARANCE TOLERANCE TYPE IC THICKNESS NOSE_RADIUS [-CHIPBREAKER] [GRADE]
# e.g. CNMG 120408-PM 4325
_ISO_PATTERN = re.compile(
    r"^([A-Z])"        # 1: shape
    r"([A-Z])"          # 2: clearance angle
    r"([A-Z])"          # 3: tolerance class
    r"([A-Z])"          # 4: type/fixing
    r"\s*"
    r"(\d{2})"          # 5: IC size
    r"(\d{2}|T\d)"      # 6: thickness
    r"(\d{2})"          # 7: nose radius
    r"(?:\s*[-]?\s*([A-Z][A-Z0-9]*))?"  # 8: chipbreaker (optional)
    r"(?:\s+(\d{4}))?$"  # 9: grade (optional)
)


class InsertCrossRefAgent:
    """Tooling insert cross-reference and cost optimizer."""

    def __init__(self) -> None:
        pass

    def parse_designation(self, designation: str) -> InsertSpec:
        """Parse an ISO 1832 or ANSI insert designation string."""
        designation = designation.strip().upper()
        match = _ISO_PATTERN.match(designation)
        if not match:
            return InsertSpec(raw_designation=designation)

        shape_code = match.group(1)
        clearance_code = match.group(2)
        tolerance_code = match.group(3)
        type_code = match.group(4)
        ic_code = match.group(5)
        thickness_code = match.group(6)
        nose_code = match.group(7)
        chipbreaker = match.group(8)
        grade = match.group(9)

        return InsertSpec(
            shape=shape_code,
            shape_name=ISO_SHAPES.get(shape_code, shape_code),
            clearance_angle=ISO_CLEARANCE.get(clearance_code, clearance_code),
            tolerance_class=ISO_TOLERANCE.get(tolerance_code, tolerance_code),
            insert_type=type_code,
            ic_mm=ISO_IC_MAP.get(ic_code),
            thickness_mm=ISO_THICKNESS_MAP.get(thickness_code),
            nose_radius_mm=ISO_NOSE_RADIUS_MAP.get(nose_code),
            chipbreaker=chipbreaker,
            grade=grade,
            raw_designation=designation,
        )

    def find_equivalents(self, db: Session, insert_id: int) -> list[dict]:
        """Find cross-manufacturer equivalents by geometry match."""
        from db_models import ToolingInsert

        source = db.query(ToolingInsert).filter(ToolingInsert.id == insert_id).first()
        if source is None:
            return []

        # Parse the source designation
        source_spec = None
        if source.iso_designation:
            source_spec = self.parse_designation(source.iso_designation)

        # Find inserts with matching geometry
        all_inserts = db.query(ToolingInsert).filter(
            ToolingInsert.id != insert_id
        ).all()

        equivalents = []
        for insert in all_inserts:
            score = self._match_score(source, source_spec, insert)
            if score >= 0.7:  # 70% match threshold
                savings_pct = None
                if source.unit_cost_usd and insert.unit_cost_usd:
                    savings_pct = round(
                        (1 - insert.unit_cost_usd / source.unit_cost_usd) * 100, 1
                    )
                equivalents.append({
                    "id": insert.id,
                    "manufacturer": insert.manufacturer,
                    "part_number": insert.part_number,
                    "iso_designation": insert.iso_designation,
                    "unit_cost_usd": insert.unit_cost_usd,
                    "cost_savings_pct": savings_pct,
                    "match_score": score,
                    "wear_validated": False,
                })

        # Sort by cost savings (cheapest first)
        equivalents.sort(key=lambda x: x.get("unit_cost_usd") or 999)
        return equivalents

    def _match_score(self, source, source_spec: Optional[InsertSpec],
                     candidate) -> float:
        """Calculate match score (0-1) between source and candidate insert."""
        if source_spec is None:
            # Fall back to ISO designation string comparison
            if source.iso_designation and candidate.iso_designation:
                # Compare first 4 characters (shape, clearance, tolerance, type)
                if source.iso_designation[:4] == candidate.iso_designation[:4]:
                    return 0.8
            return 0.0

        candidate_spec = None
        if candidate.iso_designation:
            candidate_spec = self.parse_designation(candidate.iso_designation)

        if candidate_spec is None:
            return 0.0

        score = 0.0
        checks = 0

        # Shape must match
        if source_spec.shape and candidate_spec.shape:
            checks += 1
            if source_spec.shape == candidate_spec.shape:
                score += 1.0

        # IC size must match
        if source_spec.ic_mm and candidate_spec.ic_mm:
            checks += 1
            if source_spec.ic_mm == candidate_spec.ic_mm:
                score += 1.0

        # Thickness must match
        if source_spec.thickness_mm and candidate_spec.thickness_mm:
            checks += 1
            if source_spec.thickness_mm == candidate_spec.thickness_mm:
                score += 1.0

        # Nose radius must match
        if source_spec.nose_radius_mm is not None and candidate_spec.nose_radius_mm is not None:
            checks += 1
            if source_spec.nose_radius_mm == candidate_spec.nose_radius_mm:
                score += 1.0

        # Insert type should match
        if source_spec.insert_type and candidate_spec.insert_type:
            checks += 1
            if source_spec.insert_type == candidate_spec.insert_type:
                score += 1.0

        return (score / checks) if checks > 0 else 0.0

    def cost_optimize(self, db: Session, user_id: Optional[int] = None) -> dict:
        """Analyze current insert spend and recommend cheaper equivalents."""
        from db_models import ToolingInsert

        inserts = db.query(ToolingInsert).all()
        if not inserts:
            return {
                "current_monthly_spend": 0,
                "optimized_monthly_spend": 0,
                "savings_usd": 0,
                "savings_pct": 0,
                "recommendations": [],
            }

        recommendations = []
        current_spend = 0
        optimized_spend = 0

        for insert in inserts:
            cost = insert.unit_cost_usd or 0
            current_spend += cost

            equivalents = self.find_equivalents(db, insert.id)
            cheaper = [e for e in equivalents if (e.get("cost_savings_pct") or 0) > 0]

            if cheaper:
                best = cheaper[0]
                optimized_spend += best["unit_cost_usd"] or cost
                recommendations.append({
                    "current_insert": {
                        "id": insert.id,
                        "manufacturer": insert.manufacturer,
                        "part_number": insert.part_number,
                        "unit_cost_usd": cost,
                    },
                    "recommended_insert": best,
                    "savings_per_insert_usd": round(cost - (best["unit_cost_usd"] or cost), 2),
                })
            else:
                optimized_spend += cost

        savings = current_spend - optimized_spend
        savings_pct = (savings / current_spend * 100) if current_spend > 0 else 0

        return {
            "current_monthly_spend": round(current_spend, 2),
            "optimized_monthly_spend": round(optimized_spend, 2),
            "savings_usd": round(savings, 2),
            "savings_pct": round(savings_pct, 1),
            "recommendations": recommendations,
        }

    def validate_with_wear_data(self, db: Session, insert_id: int,
                                 candidate_id: int) -> dict:
        """Compare wear curves between two inserts using sensor data."""
        from db_models import ToolingInsert, SensorReading, ToolRecord

        source = db.query(ToolingInsert).filter(ToolingInsert.id == insert_id).first()
        candidate = db.query(ToolingInsert).filter(ToolingInsert.id == candidate_id).first()

        if not source or not candidate:
            return {
                "original_insert_id": insert_id,
                "candidate_insert_id": candidate_id,
                "equivalent": None,
                "confidence": 0.0,
                "data_points": 0,
            }

        # Find tools that use these inserts (by part number in tool_type field)
        source_tools = db.query(ToolRecord).filter(
            ToolRecord.tool_type.ilike(f"%{source.part_number}%")
        ).all()
        candidate_tools = db.query(ToolRecord).filter(
            ToolRecord.tool_type.ilike(f"%{candidate.part_number}%")
        ).all()

        source_wear_scores = []
        for tool in source_tools:
            readings = db.query(SensorReading).filter(
                SensorReading.tool_id == tool.tool_id
            ).order_by(SensorReading.recorded_at).all()
            source_wear_scores.extend([r.wear_score for r in readings])

        candidate_wear_scores = []
        for tool in candidate_tools:
            readings = db.query(SensorReading).filter(
                SensorReading.tool_id == tool.tool_id
            ).order_by(SensorReading.recorded_at).all()
            candidate_wear_scores.extend([r.wear_score for r in readings])

        total_points = len(source_wear_scores) + len(candidate_wear_scores)

        # Calculate average wear rates
        source_avg = sum(source_wear_scores) / len(source_wear_scores) if source_wear_scores else None
        candidate_avg = sum(candidate_wear_scores) / len(candidate_wear_scores) if candidate_wear_scores else None

        equivalent = None
        confidence = 0.0
        if source_avg is not None and candidate_avg is not None and total_points >= 10:
            # Within 20% wear rate is considered equivalent
            ratio = candidate_avg / source_avg if source_avg > 0 else 999
            equivalent = 0.8 <= ratio <= 1.2
            confidence = min(1.0, total_points / 50)  # More data = higher confidence

        return {
            "original_insert_id": insert_id,
            "candidate_insert_id": candidate_id,
            "original_avg_wear_rate": round(source_avg, 2) if source_avg else None,
            "candidate_avg_wear_rate": round(candidate_avg, 2) if candidate_avg else None,
            "equivalent": equivalent,
            "confidence": round(confidence, 2),
            "data_points": total_points,
        }

    def import_from_invoice(self, text: str) -> list[InsertSpec]:
        """Parse tooling invoice text for insert part numbers."""
        found = []
        for line in text.split("\n"):
            match = _ISO_PATTERN.search(line.upper())
            if match:
                found.append(self.parse_designation(match.group(0)))
        return found
