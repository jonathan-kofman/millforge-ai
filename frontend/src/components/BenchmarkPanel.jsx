import { useState, useEffect } from "react";

export default function BenchmarkPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/schedule/benchmark");
      if (!res.ok) throw new Error("Benchmark request failed");
      setData(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { run(); }, []);

  return (
    <div className="card mt-8">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-semibold text-white">
            Algorithm Benchmark: EDD vs Simulated Annealing
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Run on the 8-order demo dataset. SA warm-starts from EDD and minimizes weighted tardiness.
          </p>
        </div>
        <button onClick={run} className="btn-secondary text-xs" disabled={loading}>
          {loading ? "Running…" : "↺ Re-run"}
        </button>
      </div>

      {error && (
        <p className="text-sm text-red-400">{error}</p>
      )}

      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <AlgoCard entry={data.edd} label="EDD (Greedy)" isWinner={data.winner === "edd"} />
            <AlgoCard entry={data.sa}  label="Simulated Annealing" isWinner={data.winner === "sa"} />
          </div>

          <div className={`rounded-lg px-4 py-3 text-sm font-medium flex items-center gap-2 ${
            data.on_time_improvement_pp > 0
              ? "bg-green-900/30 text-green-300 border border-green-800"
              : data.on_time_improvement_pp < 0
              ? "bg-red-900/30 text-red-300 border border-red-800"
              : "bg-gray-800 text-gray-400"
          }`}>
            {data.on_time_improvement_pp > 0 && (
              <>✓ SA delivers <strong>+{data.on_time_improvement_pp}pp</strong> on-time improvement over EDD</>
            )}
            {data.on_time_improvement_pp === 0 && (
              <>SA matches EDD — both optimal for this instance</>
            )}
            {data.on_time_improvement_pp < 0 && (
              <>EDD leads by <strong>{Math.abs(data.on_time_improvement_pp)}pp</strong> on this instance</>
            )}
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="text-center py-6 text-gray-500 text-sm">Running benchmark…</div>
      )}
    </div>
  );
}

function AlgoCard({ entry, label, isWinner }) {
  return (
    <div className={`rounded-lg p-4 border ${isWinner ? "border-forge-500 bg-forge-500/5" : "border-gray-700 bg-gray-800"}`}>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-white">{label}</p>
        {isWinner && (
          <span className="text-xs bg-forge-500 text-white px-2 py-0.5 rounded-full font-medium">
            Winner
          </span>
        )}
      </div>
      <div className="space-y-1.5 text-xs">
        <Row label="On-time rate"  value={`${entry.on_time_rate_percent}%`}  highlight={isWinner} />
        <Row label="On-time"       value={`${entry.on_time_count}/${entry.total_orders}`} />
        <Row label="Makespan"      value={`${entry.makespan_hours}h`} />
        <Row label="Utilization"   value={`${entry.utilization_percent}%`} />
        <Row label="Solve time"    value={`${entry.solve_ms}ms`} />
      </div>
    </div>
  );
}

function Row({ label, value, highlight }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className={highlight ? "text-forge-400 font-semibold" : "text-gray-300"}>{value}</span>
    </div>
  );
}
