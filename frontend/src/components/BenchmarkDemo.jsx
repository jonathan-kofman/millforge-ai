import { useState, useEffect, useRef, useCallback } from "react";
import { AlertTriangle } from "lucide-react";
import { API_BASE } from "../config";

// ── SVG ring for on-time percentage ──────────────────────────────────────────
function OnTimeRing({ percent, color, size = 88 }) {
  const r = 36;
  const circ = 2 * Math.PI * r;
  const [offset, setOffset] = useState(circ);

  useEffect(() => {
    const id = requestAnimationFrame(() =>
      setTimeout(() => setOffset(circ * (1 - percent / 100)), 60)
    );
    return () => cancelAnimationFrame(id);
  }, [percent, circ]);

  return (
    <svg width={size} height={size} viewBox="0 0 88 88">
      <circle cx="44" cy="44" r={r} fill="none" stroke="#1f2937" strokeWidth="8" />
      <circle
        cx="44" cy="44" r={r}
        fill="none"
        stroke={color}
        strokeWidth="8"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 44 44)"
        style={{ transition: "stroke-dashoffset 0.9s ease-out" }}
      />
      <text x="44" y="48" textAnchor="middle" fontSize="14" fontWeight="bold" fill="white">
        {percent}%
      </text>
    </svg>
  );
}

// ── SVG bar chart (3 algorithms × 2 metrics) ─────────────────────────────────
function BarChart({ data }) {
  const [animScale, setAnimScale] = useState(0);

  useEffect(() => {
    const id = requestAnimationFrame(() =>
      setTimeout(() => setAnimScale(1), 80)
    );
    return () => cancelAnimationFrame(id);
  }, [data]);

  const bars = [
    { label: "FIFO",  color: "#6b7280", value: data.fifo.on_time_rate_percent },
    { label: "EDD",   color: "#3b82f6", value: data.edd.on_time_rate_percent  },
    { label: "SA",    color: "#f97316", value: data.sa.on_time_rate_percent   },
  ];

  const chartH = 80;
  const barW   = 36;
  const gap    = 24;
  const totalW = bars.length * (barW + gap) - gap + 24;

  return (
    <svg viewBox={`0 0 ${totalW} ${chartH + 28}`} width="100%" style={{ maxWidth: 240 }}>
      {bars.map(({ label, color, value }, i) => {
        const barH = (value / 100) * chartH * animScale;
        const x = i * (barW + gap) + 12;
        const y = chartH - barH;
        return (
          <g key={label}>
            <rect
              x={x} y={y} width={barW} height={barH}
              rx="4" fill={color} opacity="0.85"
              style={{ transition: "y 0.8s ease-out, height 0.8s ease-out" }}
            />
            <text x={x + barW / 2} y={chartH + 14} textAnchor="middle" fontSize="10" fill="#9ca3af">
              {label}
            </text>
            <text x={x + barW / 2} y={Math.max(y - 4, 10)} textAnchor="middle" fontSize="10" fill="#e5e7eb">
              {value}%
            </text>
          </g>
        );
      })}
      <line x1="8" y1={chartH} x2={totalW - 8} y2={chartH} stroke="#374151" strokeWidth="1" />
    </svg>
  );
}

// ── Stat row ─────────────────────────────────────────────────────────────────
function Stat({ label, value, accent }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-gray-500">{label}</span>
      <span className={accent ? "text-orange-400 font-semibold" : "text-gray-300"}>{value}</span>
    </div>
  );
}

// ── Algorithm card ────────────────────────────────────────────────────────────
const ALGO_META = {
  fifo: { label: "FIFO Baseline",          color: "#6b7280", ringColor: "#6b7280", desc: "Arrival order — no optimisation",              shopLabel: "How most shops run today" },
  edd:  { label: "EDD (MillForge AI Greedy)", color: "#3b82f6", ringColor: "#3b82f6", desc: "Earliest due date with setup-time awareness", shopLabel: "MillForge default — fast and reliable" },
  sa:   { label: "SA (MillForge AI Best)",    color: "#f97316", ringColor: "#f97316", desc: "Simulated annealing — minimises tardiness",   shopLabel: "MillForge optimized — best for complex schedules" },
};

