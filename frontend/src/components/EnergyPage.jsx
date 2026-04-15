import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const SCENARIO_OPTIONS = [
  { value: "grid_only",     label: "Grid Only (baseline)" },
  { value: "solar",         label: "Solar" },
  { value: "battery",       label: "Battery Storage" },
  { value: "solar_battery", label: "Solar + Battery" },
  { value: "wind",          label: "Wind" },
  { value: "smr",           label: "Small Modular Reactor" },
];

const SUB_TABS = [
  { id: "rates",     label: "Live Rates" },
  { id: "arbitrage", label: "Arbitrage Savings" },
  { id: "scenario",  label: "10-Year Scenario" },
];

// ── Live Rates sub-tab ─────────────────────────────────────────────────────

function LiveRates() {
  const [rates, setRates] = useState(null);
  const [windows, setWindows] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    const controllers = [new AbortController(), new AbortController()];
    const timeoutIds = [
      setTimeout(() => controllers[0].abort(), 10000),
      setTimeout(() => controllers[1].abort(), 10000),
    ];
    Promise.all([
      fetch(`${API_BASE}/api/energy/rates`, { signal: controllers[0].signal }).then(r => r.json()),
      fetch(`${API_BASE}/api/energy/negative-pricing-windows`, { signal: controllers[1].signal }).then(r => r.json()),
    ])
      .then(([r, w]) => { setRates(r); setWindows(w); })
      .catch(e => {
        if (e.name === "AbortError") {
          setError("Request timed out. The grid data API may be unavailable.");
        } else {
          setError(e.message);
        }
      })
      .finally(() => {
        timeoutIds.forEach(clearTimeout);
        setLoading(false);
      });
  }, []);

  if (loading) return <p className="text-gray-500 text-sm">Loading rate data…</p>;
  if (error) return <p className="text-red-400 text-sm">{error}</p>;

  const hourlyRates = rates?.rates_usd_per_kwh || [];
  const maxRate = Math.max(...hourlyRates.map(h => typeof h === "number" ? h : 0), 0.001);
  const cheapWindows = windows?.windows || [];

  const isSimulated = !rates?.data_source || rates.data_source === "simulated" || rates.data_source === "mock";

  return (
    <div className="space-y-6">
      {isSimulated && (
        <div className="text-xs text-yellow-500 bg-yellow-500/10 border border-yellow-500/20 rounded px-3 py-2">
          Showing simulated rate data — configure EIA_API_KEY for live PJM pricing
        </div>
      )}
      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Data Source", val: rates?.data_source ?? "simulated" },
          { label: "Peak Rate", val: `$${maxRate.toFixed(3)}/kWh` },
          { label: "Cheap Windows", val: cheapWindows.length },
          { label: "Carbon Intensity", val: rates?.carbon_intensity_kg_kwh ? `${rates.carbon_intensity_kg_kwh} kg/kWh` : "0.386 kg/kWh" },
        ].map(s => (
          <div key={s.label} className="bg-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-500 mb-1">{s.label}</p>
            <p className="text-lg font-bold text-forge-500">{s.val}</p>
          </div>
        ))}
      </div>

      {/* Hourly bar chart */}
      {hourlyRates.length > 0 && (
        <div className="card">
          <p className="text-sm font-semibold text-white mb-4">24-Hour Rate Curve ($/kWh)</p>
          <div className="flex items-end gap-1 h-28">
            {hourlyRates.map((h, i) => {
              const rate = typeof h === "number" ? h : (h.rate_per_kwh ?? h.rate ?? 0);
              const pct = (rate / maxRate) * 100;
              const isCheap = rate <= maxRate * 0.6;
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative">
                  <div
                    className={`w-full rounded-sm transition-all ${isCheap ? "bg-green-500" : "bg-forge-500"}`}
                    style={{ height: `${Math.max(pct, 4)}%` }}
                  />
                  {/* tooltip */}
                  <div className="absolute bottom-full mb-1 hidden group-hover:block bg-gray-700 text-xs text-white px-2 py-1 rounded whitespace-nowrap z-10">
                    {i}:00 — ${rate.toFixed(3)}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-xs text-gray-600 mt-1">
            <span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>11 PM</span>
          </div>
          <div className="flex gap-4 mt-3">
            <span className="flex items-center gap-1.5 text-xs text-gray-400"><span className="w-3 h-3 rounded-sm bg-green-500 inline-block" /> Cheap window</span>
            <span className="flex items-center gap-1.5 text-xs text-gray-400"><span className="w-3 h-3 rounded-sm bg-forge-500 inline-block" /> Peak pricing</span>
          </div>
        </div>
      )}

      {/* Cheap windows list */}
      {cheapWindows.length > 0 && (
        <div className="card">
          <p className="text-sm font-semibold text-white mb-3">Recommended Run Windows</p>
          <p className="text-xs text-gray-500 mb-4">Schedule energy-intensive jobs during these hours to minimize electricity cost.</p>
          <div className="space-y-2">
            {cheapWindows.slice(0, 6).map((w, i) => (
              <div key={i} className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
                <span className="text-sm text-white font-medium">
                  {w.hour ?? "?"}:00 – {(w.hour != null ? w.hour + (w.duration_hours ?? 1) : "?")}:00
                </span>
                <span className="text-xs text-green-400 font-semibold">
                  ${(w.rate_usd_per_mwh != null ? w.rate_usd_per_mwh / 1000 : 0).toFixed(3)}/kWh
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Arbitrage sub-tab ──────────────────────────────────────────────────────

function Arbitrage() {
  const [form, setForm] = useState({ daily_flexible_kwh: 500, days_per_year: 250 });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(`${API_BASE}/api/energy/arbitrage-analysis`, {
        signal: controller.signal,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          daily_flexible_kwh: Number(form.daily_flexible_kwh),
          days_per_year: Number(form.days_per_year),
        }),
      });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error((await res.json()).detail);
      setResult(await res.json());
    } catch (err) {
      if (err.name === "AbortError") {
        setError("Request timed out. The grid data API may be unavailable.");
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h3 className="text-lg font-semibold text-white mb-1">Load-Shifting Savings</h3>
        <p className="text-sm text-gray-400">
          Move flexible production load from peak hours to off-peak hours. No capital investment required — just smarter scheduling.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="card space-y-4">
        <div>
          <label className="label">Flexible Load (kWh/day)</label>
          <input
            className="input"
            type="number"
            min="1"
            value={form.daily_flexible_kwh}
            onChange={e => setForm(f => ({ ...f, daily_flexible_kwh: e.target.value }))}
          />
          <p className="text-xs text-gray-600 mt-1">kWh you can shift out of peak hours each production day</p>
        </div>
        <div>
          <label className="label">Production Days / Year</label>
          <input
            className="input"
            type="number"
            min="1"
            max="365"
            value={form.days_per_year}
            onChange={e => setForm(f => ({ ...f, days_per_year: e.target.value }))}
          />
        </div>
        <button type="submit" disabled={loading} className="btn-primary w-full">
          {loading ? "Calculating…" : "Calculate Savings"}
        </button>
        {error && <p className="text-red-400 text-sm">{error}</p>}
      </form>

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: "Daily Savings", val: `$${(result.daily_savings_usd ?? 0).toFixed(2)}` },
              { label: "Annual Savings", val: `$${(result.annual_savings_usd ?? 0).toFixed(0)}` },
              { label: "Peak Rate", val: `$${(result.peak_rate_per_kwh ?? 0).toFixed(3)}/kWh` },
              { label: "Off-Peak Rate", val: `$${(result.off_peak_rate_per_kwh ?? 0).toFixed(3)}/kWh` },
            ].map(s => (
              <div key={s.label} className="bg-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 mb-1">{s.label}</p>
                <p className="text-xl font-bold text-forge-500">{s.val}</p>
              </div>
            ))}
          </div>
          {result.recommendation && (
            <div className="card">
              <p className="text-sm font-semibold text-white mb-1">Recommendation</p>
              <p className="text-sm text-gray-400">{result.recommendation}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 10-Year Scenario sub-tab ───────────────────────────────────────────────

function Scenario() {
  const [form, setForm] = useState({ scenario: "solar_battery", annual_kwh: 1200000, capex_usd: 500000 });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [comparisonResults, setComparisonResults] = useState([]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(`${API_BASE}/api/energy/scenario`, {
        signal: controller.signal,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario: form.scenario,
          annual_kwh: Number(form.annual_kwh),
          capex_usd: Number(form.capex_usd),
        }),
      });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error((await res.json()).detail);
      setResult(await res.json());
    } catch (err) {
      if (err.name === "AbortError") {
        setError("Request timed out. The grid data API may be unavailable.");
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleAddToComparison = () => {
    if (!result) return;
    setComparisonResults(prev => [...prev, result]);
  };

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h3 className="text-lg font-semibold text-white mb-1">10-Year NPV Analysis</h3>
        <p className="text-sm text-gray-400">
          Compare on-site energy generation options against grid-only. Based on Lazard LCOE v17 (2024) constants.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="card space-y-4">
        <div>
          <label className="label">Energy Scenario</label>
          <select
            className="input"
            value={form.scenario}
            onChange={e => setForm(f => ({ ...f, scenario: e.target.value }))}
          >
            {SCENARIO_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Annual Consumption (kWh)</label>
          <input
            className="input"
            type="number"
            min="1"
            value={form.annual_kwh}
            onChange={e => setForm(f => ({ ...f, annual_kwh: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Capital Investment ($)</label>
          <input
            className="input"
            type="number"
            min="0"
            value={form.capex_usd}
            onChange={e => setForm(f => ({ ...f, capex_usd: e.target.value }))}
          />
        </div>
        <button type="submit" disabled={loading} className="btn-primary w-full">
          {loading ? "Calculating…" : "Run 10-Year Analysis"}
        </button>
        {error && <p className="text-red-400 text-sm">{error}</p>}
      </form>

      {result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: "10-Year NPV", val: `$${((result.npv_usd ?? 0) / 1000).toFixed(0)}K` },
              { label: "Annual Cost", val: `$${((result.annual_cost_usd ?? 0) / 1000).toFixed(0)}K/yr` },
              { label: "LCOE", val: `$${(result.lcoe_per_kwh ?? 0).toFixed(3)}/kWh` },
              { label: "Payback", val: result.payback_years != null ? `${result.payback_years.toFixed(1)} yrs` : "N/A" },
            ].map(s => (
              <div key={s.label} className="bg-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 mb-1">{s.label}</p>
                <p className="text-xl font-bold text-forge-500">{s.val}</p>
              </div>
            ))}
          </div>
          {result.notes && (
            <div className="card">
              <p className="text-sm text-gray-400">{result.notes}</p>
            </div>
          )}
          <button
            onClick={handleAddToComparison}
            className="w-full text-sm border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500 rounded-lg px-4 py-2 transition-colors"
          >
            Add to Comparison
          </button>
        </div>
      )}

      {comparisonResults.length >= 2 && (
        <div className="mt-6">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-white">Scenario Comparison</p>
            <button onClick={() => setComparisonResults([])} className="text-xs text-gray-500 hover:text-gray-300">Clear</button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900/50">
                  <th className="text-left px-4 py-3 text-gray-500 font-medium">Metric</th>
                  {comparisonResults.map((r, i) => (
                    <th key={i} className={`px-4 py-3 text-center font-semibold ${r.npv_usd === Math.max(...comparisonResults.map(x => x.npv_usd)) ? "text-forge-400" : "text-gray-400"}`}>
                      {r.scenario}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { key: "npv_usd", label: "10-yr NPV", fmt: v => `$${(v/1000).toFixed(0)}k` },
                  { key: "payback_years", label: "Payback", fmt: v => v ? `${v.toFixed(1)} yrs` : "N/A" },
                  { key: "annual_savings_usd", label: "Annual Savings", fmt: v => `$${v?.toLocaleString() ?? "—"}` },
                ].map(({ key, label, fmt }) => (
                  <tr key={key} className="border-b border-gray-800/60 last:border-0">
                    <td className="px-4 py-3 text-gray-400 font-medium bg-gray-900/30">{label}</td>
                    {comparisonResults.map((r, i) => (
                      <td key={i} className="px-4 py-3 text-center text-white bg-gray-900/20">{fmt(r[key])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────

export default function EnergyPage() {
  const [activeTab, setActiveTab] = useState("rates");

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white mb-1">Energy Intelligence</h2>
        <p className="text-gray-400 text-sm">
          No human decides when to run energy-intensive jobs — MillForge watches the grid and shifts production to the cheapest windows automatically.
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

      {activeTab === "rates"     && <LiveRates />}
      {activeTab === "arbitrage" && <Arbitrage />}
      {activeTab === "scenario"  && <Scenario />}
    </div>
  );
}
