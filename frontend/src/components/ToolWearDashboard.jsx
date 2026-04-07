import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

const ALERT_COLORS = {
  GREEN: "#22c55e",
  YELLOW: "#eab308",
  RED: "#ef4444",
  CRITICAL: "#7c3aed",
};

const ALERT_BG = {
  GREEN: "bg-green-100 text-green-800",
  YELLOW: "bg-yellow-100 text-yellow-800",
  RED: "bg-red-100 text-red-800",
  CRITICAL: "bg-purple-100 text-purple-800",
};

function WearGauge({ score, level }) {
  const color = ALERT_COLORS[level] || "#6b7280";
  const pct = Math.min(100, Math.max(0, score));
  const circumference = 2 * Math.PI * 40;
  const strokeDash = (pct / 100) * circumference;

  return (
    <svg width="100" height="100" viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="40" fill="none" stroke="#e5e7eb" strokeWidth="10" />
      <circle
        cx="50"
        cy="50"
        r="40"
        fill="none"
        stroke={color}
        strokeWidth="10"
        strokeDasharray={`${strokeDash} ${circumference}`}
        strokeLinecap="round"
        transform="rotate(-90 50 50)"
        style={{ transition: "stroke-dasharray 0.5s ease" }}
      />
      <text x="50" y="54" textAnchor="middle" fontSize="18" fontWeight="bold" fill={color}>
        {Math.round(pct)}
      </text>
    </svg>
  );
}

function TrafficLight({ level }) {
  const order = ["GREEN", "YELLOW", "RED", "CRITICAL"];
  return (
    <div className="flex gap-1 items-center">
      {order.map((l) => (
        <div
          key={l}
          className="w-3 h-3 rounded-full transition-all"
          style={{
            backgroundColor: l === level ? ALERT_COLORS[l] : "#d1d5db",
            boxShadow: l === level ? `0 0 6px ${ALERT_COLORS[l]}` : "none",
          }}
        />
      ))}
      <span className={`ml-2 text-xs font-semibold px-2 py-0.5 rounded ${ALERT_BG[level] || ""}`}>
        {level}
      </span>
    </div>
  );
}

function ToolCard({ tool, onSimulate, onReset }) {
  const rul = tool.rul_minutes;
  const rulText = rul != null ? `${Math.round(rul)} min` : "—";

  return (
    <div className="card border border-gray-200 p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-mono text-sm font-bold text-gray-900">{tool.tool_id}</div>
          <div className="text-xs text-gray-500">
            Machine {tool.machine_id} · {tool.tool_type} · {tool.material}
          </div>
        </div>
        <TrafficLight level={tool.alert_level} />
      </div>

      <div className="flex items-center gap-4">
        <WearGauge score={tool.wear_score} level={tool.alert_level} />
        <div className="flex flex-col gap-1 text-sm">
          <div>
            <span className="text-gray-500">Wear score</span>{" "}
            <span className="font-semibold">{tool.wear_score.toFixed(1)}%</span>
          </div>
          <div>
            <span className="text-gray-500">RUL</span>{" "}
            <span className="font-semibold">{rulText}</span>
          </div>
          <div>
            <span className="text-gray-500">Readings</span>{" "}
            <span className="font-semibold">{tool.reading_count}</span>
          </div>
          <div>
            <span className="text-gray-500">Baseline</span>{" "}
            <span className={tool.baseline_ready ? "text-green-600 font-semibold" : "text-gray-400"}>
              {tool.baseline_ready ? "ready" : "learning…"}
            </span>
          </div>
        </div>
      </div>

      <div className="flex gap-2 mt-auto">
        <button
          onClick={() => onSimulate(tool.tool_id)}
          className="btn-primary text-xs py-1 px-3"
        >
          Simulate wear
        </button>
        <button
          onClick={() => onReset(tool.tool_id)}
          className="text-xs py-1 px-3 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
        >
          Reset (tool changed)
        </button>
      </div>
    </div>
  );
}

