import { useState, useEffect } from "react";
import { API_BASE } from "../config";

function KPI({ label, value, sub, color = "text-white" }) {
  return (
    <div className="bg-gray-800 rounded-lg p-5">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  );
}

function SpotTicker({ prices, sources }) {
  if (!prices) return null;
  const entries = Object.entries(prices).slice(0, 8);
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
      <h3 className="text-sm font-semibold text-gray-400 mb-4">Live Spot Prices (USD/lb)</h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {entries.map(([mat, price]) => (
          <div key={mat} className="text-center">
            <p className="text-xs text-gray-500 capitalize">{mat.replace("_", " ")}</p>
            <p className="text-lg font-bold text-white">${price.toFixed(2)}</p>
            <p className="text-[10px] text-gray-600">
              {sources?.[mat] === "yahoo_finance" ? "live" : "fallback"}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState(null);
  const [spots, setSpots] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/business/metrics`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null)),
      fetch(`${API_BASE}/api/market-quotes/spot-prices`)
        .then((r) => (r.ok ? r.json() : null)),
      fetch(`${API_BASE}/health`)
        .then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([m, s, h]) => {
        setMetrics(m);
        setSpots(s);
        setHealth(h);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-gray-500 text-center py-10 animate-pulse">Loading...</p>;

  const m = metrics || {};
  const h = health || {};

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white mb-1">Dashboard</h2>
        <p className="text-sm text-gray-500">Live business metrics and platform health.</p>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPI
          label="Total Users"
          value={m.users?.total ?? "—"}
          color="text-white"
        />
        <KPI
          label="Active Jobs"
          value={m.jobs?.active ?? "—"}
          sub={`${m.jobs?.total ?? 0} total, ${m.jobs?.completion_rate_percent ?? 0}% complete`}
          color="text-forge-400"
        />
        <KPI
          label="QC Pass Rate"
          value={m.quality?.pass_rate_percent != null ? `${m.quality.pass_rate_percent}%` : "—"}
          sub={`${m.quality?.total_inspections ?? 0} inspections`}
          color={
            (m.quality?.pass_rate_percent ?? 0) >= 90
              ? "text-green-400"
              : (m.quality?.pass_rate_percent ?? 0) >= 70
              ? "text-yellow-400"
              : "text-red-400"
          }
        />
        <KPI
          label="Lights-Out Readiness"
          value={h.readiness_percent != null ? `${h.readiness_percent}%` : "—"}
          sub={`${h.automated_touchpoints ?? 0}/${h.total_touchpoints ?? 0} touchpoints automated`}
          color="text-forge-400"
        />
      </div>

      {/* Touchpoint status */}
      {h.lights_out_readiness && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h3 className="text-sm font-semibold text-gray-400 mb-4">Automation Status</h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Object.entries(h.lights_out_readiness).map(([tp, status]) => {
              const auto = [
                "automated",
                "real_grid_data",
                "real_data",
                "directory_active",
                "onnx_inference",
              ].includes(status);
              return (
                <div
                  key={tp}
                  className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-2.5"
                >
                  <span className="text-sm text-gray-300 capitalize">
                    {tp.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                      auto
                        ? "bg-green-900/50 text-green-400"
                        : "bg-yellow-900/50 text-yellow-400"
                    }`}
                  >
                    {status.replace(/_/g, " ")}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Spot prices */}
      {spots && (
        <SpotTicker
          prices={spots.prices_usd_per_lb}
          sources={spots.data_sources}
        />
      )}

      {/* Data sources */}
      {h.data_sources && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
          <h3 className="text-sm font-semibold text-gray-400 mb-4">Data Sources</h3>
          <div className="space-y-2">
            {Object.entries(h.data_sources).map(([key, val]) => (
              <div key={key} className="flex items-start gap-3 text-sm">
                <span className="text-gray-500 w-40 flex-shrink-0 capitalize">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="text-gray-300">{val}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
