"""
CSV bulk order importer with fuzzy column matching.

Parses a CSV upload, maps headers to canonical field names using aliases,
validates each row, and stores a preview in memory for a two-phase
import (preview → confirm).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Canonical field → list of accepted header aliases (lower-cased, underscores)
_ALIASES: Dict[str, List[str]] = {
    "material":   ["material", "mat", "metal", "type", "material_type"],
    "quantity":   ["quantity", "qty", "amount", "count", "units", "number", "num"],
    "due_date":   ["due_date", "deadline", "due", "delivery_date", "required_by",
                   "ship_date", "due_date", "duedate"],
    "order_id":   ["order_id", "order", "part_number", "part_no", "id",
                   "job_id", "po_number", "partno"],
    "dimensions": ["dimensions", "dims", "size", "spec", "specifications", "dimension"],
    "length_mm":  ["length_mm", "length", "len", "l_mm"],
    "width_mm":   ["width_mm", "width", "w_mm", "wid"],
    "height_mm":  ["height_mm", "height", "h_mm", "ht", "thickness", "thick"],
    "priority":   ["priority", "pri", "urgency", "importance"],
    "complexity": ["complexity", "cx", "multiplier", "difficulty", "complex"],
}

_VALID_MATERIALS = {"steel", "aluminum", "aluminium", "titanium", "copper"}
_MATERIAL_NORMALIZE = {"aluminium": "aluminum"}

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
)

# Module-level preview cache: token → {column_mapping, valid_rows, error_rows}
# POC: no TTL; tokens are single-use (consumed on confirm).
_PREVIEW_CACHE: Dict[str, dict] = {}

CSV_TEMPLATE = (
    "order_id,material,quantity,length_mm,width_mm,height_mm,due_date,priority\n"
    "ORD-001,steel,500,200,100,10,2025-12-01,3\n"
    "ORD-002,aluminum,200,150,75,8,2025-12-07,5\n"
    "ORD-003,titanium,50,300,150,20,2025-12-15,2\n"
)


def _map_header(header: str) -> Optional[str]:
    """Return canonical field name for a CSV header, or None if unrecognised."""
    h = header.strip().lower().replace(" ", "_").replace("-", "_")
    for canonical, aliases in _ALIASES.items():
        if h in aliases:
            return canonical
    return None


def _parse_date(s: str) -> datetime:
    """Try several common date formats; raise ValueError if none match."""
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date '{s}' — expected YYYY-MM-DD or MM/DD/YYYY")


def parse_csv(
    content: str | bytes,
) -> Tuple[Dict[str, str], List[dict], List[dict]]:
    """
    Parse CSV content.

    Returns
    -------
    column_mapping : Dict[str, str]
        original header → canonical field name (only recognised headers included)
    valid_rows : List[dict]
        Parsed, validated rows ready for DB insertion.  ``due_date`` is a
        Python datetime object.
    error_rows : List[dict]
        Rows that failed validation: ``{row_number, raw_data, error}``

    Raises
    ------
    ValueError
        If the CSV has no headers, or required columns (material, quantity,
        due_date) cannot be matched to any header.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")  # strip BOM if present

    reader = csv.DictReader(io.StringIO(content.strip()))
    if not reader.fieldnames:
        raise ValueError("CSV has no headers")

    # Build column mapping: original header → canonical field
    column_mapping: Dict[str, str] = {}
    for original in reader.fieldnames:
        canonical = _map_header(original)
        if canonical and canonical not in column_mapping.values():
            column_mapping[original] = canonical

    # Check required columns are covered
    mapped = set(column_mapping.values())
    missing = {"material", "quantity", "due_date"} - mapped
    if missing:
        raise ValueError(
            f"Missing required columns: {', '.join(sorted(missing))}. "
            "Expected headers like: material, quantity, due_date "
            "(or aliases: qty, deadline, mat…)"
        )

    # Reverse map: canonical field → first matching original header
    rev: Dict[str, str] = {}
    for orig, canon in column_mapping.items():
        if canon not in rev:
            rev[canon] = orig

    valid_rows: List[dict] = []
    error_rows: List[dict] = []

    for row_num, row in enumerate(reader, start=2):  # row 1 = header
        raw = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}
        try:
            # --- required ---
            mat_raw = raw.get(rev["material"], "").strip().lower()
            mat_raw = _MATERIAL_NORMALIZE.get(mat_raw, mat_raw)
            if mat_raw not in _VALID_MATERIALS:
                raise ValueError(f"Unknown material '{mat_raw}' (valid: steel, aluminum, titanium, copper)")

            qty_str = raw.get(rev["quantity"], "").strip()
            if not qty_str:
                raise ValueError("quantity is empty")
            qty = int(qty_str)
            if qty <= 0:
                raise ValueError(f"quantity must be > 0, got {qty}")

            due_raw = raw.get(rev["due_date"], "").strip()
            if not due_raw:
                raise ValueError("due_date is empty")
            due_date = _parse_date(due_raw)

            # --- optional ---
            order_id: Optional[str] = None
            if "order_id" in rev:
                val = raw.get(rev["order_id"], "").strip()
                order_id = val if val else None

            dimensions = "100x100x10mm"
            if "dimensions" in rev:
                val = raw.get(rev["dimensions"], "").strip()
                if val:
                    dimensions = val
            elif "length_mm" in rev or "width_mm" in rev or "height_mm" in rev:
                # Combine separate L/W/H columns into "LxWxHmm"
                l_val = raw.get(rev.get("length_mm", ""), "").strip() if "length_mm" in rev else ""
                w_val = raw.get(rev.get("width_mm", ""), "").strip() if "width_mm" in rev else ""
                h_val = raw.get(rev.get("height_mm", ""), "").strip() if "height_mm" in rev else ""
                l = float(l_val) if l_val else 100.0
                w = float(w_val) if w_val else 100.0
                h = float(h_val) if h_val else 10.0
                dimensions = f"{l:.0f}x{w:.0f}x{h:.0f}mm"

            priority = 5
            if "priority" in rev:
                val = raw.get(rev["priority"], "").strip()
                if val:
                    priority = max(1, min(10, int(val)))

            complexity = 1.0
            if "complexity" in rev:
                val = raw.get(rev["complexity"], "").strip()
                if val:
                    complexity = max(0.1, min(5.0, float(val)))

            valid_rows.append({
                "row_number": row_num,
                "order_id": order_id,
                "material": mat_raw,
                "quantity": qty,
                "due_date": due_date,
                "dimensions": dimensions,
                "priority": priority,
                "complexity": complexity,
            })
        except Exception as exc:
            error_rows.append({
                "row_number": row_num,
                "raw_data": dict(raw),
                "error": str(exc),
            })

    return column_mapping, valid_rows, error_rows


def create_preview(
    column_mapping: Dict[str, str],
    valid_rows: List[dict],
    error_rows: List[dict],
) -> str:
    """Store parsed result in memory and return a single-use preview token."""
    token = uuid.uuid4().hex
    _PREVIEW_CACHE[token] = {
        "column_mapping": column_mapping,
        "valid_rows": valid_rows,
        "error_rows": error_rows,
    }
    return token


def get_preview(token: str) -> Optional[dict]:
    """Return cached preview data without consuming it, or None."""
    return _PREVIEW_CACHE.get(token)


def consume_preview(token: str) -> Optional[dict]:
    """Return and remove cached preview data (single-use), or None if missing."""
    return _PREVIEW_CACHE.pop(token, None)
