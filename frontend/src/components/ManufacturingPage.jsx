import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const PROCESS_FAMILIES = [
  "cnc_milling", "cnc_turning", "cnc_grinding",
  "welding_arc", "welding_laser", "welding_eb",
  "bending_press_brake",
  "cutting_laser", "cutting_plasma", "cutting_waterjet",
  "stamping", "edm_wire", "edm_sinker",
  "injection_molding",
  "inspection_cmm", "inspection_vision",
];

const MATERIAL_FAMILIES = [
  "carbon_steel", "stainless_steel", "tool_steel",
  "aluminum_alloy", "titanium_alloy", "nickel_alloy",
  "copper_alloy", "superalloy", "polymer",
  "composite", "ceramic", "refractory",
];

const SUB_TABS = [
  { id: "router",    label: "Process Router" },
  { id: "catalog",   label: "Materials Catalog" },
  { id: "feasibility", label: "Feasibility Check" },
];

// ── Process Router sub-tab ─────────────────────────────────────────────────

function ProcessRouter() {
  const [form, setForm] = useState({
    part_id: "",
    part_name: "",
    material_name: "steel",
    material_family: "ferrous",
    target_quantity: "",
    tolerance_class: "ISO_2768_m",
    priority: 5,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/manufacturing/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          intent: {
            part_id: form.part_id,
            part_name: form.part_name,
            material: { material_name: form.material_name, material_family: form.material_family },
            target_quantity: Number(form.target_quantity),
            tolerance_class: form.tolerance_class,
            priority: Number(form.priority),
          },
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail ?? `Error ${res.status}`);
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const scoreColor = (score) => {
    if (score >= 0.75) return "text-green-400";
    if (score >= 0.5) return "text-yellow-400";
    return "text-red-400";
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-400">
        Describe a part and MillForge ranks every registered process/machine combination by cost, time, quality, and energy — no human decides the process.
      </p>

      <form onSubmit={handleSubmit} className="card">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Part ID</label>
            <input className="input" value={form.part_id} onChange={e => setForm(f => ({ ...f, part_id: e.target.value }))} />
          </div>
          <div>
            <label className="label">Part Name</label>
            <input className="input" value={form.part_name} onChange={e => setForm(f => ({ ...f, part_name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Material</label>
            <input className="input" placeholder="aluminum, steel, Ti-6Al-4V…" value={form.material_name} onChange={e => setForm(f => ({ ...f, material_name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Material Family</label>
            <select className="input" value={form.material_family} onChange={e => setForm(f => ({ ...f, material_family: e.target.value }))}>
              <option value="ferrous">Ferrous</option>
              <option value="non_ferrous">Non-Ferrous</option>
              <option value="polymer">Polymer</option>
              <option value="composite">Composite</option>
              <option value="ceramic">Ceramic</option>
            </select>
          </div>
          <div>
            <label className="label">Quantity</label>
            <input className="input" type="number" min="1" value={form.target_quantity} onChange={e => setForm(f => ({ ...f, target_quantity: e.target.value }))} />
          </div>
          <div>
            <label className="label">Tolerance Class</label>
            <select className="input" value={form.tolerance_class} onChange={e => setForm(f => ({ ...f, tolerance_class: e.target.value }))}>
              <option value="ISO_2768_c">ISO 2768-c (coarse)</option>
              <option value="ISO_2768_m">ISO 2768-m (medium)</option>
              <option value="ISO_2768_f">ISO 2768-f (fine)</option>
              <option value="ISO_2768_v">ISO 2768-v (very fine)</option>
              <option value="AS9100">AS9100 (aerospace)</option>
              <option value="GD_T_ASME">GD&T ASME (precision)</option>
            </select>
          </div>
        </div>
        <button type="submit" disabled={loading} className="btn-primary mt-4 w-full">
          {loading ? "Routing…" : "Find Best Process"}
        </button>
        {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
      </form>

      {result && (
        <div className="space-y-3">
          <p className="text-sm text-gray-500">
            {result.options?.length ?? 0} viable process/machine combinations, ranked by weighted score
          </p>
          {(result.options ?? []).slice(0, 8).map((opt, i) => (
            <div key={i} className={`card border ${i === 0 ? "border-forge-500/40 bg-forge-500/5" : ""}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    {i === 0 && <span className="text-xs bg-forge-500 text-white px-2 py-0.5 rounded-full">Best Match</span>}
                    <span className="font-semibold text-white text-sm">{opt.process_family}</span>
                  </div>
                  <p className="text-xs text-gray-400 mb-2">{opt.machine_name ?? opt.machine_id ?? "Synthetic estimate"}</p>
                  <div className="flex flex-wrap gap-3 text-xs text-gray-500">
                    <span>Cycle: {opt.estimated_cycle_time_minutes?.toFixed(1)} min</span>
                    <span>Setup: {opt.setup_time_minutes?.toFixed(1)} min</span>
                    <span>Cost: ${opt.estimated_cost_usd?.toFixed(2)}</span>
                  </div>
                </div>
                <div className="text-right">
                  <p className={`text-2xl font-bold ${scoreColor(opt.score)}`}>
                    {(opt.score * 100).toFixed(0)}
                  </p>
                  <p className="text-xs text-gray-600">score</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Materials Catalog sub-tab ──────────────────────────────────────────────

function MaterialsCatalog() {
  const [family, setFamily] = useState("");
  const [query, setQuery] = useState("");
  const [materials, setMaterials] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchMaterials = async (fam) => {
    setLoading(true);
    setError(null);
    try {
      const url = fam
        ? `${API_BASE}/api/manufacturing/materials?family=${encodeURIComponent(fam)}`
        : `${API_BASE}/api/manufacturing/materials`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to load catalog");
      const data = await res.json();
      setMaterials(data.materials ?? []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchMaterials(family); }, [family]);

  const handleLookup = async (name) => {
    setDetailLoading(true);
    setSelected(null);
    try {
      const res = await fetch(`${API_BASE}/api/manufacturing/materials/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error("Not found");
      const data = await res.json();
      setSelected(data.material ?? data);
    } catch (err) {
      setError(err.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const filtered = query
    ? materials.filter(m =>
        m.name?.toLowerCase().includes(query.toLowerCase()) ||
        m.common_names?.some(n => n.toLowerCase().includes(query.toLowerCase()))
      )
    : materials;

  const machinabilityColor = (v) => {
    if (v >= 0.7) return "bg-green-500";
    if (v >= 0.4) return "bg-yellow-500";
    return "bg-red-500";
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-400">80+ engineering materials with machinability, density, tensile strength, and process compatibility data.</p>

      <div className="flex gap-3 flex-wrap">
        <select
          className="input w-auto"
          value={family}
          onChange={e => setFamily(e.target.value)}
        >
          <option value="">All families</option>
          {MATERIAL_FAMILIES.map(f => (
            <option key={f} value={f}>{f.replace(/_/g, " ")}</option>
          ))}
        </select>
        <input
          className="input flex-1 min-w-40"
          placeholder="Search by name or alias (6061, Ti-6Al-4V…)"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        {query && (
          <button
            className="btn-secondary text-sm"
            onClick={() => handleLookup(query)}
            disabled={detailLoading}
          >
            {detailLoading ? "Looking up…" : "Deep Lookup →"}
          </button>
        )}
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {/* Detail panel */}
      {selected && (
        <div className="card border-forge-500/30">
          <div className="flex items-start justify-between mb-3">
            <div>
              <p className="font-bold text-white">{selected.name}</p>
              <p className="text-xs text-gray-500">{selected.family?.replace(/_/g, " ")} · {selected.common_names?.slice(0, 3).join(", ")}</p>
            </div>
            <button onClick={() => setSelected(null)} className="text-gray-600 hover:text-gray-400 text-xs">✕</button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            {[
              { label: "Density", val: selected.density_g_cm3 ? `${selected.density_g_cm3} g/cm³` : "—" },
              { label: "Tensile Strength", val: selected.tensile_strength_mpa ? `${selected.tensile_strength_mpa} MPa` : "—" },
              { label: "Hardness", val: selected.hardness_typical ?? "—" },
              { label: "Thermal Conductivity", val: selected.thermal_conductivity_w_mk ? `${selected.thermal_conductivity_w_mk} W/m·K` : "—" },
            ].map(s => (
              <div key={s.label} className="bg-gray-800 rounded p-3">
                <p className="text-xs text-gray-500 mb-0.5">{s.label}</p>
                <p className="text-sm font-semibold text-white">{s.val}</p>
              </div>
            ))}
          </div>
          {selected.machinability_rating != null && (
            <div className="mb-3">
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs text-gray-500">Machinability</p>
                <p className="text-xs text-gray-400">{(selected.machinability_rating * 100).toFixed(0)}%</p>
              </div>
              <div className="h-2 bg-gray-700 rounded-full">
                <div
                  className={`h-2 rounded-full ${machinabilityColor(selected.machinability_rating)}`}
                  style={{ width: `${selected.machinability_rating * 100}%` }}
                />
              </div>
            </div>
          )}
          {selected.suitable_processes?.length > 0 && (
            <div className="mb-2">
              <p className="text-xs text-gray-500 mb-1.5">Suitable Processes</p>
              <div className="flex flex-wrap gap-1">
                {selected.suitable_processes.map(p => (
                  <span key={p} className="text-xs bg-gray-800 text-gray-300 border border-gray-700 px-2 py-0.5 rounded-full">{p.replace(/_/g, " ")}</span>
                ))}
              </div>
            </div>
          )}
          {selected.notes && <p className="text-xs text-gray-500 mt-2 italic">{selected.notes}</p>}
        </div>
      )}

      {/* Material grid */}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading catalog…</p>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.slice(0, 60).map(m => (
            <button
              key={m.name}
              onClick={() => setSelected(m)}
              className="card text-left hover:border-gray-700 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white truncate">{m.name}</p>
                  <p className="text-xs text-gray-500">{m.family?.replace(/_/g, " ")}</p>
                </div>
                {m.machinability_rating != null && (
                  <div className="flex-shrink-0 text-right">
                    <div className="text-xs text-gray-600 mb-0.5">machinability</div>
                    <div className="h-1.5 w-16 bg-gray-700 rounded-full">
                      <div
                        className={`h-1.5 rounded-full ${machinabilityColor(m.machinability_rating)}`}
                        style={{ width: `${m.machinability_rating * 100}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>
              {m.common_names?.length > 0 && (
                <p className="text-xs text-gray-600 mt-1 truncate">{m.common_names.slice(0, 3).join(", ")}</p>
              )}
            </button>
          ))}
        </div>
      )}
      {filtered.length > 60 && (
        <p className="text-xs text-gray-600 text-center">Showing 60 of {filtered.length}. Refine by family or search.</p>
      )}
    </div>
  );
}

// ── Feasibility Check sub-tab ──────────────────────────────────────────────

function FeasibilityCheck() {
  const [form, setForm] = useState({
    part_id: "",
    part_name: "",
    material_name: "",
    material_family: "non_ferrous",
    target_quantity: "",
    tolerance_class: "ISO_2768_m",
    priority: 5,
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/manufacturing/feasibility`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          intent: {
            part_id: form.part_id,
            part_name: form.part_name,
            material: { material_name: form.material_name, material_family: form.material_family },
            target_quantity: Number(form.target_quantity),
            tolerance_class: form.tolerance_class,
            priority: Number(form.priority),
          },
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail ?? `Error ${res.status}`);
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const severityColor = (s) => ({
    critical: "bg-red-500/20 border-red-500/40 text-red-300",
    warning:  "bg-yellow-500/20 border-yellow-500/40 text-yellow-300",
    info:     "bg-blue-500/20 border-blue-500/40 text-blue-300",
  })[s] ?? "bg-gray-700 text-gray-300";

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-400">
        Check if a part is manufacturable with registered processes — material-process compatibility, tolerance achievability, batch economics, safety concerns.
      </p>

      <form onSubmit={handleSubmit} className="card">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Part Name</label>
            <input className="input" value={form.part_name} onChange={e => setForm(f => ({ ...f, part_name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Material</label>
            <input className="input" value={form.material_name} onChange={e => setForm(f => ({ ...f, material_name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Quantity</label>
            <input className="input" type="number" min="1" value={form.target_quantity} onChange={e => setForm(f => ({ ...f, target_quantity: e.target.value }))} />
          </div>
          <div>
            <label className="label">Tolerance / Standard</label>
            <select className="input" value={form.tolerance_class} onChange={e => setForm(f => ({ ...f, tolerance_class: e.target.value }))}>
              <option value="ISO_2768_c">ISO 2768-c</option>
              <option value="ISO_2768_m">ISO 2768-m</option>
              <option value="ISO_2768_f">ISO 2768-f</option>
              <option value="ISO_2768_v">ISO 2768-v</option>
              <option value="AS9100">AS9100 (aerospace)</option>
              <option value="GD_T_ASME">GD&T ASME</option>
            </select>
          </div>
        </div>
        <button type="submit" disabled={loading} className="btn-primary mt-4 w-full">
          {loading ? "Checking feasibility…" : "Check Feasibility"}
        </button>
        {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
      </form>

      {result && (
        <div className="space-y-4">
          {/* Overall verdict */}
          <div className={`rounded-xl px-6 py-5 border ${result.feasible ? "bg-green-500/10 border-green-500/30" : "bg-red-500/10 border-red-500/30"}`}>
            <div className="flex items-center gap-3">
              <span className="text-2xl">{result.feasible ? "✅" : "❌"}</span>
              <div>
                <p className={`font-bold text-lg ${result.feasible ? "text-green-400" : "text-red-400"}`}>
                  {result.feasible ? "Feasible" : "Infeasible"}
                </p>
                {result.supported_processes?.length > 0 && (
                  <p className="text-sm text-gray-400">Supported: <span className="text-white">{result.supported_processes.join(", ")}</span></p>
                )}
              </div>
            </div>
          </div>

          {/* Validation errors */}
          {result.validation_errors?.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-white">Validation Errors</p>
              {result.validation_errors.map((err, i) => (
                <div key={i} className="rounded-lg border px-4 py-3 bg-red-500/10 border-red-500/30 text-sm text-red-300">
                  {err}
                </div>
              ))}
            </div>
          )}

          {/* Warnings */}
          {result.routing_warnings?.length > 0 && (
            <div className="card">
              <p className="text-sm font-semibold text-white mb-2">Routing Warnings</p>
              <ul className="space-y-1">
                {result.routing_warnings.map((w, i) => (
                  <li key={i} className="text-sm text-gray-400 flex gap-2">
                    <span className="text-forge-500 flex-shrink-0">→</span>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────

export default function ManufacturingPage() {
  const [activeTab, setActiveTab] = useState("router");

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white mb-1">Manufacturing Intelligence</h2>
        <p className="text-gray-400 text-sm">
          Process-agnostic routing across 16 manufacturing processes — CNC, welding, cutting, bending, stamping, EDM, molding, and inspection.
        </p>
      </div>

      <nav className="flex gap-1 border-b border-gray-800 mb-6">
        {SUB_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-forge-500 text-forge-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {activeTab === "router"      && <ProcessRouter />}
      {activeTab === "catalog"     && <MaterialsCatalog />}
      {activeTab === "feasibility" && <FeasibilityCheck />}
    </div>
  );
}
