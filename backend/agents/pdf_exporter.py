"""
MillForge Schedule PDF Exporter

Generates a production-ready PDF from a saved ScheduleRun including:
  - Header with run metadata
  - Summary KPI table (on-time rate, makespan, utilization)
  - Gantt chart with material-coded bars per machine
  - Order details table
  - Footer
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.graphics.shapes import Drawing, Rect, Line, String
from reportlab.graphics import renderPDF
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Material → RGB colour tuple (0–1 scale)
_MATERIAL_COLORS = {
    "steel":    colors.HexColor("#4A5568"),   # slate grey
    "aluminum": colors.HexColor("#3182CE"),   # blue
    "titanium": colors.HexColor("#805AD5"),   # purple
    "copper":   colors.HexColor("#DD6B20"),   # orange
}
_DEFAULT_COLOR = colors.HexColor("#718096")

_PAGE_W, _PAGE_H = letter          # 612 x 792 pts
_MARGIN = 0.65 * inch
_CONTENT_W = _PAGE_W - 2 * _MARGIN


def _mat_color(material: str) -> colors.Color:
    return _MATERIAL_COLORS.get(material.lower(), _DEFAULT_COLOR)


def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def _build_gantt(orders: List[dict], makespan_hours: float) -> Drawing:
    """
    Build a Gantt chart as a reportlab Drawing.

    X-axis = time (hours from first setup_start), Y-axis = machine lanes.
    Each bar spans setup_start → completion_time, coloured by material.
    """
    chart_w = _CONTENT_W
    bar_h = 18
    lane_gap = 6
    label_w = 48  # pts for machine label column
    axis_h = 24   # height of time axis area at bottom

    machines = sorted({o["machine_id"] for o in orders})
    n_machines = len(machines)
    machine_idx = {m: i for i, m in enumerate(machines)}

    chart_area_h = n_machines * (bar_h + lane_gap) + lane_gap
    total_h = chart_area_h + axis_h + 10

    drawing = Drawing(chart_w, total_h)

    # background
    drawing.add(Rect(0, axis_h, chart_w, chart_area_h + 10,
                     fillColor=colors.HexColor("#F7FAFC"), strokeColor=colors.HexColor("#E2E8F0"),
                     strokeWidth=0.5))

    # compute time scale
    if not orders:
        return drawing

    all_starts = [_parse_dt(o["setup_start"]) for o in orders]
    t0 = min(all_starts)
    total_secs = makespan_hours * 3600 if makespan_hours > 0 else 1

    avail_w = chart_w - label_w
    x_origin = label_w

    def _t_to_x(dt_str: str) -> float:
        delta = (_parse_dt(dt_str) - t0).total_seconds()
        return x_origin + (delta / total_secs) * avail_w

    def _machine_y(machine_id: int) -> float:
        idx = machine_idx[machine_id]
        return axis_h + lane_gap + idx * (bar_h + lane_gap)

    # machine labels + lane lines
    for m in machines:
        y = _machine_y(m)
        drawing.add(String(2, y + 4, f"M{m}",
                           fontName="Helvetica-Bold", fontSize=9,
                           fillColor=colors.HexColor("#2D3748")))
        # subtle lane background
        lane_color = colors.HexColor("#EBF4FF") if machine_idx[m] % 2 == 0 else colors.HexColor("#F7FAFC")
        drawing.add(Rect(x_origin, y - 2, avail_w, bar_h + 4,
                         fillColor=lane_color, strokeColor=None))

    # order bars
    for order in orders:
        m_id = order["machine_id"]
        y = _machine_y(m_id)
        x1 = _t_to_x(order["setup_start"])
        x2 = _t_to_x(order["completion_time"])
        bar_width = max(x2 - x1, 2)

        fill = _mat_color(order["material"])
        stroke = colors.HexColor("#2D3748")
        drawing.add(Rect(x1, y, bar_width, bar_h,
                         fillColor=fill, strokeColor=stroke, strokeWidth=0.4))

        # label inside bar if wide enough
        if bar_width > 30:
            label = order["order_id"]
            drawing.add(String(x1 + 2, y + 5, label,
                               fontName="Helvetica", fontSize=6,
                               fillColor=colors.white))

        # red outline for late orders
        if not order.get("on_time", True):
            drawing.add(Rect(x1, y, bar_width, bar_h,
                             fillColor=None, strokeColor=colors.HexColor("#E53E3E"),
                             strokeWidth=1.2))

    # time axis ticks
    tick_count = min(6, max(2, int(makespan_hours)))
    for i in range(tick_count + 1):
        t_h = makespan_hours * i / tick_count
        x = x_origin + (t_h / makespan_hours) * avail_w if makespan_hours > 0 else x_origin
        drawing.add(Line(x, axis_h, x, axis_h + chart_area_h,
                         strokeColor=colors.HexColor("#CBD5E0"), strokeWidth=0.4))
        drawing.add(String(x - 8, 2, f"{t_h:.0f}h",
                           fontName="Helvetica", fontSize=7,
                           fillColor=colors.HexColor("#718096")))

    return drawing


def _legend_table() -> Table:
    """Compact material colour legend row."""
    cells = []
    for mat, col in _MATERIAL_COLORS.items():
        swatch = Paragraph(
            f'<font color="{col.hexval()}" size="14">■</font> {mat.capitalize()}',
            getSampleStyleSheet()["Normal"],
        )
        cells.append(swatch)
    tbl = Table([cells], colWidths=[_CONTENT_W / 4] * 4)
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return tbl


def build_schedule_pdf(
    schedule_run_id: int,
    algorithm: str,
    summary: dict,
    orders: List[dict],
    generated_at: Optional[datetime] = None,
) -> bytes:
    """
    Render a ScheduleRun as a PDF and return the raw bytes.

    Parameters
    ----------
    schedule_run_id : int
    algorithm : str
    summary : dict  — keys: total_orders, on_time_count, on_time_rate_percent,
                            makespan_hours, utilization_percent
    orders : List[dict] — ScheduledOrderOutput dicts with ISO datetime strings
    generated_at : Optional[datetime]
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
    )
    styles = getSampleStyleSheet()
    story = []

    # ---- Header -----------------------------------------------------------
    title_style = styles["Heading1"]
    title_style.alignment = TA_CENTER
    story.append(Paragraph("MillForge Production Schedule", title_style))

    ts = generated_at.strftime("%Y-%m-%d %H:%M UTC") if generated_at else "—"
    sub_style = styles["Normal"]
    sub_style.alignment = TA_CENTER
    story.append(Paragraph(
        f"Schedule Run #{schedule_run_id} &nbsp;|&nbsp; Algorithm: {algorithm.upper()} &nbsp;|&nbsp; Generated: {ts}",
        sub_style,
    ))
    story.append(Spacer(1, 0.2 * inch))

    # ---- Summary KPI table ------------------------------------------------
    on_time_pct = summary.get("on_time_rate_percent", 0.0)
    on_time_count = summary.get("on_time_count", 0)
    total_orders = summary.get("total_orders", len(orders))
    makespan = summary.get("makespan_hours", 0.0)
    utilization = summary.get("utilization_percent", 0.0)

    kpi_data = [
        ["Metric", "Value"],
        ["Total Orders", str(total_orders)],
        ["On-Time Orders", f"{on_time_count} / {total_orders}  ({on_time_pct:.1f}%)"],
        ["Makespan", f"{makespan:.2f} h"],
        ["Machine Utilization", f"{utilization:.1f}%"],
        ["Algorithm", algorithm.upper()],
    ]
    kpi_tbl = Table(kpi_data, colWidths=[_CONTENT_W * 0.45, _CONTENT_W * 0.55])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EBF8FF")]),
        ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#BEE3F8")),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 0.2 * inch))

    # ---- Gantt chart ------------------------------------------------------
    h2 = styles["Heading2"]
    h2.alignment = TA_LEFT
    story.append(Paragraph("Production Gantt Chart", h2))
    story.append(Spacer(1, 0.05 * inch))
    if orders:
        gantt = _build_gantt(orders, makespan)
        story.append(gantt)
        story.append(Spacer(1, 0.05 * inch))
        story.append(_legend_table())
        story.append(Paragraph(
            "<font size='7' color='#718096'>Red outline = late order.  "
            "Bars coloured by material.  X-axis = hours from schedule start.</font>",
            styles["Normal"],
        ))
    else:
        story.append(Paragraph("No order data available for Gantt chart.", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    # ---- Order details table ----------------------------------------------
    story.append(Paragraph("Order Details", h2))
    story.append(Spacer(1, 0.05 * inch))

    col_widths = [
        _CONTENT_W * 0.13,  # Order ID
        _CONTENT_W * 0.10,  # Material
        _CONTENT_W * 0.07,  # Qty
        _CONTENT_W * 0.07,  # Machine
        _CONTENT_W * 0.18,  # Completion
        _CONTENT_W * 0.10,  # Setup (min)
        _CONTENT_W * 0.10,  # Proc (min)
        _CONTENT_W * 0.12,  # Lateness
        _CONTENT_W * 0.13,  # On-Time
    ]
    tbl_data = [["Order ID", "Material", "Qty", "M#", "Completion", "Setup\n(min)", "Proc\n(min)", "Late\n(h)", "On-Time"]]
    for o in orders:
        try:
            ct = _parse_dt(o["completion_time"]).strftime("%m/%d %H:%M")
        except Exception:
            ct = str(o.get("completion_time", ""))
        tbl_data.append([
            o["order_id"],
            o["material"].capitalize(),
            str(o["quantity"]),
            str(o["machine_id"]),
            ct,
            str(o.get("setup_minutes", "")),
            f"{o.get('processing_minutes', 0):.0f}",
            f"{o.get('lateness_hours', 0):.1f}",
            "✓" if o.get("on_time") else "✗",
        ])

    detail_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    row_colors = []
    for i, row in enumerate(tbl_data[1:], start=1):
        on_time = row[-1] == "✓"
        bg = colors.white if on_time else colors.HexColor("#FFF5F5")
        row_colors.append(("BACKGROUND", (0, i), (-1, i), bg))

    detail_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("ALIGN",         (2, 0), (-1, -1), "CENTER"),
        *row_colors,
    ]))
    story.append(detail_tbl)
    story.append(Spacer(1, 0.3 * inch))

    # ---- Footer -----------------------------------------------------------
    footer_style = styles["Normal"]
    footer_style.fontSize = 8
    footer_style.textColor = colors.HexColor("#718096")
    footer_style.alignment = TA_CENTER
    story.append(Paragraph(
        "MillForge — Lights-Out American Metal Manufacturing Intelligence",
        footer_style,
    ))

    doc.build(story)
    return buf.getvalue()
