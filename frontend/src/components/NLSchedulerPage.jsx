import { useState } from "react";
import { API_BASE } from "../config";

const EXAMPLE_INSTRUCTIONS = [
  "Rush all titanium orders — aerospace deadline moved up",
  "Defer low-priority steel to the end of the queue",
  "Expedite everything due this week",
  "Push the copper orders — supplier shipment delayed",
];

const EXAMPLE_ORDERS = JSON.stringify(
  [
    { order_id: "ORD-001", material: "titanium", quantity: 50, dimensions: "100x50x10mm", due_date: new Date(Date.now() + 48 * 3600 * 1000).toISOString(), priority: 5, complexity: 1.5 },
    { order_id: "ORD-002", material: "steel",    quantity: 300, dimensions: "200x100x8mm", due_date: new Date(Date.now() + 72 * 3600 * 1000).toISOString(), priority: 5, complexity: 1.0 },
    { order_id: "ORD-003", material: "aluminum", quantity: 120, dimensions: "150x80x6mm",  due_date: new Date(Date.now() + 96 * 3600 * 1000).toISOString(), priority: 7, complexity: 1.2 },
  ],
  null, 2
);

function OverrideRow({ item }) {
  return (
    <tr className="border-b border-gray-800">
      <td className="py-2 px-3 text-sm font-mono text-gray-300">{item.order_id}</td>
      <td className="py-2 px-3 text-sm text-center">
        <span className="bg-forge-500/20 text-forge-300 text-xs font-semibold px-2 py-0.5 rounded">
          P{item.new_priority}
        </span>
      </td>
      <td className="py-2 px-3 text-sm text-gray-400">{item.reason}</td>
    </tr>
  );
}

function ScheduleRow({ s }) {
  return (
    <tr className="border-b border-gray-800 text-sm">
      <td className="py-2 px-3 font-mono text-gray-300">{s.order_id}</td>
      <td className="py-2 px-3 text-gray-400">{s.material}</td>
      <td className="py-2 px-3 text-center text-gray-400">M-{s.machine_id}</td>
      <td className="py-2 px-3 text-gray-400">
        {new Date(s.completion_time).toLocaleString()}
      </td>
      <td className="py-2 px-3 text-center">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded ${s.on_time ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
          {s.on_time ? "on time" : `${s.lateness_hours?.toFixed(1)}h late`}
        </span>
      </td>
    </tr>
  );
}

export default function NLSchedulerPage() {
  const [mode, setMode] = useState("auto"); // "auto" | "quick"
  const [instruction, setInstruction] = useState("");
  const [ordersJson, setOrdersJson] = useState(EXAMPLE_ORDERS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);

    try {
      let res;
      if (mode === "auto") {
        res = await fetch(`${API_BASE}/api/schedule/nl/auto`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ instruction }),
        });
      } else {
        let orders;
        try {
          orders = JSON.parse(ordersJson);
        } catch {
          throw new Error("Orders JSON is invalid — check the syntax.");
        }
        res = await fetch(`${API_BASE}/api/schedule/nl`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ instruction, orders }),
        });
      }

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

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white">Natural-Language Scheduler</h2>
        <p className="text-sm text-gray-400 mt-1">
          Type a plain-English instruction. MillForge interprets it and re-sequences your queue accordingly.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="card space-y-5">
        {/* Mode toggle */}
        <div className="flex gap-2">
          {[
            { id: "auto", label: "Auto (my pending orders)" },
            { id: "quick", label: "Quick (paste orders)" },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded border transition-colors ${
                mode === m.id
                  ? "bg-forge-500 border-forge-500 text-white"
                  : "border-gray-700 text-gray-400 hover:border-gray-600"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* Instruction */}
        <div>
          <label className="label">Instruction</label>
          <div className="flex flex-wrap gap-2 mt-1 mb-2">
            {EXAMPLE_INSTRUCTIONS.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => setInstruction(ex)}
                className="text-xs text-gray-500 border border-gray-700 rounded px-2 py-1 hover:text-gray-300 hover:border-gray-600 transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>
          <textarea
            className="input mt-1 min-h-[80px] resize-y"
            placeholder='e.g. "Rush all titanium orders — aerospace deadline moved up"'
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            required
          />
        </div>

        {/* Orders JSON (quick mode only) */}
        {mode === "quick" && (
          <div>
            <label className="label">Orders (JSON array)</label>
            <p className="text-xs text-yellow-500 mt-1 mb-1">These are example orders — replace with your real order data before submitting.</p>
            <textarea
              className="input mt-1 font-mono text-xs min-h-[180px] resize-y"
              value={ordersJson}
              onChange={(e) => setOrdersJson(e.target.value)}
            />
          </div>
        )}

        {error && (
          <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>
        )}

        <button type="submit" disabled={loading || !instruction.trim()} className="btn-primary w-full">
          {loading ? "Interpreting…" : "Interpret & Schedule"}
        </button>
      </form>

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Interpretation */}
          <div className="card space-y-3">
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Interpretation</h3>
            <p className="text-sm text-gray-300 italic">"{result.instruction}"</p>
            <p className="text-sm text-gray-400">{result.override_summary}</p>
          </div>

          {/* Priority overrides */}
          {result.overrides_applied?.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">
                Priority Overrides ({result.overrides_applied.length})
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 uppercase border-b border-gray-800">
                      <th className="py-2 px-3">Order</th>
                      <th className="py-2 px-3 text-center">New Priority</th>
                      <th className="py-2 px-3">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.overrides_applied.map((item) => (
                      <OverrideRow key={item.order_id} item={item} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {result.overrides_applied?.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-2">No priority overrides were applied.</p>
          )}

          {/* Resulting schedule */}
          {result.schedule?.schedule?.length > 0 && (
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Resulting Schedule</h3>
                <span className="text-xs text-gray-500">
                  {result.schedule.summary?.on_time_count}/{result.schedule.summary?.total_orders} on time
                  {" · "}
                  {result.schedule.summary?.on_time_rate_percent?.toFixed(1)}%
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 uppercase border-b border-gray-800">
                      <th className="py-2 px-3">Order</th>
                      <th className="py-2 px-3">Material</th>
                      <th className="py-2 px-3 text-center">Machine</th>
                      <th className="py-2 px-3">Completion</th>
                      <th className="py-2 px-3 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.schedule.schedule.map((s) => (
                      <ScheduleRow key={s.order_id} s={s} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {result.validation_failures?.length > 0 && (
            <div className="text-sm text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 rounded px-3 py-2">
              Validation issues: {result.validation_failures.join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
