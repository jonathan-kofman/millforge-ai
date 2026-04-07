import { useState } from "react";

const MATERIAL_COLORS = {
  steel: "#3b82f6",
  aluminum: "#22c55e",
  titanium: "#a855f7",
  copper: "#f97316",
};

const TOOL_CHANGE_COLOR = "#f59e0b";

function GanttBar({ label, color, left, width, isToolChange }) {
  return (
    <div
      className="absolute h-6 rounded text-xs flex items-center px-1 overflow-hidden font-mono"
      style={{
        left: `${left}%`,
        width: `${Math.max(width, 1)}%`,
        backgroundColor: color,
        opacity: isToolChange ? 0.9 : 0.8,
        border: isToolChange ? "2px dashed #b45309" : "none",
        color: "#fff",
        whiteSpace: "nowrap",
        minWidth: "2px",
      }}
      title={label}
    >
      {width > 4 ? label : ""}
    </div>
  );
}

function GanttRow({ machineId, jobs, toolChanges, minTime, totalMinutes }) {
  const machineJobs = jobs.filter((j) => j.machine_id === machineId);
  const machineChanges = toolChanges.filter((tc) => tc.machine_id === machineId);

  function pct(dt) {
    const t = new Date(dt).getTime();
    return ((t - minTime) / (totalMinutes * 60000)) * 100;
  }

  function width(start, end) {
    const s = new Date(start).getTime();
    const e = new Date(end).getTime();
    return ((e - s) / (totalMinutes * 60000)) * 100;
  }

  return (
    <div className="flex items-center gap-2">
      <div className="w-20 text-right text-xs text-gray-500 font-mono shrink-0">
        M{machineId}
      </div>
      <div className="relative flex-1 h-7 bg-gray-100 rounded overflow-visible">
        {machineJobs.map((job) => (
          <GanttBar
            key={job.order_id}
            label={job.order_id}
            color={MATERIAL_COLORS[job.material] || "#6b7280"}
            left={pct(job.processing_start)}
            width={width(job.processing_start, job.completion_time)}
            isToolChange={false}
          />
        ))}
        {machineChanges.map((tc, i) => {
          const startMs = new Date(tc.scheduled_at).getTime();
          const endMs = startMs + tc.duration_minutes * 60000;
          return (
            <GanttBar
              key={i}
              label={`TC: ${tc.tool_id}`}
              color={TOOL_CHANGE_COLOR}
              left={pct(tc.scheduled_at)}
              width={((endMs - startMs) / (totalMinutes * 60000)) * 100}
              isToolChange
            />
          );
        })}
      </div>
    </div>
  );
}

export default function ToolAwareSchedule() {
  const [orders, setOrders] = useState(
    `[
  {"order_id":"ORD-001","material":"steel","quantity":400,"dimensions":"200x100x10mm","due_date":"${new Date(Date.now() + 8 * 3600000).toISOString()}","priority":2,"complexity":1.0},
  {"order_id":"ORD-002","material":"aluminum","quantity":300,"dimensions":"150x80x5mm","due_date":"${new Date(Date.now() + 12 * 3600000).toISOString()}","priority":3,"complexity":1.2},
  {"order_id":"ORD-003","material":"steel","quantity":600,"dimensions":"300x200x15mm","due_date":"${new Date(Date.now() + 24 * 3600000).toISOString()}","priority":4,"complexity":1.5}
]`
  );
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const parsed = JSON.parse(orders);
      const res = await fetch("/api/schedule/tool-aware", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orders: parsed }),
      });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  // Gantt setup
  let gantt = null;
  if (result) {
    const schedule = result.schedule || [];
    const machineIds = [...new Set(schedule.map((j) => j.machine_id))].sort((a, b) => a - b);
    const toolChanges = result.tool_changes || [];

    const allTimes = [
      ...schedule.map((j) => new Date(j.processing_start).getTime()),
      ...schedule.map((j) => new Date(j.completion_time).getTime()),
      ...toolChanges.map((tc) => new Date(tc.scheduled_at).getTime()),
    ];
    const minTime = Math.min(...allTimes);
    const maxTime = Math.max(...allTimes);
    const totalMinutes = (maxTime - minTime) / 60000 || 60;

    gantt = { machineIds, toolChanges, minTime, totalMinutes, schedule };
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Tool-Aware Schedule</h1>
        <p className="text-sm text-gray-500 mt-1">
          SA optimizer + tool-change events inserted at natural job boundaries
        </p>
      </div>

      <form onSubmit={handleSubmit} className="card border border-gray-200 p-4 space-y-3">
        <label className="label">Orders (JSON array)</label>
        <textarea
          className="input font-mono text-xs"
          rows={8}
          value={orders}
          onChange={(e) => setOrders(e.target.value)}
        />
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? "Scheduling…" : "Run tool-aware schedule"}
        </button>
      </form>

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">{error}</div>
      )}

      {result && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "On-time rate", value: `${result.summary.on_time_rate_percent.toFixed(1)}%` },
              { label: "Makespan", value: `${result.summary.makespan_hours.toFixed(1)}h` },
              { label: "Tool changes", value: result.tool_changes?.length ?? 0 },
              { label: "Tool warnings", value: result.tool_warnings?.length ?? 0 },
            ].map(({ label, value }) => (
              <div key={label} className="card border border-gray-200 p-3 text-center">
                <div className="text-xl font-bold text-forge-navy">{value}</div>
                <div className="text-xs text-gray-500 mt-1">{label}</div>
              </div>
            ))}
          </div>

          {/* Tool warnings */}
          {result.tool_warnings?.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded p-3 space-y-1">
              <div className="text-sm font-semibold text-yellow-800">Tool wear alerts</div>
              {result.tool_warnings.map((w, i) => (
                <div key={i} className="text-xs text-yellow-700">{w}</div>
              ))}
            </div>
          )}

          {/* Tool changes */}
          {result.tool_changes?.length > 0 && (
            <div className="card border border-amber-200 p-4">
              <h3 className="font-semibold text-gray-900 mb-2">Scheduled tool changes</h3>
              <div className="space-y-1">
                {result.tool_changes.map((tc, i) => (
                  <div key={i} className="text-xs text-gray-700 flex gap-3">
                    <span className="font-mono text-amber-700">{tc.tool_id}</span>
                    <span>Machine {tc.machine_id}</span>
                    <span>After {tc.before_order_id} → before {tc.after_order_id}</span>
                    <span className="text-gray-500">{tc.duration_minutes} min</span>
                    <span className="text-gray-400">{tc.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Gantt */}
          {gantt && (
            <div className="card border border-gray-200 p-4">
              <div className="flex items-center gap-4 mb-3">
                <h3 className="font-semibold text-gray-900">Gantt chart</h3>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  {Object.entries(MATERIAL_COLORS).map(([m, c]) => (
                    <span key={m} className="flex items-center gap-1">
                      <span className="w-3 h-3 rounded" style={{ backgroundColor: c }} />
                      {m}
                    </span>
                  ))}
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-3 rounded border-2 border-dashed border-amber-600" style={{ backgroundColor: TOOL_CHANGE_COLOR }} />
                    tool change
                  </span>
                </div>
              </div>
              <div className="space-y-2">
                {gantt.machineIds.map((mid) => (
                  <GanttRow
                    key={mid}
                    machineId={mid}
                    jobs={gantt.schedule}
                    toolChanges={gantt.toolChanges}
                    minTime={gantt.minTime}
                    totalMinutes={gantt.totalMinutes}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
