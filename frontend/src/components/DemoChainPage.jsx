import { useState, useRef } from "react";
import { API_BASE } from "../config";

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];

const MATERIAL_COLOR = {
  steel: "text-blue-400",
  aluminum: "text-emerald-400",
  titanium: "text-purple-400",
  copper: "text-orange-400",
};

function StatCard({ label, value, sub, accent }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-xl font-semibold ${accent || "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <div className="bg-gray-900 px-4 py-2 border-b border-gray-800">
        <h3 className="text-sm font-medium text-gray-300">{title}</h3>
      </div>
      <div className="p-4 bg-gray-950 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {children}
      </div>
    </div>
  );
}

export default function DemoChainPage() {
  const [file, setFile] = useState(null);
  const [material, setMaterial] = useState("steel");
  const [quantity, setQuantity] = useState(200);
  const [priority, setPriority] = useState(3);
  const [dueDays, setDueDays] = useState(14);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError("Select an STL file first."); return; }
    setError(null);
    setLoading(true);
    setResult(null);

    const form = new FormData();
    form.append("file", file);
    form.append("material", material);
    form.append("quantity", String(quantity));
    form.append("priority", String(priority));
    form.append("due_date_days", String(dueDays));

    try {
      const res = await fetch(`${API_BASE}/api/demo/cad-to-quote`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fmt = (n, dec = 2) => (typeof n === "number" ? n.toFixed(dec) : "—");
  const fmtUSD = (n) => (typeof n === "number" ? `$${n.toLocaleString("en-US", { minimumFractionDigits: 2 })}` : "—");
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">ARIA End-to-End Demo</h2>
        <p className="text-sm text-gray-400 mt-1">
          Upload an STL file — MillForge schedules it, estimates energy cost, and generates a quote with no human input.
        </p>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="card space-y-5">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Input</h3>

        {/* File drop */}
        <div>
          <label className="label">STL File</label>
          <div
            onClick={() => fileRef.current?.click()}
            className={`mt-1 border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
              file ? "border-forge-500 bg-forge-500/5" : "border-gray-700 hover:border-gray-600"
            }`}
          >
            {file ? (
              <p className="text-sm text-forge-400 font-medium">{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
            ) : (
              <p className="text-sm text-gray-500">Click to select an STL file</p>
            )}
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".stl"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <label className="label">Material</label>
            <select
              className="input mt-1"
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
            >
              {MATERIALS.map((m) => (
                <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Quantity</label>
            <input
              type="number"
              className="input mt-1"
              min={1}
              max={100000}
              value={quantity}
              onChange={(e) => setQuantity(Number(e.target.value))}
            />
          </div>

          <div>
            <label className="label">Priority (1=urgent)</label>
            <input
              type="number"
              className="input mt-1"
              min={1}
              max={10}
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
            />
          </div>

          <div>
            <label className="label">Due in (days)</label>
            <input
              type="number"
              className="input mt-1"
              min={1}
              max={365}
              value={dueDays}
              onChange={(e) => setDueDays(Number(e.target.value))}
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>
        )}

        <button type="submit" disabled={loading} className="btn-primary w-full">
          {loading ? "Running chain…" : "Run: STL → Schedule → Energy → Quote"}
        </button>
      </form>

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Summary banner */}
          <div className={`rounded-lg px-4 py-3 border text-sm font-medium ${
            result.on_time
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
              : "bg-red-500/10 border-red-500/30 text-red-400"
          }`}>
            {result.on_time ? "On-time" : "Late"} — {result.summary}
          </div>

          {/* 4 sections */}
          <Section title="1. CAD Parse">
            <StatCard label="Dimensions" value={result.cad_parse.dimensions} />
            <StatCard label="Complexity" value={`${result.cad_parse.complexity} / 10`} />
            <StatCard label="Volume" value={`${fmt(result.cad_parse.estimated_volume_cm3)} cm³`} />
            <StatCard label="Triangles" value={result.cad_parse.triangle_count.toLocaleString()} />
          </Section>

          <Section title="2. Schedule">
            <StatCard label="Machine" value={`M-${result.scheduled_order.machine_id}`} />
            <StatCard
              label="Material"
              value={result.scheduled_order.material}
              accent={MATERIAL_COLOR[result.scheduled_order.material]}
            />
            <StatCard
              label="Completion"
              value={fmtDate(result.scheduled_order.completion_time)}
              sub={result.on_time ? "On time" : `${fmt(result.scheduled_order.lateness_hours, 1)}h late`}
              accent={result.on_time ? "text-emerald-400" : "text-red-400"}
            />
            <StatCard
              label="Processing"
              value={`${fmt(result.scheduled_order.processing_minutes / 60, 1)}h`}
              sub={`Setup: ${result.scheduled_order.setup_minutes}min`}
            />
          </Section>

          <Section title="3. Energy">
            <StatCard label="Consumption" value={`${fmt(result.energy.estimated_kwh)} kWh`} />
            <StatCard label="Cost" value={fmtUSD(result.energy.estimated_cost_usd)} />
            <StatCard label="Source" value={result.energy.data_source} />
            <StatCard label="Recommendation" value={result.energy.recommendation} />
          </Section>

          <Section title="4. Quote">
            <StatCard label="Unit Price" value={fmtUSD(result.quote.unit_price_usd)} />
            <StatCard label="Total" value={fmtUSD(result.quote.total_price_usd)} accent="text-forge-400" />
            <StatCard
              label="Lead Time"
              value={`${result.quote.estimated_lead_time_days}d`}
              sub={`${fmt(result.quote.estimated_lead_time_hours, 1)}h`}
            />
            <StatCard
              label="Carbon"
              value={result.quote.carbon_footprint_kg_co2 != null ? `${fmt(result.quote.carbon_footprint_kg_co2)} kg` : "N/A"}
              sub="CO₂"
            />
          </Section>

          <p className="text-xs text-gray-600 text-right">
            Generated {fmtDate(result.generated_at)} · Quote valid until {fmtDate(result.quote.valid_until)}
          </p>
        </div>
      )}
    </div>
  );
}
