import { useState, useEffect } from "react";
import { API_BASE } from "../config";

// Spark line — 24-hour rate curve
function SparkLine({ rates, height = 40 }) {
  if (!rates || rates.length === 0) return null;
  const max = Math.max(...rates);
  const min = Math.min(...rates);
  const range = max - min || 0.001;
  const w = 240;
  const points = rates.map((r, i) => {
    const x = (i / (rates.length - 1)) * w;
    const y = height - ((r - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" style={{ maxWidth: w }}>
      <polyline
        points={points}
        fill="none"
        stroke="#f97316"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Pill({ label, value, accent }) {
  return (
    <div className="flex flex-col items-center">
      <span className={`text-lg font-bold ${accent ? "text-orange-400" : "text-white"}`}>{value}</span>
      <span className="text-xs text-gray-500">{label}</span>
    </div>
  );
}

const NEG_WINDOWS_TIMEOUT_MS = 5000;
const NEG_WINDOWS_FALLBACK = {
  total_windows: 0,
  max_credit_usd_per_mwh: 0,
  recommendation: "No negative pricing windows detected in next 24 hrs.",
  data_source: "simulated_fallback",
};

const MOCK_RATES = [
  0.08, 0.07, 0.07, 0.06, 0.06, 0.07,
  0.09, 0.12, 0.15, 0.16, 0.15, 0.14,
  0.14, 0.13, 0.14, 0.16, 0.18, 0.19,
  0.17, 0.14, 0.12, 0.11, 0.10, 0.09,
];

export default function EnergyWidget() {
  const [data, setData] = useState(null);
  const [negWindows, setNegWindows] = useState(null);
  const [rates, setRates] = useState(MOCK_RATES);
  const [ratesLive, setRatesLive] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const now = new Date().toISOString();

    const negWindowsFetch = Promise.race([
      fetch(`${API_BASE}/api/energy/negative-pricing-windows`).then(r => r.ok ? r.json() : null),
      new Promise(resolve => setTimeout(() => resolve(null), NEG_WINDOWS_TIMEOUT_MS)),
    ]);

    Promise.all([
      fetch(`${API_BASE}/api/energy/estimate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_time: now, duration_hours: 1, material: "titanium" }),
      }).then(r => r.ok ? r.json() : null).catch(() => null),
      negWindowsFetch,
      fetch(`${API_BASE}/api/energy/rates`).then(r => r.ok ? r.json() : null).catch(() => null),
    ])
      .then(([est, neg, ratesData]) => {
        if (!est && !neg) { setLoadError(true); return; }
        setData(est);
        setNegWindows(neg ?? NEG_WINDOWS_FALLBACK);
        if (ratesData?.rates_usd_per_kwh?.length === 24) {
          setRates(ratesData.rates_usd_per_kwh);
          setRatesLive(ratesData.data_source === "EIA_realtime");
        }
      })
      .catch(() => {
        setLoadError(true);
        setNegWindows(NEG_WINDOWS_FALLBACK);
      });
  }, []);

  const isLive = data?.data_source === "EIA_realtime";

  if (loadError) {
    return (
      <section className="max-w-6xl mx-auto px-4 py-12">
        <div className="text-center mb-8">
          <p className="text-sm font-bold tracking-widest text-orange-500 uppercase mb-2">Energy Intelligence</p>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-2">The other half of the problem.</h2>
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-6 text-center text-gray-500 text-sm">
          Energy data unavailable — backend offline or rate-limited.
        </div>
      </section>
    );
  }

  return (
    <section className="max-w-6xl mx-auto px-4 py-12">
      <div className="text-center mb-8">
        <p className="text-sm font-bold tracking-widest text-orange-500 uppercase mb-2">
          Energy Intelligence
        </p>
        <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-2">
          The other half of the problem.
        </h2>
        <p className="text-gray-400 text-sm max-w-xl mx-auto">
          Energy is 20–40% of mill operating cost. MillForge sequences jobs to minimize
          energy spend — shifting high-load material runs to off-peak windows automatically.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Live PJM price card */}
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white">Live Grid Rate</p>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${isLive ? "bg-green-900/50 text-green-400" : "bg-gray-800 text-gray-500"}`}>
              {isLive ? "EIA live" : "simulated"}
            </span>
          </div>
          <div className="flex gap-6">
            <Pill
              label="current $/kWh"
              value={data?.peak_rate != null ? `$${data.peak_rate.toFixed(3)}` : "—"}
              accent
            />
            <Pill
              label="off-peak $/kWh"
              value={data?.off_peak_rate != null ? `$${data.off_peak_rate.toFixed(3)}` : "—"}
            />
          </div>
          <SparkLine rates={rates} />
          <p className="text-xs text-gray-600">{ratesLive ? "EIA live 24-hour curve" : "24-hour pricing curve (simulated)"}</p>
        </div>

        {/* Best window card */}
        <div className="rounded-xl border border-orange-900/50 bg-orange-500/5 p-5 flex flex-col gap-3">
          <p className="text-sm font-semibold text-white">Optimal Run Window</p>
          <div className="flex gap-6">
            <Pill
              label="best $/kWh"
              value={data?.off_peak_rate != null ? `$${data.off_peak_rate.toFixed(3)}` : "—"}
              accent
            />
            <Pill
              label="vs peak"
              value={
                data?.peak_rate != null && data?.off_peak_rate != null && data.peak_rate !== 0
                  ? `-${(((data.peak_rate - data.off_peak_rate) / data.peak_rate) * 100).toFixed(0)}%`
                  : "—"
              }
            />
          </div>
          <p className="text-xs text-gray-400 leading-relaxed">
            {data?.recommendation || "Schedule energy-intensive jobs during off-peak windows to reduce cost."}
          </p>
        </div>

        {/* Negative pricing / arbitrage card */}
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5 flex flex-col gap-3">
          <p className="text-sm font-semibold text-white">Negative Pricing</p>
          <div className="flex gap-6">
            <Pill
              label="windows today"
              value={negWindows ? String(negWindows.total_windows) : "—"}
              accent={negWindows?.total_windows > 0}
            />
            <Pill
              label="max credit $/MWh"
              value={negWindows?.max_credit_usd_per_mwh != null ? `$${negWindows.max_credit_usd_per_mwh.toFixed(0)}` : "—"}
            />
          </div>
          <p className="text-xs text-gray-400 leading-relaxed">
            {negWindows?.recommendation || "Loading…"}
          </p>
          <p className="text-xs text-gray-600">
            Negative LMP = grid pays you to run heavy loads
          </p>
        </div>
      </div>
    </section>
  );
}