function AlgoCard({ algo, entry, isWinner, rushDiff, flash }) {
  const meta = ALGO_META[algo];
  const borderClass = isWinner
    ? "border-orange-500 bg-orange-500/5"
    : algo === "fifo"
    ? "border-gray-700 bg-gray-800/50"
    : "border-blue-800 bg-blue-900/10";

  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-3 ${borderClass} ${flash ? "flash-border" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">{meta.label}</p>
          <p className="text-xs text-gray-500 mt-0.5">{meta.desc}</p>
        </div>
        {isWinner && (
          <span className="text-xs bg-orange-500 text-white px-2 py-0.5 rounded-full font-medium whitespace-nowrap">
            Best
          </span>
        )}
      </div>

      <div className="flex items-center gap-4">
        <OnTimeRing percent={entry.on_time_rate_percent} color={meta.ringColor} />
        <div className="flex-1 space-y-1.5">
          <Stat label="On-time" value={`${entry.on_time_count}/${entry.total_orders}`} accent={isWinner} />
          <Stat label="Makespan" value={`${entry.makespan_hours}h`} />
          <Stat label="Utilization" value={`${entry.utilization_percent}%`} />
          <Stat label="Solve" value={`${entry.solve_ms}ms`} />
        </div>
      </div>

      {rushDiff !== null && (
        <div className={`text-xs rounded px-2 py-1.5 font-medium text-center ${
          rushDiff < 0 ? "bg-red-900/40 text-red-300" : "bg-gray-800 text-gray-400"
        }`}>
          Rush impact: {rushDiff > 0 ? "+" : ""}{rushDiff}pp
        </div>
      )}
      <p className="text-xs text-gray-600 text-center">{meta.shopLabel}</p>
    </div>
  );
}

// ── Cached fallback (deterministic locked numbers) ───────────────────────────
const FALLBACK_DATA = {
  fifo: { on_time_rate_percent: 60.7, on_time_count: 17, total_orders: 28, makespan_hours: 148, utilization_percent: 71, solve_ms: 1 },
  edd:  { on_time_rate_percent: 82.1, on_time_count: 23, total_orders: 28, makespan_hours: 142, utilization_percent: 78, solve_ms: 8 },
  sa:   { on_time_rate_percent: 96.4, on_time_count: 27, total_orders: 28, makespan_hours: 138, utilization_percent: 82, solve_ms: 847 },
  winner: "sa",
  on_time_improvement_pp: 35.7,
  dataset_description: "28-order simulated dataset",
  _cached: true,
};

