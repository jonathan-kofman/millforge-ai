import { useState } from "react";
import { API_BASE } from "../config";

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];

const PRIORITY_OPTIONS = [
  { value: 1,  label: "Rush",   desc: "Drop everything" },
  { value: 5,  label: "Normal", desc: "Standard queue"  },
  { value: 10, label: "Low",    desc: "Fill capacity"   },
];

const DEFAULT_FORM = {
  material: "steel",
  dimensions: "200x100x10mm",
  quantity: 500,
  priority: 5,
  shifts_per_day: "",
  hours_per_shift: "",
};

function Stat({ label, value, sub, highlight }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-xl font-bold ${highlight ? "text-forge-400" : "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-gray-600 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function QuoteForm({ onNavigate }) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((f) => ({
      ...f,
      [name]: name === "quantity" ? Number(value) : value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = {
        ...form,
        shifts_per_day: form.shifts_per_day ? Number(form.shifts_per_day) : undefined,
        hours_per_shift: form.hours_per_shift ? Number(form.hours_per_shift) : undefined,
      };
      const res = await fetch(`${API_BASE}/api/quote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Request failed");
      }
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-1">Instant Quote</p>
        <h2 className="text-2xl font-bold text-white mb-1">Get a real-time price estimate</h2>
        <p className="text-gray-400 text-sm">Powered by the AI scheduling engine — lead time and price in under 2 seconds.</p>
      </div>

      <form onSubmit={handleSubmit} className="card space-y-5">
        {/* Row 1: Material + Quantity */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Material</label>
            <select name="material" value={form.material} onChange={handleChange} className="input">
              {MATERIALS.map((m) => (
                <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Quantity</label>
            <input
              name="quantity"
              type="number"
              min={1}
              max={100000}
              value={form.quantity}
              onChange={handleChange}
              className="input"
              required
            />
          </div>
        </div>

        {/* Row 2: Dimensions */}
        <div>
          <label className="label">Dimensions (L×W×H)</label>
          <input
            name="dimensions"
            value={form.dimensions}
            onChange={handleChange}
            placeholder="e.g. 200x100x10mm"
            className="input"
            required
          />
        </div>

        {/* Row 3: Priority — segmented control */}
        <div>
          <label className="label">Priority</label>
          <div className="grid grid-cols-3 gap-2">
            {PRIORITY_OPTIONS.map(({ value, label, desc }) => (
              <button
                type="button"
                key={value}
                onClick={() => setForm(f => ({ ...f, priority: value }))}
                className={`py-2.5 px-3 rounded-lg border text-sm font-medium transition-all duration-150 text-left ${
                  form.priority === value
                    ? "bg-forge-500/15 border-forge-500/50 text-forge-400"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-300"
                }`}
              >
                <div className="font-semibold">{label}</div>
                <div className="text-xs opacity-70 mt-0.5">{desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Advanced — collapsible */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(v => !v)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            <span className={`transition-transform duration-150 ${showAdvanced ? "rotate-90" : ""}`}>▶</span>
            Advanced — shift calendar
          </button>

          {showAdvanced && (
            <div className="grid grid-cols-2 gap-4 mt-3">
              <div>
                <label className="label">Shifts per day</label>
                <select name="shifts_per_day" value={form.shifts_per_day} onChange={handleChange} className="input">
                  <option value="">— assume 24h —</option>
                  <option value="1">1 shift</option>
                  <option value="2">2 shifts</option>
                  <option value="3">3 shifts</option>
                </select>
              </div>
              <div>
                <label className="label">Hours per shift</label>
                <select name="hours_per_shift" value={form.hours_per_shift} onChange={handleChange} className="input">
                  <option value="">— assume 24h —</option>
                  <option value="8">8 hours</option>
                  <option value="10">10 hours</option>
                  <option value="12">12 hours</option>
                </select>
              </div>
            </div>
          )}
        </div>

        <button type="submit" className="btn-gradient w-full text-center" disabled={loading}>
          {loading ? "Calculating…" : "Get Quote →"}
        </button>
      </form>

      {error && (
        <div className="mt-4 alert-error">{error}</div>
      )}

      {result && (
        <div className="mt-5 card space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <span className="w-5 h-5 rounded-full bg-green-500/20 border border-green-500/30 flex items-center justify-center text-green-400 text-xs">✓</span>
              Quote {result.quote_id}
            </h3>
            <span className="text-xs text-gray-600">
              Valid until {new Date(result.valid_until).toLocaleDateString()}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Stat label="Total Price"      value={`$${result.total_price_usd.toLocaleString()}`} highlight />
            <Stat label="Lead Time"        value={`${result.estimated_lead_time_days} days`}     highlight />
            <Stat label="Unit Price"       value={`$${result.unit_price_usd}`} />
            <Stat label="Machine Hours"    value={`${result.estimated_lead_time_hours}h`} />
          </div>

          {result.carbon_footprint_kg_co2 != null && (
            <div className="flex items-center gap-2 bg-emerald-900/20 border border-emerald-800/40 rounded-lg px-4 py-2.5">
              <span className="text-emerald-400 text-sm">🌱</span>
              <p className="text-xs text-emerald-400">
                Carbon footprint: <span className="font-semibold">{result.carbon_footprint_kg_co2.toFixed(1)} kg CO₂</span>
              </p>
            </div>
          )}

          <p className="text-sm text-gray-400 border-t border-gray-800 pt-3">{result.notes}</p>

          <div className="border-t border-gray-800 pt-4 flex flex-col sm:flex-row gap-2">
            <button
              onClick={() => {
                setResult(null);
                setForm(DEFAULT_FORM);
              }}
              className="btn-secondary text-sm flex-1"
            >
              Get another quote
            </button>
            <button
              onClick={() => onNavigate?.("schedule")}
              className="btn-primary text-sm flex-1"
            >
              View production schedule →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
