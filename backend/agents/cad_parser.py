"""
CAD Parser agent — extracts order parameters from STL file uploads.

This is the ARIA-OS integration point: ARIA CAD output → STL upload →
auto-populated draft order → MillForge scheduling pipeline.
No human translates CAD geometry into job parameters.
"""

import io
import numpy as np


def extract_from_stl(file_bytes: bytes) -> dict:
    """
    Parse an STL file and extract order parameters.

    Returns a dict with:
        dimensions      str  e.g. "45.2x32.1x18.7mm"
        complexity      int  1-10 (triangle_count // 1000, clamped)
        estimated_volume_cm3  float  bounding box volume proxy in cm³
        triangle_count  int  total number of triangles in the mesh
        source          str  "stl_upload"
    """
    try:
        from stl import mesh as stl_mesh
    except ImportError as exc:
        raise RuntimeError(
            "numpy-stl is required for STL parsing. "
            "Install it with: pip install numpy-stl>=3.0.0"
        ) from exc

    m = stl_mesh.Mesh.from_file("", fh=io.BytesIO(file_bytes))

    # Bounding box — vectors shape is (n_triangles, 3, 3)
    all_points = m.vectors.reshape(-1, 3)
    min_xyz = all_points.min(axis=0)
    max_xyz = all_points.max(axis=0)
    dims_mm = max_xyz - min_xyz                  # x, y, z in model units (mm)

    x, y, z = float(dims_mm[0]), float(dims_mm[1]), float(dims_mm[2])
    triangle_count = len(m.vectors)

    # Complexity: 1 per 1000 triangles, clamped to [1, 10]
    complexity = min(10, max(1, triangle_count // 1000))

    # Volume proxy: bounding box in cm³
    estimated_volume_cm3 = round((x * y * z) / 1000.0, 2)

    dimensions = f"{round(x, 1)}x{round(y, 1)}x{round(z, 1)}mm"

    return {
        "dimensions": dimensions,
        "complexity": complexity,
        "estimated_volume_cm3": estimated_volume_cm3,
        "triangle_count": triangle_count,
        "source": "stl_upload",
    }