export default function ToolWearDashboard() {
  const [tools, setTools] = useState([]);
  const [history, setHistory] = useState(null); // { tool_id, scores }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [registerForm, setRegisterForm] = useState({ tool_id: "", machine_id: 1, tool_type: "end_mill", material: "steel", expected_life_minutes: 480 });
  const [showRegister, setShowRegister] = useState(false);

  const fetchTools = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/toolwear/tools`, { credentials: "include" });
      if (!res.ok) throw new Error(await res.text());
      setTools(await res.json());
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { fetchTools(); }, [fetchTools]);

  async function handleSimulate(toolId) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/toolwear/simulate/${toolId}?steps=40`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setHistory({ tool_id: toolId, scores: data.wear_scores, final: data.final_alert_level });
      await fetchTools();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleReset(toolId) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/toolwear/reset/${toolId}`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(await res.text());
      setHistory(null);
      await fetchTools();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/toolwear/tools`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...registerForm,
          machine_id: parseInt(registerForm.machine_id),
          expected_life_minutes: parseInt(registerForm.expected_life_minutes) || 480,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setShowRegister(false);
      setRegisterForm({ tool_id: "", machine_id: 1, tool_type: "end_mill", material: "steel", expected_life_minutes: 480 });
      await fetchTools();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const historyData = history
    ? history.scores.map((s, i) => ({ reading: i + 1, wear: s }))
    : [];

  const criticalCount = tools.filter((t) => t.alert_level === "CRITICAL" || t.alert_level === "RED").length;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Machine Health</h1>
          <p className="text-sm text-gray-500 mt-1">
            Tool wear monitoring — spectral drift detection + remaining useful life
          </p>
        </div>
        <div className="flex items-center gap-3">
          {criticalCount > 0 && (
            <div className="text-sm font-semibold text-red-600 bg-red-50 border border-red-200 px-3 py-1 rounded">
              {criticalCount} tool{criticalCount > 1 ? "s" : ""} need attention
            </div>
          )}
          <button
            onClick={() => setShowRegister(!showRegister)}
            className="btn-primary text-sm"
          >
            + Register tool
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
          {error}
        </div>
      )}

      {/* Register form */}
      {showRegister && (
        <form onSubmit={handleRegister} className="card border border-gray-200 p-4 grid grid-cols-2 gap-3">
          <div>
            <label className="label">Tool ID</label>
            <input
              className="input"
              required
              value={registerForm.tool_id}
              onChange={(e) => setRegisterForm((p) => ({ ...p, tool_id: e.target.value }))}
              placeholder="e.g. TOOL-M1-001"
            />
          </div>
          <div>
            <label className="label">Machine ID</label>
            <input
              className="input"
              type="number"
              min="1"
              value={registerForm.machine_id}
              onChange={(e) => setRegisterForm((p) => ({ ...p, machine_id: e.target.value }))}
            />
          </div>
          <div>
            <label className="label">Tool type</label>
            <select
              className="input"
              value={registerForm.tool_type}
              onChange={(e) => setRegisterForm((p) => ({ ...p, tool_type: e.target.value }))}
            >
              {["end_mill", "drill", "insert", "tap", "reamer", "boring_bar"].map((t) => (
                <option key={t} value={t}>{t.replace("_", " ")}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Material</label>
            <select
              className="input"
              value={registerForm.material}
              onChange={(e) => setRegisterForm((p) => ({ ...p, material: e.target.value }))}
            >
              {["steel", "aluminum", "titanium", "copper"].map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Expected Life (minutes)</label>
            <input
              className="input"
              type="number"
              min="1"
              value={registerForm.expected_life_minutes}
              onChange={(e) => setRegisterForm((p) => ({ ...p, expected_life_minutes: e.target.value }))}
            />
          </div>
          <div className="col-span-2 flex gap-2">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? "Registering…" : "Register"}
            </button>
            <button
              type="button"
              onClick={() => setShowRegister(false)}
              className="px-4 py-2 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Fleet grid */}
      {tools.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <div className="text-4xl mb-3">⚙</div>
          <p className="font-medium">No tools registered yet.</p>
          <p className="text-sm mt-1">Register a tool above or click "Simulate wear" after registering to see the dashboard in action.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {tools.map((tool) => (
            <ToolCard
              key={tool.tool_id}
              tool={tool}
              onSimulate={handleSimulate}
              onReset={handleReset}
            />
          ))}
        </div>
      )}

      {/* Wear history chart */}
      {history && historyData.length > 0 && (
        <div className="card border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="font-semibold text-gray-900">Wear history — {history.tool_id}</h2>
              <p className="text-xs text-gray-500">Simulated spectral drift progression</p>
            </div>
            <span className={`text-xs font-semibold px-2 py-1 rounded ${ALERT_BG[history.final] || ""}`}>
              Final: {history.final}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={historyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="reading" label={{ value: "Reading #", position: "insideBottom", offset: -2, fontSize: 11 }} />
              <YAxis domain={[0, 100]} label={{ value: "Wear %", angle: -90, position: "insideLeft", fontSize: 11 }} />
              <Tooltip formatter={(v) => [`${v.toFixed(1)}%`, "Wear score"]} />
              <ReferenceLine y={40} stroke="#eab308" strokeDasharray="4 2" label={{ value: "YELLOW", fill: "#eab308", fontSize: 10 }} />
              <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 2" label={{ value: "RED", fill: "#ef4444", fontSize: 10 }} />
              <ReferenceLine y={90} stroke="#7c3aed" strokeDasharray="4 2" label={{ value: "CRITICAL", fill: "#7c3aed", fontSize: 10 }} />
              <Line type="monotone" dataKey="wear" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
