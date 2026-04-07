import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const SUB_TABS = [
  { id: "inventory",   label: "Inventory" },
  { id: "maintenance", label: "Maintenance" },
  { id: "twin",        label: "Digital Twin" },
];

// ── Inventory sub-tab ──────────────────────────────────────────────────────

function Inventory() {
  const [status, setStatus] = useState(null);
  const [reorder, setReorder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reorderLoading, setReorderLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/inventory/status`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleReorder = async () => {
    setReorderLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ radius_miles: "500" });
      if (lat && lng) { params.set("lat", lat); params.set("lng", lng); }
      const res = await fetch(`${API_BASE}/api/inventory/reorder-with-suppliers?${params}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error((await res.json()).detail ?? "Reorder failed");
      setReorder(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setReorderLoading(false);
    }
  };

  const stockColor = (level, reorder_point) => {
    if (!reorder_point) return "bg-blue-500";
    if (level <= reorder_point * 0.5) return "bg-red-500";
    if (level <= reorder_point) return "bg-yellow-500";
    return "bg-green-500";
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-400">
        No human monitors stock levels — MillForge watches reorder points and generates POs with geo-ranked suppliers automatically.
      </p>

      {loading ? (
        <p className="text-gray-500 text-sm">Loading inventory…</p>
      ) : status ? (
        <div className="space-y-3">
          <p className="text-sm font-semibold text-white">Current Stock Levels</p>
          {(status.items ?? status.stock ?? Object.entries(status).filter(([k]) => k !== "data_source").map(([k, v]) => ({ material: k, ...v }))).map((item, i) => {
            const mat = item.material ?? item.material_type ?? `Item ${i}`;
            const level = item.current_stock ?? item.quantity_on_hand ?? item.level ?? 0;
            const reorder_point = item.reorder_point ?? item.min_stock ?? 0;
            const unit = item.unit ?? "units";
            const pct = reorder_point > 0 ? Math.min((level / (reorder_point * 3)) * 100, 100) : 50;
            return (
              <div key={mat} className="card">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-white capitalize">{mat}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-400">{level.toLocaleString()} {unit}</span>
                    {level <= reorder_point && (
                      <span className="text-xs bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-0.5 rounded-full">Reorder</span>
                    )}
                  </div>
                </div>
                <div className="h-2 bg-gray-700 rounded-full">
                  <div
                    className={`h-2 rounded-full ${stockColor(level, reorder_point)}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                {reorder_point > 0 && (
                  <p className="text-xs text-gray-600 mt-1">Reorder point: {reorder_point.toLocaleString()} {unit}</p>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-gray-500 text-sm">No inventory data available.</p>
      )}

      {/* Reorder with suppliers */}
      <div className="card">
        <p className="text-sm font-semibold text-white mb-3">Auto-Reorder with Nearest Suppliers</p>
        <div className="flex gap-3 mb-3">
          <div className="flex-1">
            <label className="label">Your Latitude</label>
            <input className="input" value={lat} onChange={e => setLat(e.target.value)} />
          </div>
          <div className="flex-1">
            <label className="label">Your Longitude</label>
            <input className="input" value={lng} onChange={e => setLng(e.target.value)} />
          </div>
        </div>
        <button onClick={handleReorder} disabled={reorderLoading} className="btn-primary">
          {reorderLoading ? "Generating POs…" : "Generate Reorder POs"}
        </button>
        {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
      </div>

      {reorder && (
        <div className="space-y-3">
          <p className="text-sm font-semibold text-white">Purchase Orders Generated</p>
          {(reorder.purchase_orders ?? reorder.reorders ?? reorder ?? []).map((po, i) => (
            <div key={i} className="card">
              <div className="flex items-start justify-between gap-4 mb-2">
                <div>
                  <p className="font-medium text-white capitalize">{po.material ?? po.material_type ?? `PO ${i + 1}`}</p>
                  <p className="text-xs text-gray-500">Qty: {(po.quantity ?? po.order_quantity ?? 0).toLocaleString()} {po.unit ?? "units"}</p>
                </div>
                <span className="text-xs bg-forge-500/20 text-forge-400 border border-forge-500/30 px-2 py-0.5 rounded-full">
                  PO Generated
                </span>
              </div>
              {po.suggested_supplier && (
                <div className="mt-2 pt-2 border-t border-gray-800">
                  <p className="text-xs text-gray-500 mb-1">Nearest Supplier</p>
                  <p className="text-sm text-white">{po.suggested_supplier.name}</p>
                  <p className="text-xs text-gray-500">
                    {po.suggested_supplier.city}, {po.suggested_supplier.state}
                    {po.distance_miles != null && ` · ${po.distance_miles.toFixed(0)} mi`}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Maintenance sub-tab ────────────────────────────────────────────────────

function Maintenance() {
  const [riskData, setRiskData] = useState(null);
  const [schedule, setSchedule] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/maintenance/risk-score`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
      fetch(`${API_BASE}/api/maintenance/schedule`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
    ])
      .then(([r, s]) => { setRiskData(r); setSchedule(s); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const riskColor = (score) => {
    if (score >= 0.7) return "text-red-400";
    if (score >= 0.4) return "text-yellow-400";
    return "text-green-400";
  };

  const riskLabel = (score) => {
    if (score >= 0.7) return "High";
    if (score >= 0.4) return "Medium";
    return "Low";
  };

  if (loading) return <p className="text-gray-500 text-sm">Loading maintenance data…</p>;
  if (error) return <p className="text-red-400 text-sm">{error}</p>;

  const machines = riskData?.machines ?? riskData?.risk_scores ?? [];

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-400">
        Predictive maintenance risk scores based on MTBF/MTTR and usage patterns. High-risk machines are flagged before they fail.
      </p>

      {machines.length > 0 ? (
        <div className="space-y-3">
          <p className="text-sm font-semibold text-white">Machine Risk Scores</p>
          {machines.map((m, i) => {
            const score = m.risk_score ?? m.score ?? 0;
            return (
              <div key={i} className="card">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-white">{m.machine_name ?? m.name ?? `Machine ${i + 1}`}</p>
                    <p className="text-xs text-gray-500">
                      MTBF: {m.mtbf_hours ?? "—"}h · MTTR: {m.mttr_hours ?? "—"}h
                    </p>
                  </div>
                  <div className="text-right">
                    <p className={`text-xl font-bold ${riskColor(score)}`}>
                      {riskLabel(score)}
                    </p>
                    <p className="text-xs text-gray-600">{(score * 100).toFixed(0)}% risk</p>
                  </div>
                </div>
                {m.next_maintenance && (
                  <p className="text-xs text-gray-500 mt-2">Next maintenance: {m.next_maintenance}</p>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="card text-center py-8">
          <p className="text-gray-500 text-sm">No machines registered yet.</p>
          <p className="text-xs text-gray-600 mt-1">Add machines in the Machines tab to see risk scores.</p>
        </div>
      )}

      {schedule?.schedule?.length > 0 && (
        <div>
          <p className="text-sm font-semibold text-white mb-3">Upcoming Maintenance</p>
          <div className="space-y-2">
            {schedule.schedule.slice(0, 5).map((item, i) => (
              <div key={i} className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
                <div>
                  <p className="text-sm text-white">{item.machine_name ?? item.machine}</p>
                  <p className="text-xs text-gray-500">{item.maintenance_type ?? item.type}</p>
                </div>
                <span className="text-xs text-gray-400">{item.scheduled_date ?? item.date}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Digital Twin sub-tab ───────────────────────────────────────────────────

function DigitalTwin() {
  const [accuracy, setAccuracy] = useState(null);
  const [calibration, setCalibration] = useState(null);
  const [twinAccuracy, setTwinAccuracy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/learning/setup-time-accuracy`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
      fetch(`${API_BASE}/api/learning/calibration-report`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
      fetch(`${API_BASE}/api/twin/accuracy`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
    ])
      .then(([a, c, t]) => { setAccuracy(a); setCalibration(c); setTwinAccuracy(t); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-gray-500 text-sm">Loading twin data…</p>;
  if (error) return <p className="text-red-400 text-sm">{error}</p>;

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-400">
        Scheduling twin that starts with physics defaults and self-calibrates to your actual shop data via a RandomForest surrogate (min 20 feedback records).
      </p>

      {/* Setup time accuracy */}
      {accuracy && (
        <div className="card">
          <p className="text-sm font-semibold text-white mb-3">Setup Time Predictor</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {[
              { label: "Model", val: accuracy.model_status ?? (accuracy.trained ? "ML Active" : "Physics Fallback") },
              { label: "Training Records", val: accuracy.training_records ?? accuracy.record_count ?? "—" },
              { label: "MAE (setup)", val: accuracy.mae_setup_minutes != null ? `${accuracy.mae_setup_minutes.toFixed(1)} min` : "—" },
            ].map(s => (
              <div key={s.label} className="bg-gray-800 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-1">{s.label}</p>
                <p className="text-base font-bold text-forge-500">{s.val}</p>
              </div>
            ))}
          </div>
          {!accuracy.trained && (
            <p className="text-xs text-gray-600 mt-3">
              Using SETUP_MATRIX physics fallback until 20+ job feedback records are logged.
            </p>
          )}
        </div>
      )}

      {/* Twin accuracy */}
      {twinAccuracy && (
        <div className="card">
          <p className="text-sm font-semibold text-white mb-3">Twin Prediction Accuracy</p>
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: "Setup MAE", val: twinAccuracy.setup_mae_minutes != null ? `${twinAccuracy.setup_mae_minutes.toFixed(1)} min` : "—" },
              { label: "Processing MAE", val: twinAccuracy.processing_mae_minutes != null ? `${twinAccuracy.processing_mae_minutes.toFixed(1)} min` : "—" },
              { label: "Jobs Analyzed", val: twinAccuracy.jobs_analyzed ?? twinAccuracy.record_count ?? "—" },
              { label: "Source", val: twinAccuracy.data_source ?? "feedback_logger" },
            ].map(s => (
              <div key={s.label} className="bg-gray-800 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-1">{s.label}</p>
                <p className="text-base font-bold text-forge-500">{s.val}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Calibration report */}
      {calibration?.records?.length > 0 ? (
        <div className="card">
          <p className="text-sm font-semibold text-white mb-3">Last {calibration.records.length} Jobs — Predicted vs Actual</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 pr-4">Order</th>
                  <th className="text-right pr-4">Pred Setup</th>
                  <th className="text-right pr-4">Actual Setup</th>
                  <th className="text-right pr-4">Pred Process</th>
                  <th className="text-right">Actual Process</th>
                </tr>
              </thead>
              <tbody>
                {calibration.records.slice(0, 10).map((r, i) => (
                  <tr key={i} className="border-b border-gray-800/50 text-gray-400">
                    <td className="py-2 pr-4 font-mono text-gray-500 truncate max-w-24">{r.order_id ?? r.canonical_id?.slice(0, 12)}</td>
                    <td className="text-right pr-4">{r.predicted_setup_minutes?.toFixed(1)}</td>
                    <td className="text-right pr-4">{r.actual_setup_minutes?.toFixed(1)}</td>
                    <td className="text-right pr-4">{r.predicted_processing_minutes?.toFixed(1)}</td>
                    <td className="text-right">{r.actual_processing_minutes?.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card text-center py-8">
          <p className="text-gray-500 text-sm">No calibration data yet.</p>
          <p className="text-xs text-gray-600 mt-1">Calibration improves as jobs complete and actuals are logged via MTConnect or manual entry.</p>
        </div>
      )}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────

export default function OperationsPage() {
  const [activeTab, setActiveTab] = useState("inventory");

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white mb-1">Operations</h2>
        <p className="text-gray-400 text-sm">
          Inventory auto-reorder, predictive maintenance, and a self-calibrating scheduling twin that improves as your shop runs.
        </p>
      </div>

      <nav className="flex gap-1 border-b border-gray-800 mb-6">
        {SUB_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-forge-500 text-forge-500"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {activeTab === "inventory"   && <Inventory />}
      {activeTab === "maintenance" && <Maintenance />}
      {activeTab === "twin"        && <DigitalTwin />}
    </div>
  );
}
