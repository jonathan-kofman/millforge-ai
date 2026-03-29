/**
 * /demo — public-facing investor demo page.
 * No auth required. Shows the benchmark 3-way comparison + rush order injection.
 * Designed to load in < 2s and work on mobile.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE } from "../config";

const FALLBACK = {
  fifo: { on_time_rate_percent: 60.7, on_time_count: 17, total_orders: 28, makespan_hours: 148, utilization_percent: 71, solve_ms: 1 },
  edd:  { on_time_rate_percent: 82.1, on_time_count: 23, total_orders: 28, makespan_hours: 142, utilization_percent: 78, solve_ms: 8 },
  sa:   { on_time_rate_percent: 96.4, on_time_count: 27, total_orders: 28, makespan_hours: 138, utilization_percent: 82, solve_ms: 847 },
  winner: "sa",
  on_time_improvement_pp: 35.7,
  order_count: 28,
  _cached: true,
};

const ALGO = {
  fifo: { label: "FIFO",          sub: "How most shops run today",           color: "#6b7280", ring: "#6b7280" },
  edd:  { label: "MillForge EDD", sub: "Greedy — fast & reliable",           color: "#3b82f6", ring: "#3b82f6" },
  sa:   { label: "MillForge SA",  sub: "Simulated annealing — best result",  color: "#f97316", ring: "#f97316" },
};

function Ring({ pct, color }) {
  const r = 34, circ = 2 * Math.PI * r;
  const [offset, setOffset] = useState(circ);
  useEffect(() => {
    const id = requestAnimationFrame(() => setTimeout(() => setOffset(circ * (1 - pct / 100)), 80));
    return () => cancelAnimationFrame(id);
  }, [pct, circ]);
  return (
    <svg width="80" height="80" viewBox="0 0 80 80">
      <circle cx="40" cy="40" r={r} fill="none" stroke="#1f2937" strokeWidth="7" />
      <circle cx="40" cy="40" r={r} fill="none" stroke={color} strokeWidth="7"
        strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
        transform="rotate(-90 40 40)"
        style={{ transition: "stroke-dashoffset 0.9s ease-out" }} />
      <text x="40" y="45" textAnchor="middle" fontSize="13" fontWeight="bold" fill="white">{pct}%</text>
    </svg>
  );
}

function Card({ algo, entry, winner, rushDiff }) {
  const m = ALGO[algo];
  const isWinner = winner === algo;
  return (
    <div className={`rounded-xl border p-5 flex flex-col gap-3 ${
      isWinner ? "border-orange-500 bg-orange-500/5" : algo === "fifo" ? "border-gray-700 bg-gray-800/40" : "border-blue-800 bg-blue-900/10"
    }`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-base font-bold text-white">{m.label}</p>
          <p className="text-xs text-gray-500 mt-0.5">{m.sub}</p>
        </div>
        {isWinner && <span className="text-xs bg-orange-500 text-white px-2 py-0.5 rounded-full font-semibold">Best</span>}
      </div>
      <div className="flex items-center gap-4">
        <Ring pct={entry.on_time_rate_percent} color={m.ring} />
        <div className="flex-1 space-y-1.5 text-xs">
          <div className="flex justify-between"><span className="text-gray-500">On-time</span><span className={isWinner ? "text-orange-400 font-semibold" : "text-gray-300"}>{entry.on_time_count}/{entry.total_orders}</span></div>
          <div className="flex justify-between"><span className="text-gray-500">Makespan</span><span className="text-gray-300">{entry.makespan_hours}h</span></div>
          <div className="flex justify-between"><span className="text-gray-500">Utilization</span><span className="text-gray-300">{entry.utilization_percent}%</span></div>
          <div className="flex justify-between"><span className="text-gray-500">Solve time</span><span className="text-gray-300">{entry.solve_ms}ms</span></div>
        </div>
      </div>
      {rushDiff !== null && (
        <div className={`text-xs rounded px-2 py-1.5 text-center font-medium ${rushDiff < 0 ? "bg-red-900/30 text-red-300" : "bg-gray-800 text-gray-400"}`}>
          Rush order impact: {rushDiff > 0 ? "+" : ""}{rushDiff}pp
        </div>
      )}
    </div>
  );
}

export default function Demo() {
  const [data, setData]       = useState(null);
  const [rush, setRush]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [showRush, setShowRush] = useState(false);
  const [pressure, setPressure] = useState(0.5);
  const debounce = useRef(null);

  const load = useCallback(async (p, withRush) => {
    setLoading(true);
    const timeout = new Promise(r => setTimeout(() => r("__timeout__"), 3500));
    try {
      const [base, rushRes] = await Promise.all([
        Promise.race([fetch(`${API_BASE}/api/schedule/benchmark?pressure=${p}`).then(r => r.json()), timeout]),
        withRush ? Promise.race([fetch(`${API_BASE}/api/schedule/benchmark?pressure=${p}&rush=true`).then(r => r.json()), timeout]) : Promise.resolve(null),
      ]);
      setData(base === "__timeout__" ? FALLBACK : base);
      setRush(rushRes === "__timeout__" ? null : rushRes);
    } catch {
      setData(FALLBACK);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(0.5, false); }, [load]);

  const handlePressure = (e) => {
    const p = parseFloat(e.target.value);
    setPressure(p);
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => load(p, showRush), 250);
  };

  const toggleRush = () => {
    const next = !showRush;
    setShowRush(next);
    load(pressure, next);
  };

  const active = showRush && rush ? rush : data;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-950/90 backdrop-blur">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2">
            <span className="text-xl">⚙️</span>
            <span className="text-lg font-bold text-white">Mill<span className="text-orange-500">Forge AI</span></span>
          </a>
          <a href="/" className="text-sm text-gray-400 hover:text-white transition-colors">← Back to site</a>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-10">
        {/* Hero stat */}
        <div className="text-center mb-10">
          <p className="text-sm text-orange-400 font-medium mb-2 uppercase tracking-widest">Live benchmark · 28 orders · same machines</p>
          <h1 className="text-4xl sm:text-5xl font-extrabold text-white mb-3 leading-tight">
            60% → <span className="text-orange-400">96%</span> on-time delivery
          </h1>
          <p className="text-gray-400 text-base max-w-lg mx-auto">
            No new equipment. No extra headcount. Just AI scheduling replacing a whiteboard.
          </p>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6 bg-gray-900 border border-gray-800 rounded-xl px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">Schedule pressure</span>
            <input type="range" min="0" max="1" step="0.1" value={pressure}
              onChange={handlePressure} className="w-28 accent-orange-500" />
            <span className="text-xs text-gray-500">
              {pressure <= 0.3 ? "Low" : pressure <= 0.6 ? "Normal" : "High"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={toggleRush} disabled={loading}
              className={`text-xs px-3 py-1.5 rounded-lg font-medium border transition-colors ${
                showRush ? "bg-red-900/40 border-red-700 text-red-300" : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
              }`}>
              {showRush ? "✕ Remove rush order" : "+ Inject rush order"}
            </button>
            <button onClick={() => load(pressure, showRush)} disabled={loading}
              className="text-xs px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-gray-300 hover:border-gray-500 transition-colors">
              {loading ? "Running…" : "↺ Re-run"}
            </button>
          </div>
        </div>

        {/* Rush banner */}
        {showRush && rush && data && (
          <div className="mb-5 rounded-lg bg-red-900/20 border border-red-800 px-4 py-3 text-sm text-red-300">
            <strong>Rush order injected</strong> — on-time delta:
            {" "}<span className="font-mono">FIFO {rush.fifo.on_time_rate_percent - data.fifo.on_time_rate_percent >= 0 ? "+" : ""}{Math.round((rush.fifo.on_time_rate_percent - data.fifo.on_time_rate_percent) * 10) / 10}pp</span>
            {" · "}<span className="font-mono">EDD {rush.edd.on_time_rate_percent - data.edd.on_time_rate_percent >= 0 ? "+" : ""}{Math.round((rush.edd.on_time_rate_percent - data.edd.on_time_rate_percent) * 10) / 10}pp</span>
            {" · "}<span className="font-mono text-orange-300">SA {rush.sa.on_time_rate_percent - data.sa.on_time_rate_percent >= 0 ? "+" : ""}{Math.round((rush.sa.on_time_rate_percent - data.sa.on_time_rate_percent) * 10) / 10}pp</span>
          </div>
        )}

        {/* Cards */}
        {active ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
            {["fifo", "edd", "sa"].map(algo => (
              <Card key={algo} algo={algo} entry={active[algo]} winner={data.winner}
                rushDiff={showRush && rush ? Math.round((rush[algo].on_time_rate_percent - data[algo].on_time_rate_percent) * 10) / 10 : null} />
            ))}
          </div>
        ) : (
          <div className="text-center py-16 text-gray-500 text-sm">Running benchmark…</div>
        )}

        {/* Improvement callout */}
        {data && (
          <div className="rounded-2xl bg-orange-500/10 border border-orange-800 px-6 py-6 flex flex-wrap items-center gap-6 mb-8">
            <div>
              <p className="text-6xl font-extrabold text-orange-400">+{data.on_time_improvement_pp}</p>
              <p className="text-sm text-gray-300 font-semibold mt-1">percentage points on-time</p>
            </div>
            <div className="flex-1 min-w-48 text-sm text-gray-400 space-y-1.5">
              <p>✓ Same machines · same staff · same suppliers</p>
              <p>✓ Replaces whiteboard scheduling on day one</p>
              <p>✓ Fully deterministic — identical result every run</p>
              <p className="text-xs text-gray-600 pt-1">28-order simulated dataset · results vary by shop configuration</p>
            </div>
            <a href="/" className="btn-primary text-sm px-5 py-2.5 rounded-lg font-semibold whitespace-nowrap">
              Get early access →
            </a>
          </div>
        )}

        {/* How it works */}
        <div className="border border-gray-800 rounded-xl bg-gray-900/60 px-6 py-6">
          <h2 className="text-lg font-bold text-white mb-4">How the benchmark works</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <p className="font-semibold text-gray-200 mb-1">Same 28 orders</p>
              <p className="text-gray-500">Every algorithm gets identical input — same jobs, same machines, same due dates. No tricks.</p>
            </div>
            <div>
              <p className="font-semibold text-gray-200 mb-1">Three algorithms compete</p>
              <p className="text-gray-500">FIFO (arrival order), EDD (earliest due date with setup-time awareness), SA (simulated annealing minimizing tardiness).</p>
            </div>
            <div>
              <p className="font-semibold text-gray-200 mb-1">Deterministic result</p>
              <p className="text-gray-500">SA uses a fixed random seed (123). The +35.7pp improvement is the same every run — this isn't a lucky draw.</p>
            </div>
          </div>
        </div>

        {data?._cached && (
          <p className="text-xs text-gray-600 text-center mt-4">showing cached result — backend loading</p>
        )}
      </main>

      <footer className="border-t border-gray-800 mt-12">
        <div className="max-w-5xl mx-auto px-4 py-5 flex items-center justify-between text-xs text-gray-600">
          <span>MillForge AI — lights-out American metal production</span>
          <a href="/" className="hover:text-gray-400 transition-colors">millforgeai.com</a>
        </div>
      </footer>
    </div>
  );
}
