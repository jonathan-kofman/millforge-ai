import { useState, useEffect } from "react";
import { API_BASE } from "../config";
import BenchmarkPanel from "./BenchmarkPanel";

const MATERIAL_COLORS = {
  steel:    { bar: "bg-blue-500",   text: "text-blue-400",   badge: "bg-blue-900/50 text-blue-300" },
  aluminum: { bar: "bg-green-500",  text: "text-green-400",  badge: "bg-green-900/50 text-green-300" },
  titanium: { bar: "bg-purple-500", text: "text-purple-400", badge: "bg-purple-900/50 text-purple-300" },
  copper:   { bar: "bg-amber-500",  text: "text-amber-400",  badge: "bg-amber-900/50 text-amber-300" },
};

export default function ScheduleViewer() {
  const [mode, setMode] = useState("demo"); // "demo" | "live"
  const [schedule, setSchedule] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [algorithm, setAlgorithm] = useState("sa");
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState(null);
  const [emptyOrders, setEmptyOrders] = useState(false);

  const loadDemo = async (algo = algorithm) => {
    setLoading(true);
    setError(null);
    setApplyResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/schedule/demo?algorithm=${algo}`);
      if (!res.ok) throw new Error("Failed to load demo schedule");
      setSchedule(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadLive = async () => {
    setLoading(true);
    setError(null);
    setApplyResult(null);
    setEmptyOrders(false);
    try {
      // Fetch user's pending orders
      const ordRes = await fetch(`${API_BASE}/api/orders?status=pending&limit=200`, { credentials: "include" });
      if (!ordRes.ok) throw new Error("Failed to fetch orders — are you signed in?");
      const ordData = await ordRes.json();
      const orders = (ordData.orders ?? ordData ?? []).filter(o => o.status !== "completed" && o.status !== "cancelled");
      if (orders.length === 0) {
        setSchedule(null);
        setEmptyOrders(true);
        return;
      }
      // Map to scheduler format
      const payload = orders.map(o => ({
        order_id: o.order_id,
        material: o.material,
        quantity: o.quantity ?? 1,
        dimensions: o.dimensions ?? "100x100x10mm",
        due_date: o.due_date ?? new Date(Date.now() + 7 * 86400000).toISOString(),
        priority: o.priority ?? 5,
        complexity: o.complexity ?? 1.0,
      }));
      const schedRes = await fetch(`${API_BASE}/api/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ orders: payload, algorithm }),
      });
      if (!schedRes.ok) throw new Error("Scheduling failed: " + (await schedRes.text()));
      const result = await schedRes.json();
      setSchedule({ ...result, _live: true, _orderIds: orders.map(o => o.order_id) });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async () => {
    if (!schedule?._live) return;
    setApplying(true);
    setError(null);
    let applied = 0;
    for (const item of schedule.schedule) {
      try {
        await fetch(`${API_BASE}/api/orders/${item.order_id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ status: "in_progress", notes: `Scheduled: Machine #${item.machine_id} · Est. completion ${new Date(item.completion_time).toLocaleString()}` }),
        });
        applied++;
      } catch { /* non-fatal */ }
    }
    setApplying(false);
    setApplyResult(`Applied — ${applied} order(s) marked in-progress with machine assignments.`);
  };

  useEffect(() => {
    if (mode === "demo") loadDemo();
    else setSchedule(null);
  }, [mode]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-2xl font-bold text-white">Production Schedule</h2>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Mode toggle */}
          <div className="flex gap-1 border border-gray-700 rounded-lg p-0.5">
            {[{ id: "demo", label: "Demo" }, { id: "live", label: "My Orders" }].map(m => (
              <button
                key={m.id}
                onClick={() => setMode(m.id)}
                className={`px-3 py-1 text-xs font-medium rounded transition-colors ${mode === m.id ? "bg-forge-500 text-white" : "text-gray-400 hover:text-white"}`}
              >
                {m.label}
              </button>
            ))}
          </div>
          {mode === "demo" && (
            <>
              <select
                value={algorithm}
                onChange={e => { setAlgorithm(e.target.value); loadDemo(e.target.value); }}
                className="input text-sm py-1.5 w-auto"
              >
                <option value="sa">Simulated Annealing</option>
                <option value="edd">EDD (Greedy)</option>
              </select>
              <button onClick={() => loadDemo(algorithm)} className="btn-secondary text-sm" disabled={loading}>
                {loading ? "Loading…" : "↺ Refresh"}
              </button>
            </>
          )}
          {mode === "live" && (
            <>
              <select
                value={algorithm}
                onChange={e => setAlgorithm(e.target.value)}
                className="input text-sm py-1.5 w-auto"
              >
                <option value="sa">Simulated Annealing</option>
                <option value="edd">EDD (Greedy)</option>
              </select>
              <button onClick={loadLive} className="btn-primary text-sm" disabled={loading}>
                {loading ? "Scheduling…" : "Generate Schedule"}
              </button>
            </>
          )}
        </div>
      </div>

      <p className="text-gray-400 mb-6 text-sm">
        {mode === "demo"
          ? "AI-optimized Gantt view for the 28-order benchmark dataset."
          : "Schedule your actual pending orders. Sign in first to access My Orders mode."}
        {schedule?.algorithm && (
          <span className="ml-2 text-xs bg-forge-500/20 text-forge-400 px-2 py-0.5 rounded-full">
            {schedule.algorithm === "sa" ? "Simulated Annealing" : "EDD Greedy"}
          </span>
        )}
      </p>

      {error && (
        <div className="p-4 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm mb-6">
          {error}
        </div>
      )}

      {mode === "live" && !schedule && !loading && !error && !emptyOrders && (
        <div className="card text-center py-12 mb-6">
          <p className="text-gray-400 text-sm mb-3">Click "Generate Schedule" to optimize your pending orders.</p>
          <p className="text-xs text-gray-600">Orders from My Orders tab · SA optimizer · machine assignments included</p>
        </div>
      )}

      {mode === "live" && emptyOrders && !schedule && !loading && (
        <div className="card text-center py-12 mb-6">
          <p className="text-white font-semibold mb-1">No pending orders in the queue yet</p>
          <p className="text-gray-400 text-sm mb-6">Add orders in My Orders, or try the benchmark demo to see the optimizer in action.</p>
          <div className="flex justify-center gap-3 flex-wrap">
            <button
              onClick={() => { setEmptyOrders(false); setMode("demo"); }}
              className="btn-secondary text-sm"
            >
              Try the benchmark demo →
            </button>
            <button className="btn-secondary text-sm" disabled>
              Go to My Orders
            </button>
          </div>
        </div>
      )}

      {loading && !schedule && (
        <div className="text-center py-20 text-gray-500">Calculating optimal schedule…</div>
      )}

      {schedule && (() => {
        const exportCSV = () => {
          const rows = schedule.schedule.map(job => ([
            job.order_id, job.machine_id, job.material, job.quantity,
            job.start_time, job.end_time, job.is_on_time ? "On Time" : "Late"
          ]));
          const header = ["Order ID", "Machine", "Material", "Quantity", "Start", "End", "Status"];
          const csv = [header, ...rows].map(r => r.join(",")).join("\n");
          const blob = new Blob([csv], { type: "text/csv" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url; a.download = "millforge_schedule.csv"; a.click();
          URL.revokeObjectURL(url);
        };
        return (
        <>
          {/* Apply banner (live mode only) */}
          {schedule._live && !applyResult && (
            <div className="flex items-center justify-between bg-forge-500/10 border border-forge-500/30 rounded-xl px-5 py-4 mb-6">
              <div>
                <p className="text-sm font-semibold text-white">Schedule ready</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {schedule.schedule?.length} orders · {schedule.summary?.on_time_rate_percent}% on time
                </p>
              </div>
              <button
                onClick={handleApply}
                disabled={applying}
                className="btn-primary text-sm"
              >
                {applying ? "Applying…" : "Apply Schedule →"}
              </button>
            </div>
          )}
          {applyResult && (
            <div className="bg-green-500/10 border border-green-500/30 rounded-xl px-5 py-4 mb-6 text-sm text-green-400">
              {applyResult}
            </div>
          )}

          {/* Anomaly warnings */}
          {schedule.anomaly_report?.anomalies?.length > 0 && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-5 py-3 mb-6">
              <p className="text-sm font-semibold text-yellow-400 mb-1">Anomalies Detected</p>
              {schedule.anomaly_report.anomalies.slice(0, 3).map((a, i) => (
                <p key={i} className="text-xs text-yellow-300">• {a.message ?? JSON.stringify(a)}</p>
              ))}
            </div>
          )}

          {/* Summary cards */}
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Schedule Summary</p>
            <button onClick={exportCSV} className="btn-secondary text-sm">Export CSV</button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
            <SummaryCard label="Total Orders"    value={schedule.summary.total_orders} />
            <SummaryCard label="On-Time Rate"    value={`${schedule.summary.on_time_rate_percent}%`} highlight />
            <SummaryCard label="Makespan"        value={`${schedule.summary.makespan_hours}h`} />
            <SummaryCard label="Utilization"     value={`${schedule.summary.utilization_percent}%`} />
          </div>

          {/* Gantt chart */}
          <GanttChart schedule={schedule} />

          {/* Table */}
          <OrderTable schedule={schedule} />

          {/* Algorithm benchmark (demo only) */}
          {mode === "demo" && <BenchmarkPanel />}
        </>
        );
      })()}
    </div>
  );
}

