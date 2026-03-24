/**
 * Collapsible panel that loads and displays GET /api/orders/schedule-history.
 */
import { useState, useEffect } from "react";
import { API_BASE } from "../config";

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function ScheduleHistoryPanel({ token, refreshKey }) {
  const [open, setOpen]       = useState(false);
  const [runs, setRuns]       = useState([]);
  const [total, setTotal]     = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const authHeaders = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/orders/schedule-history?limit=10`, { headers: authHeaders })
      .then(r => { if (!r.ok) throw new Error("Failed to load history"); return r.json(); })
      .then(d => { setRuns(d.runs); setTotal(d.total); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [open, token, refreshKey]);

  return (
    <div className="mt-4 border border-gray-800 rounded-lg overflow-hidden">
      {/* Toggle header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-900/60 hover:bg-gray-800/60 transition-colors text-left"
      >
        <span className="text-sm font-medium text-gray-300">
          Schedule History
          {total > 0 && (
            <span className="ml-2 text-xs bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded-full">
              {total} run{total !== 1 ? "s" : ""}
            </span>
          )}
        </span>
        <span className="text-gray-500 text-xs">{open ? "▲" : "▼"}</span>
      </button>

      {/* Content */}
      {open && (
        <div className="bg-gray-900/30 px-4 py-3">
          {loading && <p className="text-xs text-gray-500 py-4 text-center">Loading history…</p>}
          {error   && <p className="text-xs text-red-400">{error}</p>}
          {!loading && runs.length === 0 && (
            <p className="text-xs text-gray-600 py-2 text-center">No schedule runs yet.</p>
          )}
          {!loading && runs.length > 0 && (
            <div className="space-y-2">
              {runs.map(run => (
                <div key={run.id} className="flex flex-wrap items-center gap-x-6 gap-y-1 px-3 py-2.5 rounded-md bg-gray-800/50 text-xs">
                  <span className="text-gray-500 font-mono">#{run.id}</span>
                  <span className="text-gray-400 uppercase tracking-wide font-medium">{run.algorithm}</span>
                  <span className="text-gray-400">
                    {run.order_ids.length} order{run.order_ids.length !== 1 ? "s" : ""}
                  </span>
                  <span className={`font-semibold ${run.on_time_rate >= 90 ? "text-green-400" : run.on_time_rate >= 70 ? "text-yellow-400" : "text-red-400"}`}>
                    {run.on_time_rate.toFixed(1)}% on-time
                  </span>
                  <span className="text-gray-500">{run.makespan_hours.toFixed(1)}h makespan</span>
                  <span className="ml-auto text-gray-600">{fmt(run.created_at)}</span>
                </div>
              ))}
              {total > 10 && (
                <p className="text-xs text-gray-600 text-center pt-1">Showing 10 of {total} runs</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