// ── Main component ────────────────────────────────────────────────────────────
export default function BenchmarkDemo() {
  const [data,      setData]      = useState(null);
  const [rushData,  setRushData]  = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [pressure,  setPressure]  = useState(0.5);
  const [showRush,  setShowRush]  = useState(false);
  const [error,     setError]     = useState(null);
  const [flash,     setFlash]     = useState(false);
  const debounceRef = useRef(null);
  const flashRef    = useRef(null);

  const triggerFlash = useCallback(() => {
    setFlash(true);
    clearTimeout(flashRef.current);
    flashRef.current = setTimeout(() => setFlash(false), 350);
  }, []);

  const fetchBenchmark = useCallback(async (p, withRush) => {
    setLoading(true);
    setError(null);
    const timeout = new Promise(resolve => setTimeout(() => resolve("__timeout__"), 3000));
    try {
      const [base, rush] = await Promise.all([
        Promise.race([
          fetch(`${API_BASE}/api/schedule/benchmark?pressure=${p}`).then(r => r.json()),
          timeout,
        ]),
        withRush
          ? Promise.race([
              fetch(`${API_BASE}/api/schedule/benchmark?pressure=${p}&rush=true`).then(r => r.json()),
              timeout,
            ])
          : Promise.resolve(null),
      ]);
      setData(base === "__timeout__" ? FALLBACK_DATA : base);
      setRushData(rush === "__timeout__" ? null : rush);
      triggerFlash();
    } catch (err) {
      setData(FALLBACK_DATA);
    } finally {
      setLoading(false);
    }
  }, [triggerFlash]);

  useEffect(() => { fetchBenchmark(0.5, false); }, [fetchBenchmark]);

  const handlePressureChange = (e) => {
    const p = parseFloat(e.target.value);
    setPressure(p);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchBenchmark(p, showRush), 250);
  };

  const handleRushToggle = () => {
    const next = !showRush;
    setShowRush(next);
    fetchBenchmark(pressure, next);
  };

  const improvement = data ? data.on_time_improvement_pp : null;

  return (
    <section className="max-w-6xl mx-auto px-4 py-12">
      {/* ── Section header ── */}
      <div className="text-center mb-8">
        <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-2">
          Metal Parts in Days, Not Months.
        </h2>
        <p className="text-gray-400 text-sm max-w-xl mx-auto">
          Same 28 orders. Same machines. See what AI scheduling actually does to your on-time rate.
        </p>
      </div>

      {/* ── Demo explainer ── */}
      <p className="text-xs text-gray-500 text-center max-w-lg mx-auto mb-5">
        Drag the slider to change schedule pressure. Inject a rush order to see how each strategy handles disruption — same 28 jobs, same machines every time.
      </p>

      {/* ── Controls ── */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        {/* Pressure slider */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-3">
            <label className="text-xs text-gray-400 whitespace-nowrap">
              Schedule pressure
            </label>
            <input
              type="range" min="0" max="1" step="0.1"
              value={pressure}
              onChange={handlePressureChange}
              className="w-32 accent-orange-500"
            />
          </div>
          <span className="text-xs text-gray-500">
            {pressure <= 0.3
              ? "Low pressure — 28 standard orders"
              : pressure <= 0.6
              ? "Normal pressure — 28 orders with mixed priorities"
              : "High pressure — 28 orders + rush jobs competing for capacity"}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Rush order toggle */}
          <button
            onClick={handleRushToggle}
            disabled={loading}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium border transition-colors ${
              showRush
                ? "bg-red-900/40 border-red-700 text-red-300 hover:bg-red-900/60"
                : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
            }`}
          >
            {showRush ? "✕ Remove rush order" : "+ Inject rush order"}
          </button>

          <button
            onClick={() => fetchBenchmark(pressure, showRush)}
            disabled={loading}
            className="text-xs btn-secondary py-1.5"
          >
            {loading ? "Running…" : "↺ Re-run"}
          </button>
        </div>
      </div>

      {/* ── Rush injection banner ── */}
      {showRush && rushData && data && (
        <div className="mb-5 rounded-lg bg-red-900/20 border border-red-800 px-4 py-3 text-sm text-red-300">
          <strong>+1 rush order injected</strong> — on-time rate impact:{" "}
          <span className="font-mono">
            FIFO {rushData.fifo.on_time_rate_percent - data.fifo.on_time_rate_percent >= 0 ? "+" : ""}
            {Math.round((rushData.fifo.on_time_rate_percent - data.fifo.on_time_rate_percent) * 10) / 10}pp
          </span>
          {" · "}
          <span className="font-mono">
            EDD {rushData.edd.on_time_rate_percent - data.edd.on_time_rate_percent >= 0 ? "+" : ""}
            {Math.round((rushData.edd.on_time_rate_percent - data.edd.on_time_rate_percent) * 10) / 10}pp
          </span>
          {" · "}
          <span className="font-mono text-orange-300">
            SA {rushData.sa.on_time_rate_percent - data.sa.on_time_rate_percent >= 0 ? "+" : ""}
            {Math.round((rushData.sa.on_time_rate_percent - data.sa.on_time_rate_percent) * 10) / 10}pp
          </span>
        </div>
      )}

      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

      {/* ── Algorithm cards ── */}
      {data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            {(["fifo", "edd", "sa"]).map((algo) => (
              <AlgoCard
                key={algo}
                algo={algo}
                entry={showRush && rushData ? rushData[algo] : data[algo]}
                isWinner={data.winner === algo}
                flash={flash}
                rushDiff={
                  showRush && rushData
                    ? Math.round((rushData[algo].on_time_rate_percent - data[algo].on_time_rate_percent) * 10) / 10
                    : null
                }
              />
            ))}
          </div>

          {/* ── Bar chart + improvement callout ── */}
          <div className="flex flex-wrap items-center gap-8 mt-2">
            <BarChart data={showRush && rushData ? rushData : data} />

            <div className="flex-1 min-w-48">
              {improvement !== null && improvement > 0 && (
                <div className="rounded-xl bg-orange-500/10 border border-orange-800 px-5 py-5">
                  <p className="text-5xl font-extrabold text-orange-400">+{improvement}</p>
                  <p className="text-sm text-gray-300 mt-2 font-semibold">
                    percentage points more orders delivered on time
                  </p>
                  <p className="text-xs text-gray-500 mt-2">
                    Same machines · same staff · same suppliers
                  </p>
                  <p className="text-xs text-gray-600 mt-3 border-t border-gray-800 pt-3">
                    Based on simulated 28-order dataset. Results vary by shop configuration.
                  </p>
                </div>
              )}
              <p className="text-xs text-gray-600 mt-3">
                {data.dataset_description}
              </p>
            </div>
          </div>
        </>
      )}

      {loading && !data && (
        <div className="text-center py-12 text-gray-500 text-sm">Running benchmark…</div>
      )}

      {data?._cached && (
        <p className="text-xs text-yellow-500 text-center mt-2 flex items-center justify-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" /> Showing cached demo data — live backend unavailable
        </p>
      )}
    </section>
  );
}