function SummaryCard({ label, value, highlight }) {
  return (
    <div className="card text-center">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${highlight ? "text-forge-500" : "text-white"}`}>{value}</p>
    </div>
  );
}

function GanttChart({ schedule }) {
  const machines = [...new Set(schedule.schedule.map((s) => s.machine_id))].sort();
  const times = schedule.schedule.flatMap((s) => [
    new Date(s.setup_start).getTime(),
    new Date(s.completion_time).getTime(),
  ]);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const totalMs = maxTime - minTime || 1;

  const pct = (t) => ((new Date(t).getTime() - minTime) / totalMs) * 100;

  return (
    <div className="card mb-8 overflow-x-auto">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Gantt Chart</h3>
      <div className="space-y-3 min-w-[600px]">
        {machines.map((machineId) => {
          const machineOrders = schedule.schedule.filter((s) => s.machine_id === machineId);
          return (
            <div key={machineId} className="flex items-center gap-3">
              <span className="text-xs text-gray-500 w-20 shrink-0 text-right">
                Machine {machineId}
              </span>
              <div className="flex-1 relative h-8 bg-gray-800 rounded">
                {machineOrders.map((s) => {
                  const colors = MATERIAL_COLORS[s.material] || MATERIAL_COLORS.steel;
                  const left = pct(s.setup_start);
                  const width = pct(s.completion_time) - left;
                  return (
                    <div
                      key={s.order_id}
                      title={`${s.order_id} | ${s.material} | ${s.on_time ? "On-time" : "Late"}`}
                      className={`absolute h-full rounded ${colors.bar} opacity-80 hover:opacity-100 transition-opacity flex items-center justify-center overflow-hidden`}
                      style={{ left: `${left}%`, width: `${Math.max(width, 1)}%` }}
                    >
                      <span className="text-white text-xs font-medium px-1 truncate">
                        {s.order_id}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-gray-600 mt-2 min-w-[600px] ml-[92px]">
        <span>Now</span>
        <span>{schedule.summary.makespan_hours}h</span>
      </div>
    </div>
  );
}

function OrderTable({ schedule }) {
  return (
    <div className="card overflow-x-auto">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Order Details</h3>
      <table className="w-full text-sm min-w-[700px]">
        <thead>
          <tr className="text-left text-gray-500 border-b border-gray-800">
            {["Order ID", "Material", "Machine", "Setup (min)", "Processing (min)", "Completion", "Status"].map((h) => (
              <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {schedule.schedule.map((s) => {
            const colors = MATERIAL_COLORS[s.material] || MATERIAL_COLORS.steel;
            return (
              <tr key={s.order_id} className="hover:bg-gray-800/50 transition-colors">
                <td className="py-2 pr-4 font-mono text-gray-300">{s.order_id}</td>
                <td className="py-2 pr-4">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors.badge}`}>
                    {s.material}
                  </span>
                </td>
                <td className="py-2 pr-4 text-gray-400">#{s.machine_id}</td>
                <td className="py-2 pr-4 text-gray-400">{s.setup_minutes}</td>
                <td className="py-2 pr-4 text-gray-400">{Math.round(s.processing_minutes)}</td>
                <td className="py-2 pr-4 text-gray-400">
                  {new Date(s.completion_time).toLocaleString()}
                </td>
                <td className="py-2">
                  {s.on_time ? (
                    <span className="text-green-400 text-xs font-medium">✓ On-time</span>
                  ) : (
                    <span className="text-red-400 text-xs font-medium">
                      +{s.lateness_hours.toFixed(1)}h late
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
