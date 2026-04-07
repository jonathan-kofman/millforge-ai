import { useState, useEffect } from "react";
import { API_BASE } from "../config";

export default function QCAnalyticsPage({ onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    fetch(`${API_BASE}/api/analytics/qc`, { credentials: "include" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-gray-500 p-6">Loading analytics…</p>;
  if (error) return <p className="text-red-400 p-6">Error: {error}</p>;

  const passRateColor = (pct) => {
    if (pct >= 90) return "text-green-400";
    if (pct >= 70) return "text-yellow-400";
    return "text-red-400";
  };

  const BarRow = ({ label, passed, total }) => {
    const pct = total > 0 ? Math.round((passed / total) * 100) : 0;
    return (
      <div className="mb-3">
        <div className="flex justify-between text-sm mb-1">
          <span className="text-gray-300 font-mono truncate max-w-xs">{label}</span>
          <span className={`font-semibold ${passRateColor(pct)}`}>{pct}%</span>
        </div>
        <div className="w-full bg-gray-700 rounded-full h-2">
          <div
            className="h-2 rounded-full bg-green-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-gray-500 mt-0.5">
          {passed}/{total} passed
        </p>
      </div>
    );
  };

  const DefectTable = ({ items, dimensionLabel }) => (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700 text-gray-500 text-left">
            <th className="pb-2 pr-4">{dimensionLabel}</th>
            <th className="pb-2 pr-4 text-right">Inspected</th>
            <th className="pb-2 pr-4 text-right">Pass rate</th>
            <th className="pb-2">Top defects</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.value} className="border-b border-gray-700/40">
              <td className="py-2 pr-4 font-mono text-gray-300">{item.value}</td>
              <td className="py-2 pr-4 text-right text-gray-500">{item.total_inspections}</td>
              <td className={`py-2 pr-4 text-right font-semibold ${passRateColor(item.pass_rate_percent)}`}>
                {item.pass_rate_percent}%
              </td>
              <td className="py-2 text-gray-500 text-xs">
                {item.top_defects.length > 0
                  ? item.top_defects.join(", ")
                  : <span className="text-green-500">none detected</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Header KPIs */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="card text-center">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Total Inspections</p>
          <p className="text-3xl font-bold text-gray-300">{data.total_inspections}</p>
        </div>
        <div className="card text-center">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Overall Pass Rate</p>
          <p className={`text-3xl font-bold ${passRateColor(data.overall_pass_rate_percent)}`}>
            {data.overall_pass_rate_percent}%
          </p>
        </div>
        <div className="card text-center col-span-2 sm:col-span-1">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Machine Types</p>
          <p className="text-3xl font-bold text-gray-300">{data.by_machine_type.length}</p>
        </div>
      </div>

      {data.total_inspections === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-500 text-lg">No inspections yet.</p>
          <p className="text-gray-500 text-sm mt-1">
            Submit a QC image from the Jobs tab to see defect analytics here.
          </p>
          {onNavigate && (
            <button
              className="btn-primary text-sm mt-4"
              onClick={() => onNavigate("jobs")}
            >
              Go to Jobs
            </button>
          )}
        </div>
      )}

      {data.total_inspections > 0 && (
        <>
          {/* Pass rate by machine type — bar chart */}
          <div className="card">
            <h2 className="text-gray-300 font-semibold mb-4">Pass Rate by Machine Type</h2>
            {data.by_machine_type.length === 0 ? (
              <p className="text-gray-500 text-sm">No data.</p>
            ) : (
              data.by_machine_type.map((item) => (
                <BarRow
                  key={item.value}
                  label={item.value}
                  passed={item.passed}
                  total={item.total_inspections}
                />
              ))
            )}
          </div>

          {/* Defect breakdown by machine type */}
          <div className="card">
            <h2 className="text-gray-300 font-semibold mb-4">Defect Breakdown by Machine Type</h2>
            {data.by_machine_type.length === 0 ? (
              <p className="text-gray-500 text-sm">No data.</p>
            ) : (
              <DefectTable items={data.by_machine_type} dimensionLabel="Machine" />
            )}
          </div>

          {/* Defect breakdown by material */}
          <div className="card">
            <h2 className="text-gray-300 font-semibold mb-4">Defect Breakdown by Material</h2>
            {data.by_material.length === 0 ? (
              <p className="text-gray-500 text-sm">No data.</p>
            ) : (
              <DefectTable items={data.by_material} dimensionLabel="Material" />
            )}
          </div>

          <p className="text-xs text-gray-500 text-right">
            Generated {new Date(data.generated_at).toLocaleString()}
          </p>
        </>
      )}
    </div>
  );
}
