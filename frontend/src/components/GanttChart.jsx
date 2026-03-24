/**
 * Pure-SVG Gantt chart for a schedule result.
 *
 * Props:
 *   schedule  – Array of ScheduledOrderOutput from POST /api/orders/schedule
 */

const MATERIAL_COLORS = {
  steel:    { fill: "#3b82f6", text: "#bfdbfe" },  // blue
  aluminum: { fill: "#10b981", text: "#a7f3d0" },  // green
  titanium: { fill: "#8b5cf6", text: "#ddd6fe" },  // purple
  copper:   { fill: "#f59e0b", text: "#fde68a" },  // amber
};
const DEFAULT_COLOR = { fill: "#6b7280", text: "#e5e7eb" };

const ROW_HEIGHT = 36;
const ROW_GAP    = 6;
const LABEL_W    = 56;   // left column for "M1", "M2" labels
const PAD_TOP    = 28;   // space for time axis labels
const PAD_BOTTOM = 8;
const TICK_COUNT = 5;

function fmt(dt) {
  const d = new Date(dt);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function GanttChart({ schedule }) {
  if (!schedule || schedule.length === 0) return null;

  // ── Compute time range ──────────────────────────────────────────────────
  const starts = schedule.map(s => new Date(s.setup_start).getTime());
  const ends   = schedule.map(s => new Date(s.completion_time).getTime());
  const tMin   = Math.min(...starts);
  const tMax   = Math.max(...ends);
  const tRange = tMax - tMin || 1;

  // ── Machine rows ────────────────────────────────────────────────────────
  const machines = [...new Set(schedule.map(s => s.machine_id))].sort((a, b) => a - b);
  const machineRow = Object.fromEntries(machines.map((m, i) => [m, i]));

  const chartW = "100%";  // responsive; we use viewBox
  const CHART_W = 800;    // internal coordinate system
  const BAR_W   = CHART_W - LABEL_W;
  const svgH    = PAD_TOP + machines.length * (ROW_HEIGHT + ROW_GAP) + PAD_BOTTOM;

  const toX = (ts) => LABEL_W + ((new Date(ts).getTime() - tMin) / tRange) * BAR_W;
  const toRow = (machineId) => PAD_TOP + machineRow[machineId] * (ROW_HEIGHT + ROW_GAP);

  // ── Tick marks ──────────────────────────────────────────────────────────
  const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, i) => {
    const t = tMin + (tRange * i) / TICK_COUNT;
    const x = LABEL_W + (BAR_W * i) / TICK_COUNT;
    return { x, label: fmt(t) };
  });

  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
        Machine Timeline (Gantt)
      </h4>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-3">
        {Object.entries(MATERIAL_COLORS).map(([mat, col]) => (
          <span key={mat} className="flex items-center gap-1 text-xs text-gray-400">
            <span className="inline-block w-3 h-3 rounded-sm" style={{ background: col.fill }} />
            {mat.charAt(0).toUpperCase() + mat.slice(1)}
          </span>
        ))}
        <span className="flex items-center gap-1 text-xs text-gray-400 ml-4">
          <span className="inline-block w-3 h-3 rounded-sm border border-dashed border-red-400" style={{ background: "transparent" }} />
          Late
        </span>
      </div>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${CHART_W} ${svgH}`}
          width={chartW}
          style={{ minWidth: 480 }}
          className="block"
          role="img"
          aria-label="Production schedule Gantt chart"
        >
          {/* Axis ticks + labels */}
          {ticks.map(({ x, label }, i) => (
            <g key={i}>
              <line x1={x} y1={PAD_TOP - 4} x2={x} y2={svgH - PAD_BOTTOM} stroke="#374151" strokeWidth={1} />
              <text
                x={x}
                y={PAD_TOP - 8}
                textAnchor={i === 0 ? "start" : i === TICK_COUNT ? "end" : "middle"}
                fontSize={9}
                fill="#6b7280"
              >
                {label}
              </text>
            </g>
          ))}

          {/* Machine row labels + background bands */}
          {machines.map((mId, i) => {
            const y = toRow(mId);
            const isEven = i % 2 === 0;
            return (
              <g key={mId}>
                <rect
                  x={0} y={y} width={CHART_W} height={ROW_HEIGHT}
                  fill={isEven ? "#111827" : "#0f172a"}
                  rx={0}
                />
                <text x={LABEL_W - 6} y={y + ROW_HEIGHT / 2 + 4} textAnchor="end" fontSize={11} fill="#9ca3af" fontWeight={500}>
                  M{mId}
                </text>
              </g>
            );
          })}

          {/* Order bars */}
          {schedule.map((s) => {
            const col  = MATERIAL_COLORS[s.material] || DEFAULT_COLOR;
            const y    = toRow(s.machine_id);
            const barY = y + 5;
            const barH = ROW_HEIGHT - 10;

            // Setup block (dimmer)
            const sx  = toX(s.setup_start);
            const px  = toX(s.processing_start);
            const ex  = toX(s.completion_time);
            const setupW = Math.max(px - sx, 1);
            const procW  = Math.max(ex - px, 1);

            return (
              <g key={s.order_id}>
                {/* Setup segment */}
                <rect
                  x={sx} y={barY} width={setupW} height={barH}
                  fill={col.fill} opacity={0.3} rx={2}
                />
                {/* Processing segment */}
                <rect
                  x={px} y={barY} width={procW} height={barH}
                  fill={col.fill} opacity={s.on_time ? 0.85 : 0.5} rx={2}
                />
                {/* Late indicator border */}
                {!s.on_time && (
                  <rect
                    x={px} y={barY} width={procW} height={barH}
                    fill="none" stroke="#f87171" strokeWidth={1.5} rx={2}
                    strokeDasharray="3,2"
                  />
                )}
                {/* Label — only render if bar is wide enough */}
                {procW > 40 && (
                  <text
                    x={px + procW / 2} y={barY + barH / 2 + 4}
                    textAnchor="middle"
                    fontSize={9}
                    fill={col.text}
                    style={{ pointerEvents: "none" }}
                  >
                    {s.order_id}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
