import { useState, useEffect, useCallback, useRef } from "react";
import { Download, Search, Upload, X } from "lucide-react";
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
const STATUSES  = ["pending", "scheduled", "in_progress", "completed", "cancelled"];

const BLANK_FORM = {
  material:      "steel",
  dimensions:    "",
  quantity:      "",
  priority:      5,
  complexity:    1.0,
  due_date:      "",
  customer_name: "",
  po_number:     "",
  part_number:   "",
  notes:         "",
};

// ── Order form modal ──────────────────────────────────────────────────────────
function OrderFormModal({ initial, onClose, onSaved }) {
  const [form, setForm]         = useState(initial || BLANK_FORM);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);
  const isEdit = !!initial?.order_id;

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const body = {
        ...form,
        quantity:   Number(form.quantity),
        priority:   Number(form.priority),
        complexity: Number(form.complexity),
        due_date:   form.due_date ? new Date(form.due_date).toISOString() : undefined,
      };
      // strip empty optional strings so backend doesn't store ""
      ["customer_name","po_number","part_number","notes"].forEach(k => {
        if (!body[k]) body[k] = null;
      });

      const url    = isEdit ? `${API_BASE}/api/orders/${initial.order_id}` : `${API_BASE}/api/orders`;
      const method = isEdit ? "PATCH" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${res.status}`);
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-start justify-center z-50 p-4 overflow-y-auto">
      <div className="card w-full max-w-2xl my-8 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-white">{isEdit ? `Edit ${initial.order_id}` : "New Order"}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X className="w-4 h-4" /></button>
        </div>

        <form onSubmit={handleSubmit} className="grid sm:grid-cols-2 gap-4">
          {/* Row 1: customer + PO */}
          <div>
            <label className="label">Customer Name</label>
            <input className="input" value={form.customer_name} onChange={set("customer_name")} placeholder="Acme Manufacturing" />
          </div>
          <div>
            <label className="label">PO Number</label>
            <input className="input" value={form.po_number} onChange={set("po_number")} placeholder="PO-2024-001" />
          </div>

          {/* Row 2: part + due date */}
          <div>
            <label className="label">Part Number</label>
            <input className="input" value={form.part_number} onChange={set("part_number")} placeholder="PN-12345" />
          </div>
          <div>
            <label className="label">Due Date <span className="text-red-400">*</span></label>
            <input type="date" className="input" value={form.due_date} onChange={set("due_date")} required />
          </div>

          {/* Row 3: material + dimensions */}
          <div>
            <label className="label">Material <span className="text-red-400">*</span></label>
            <select className="input" value={form.material} onChange={set("material")}>
              {MATERIALS.map(m => <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Dimensions <span className="text-red-400">*</span></label>
            <input className="input" value={form.dimensions} onChange={set("dimensions")} placeholder="200×100×10mm" required />
          </div>

          {/* Row 4: qty + priority + complexity */}
          <div>
            <label className="label">Quantity <span className="text-red-400">*</span></label>
            <input type="number" min={1} className="input" value={form.quantity} onChange={set("quantity")} required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Priority <span className="text-xs text-gray-600">(1=urgent)</span></label>
              <input type="number" min={1} max={10} className="input" value={form.priority} onChange={set("priority")} />
            </div>
            <div>
              <label className="label">Complexity</label>
              <input type="number" min={0.1} max={5} step={0.1} className="input" value={form.complexity} onChange={set("complexity")} />
            </div>
          </div>

          {/* Notes */}
          <div className="sm:col-span-2">
            <label className="label">Notes</label>
            <input className="input" value={form.notes} onChange={set("notes")} placeholder="Optional notes…" />
          </div>

          {error && <p className="sm:col-span-2 text-sm text-red-400">{error}</p>}

          <div className="sm:col-span-2 flex gap-2">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? (isEdit ? "Saving…" : "Creating…") : (isEdit ? "Save Changes" : "Create Order")}
            </button>
            <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function OrdersView() {
  const [orders,         setOrders]         = useState([]);
  const [total,          setTotal]          = useState(0);
  const [loading,        setLoading]        = useState(false);
  const [error,          setError]          = useState(null);
  const [showForm,       setShowForm]       = useState(false);
  const [editOrder,      setEditOrder]      = useState(null);   // order obj when editing
  const [scheduleLoading,setScheduleLoading]= useState(false);
  const [scheduleResult, setScheduleResult] = useState(null);
  const [scheduleError,  setScheduleError]  = useState(null);
  const [historyKey,     setHistoryKey]     = useState(0);
  const [confirmDeleteId,setConfirmDeleteId]= useState(null);

  // filter state
  const [statusFilter,   setStatusFilter]   = useState("");
  const [searchText,     setSearchText]     = useState("");

  // CSV import
  const csvRef = useRef(null);
  const [csvLoading, setCsvLoading] = useState(false);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/orders?limit=200`, { credentials: "include" });
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

  const handleDelete = async (orderId) => {
    try {
      const res = await fetch(`${API_BASE}/api/orders/${orderId}`, { method: "DELETE", credentials: "include" });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
    } catch (err) {
      setError(err.message);
      setConfirmDeleteId(null);
      return;
    }
    setConfirmDeleteId(null);
    fetchOrders();
  };

  const handleStatusChange = async (orderId, newStatus) => {
    try {
      const res = await fetch(`${API_BASE}/api/orders/${orderId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) throw new Error(`Status update failed (${res.status})`);
    } catch (err) {
      setError(err.message);
      return;
    }
    fetchOrders();
  };

  const handleSchedule = async () => {
    setScheduleLoading(true);
    setScheduleError(null);
    setScheduleResult(null);
    try {
      // Fetch pending/scheduled orders to pass to the scheduler
      const ordRes = await fetch(`${API_BASE}/api/orders?status=pending&limit=200`, { credentials: "include" });
      if (!ordRes.ok) throw new Error("Failed to fetch orders");
      const ordData = await ordRes.json();
      const pending = (ordData.orders ?? ordData ?? []).filter(
        o => o.status !== "completed" && o.status !== "cancelled"
      );
      if (pending.length === 0) {
        setScheduleError("No pending orders to schedule.");
        return;
      }
      const payload = pending.map(o => ({
        order_id:   o.order_id,
        material:   o.material,
        quantity:   o.quantity ?? 1,
        dimensions: o.dimensions ?? "100x100x10mm",
        due_date:   o.due_date ?? new Date(Date.now() + 7 * 86400000).toISOString(),
        priority:   o.priority ?? 5,
        complexity: o.complexity ?? 1.0,
      }));
      const res = await fetch(`${API_BASE}/api/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ orders: payload, algorithm: "sa" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Scheduling failed");
      }
      const data = await res.json();
      setScheduleResult(data);
      fetchOrders();
      setHistoryKey(k => k + 1);
    } catch (err) {
      setScheduleError(err.message);
    } finally {
      setScheduleLoading(false);
    }
  };

  const handleCsvImport = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setCsvLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_BASE}/api/orders/import-csv`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `CSV import failed (${res.status})`);
      }
      fetchOrders();
    } catch (err) {
      setError(err.message);
    } finally {
      setCsvLoading(false);
      e.target.value = "";
    }
  };

  // ── Filtering ──────────────────────────────────────────────────────────────
  const filtered = orders.filter(o => {
    if (statusFilter && o.status !== statusFilter) return false;
    if (searchText) {
      const q = searchText.toLowerCase();
      return (
        o.order_id.toLowerCase().includes(q) ||
        (o.customer_name || "").toLowerCase().includes(q) ||
        (o.po_number     || "").toLowerCase().includes(q) ||
        (o.part_number   || "").toLowerCase().includes(q) ||
        (o.material      || "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const pendingCount = orders.filter(o => o.status === "pending").length;

  const openEdit = (order) => {
    setEditOrder({
      ...order,
      due_date: order.due_date ? new Date(order.due_date).toISOString().split("T")[0] : "",
    });
    setShowForm(false);
  };

  return (
    <div>
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold text-white">My Orders</h2>
          <p className="text-gray-400 text-sm mt-1">{total} order{total !== 1 ? "s" : ""} total</p>
        </div>
        <div className="flex gap-2 flex-wrap justify-end">
          {pendingCount > 0 && (
            <button
              onClick={handleSchedule}
              disabled={scheduleLoading}
              className="btn-secondary border border-forge-500 text-forge-400 hover:bg-forge-500/10"
            >
              {scheduleLoading ? "Scheduling…" : `Schedule ${pendingCount} Pending`}
            </button>
          )}
          {/* CSV import — hidden file input */}
          <button
            className="btn-secondary flex items-center gap-1.5 text-sm"
            onClick={() => csvRef.current?.click()}
            disabled={csvLoading}
            title="Import orders from CSV"
          >
            <Upload className="w-3.5 h-3.5" />
            {csvLoading ? "Importing…" : "Import CSV"}
          </button>
          <input ref={csvRef} type="file" accept=".csv" className="hidden" onChange={handleCsvImport} />
          <button onClick={() => { setShowForm(true); setEditOrder(null); }} className="btn-primary">
            + New Order
          </button>
        </div>
      </div>

      {/* ── Filter bar ── */}
      <div className="flex flex-wrap gap-2 mb-4">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
          <input
            className="input pl-8 text-sm"
            placeholder="Search order, customer, PO, part…"
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
          />
        </div>
        <select
          className="input text-sm w-40"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          {STATUSES.map(s => (
            <option key={s} value={s}>{s.replace("_", " ")}</option>
          ))}
        </select>
        {(statusFilter || searchText) && (
          <button
            className="text-xs text-gray-500 hover:text-gray-300 px-2"
            onClick={() => { setStatusFilter(""); setSearchText(""); }}
          >
            Clear
          </button>
        )}
      </div>

      {/* ── Alerts ── */}
      {error && <div className="alert-error mb-4">{error}</div>}
      {scheduleError && <div className="alert-error mb-4">Schedule error: {scheduleError}</div>}

      {/* ── Schedule result card ── */}
      {scheduleResult && (
        <div className="card mb-6 border border-forge-500/30">
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
                const url  = URL.createObjectURL(blob);
                const a    = document.createElement("a");
                a.href     = url;
                a.download = `schedule_${scheduleResult.schedule_run_id}.pdf`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              <Download className="w-3.5 h-3.5" /> Export PDF
            </button>
            <button className="text-xs text-gray-600 hover:text-gray-400" onClick={() => setScheduleResult(null)}>
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* ── Orders table ── */}
      {loading && <div className="text-center py-10 text-gray-500">Loading orders…</div>}

      {!loading && filtered.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-sm">
            {orders.length === 0
              ? <>No orders yet. Click <strong>+ New Order</strong> to get started.</>
              : "No orders match the current filters."}
          </p>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-800">
                {["Order ID", "Customer", "PO / Part", "Material", "Qty", "Due", "Priority", "Status", ""].map(h => (
                  <th key={h} className="pb-2 pr-3 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {filtered.map(o => (
                <tr key={o.order_id} className="hover:bg-gray-800/40 transition-colors group">
                  <td className="py-2 pr-3 font-mono text-gray-300 text-xs whitespace-nowrap">{o.order_id}</td>
                  <td className="py-2 pr-3 text-gray-300 text-xs max-w-[120px] truncate">
                    {o.customer_name || <span className="text-gray-700">—</span>}
                  </td>
                  <td className="py-2 pr-3 text-xs">
                    {o.po_number && <div className="text-gray-400">{o.po_number}</div>}
                    {o.part_number && <div className="text-gray-600">{o.part_number}</div>}
                    {!o.po_number && !o.part_number && <span className="text-gray-700">—</span>}
                  </td>
                  <td className="py-2 pr-3 text-gray-300 capitalize text-xs">{o.material}</td>
                  <td className="py-2 pr-3 text-gray-400 text-xs">{o.quantity.toLocaleString()}</td>
                  <td className="py-2 pr-3 text-xs whitespace-nowrap">
                    <span className={new Date(o.due_date) < new Date() && o.status !== "completed" ? "text-red-400" : "text-gray-400"}>
                      {new Date(o.due_date).toLocaleDateString()}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-gray-400 text-xs">{o.priority}</td>
                  <td className="py-2 pr-3">
                    <select
                      value={o.status}
                      onChange={e => handleStatusChange(o.order_id, e.target.value)}
                      className={`text-xs px-2 py-0.5 rounded-full border-0 cursor-pointer bg-transparent ${STATUS_COLORS[o.status] || "text-gray-400"}`}
                    >
                      {STATUSES.map(s => (
                        <option key={s} value={s} className="bg-gray-900 text-gray-100">{s.replace("_", " ")}</option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => openEdit(o)}
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        Edit
                      </button>
                      {confirmDeleteId === o.order_id ? (
                        <span className="flex items-center gap-1">
                          <button onClick={() => handleDelete(o.order_id)} className="text-xs text-red-400 font-semibold hover:text-red-300">Confirm</button>
                          <button onClick={() => setConfirmDeleteId(null)} className="text-xs text-gray-500 hover:text-gray-400">×</button>
                        </span>
                      ) : (
                        <button onClick={() => setConfirmDeleteId(o.order_id)} className="text-xs text-red-500 hover:text-red-400">
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length < total && (
            <p className="text-xs text-gray-600 text-center pt-3">
              Showing {filtered.length} of {total} orders
            </p>
          )}
        </div>
      )}

      {/* ── Schedule history ── */}
      <ScheduleHistoryPanel refreshKey={historyKey} />

      {/* ── Create / Edit modal ── */}
      {(showForm || editOrder) && (
        <OrderFormModal
          initial={editOrder}
          onClose={() => { setShowForm(false); setEditOrder(null); }}
          onSaved={() => { setShowForm(false); setEditOrder(null); fetchOrders(); }}
        />
      )}
    </div>
  );
}
