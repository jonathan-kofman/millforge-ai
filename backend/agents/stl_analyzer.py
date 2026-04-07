"""
STLAnalyzer — lightweight STL geometry analysis using trimesh.

Extracts bounding box, volume, face count, and surface area from an STL
file's bytes. Used by the ARIA scan bridge's /api/aria/stl-analyze endpoint
so the shop owner can upload a raw STL instead of pasting a JSON catalog
entry.

trimesh is an optional dependency. If not installed, all methods fall back
to a bounding-box-only estimate based on STL header parsing.
"""

from __future__ import annotations

import io
import struct
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# trimesh is optional — graceful fallback if not installed
try:
    import trimesh  # type: ignore
    _TRIMESH_AVAILABLE = True
except ImportError:
    _TRIMESH_AVAILABLE = False
    logger.warning("trimesh not installed — STL analysis uses header-only fallback")


class STLAnalyzer:
    """
    Stateless STL analysis. Call analyze(stl_bytes) → dict.

    Result dict keys:
        dimensions        (str)  — "XxYxZmm" bounding box
        bounding_box      (dict) — {x, y, z} in mm
        volume_mm3        (float) — mesh volume (0 if not watertight)
        surface_area_mm2  (float)
        face_count        (int)
        is_watertight     (bool)
        complexity        (float) — [1.0, 5.0] based on face count
        analysis_method   (str)  — "trimesh" or "header_fallback"
    """

    def analyze(self, stl_bytes: bytes) -> Dict[str, Any]:
        """Analyse raw STL bytes and return geometry metrics."""
        if _TRIMESH_AVAILABLE:
            try:
                return self._analyze_trimesh(stl_bytes)
            except Exception as e:
                logger.warning("trimesh analysis failed (%s), falling back", e)

        return self._analyze_header(stl_bytes)

    # ------------------------------------------------------------------
    # trimesh path (preferred)
    # ------------------------------------------------------------------

    def _analyze_trimesh(self, stl_bytes: bytes) -> Dict[str, Any]:
        mesh = trimesh.load(io.BytesIO(stl_bytes), file_type="stl")

        # trimesh may return a Scene for multi-mesh STLs
        if hasattr(mesh, "to_geometry"):
            mesh = mesh.to_geometry()
        elif hasattr(mesh, "dump"):
            mesh = mesh.dump(concatenate=True)

        verts = mesh.vertices
        mins = verts.min(axis=0)
        maxs = verts.max(axis=0)
        bb = maxs - mins  # [x, y, z] in mm

        x, y, z = float(bb[0]), float(bb[1]), float(bb[2])
        is_watertight = bool(mesh.is_watertight)
        volume = float(abs(mesh.volume)) if is_watertight else 0.0
        surface_area = float(mesh.area)
        face_count = len(mesh.faces)
        complexity = self._complexity_from_faces(face_count)

        return {
            "dimensions": f"{round(x)}x{round(y)}x{round(z)}mm",
            "bounding_box": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
            "volume_mm3": round(volume, 2),
            "surface_area_mm2": round(surface_area, 2),
            "face_count": face_count,
            "is_watertight": is_watertight,
            "complexity": complexity,
            "analysis_method": "trimesh",
        }

    # ------------------------------------------------------------------
    # Header-only fallback (works without trimesh)
    # ------------------------------------------------------------------

    def _analyze_header(self, stl_bytes: bytes) -> Dict[str, Any]:
        """
        Binary STL: 80-byte header + 4-byte triangle count + N*50 bytes.
        Parse triangles to get bounding box; volume = 0 (unknown watertight).
        """
        if len(stl_bytes) < 84:
            return self._empty_result()

        # Detect ASCII STL
        header = stl_bytes[:80]
        if header.lstrip().lower().startswith(b"solid") and b"facet" in stl_bytes[:256]:
            return self._analyze_ascii(stl_bytes)

        face_count = struct.unpack_from("<I", stl_bytes, 80)[0]
        expected_len = 84 + face_count * 50
        if len(stl_bytes) < expected_len:
            face_count = (len(stl_bytes) - 84) // 50

        mins = [float("inf")] * 3
        maxs = [float("-inf")] * 3
        offset = 84
        for _ in range(face_count):
            if offset + 50 > len(stl_bytes):
                break
            offset += 12  # skip normal
            for v in range(3):
                vx, vy, vz = struct.unpack_from("<fff", stl_bytes, offset)
                mins[0] = min(mins[0], vx)
                mins[1] = min(mins[1], vy)
                mins[2] = min(mins[2], vz)
                maxs[0] = max(maxs[0], vx)
                maxs[1] = max(maxs[1], vy)
                maxs[2] = max(maxs[2], vz)
                offset += 12
            offset += 2  # attribute byte count

        if mins[0] == float("inf"):
            return self._empty_result()

        x = maxs[0] - mins[0]
        y = maxs[1] - mins[1]
        z = maxs[2] - mins[2]
        complexity = self._complexity_from_faces(face_count)

        return {
            "dimensions": f"{round(x)}x{round(y)}x{round(z)}mm",
            "bounding_box": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
            "volume_mm3": 0.0,
            "surface_area_mm2": 0.0,
            "face_count": face_count,
            "is_watertight": False,
            "complexity": complexity,
            "analysis_method": "header_fallback",
        }

    def _analyze_ascii(self, stl_bytes: bytes) -> Dict[str, Any]:
        """Parse ASCII STL for bounding box."""
        text = stl_bytes.decode("utf-8", errors="replace")
        face_count = text.count("facet normal")
        mins = [float("inf")] * 3
        maxs = [float("-inf")] * 3
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("vertex"):
                parts = line.split()
                if len(parts) == 4:
                    try:
                        vx, vy, vz = float(parts[1]), float(parts[2]), float(parts[3])
                        mins[0] = min(mins[0], vx)
                        mins[1] = min(mins[1], vy)
                        mins[2] = min(mins[2], vz)
                        maxs[0] = max(maxs[0], vx)
                        maxs[1] = max(maxs[1], vy)
                        maxs[2] = max(maxs[2], vz)
                    except ValueError:
                        pass

        if mins[0] == float("inf"):
            return self._empty_result()

        x, y, z = maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]
        complexity = self._complexity_from_faces(face_count)
        return {
            "dimensions": f"{round(x)}x{round(y)}x{round(z)}mm",
            "bounding_box": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
            "volume_mm3": 0.0,
            "surface_area_mm2": 0.0,
            "face_count": face_count,
            "is_watertight": False,
            "complexity": complexity,
            "analysis_method": "header_fallback",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _complexity_from_faces(face_count: int) -> float:
        """Map face count to complexity score [1.0, 5.0]."""
        # Each 2000 faces adds 1 complexity point above baseline of 1.0
        score = 1.0 + face_count / 2000.0
        return round(min(5.0, max(1.0, score)), 2)

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "dimensions": "0x0x0mm",
            "bounding_box": {"x": 0.0, "y": 0.0, "z": 0.0},
            "volume_mm3": 0.0,
            "surface_area_mm2": 0.0,
            "face_count": 0,
            "is_watertight": False,
            "complexity": 1.0,
            "analysis_method": "header_fallback",
        }

    def to_catalog_entry(
        self,
        stl_result: Dict[str, Any],
        material: str = "steel",
        part_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert an STL analysis result to a catalog_entry dict compatible with
        ARIABridgeAgent, so STL uploads can be routed through the same pipeline.
        """
        return {
            "part_id": part_id or "STL-UPLOAD",
            "material": material,
            "bounding_box": stl_result["bounding_box"],
            "volume_mm3": stl_result["volume_mm3"],
            "primitives_summary": [],  # no feature extraction from raw STL
        }
