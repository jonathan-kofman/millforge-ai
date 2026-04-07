import { useState, useRef } from "react";

const EXAMPLE_CATALOG = JSON.stringify(
  {
    part_id: "SCAN-2024-001",
    material: "6061-T6",
    bounding_box: { x: 200, y: 100, z: 30 },
    volume_mm3: 250000,
    primitives_summary: [
      { type: "hole", count: 4 },
      { type: "pocket", count: 2 },
      { type: "thread", count: 4 },
    ],
  },
  null,
  2
);

const ALERT_COLORS = {
  GREEN: "text-green-400 bg-green-900/30 border-green-700",
  YELLOW: "text-yellow-400 bg-yellow-900/30 border-yellow-700",
  RED: "text-red-400 bg-red-900/30 border-red-700",
  CRITICAL: "text-purple-400 bg-purple-900/30 border-purple-700",
};

function ComplexityBadge({ value }) {
  const color =
    value >= 4.0
      ? "bg-red-900/40 text-red-400"
      : value >= 3.0
      ? "bg-yellow-900/40 text-yellow-400"
      : value >= 2.0
      ? "bg-blue-900/40 text-blue-400"
      : "bg-green-900/40 text-green-400";
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${color}`}>
      {value.toFixed(1)}×
    </span>
  );
}

function PartSummaryCard({ summary }) {
  return (
    <div className="card p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-bold text-gray-100">
          {summary.part_id}
        </span>
        <span
          className={`text-xs px-2 py-0.5 rounded border ${
            summary.material_valid
              ? "bg-green-900/30 border-green-700 text-green-400"
              : "bg-red-900/30 border-red-700 text-red-400"
          }`}
        >
          {summary.material_mapped}
          {!summary.material_valid && " (unmapped)"}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-400">
        <span>
          <span className="text-gray-500">Dimensions</span>{" "}
          {summary.dimensions}
        </span>
        <span>
          <span className="text-gray-500">Volume</span>{" "}
          {summary.volume_mm3 != null
            ? `${(summary.volume_mm3 / 1000).toFixed(1)} cm³`
            : "—"}
        </span>
        <span className="flex items-center gap-1">
          <span className="text-gray-500">Complexity</span>{" "}
          <ComplexityBadge value={summary.complexity} />
        </span>
        <span>
          <span className="text-gray-500">Features</span>{" "}
          {summary.feature_count}
        </span>
        <span className="col-span-2">
          <span className="text-gray-500">Machining est.</span>{" "}
          {summary.estimated_machining_minutes.toFixed(0)} min
        </span>
      </div>
      {summary.primitive_types?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {summary.primitive_types.map((t, i) => (
            <span
              key={i}
              className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded"
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function QuoteCard({ quote }) {
  return (
    <div className="card border-blue-700 bg-blue-900/20 p-4 space-y-3">
      <div className="text-sm font-semibold text-blue-300">Instant Quote</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Unit price", value: `$${quote.unit_price_usd.toFixed(2)}` },
          {
            label: "Total",
            value: `$${quote.total_price_usd.toFixed(2)}`,
          },
          {
            label: "Lead time",
            value: `${quote.estimated_lead_time_days.toFixed(1)}d`,
          },
          {
            label: "Machining",
            value: `${quote.estimated_machining_minutes?.toFixed(0) ?? "—"} min`,
          },
        ].map(({ label, value }) => (
          <div key={label} className="text-center">
            <div className="text-lg font-bold text-blue-200">{value}</div>
            <div className="text-xs text-blue-400">{label}</div>
          </div>
        ))}
      </div>
      <div className="text-xs text-blue-400">
        Quote valid until{" "}
        {new Date(quote.valid_until).toLocaleDateString()}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// JSON import tab
// ---------------------------------------------------------------------------

function JSONImportTab({ onResult }) {
  const [json, setJson] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [dueDays, setDueDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleImport(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const catalog_entry = JSON.parse(json);
      const res = await fetch("/api/aria/import", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog_entry, quantity, due_days: dueDays }),
      });
      if (!res.ok) throw new Error(await res.text());
      onResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleImport} className="space-y-3">
      <label className="label">Catalog entry (JSON)</label>
      <textarea
        className="input font-mono text-xs"
        rows={12}
        value={json}
        placeholder={EXAMPLE_CATALOG}
        onChange={(e) => setJson(e.target.value)}
      />
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="label">Quantity</label>
          <input
            className="input"
            type="number"
            min="1"
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value) || 1)}
          />
        </div>
        <div className="flex-1">
          <label className="label">Due (days)</label>
          <input
            className="input"
            type="number"
            min="1"
            value={dueDays}
            onChange={(e) => setDueDays(parseInt(e.target.value) || 14)}
          />
        </div>
      </div>
      {error && (
        <div className="text-sm text-red-400 bg-red-900/30 border border-red-700 rounded p-2">
          {error}
        </div>
      )}
      <button type="submit" className="btn-primary" disabled={loading}>
        {loading ? "Importing…" : "Import from scan"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// STL upload tab
// ---------------------------------------------------------------------------

function STLUploadTab({ onResult }) {
  const fileRef = useRef(null);
  const [material, setMaterial] = useState("steel");
  const [quantity, setQuantity] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleUpload(e) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return setError("Select an STL file first.");
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `/api/aria/stl-analyze?material=${encodeURIComponent(material)}&quantity=${quantity}`,
        { method: "POST", credentials: "include", body: form }
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      // Wrap in same shape as /import response
      onResult({
        order: {
          order_id: `STL-${Date.now()}`,
          material: data.quote.material,
          quantity,
          dimensions: data.stl_analysis.dimensions,
          due_date: data.quote.valid_until,
          priority: 5,
          complexity: data.part_summary.complexity,
        },
        quote: data.quote,
        part_summary: data.part_summary,
        stl_analysis: data.stl_analysis,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleUpload} className="space-y-3">
      <p className="text-xs text-gray-500">
        Upload a raw STL — no ARIA catalog JSON required. Geometry is
        extracted automatically.
      </p>
      <div>
        <label className="label">STL file</label>
        <input
          ref={fileRef}
          type="file"
          accept=".stl"
          className="block w-full text-sm text-gray-400 file:mr-4 file:py-1 file:px-3 file:rounded file:border file:border-gray-600 file:text-sm file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700"
        />
      </div>
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="label">Material</label>
          <select
            className="input"
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
          >
            {["steel", "aluminum", "titanium", "copper"].map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="label">Quantity</label>
          <input
            className="input"
            type="number"
            min="1"
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value) || 1)}
          />
        </div>
      </div>
      {error && (
        <div className="text-sm text-red-400 bg-red-900/30 border border-red-700 rounded p-2">
          {error}
        </div>
      )}
      <button type="submit" className="btn-primary" disabled={loading}>
        {loading ? "Analyzing…" : "Analyze STL"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Batch import tab
// ---------------------------------------------------------------------------

function BatchImportTab() {
  const [json, setJson] = useState(
    JSON.stringify(
      [
        {
          material: "6061-T6",
          bounding_box: { x: 150, y: 80, z: 20 },
          volume_mm3: 120000,
        },
        {
          material: "steel",
          bounding_box: { x: 200, y: 100, z: 30 },
          primitives_summary: [{ type: "hole", count: 6 }],
        },
      ],
      null,
      2
    )
  );
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function handleBatch(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const catalog_entries = JSON.parse(json);
      const res = await fetch("/api/aria/bulk-import", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog_entries }),
      });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleBatch} className="space-y-3">
      <label className="label">Catalog entries (JSON array)</label>
      <textarea
        className="input font-mono text-xs"
        rows={10}
        value={json}
        onChange={(e) => setJson(e.target.value)}
      />
      {error && (
        <div className="text-sm text-red-400 bg-red-900/30 border border-red-700 rounded p-2">
          {error}
        </div>
      )}
      <button type="submit" className="btn-primary" disabled={loading}>
        {loading ? "Importing…" : "Bulk import"}
      </button>
      {result && (
        <div className="space-y-2 mt-2">
          <div className="flex gap-4 text-sm">
            <span className="text-green-400 font-semibold">
              ✓ {result.imported} imported
            </span>
            {result.skipped > 0 && (
              <span className="text-red-400 font-semibold">
                ✗ {result.skipped} skipped
              </span>
            )}
          </div>
          {result.skipped_details?.length > 0 && (
            <div className="text-xs text-red-400 space-y-1">
              {result.skipped_details.map((s, i) => (
                <div key={i}>
                  {s.part_id}: {s.error}
                </div>
              ))}
            </div>
          )}
          <div className="space-y-1">
            {result.orders.map((o) => (
              <div
                key={o.order_id}
                className="text-xs font-mono text-gray-300 bg-gray-800 border border-gray-700 rounded px-2 py-1"
              >
                {o.order_id} · {o.material} · qty {o.quantity}
              </div>
            ))}
          </div>
        </div>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ARIAImport() {
  const [activeTab, setActiveTab] = useState("json");
  const [result, setResult] = useState(null);

  const tabs = [
    { id: "json", label: "JSON Catalog" },
    { id: "stl", label: "STL Upload" },
    { id: "batch", label: "Batch Import" },
  ];

  function handleSchedule() {
    if (!result?.order) return;
    // Copy order ID to clipboard for use in the scheduler tab
    navigator.clipboard?.writeText(JSON.stringify([result.order], null, 2));
    alert(
      "Order JSON copied to clipboard — paste into the Schedule tab to run."
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Import from Scan</h1>
        <p className="text-sm text-gray-500 mt-1">
          ARIA-OS catalog → instant quote → schedulable order. No CAD software
          required.
        </p>
      </div>

      {/* Tab nav */}
      <div className="flex border-b border-gray-800">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => { setActiveTab(t.id); setResult(null); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-forge-500 text-forge-500"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="card p-4">
        {activeTab === "json" && (
          <JSONImportTab onResult={setResult} />
        )}
        {activeTab === "stl" && (
          <STLUploadTab onResult={setResult} />
        )}
        {activeTab === "batch" && <BatchImportTab />}
      </div>

      {/* Result */}
      {result && activeTab !== "batch" && (
        <div className="space-y-4">
          {result.part_summary && (
            <PartSummaryCard summary={result.part_summary} />
          )}
          {result.quote && <QuoteCard quote={result.quote} />}

          {result.stl_analysis && (
            <div className="card p-4">
              <div className="text-sm font-semibold text-gray-100 mb-2">
                STL Geometry
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs text-gray-400">
                {[
                  { label: "Dimensions", value: result.stl_analysis.dimensions },
                  { label: "Volume", value: result.stl_analysis.volume_mm3 > 0 ? `${(result.stl_analysis.volume_mm3 / 1000).toFixed(1)} cm³` : "—" },
                  { label: "Faces", value: result.stl_analysis.face_count.toLocaleString() },
                  { label: "Watertight", value: result.stl_analysis.is_watertight ? "Yes" : "No" },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <div className="text-gray-400">{label}</div>
                    <div className="font-medium text-gray-200">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.order && (
            <div className="flex gap-3">
              <button onClick={handleSchedule} className="btn-primary text-sm">
                Copy order → Schedule
              </button>
              <div className="text-xs text-gray-500 self-center">
                Order ID: <span className="font-mono">{result.order.order_id}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
