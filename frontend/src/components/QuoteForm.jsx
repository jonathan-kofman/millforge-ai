import { useState } from "react";
import { API_BASE } from "../config";

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];

const DEFAULT_FORM = {
  material: "steel",
  dimensions: "200x100x10mm",
  quantity: 500,
  priority: 5,
};

export default function QuoteForm() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((f) => ({ ...f, [name]: name === "quantity" || name === "priority" ? Number(value) : value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/quote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
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
      <h2 className="text-2xl font-bold text-white mb-2">Instant Quote</h2>
      <p className="text-gray-400 mb-8">
        Enter your part specs and get a real-time lead time and price estimate — powered by our
        AI scheduling engine.
      </p>

      <form onSubmit={handleSubmit} className="card space-y-5">
        <div>
          <label className="label">Material</label>
          <select name="material" value={form.material} onChange={handleChange} className="input">
            {MATERIALS.map((m) => (
              <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>
            ))}
          </select>
        </div>

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

        <div>
          <label className="label">Priority (1 = urgent, 10 = low)</label>
          <input
            name="priority"
            type="range"
            min={1}
            max={10}
            value={form.priority}
            onChange={handleChange}
            className="w-full accent-forge-500"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>Urgent (1)</span>
            <span className="font-medium text-forge-500">Current: {form.priority}</span>
            <span>Low (10)</span>
          </div>
        </div>

        <button type="submit" className="btn-primary w-full" disabled={loading}>
          {loading ? "Calculating…" : "Get Quote"}
        </button>
      </form>

      {error && (
        <div className="mt-4 p-4 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 card space-y-4">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <span className="text-green-400">✓</span> Quote {result.quote_id}
          </h3>

          <div className="grid grid-cols-2 gap-4">
            <Stat label="Lead Time" value={`${result.estimated_lead_time_days} days`} highlight />
            <Stat label="Total Price" value={`$${result.total_price_usd.toLocaleString()}`} highlight />
            <Stat label="Unit Price" value={`$${result.unit_price_usd}`} />
            <Stat label="Lead Time (hrs)" value={`${result.estimated_lead_time_hours}h`} />
          </div>

          <p className="text-sm text-gray-400 border-t border-gray-800 pt-4">{result.notes}</p>
          <p className="text-xs text-gray-600">
            Quote valid until: {new Date(result.valid_until).toLocaleDateString()}
          </p>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-xl font-bold ${highlight ? "text-forge-500" : "text-white"}`}>{value}</p>
    </div>
  );
}
