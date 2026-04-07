import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import GanttChart from "./GanttChart";
import ScheduleHistoryPanel from "./ScheduleHistoryPanel";

const STATUS_COLORS = {
  pending:     "bg-yellow-900/50 text-yellow-300",
  scheduled:   "bg-blue-900/50 text-blue-300",
  in_progress: "bg-forge-500/20 text-forge-400",
  completed:   "bg-green-900/50 text-green-300",
  cancelled:   "bg-gray-800 text-gray-500",
};

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];

const BLANK_FORM = {
  material: "steel", dimensions: "",
  quantity: "", priority: 5, notes: "",
};

export default function OrdersView() {
  const [orders, setOrders] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleResult, setScheduleResult] = useState(null);
  const [scheduleError, setScheduleError] = useState(null);
  const [historyKey, setHistoryKey] = useState(0);  // bump to refresh history panel
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/orders`, { credentials: "include" });
      if (!res.ok) throw new Error("Failed to fetch orders");
      const data = await res.json();
      setOrders(data.orders);
      setTotal(data.total);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setFormLoading(true);
    setFormError(null);
    try {
      const res = await fetch(`${API_BASE}/api/orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ ...form, quantity: Number(form.quantity), priority: Number(form.priority) }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to create order");
      }
      setShowForm(false);
      setForm(BLANK_FORM);
      fetchOrders();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (orderId) => {
    await fetch(`${API_BASE}/api/orders/${orderId}`, { method: "DELETE", credentials: "include" });
    setConfirmDeleteId(null);
    fetchOrders();
  };

  const handleStatusChange = async (orderId, newStatus) => {
    await fetch(`${API_BASE}/api/orders/${orderId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ status: newStatus }),
    });
    fetchOrders();
  };

  const pendingCount = orders.filter(o => o.status === "pending").length;

  const handleSchedule = async () => {
    setScheduleLoading(true);
    setScheduleError(null);
    setScheduleResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/orders/schedule?algorithm=sa`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Scheduling failed");
      }
      const data = await res.json();
      setScheduleResult(data);
      fetchOrders(); // refresh statuses
      setHistoryKey(k => k + 1); // refresh history panel
    } catch (err) {
      setScheduleError(err.message);
    } finally {
      setScheduleLoading(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div>
          <h2 className="text-2xl font-bold text-white">My Orders</h2>
          <p className="text-gray-400 text-sm mt-1">{total} order{total !== 1 ? "s" : ""} total</p>
        </div>
        <div className="flex gap-2">
          {pendingCount > 0 && (
            <button
              onClick={handleSchedule}
              disabled={scheduleLoading}
              className="btn-secondary border border-forge-500 text-forge-400 hover:bg-forge-500/10"
            >
              {scheduleLoading ? "Scheduling…" : `Schedule ${pendingCount} Pending`}
            </button>
          )}
          <button onClick={() => setShowForm(true)} className="btn-primary">
            + New Order
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 alert-error">
          {error}
        </div>
      )}

      {scheduleError && (
        <div className="mt-4 alert-error">
          Schedule error: {scheduleError}
        </div>
      )}

      {scheduleResult && (
        <div className="card mt-4 border border-forge-500/30">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-base font-semibold text-white">
              Schedule Run #{scheduleResult.schedule_run_id}
            </h3>
            <span className="text-xs text-gray-500 uppercase tracking-wide">
              {scheduleResult.algorithm.toUpperCase()}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            {[
              ["Orders Scheduled", scheduleResult.orders_scheduled],
              ["On-Time Rate", `${scheduleResult.summary.on_time_rate_percent.toFixed(1)}%`],
              ["Makespan", `${scheduleResult.summary.makespan_hours.toFixed(1)}h`],
              ["Utilization", `${scheduleResult.summary.utilization_percent.toFixed(1)}%`],
            ].map(([label, val]) => (
              <div key={label} className="text-center">
                <div className="text-lg font-bold text-forge-400">{val}</div>
                <div className="text-xs text-gray-500 mt-0.5">{label}</div>
              </div>
            ))}
          </div>
          <GanttChart schedule={scheduleResult.schedule} />

          {/* Detail table toggle */}
          <details className="mt-3">
            <summary className="text-xs text-gray-600 hover:text-gray-400 cursor-pointer select-none">
              Show detail table
            </summary>
            <div className="overflow-x-auto mt-2">
              <table className="w-full text-xs min-w-[600px]">
                <thead>
                  <tr className="text-left text-gray-600 border-b border-gray-800">
                    {["Order", "Machine", "Material", "Start", "Done", "On Time"].map(h => (
                      <th key={h} className="pb-1 pr-3 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/50">
                  {scheduleResult.schedule.map(s => (
                    <tr key={s.order_id}>
                      <td className="py-1 pr-3 font-mono text-gray-400">{s.order_id}</td>
                      <td className="py-1 pr-3 text-gray-400">M{s.machine_id}</td>
                      <td className="py-1 pr-3 text-gray-400 capitalize">{s.material}</td>
                      <td className="py-1 pr-3 text-gray-500">{new Date(s.processing_start).toLocaleString()}</td>
                      <td className="py-1 pr-3 text-gray-500">{new Date(s.completion_time).toLocaleString()}</td>
                      <td className="py-1">
                        <span className={s.on_time ? "text-green-400" : "text-red-400"}>
                          {s.on_time ? "✓" : "✗"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <div className="mt-3 flex items-center gap-3">
            <button
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-forge-500/20 text-forge-400 hover:bg-forge-500/30 transition-colors font-medium"
              onClick={async () => {
                const res = await fetch(
                  `${API_BASE}/api/schedule/export-pdf?schedule_id=${scheduleResult.schedule_run_id}`,
                  { credentials: "include" }
                );
                if (!res.ok) return;
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `schedule_${scheduleResult.schedule_run_id}.pdf`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              ⬇ Export PDF
            </button>
            <button
              className="text-xs text-gray-600 hover:text-gray-400"
              onClick={() => setScheduleResult(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Create order form */}
      {showForm && (
        <div className="card mb-6 mt-4">
          <h3 className="text-base font-semibold text-white mb-4">New Order</h3>
          <form onSubmit={handleCreate} className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="label">Material</label>
              <select value={form.material} onChange={e => setForm(f => ({ ...f, material: e.target.value }))} className="input">
                {MATERIALS.map(m => <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Dimensions</label>
              <input value={form.dimensions} onChange={e => setForm(f => ({ ...f, dimensions: e.target.value }))}
                className="input" placeholder="200x100x10mm" required />
            </div>
            <div>
              <label className="label">Quantity</label>
              <input type="number" min={1} value={form.quantity}
                onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} className="input" required />
            </div>
            <div>
              <label className="label">Priority (1=urgent, 10=low)</label>
              <input type="number" min={1} max={10} value={form.priority}
                onChange={e => setForm(f => ({ ...f, priority: e.target.value }))} className="input" />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Notes</label>
              <input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                className="input" placeholder="Optional notes…" />
            </div>
            {formError && (
              <p className="sm:col-span-2 text-sm text-red-400">{formError}</p>
            )}
            <div className="sm:col-span-2 flex gap-2">
              <button type="submit" className="btn-primary" disabled={formLoading}>
                {formLoading ? "Creating…" : "Create Order"}
              </button>
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Orders table */}
      {loading && <div className="text-center py-10 text-gray-500">Loading orders…</div>}

      {!loading && orders.length === 0 && (
        <div className="card text-center py-12 mt-4">
          <p className="text-gray-400 text-sm">No orders yet. Click <strong>+ New Order</strong> to get started.</p>
        </div>
      )}

      {!loading && orders.length > 0 && (
        <div className="card overflow-x-auto mt-4">
          <table className="w-full text-sm min-w-[700px]">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-800">
                {["Order ID", "Material", "Qty", "Priority", "Due", "Status", "Actions"].map(h => (
                  <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {orders.map(o => (
                <tr key={o.order_id} className="hover:bg-gray-800/50 transition-colors">
                  <td className="py-2 pr-4 font-mono text-gray-300 text-xs">{o.order_id}</td>
                  <td className="py-2 pr-4 text-gray-300 capitalize">{o.material}</td>
                  <td className="py-2 pr-4 text-gray-400">{o.quantity.toLocaleString()}</td>
                  <td className="py-2 pr-4 text-gray-400">{o.priority}</td>
                  <td className="py-2 pr-4 text-gray-400 text-xs">{new Date(o.due_date).toLocaleDateString()}</td>
                  <td className="py-2 pr-4">
                    <select
                      value={o.status}
                      onChange={e => handleStatusChange(o.order_id, e.target.value)}
                      className={`text-xs px-2 py-0.5 rounded-full border-0 cursor-pointer bg-transparent ${STATUS_COLORS[o.status] || "text-gray-400"}`}
                    >
                      {["pending","scheduled","in_progress","completed","cancelled"].map(s => (
                        <option key={s} value={s} className="bg-gray-900 text-gray-100">{s.replace("_"," ")}</option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2">
                    {confirmDeleteId === o.order_id ? (
                      <span className="flex items-center gap-2">
                        <button onClick={() => handleDelete(o.order_id)} className="text-xs text-red-400 font-semibold hover:text-red-300">Confirm</button>
                        <button onClick={() => setConfirmDeleteId(null)} className="text-xs text-gray-500 hover:text-gray-400">Cancel</button>
                      </span>
                    ) : (
                      <button onClick={() => setConfirmDeleteId(o.order_id)} className="text-xs text-red-500 hover:text-red-400">
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Schedule history accordion */}
      <ScheduleHistoryPanel refreshKey={historyKey} />
    </div>
  );
}
