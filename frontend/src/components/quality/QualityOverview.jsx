import { useState, useEffect } from "react";
import { API_BASE } from "../../config";

export default function QualityOverview() {
  const [mtrs, setMtrs] = useState([]);
  const [drawings, setDrawings] = useState([]);
  const [readiness, setReadiness] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/quality/mtr?limit=5`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
      fetch(`${API_BASE}/api/quality/drawing?limit=5`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
      fetch(`${API_BASE}/api/quality/as9100/readiness`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ]).then(([m, d, r]) => {
      setMtrs(m);
      setDrawings(d);
      setReadiness(r);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="p-6 text-gray-500 animate-pulse">Loading...</div>;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 p-6">
      {/* AS9100 Readiness */}
      <div className="card p-6">
        <h3 className="text-lg font-semibold text-white mb-2">AS9100 Readiness</h3>
        {readiness ? (
          <>
            <div className="text-4xl font-bold text-forge-400 mb-2">
              {readiness.overall_score.toFixed(0)}%
            </div>
            <p className="text-sm text-forge-300">
              {readiness.gaps.length} gaps remaining
            </p>
          </>
        ) : (
          <p className="text-forge-400">
            Not initialized.{" "}
            <span className="text-forge-300">Go to AS9100 tab to start.</span>
          </p>
        )}
      </div>

      {/* Recent MTRs */}
      <div className="card p-6">
        <h3 className="text-lg font-semibold text-white mb-2">Recent Material Certs</h3>
        {mtrs.length === 0 ? (
          <p className="text-forge-400">No MTRs uploaded yet.</p>
        ) : (
          <ul className="space-y-2">
            {mtrs.map((m) => (
              <li key={m.id} className="flex justify-between text-sm">
                <span className="text-forge-200 truncate">{m.filename}</span>
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    m.verification_status === "pass"
                      ? "bg-green-800 text-green-200"
                      : m.verification_status === "fail"
                      ? "bg-red-800 text-red-200"
                      : "bg-yellow-800 text-yellow-200"
                  }`}
                >
                  {m.verification_status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Recent Drawings */}
      <div className="card p-6">
        <h3 className="text-lg font-semibold text-white mb-2">Inspection Plans</h3>
        {drawings.length === 0 ? (
          <p className="text-forge-400">No drawings uploaded yet.</p>
        ) : (
          <ul className="space-y-2">
            {drawings.map((d) => (
              <li key={d.id} className="flex justify-between text-sm">
                <span className="text-forge-200 truncate">{d.filename}</span>
                <span className="text-forge-400">{d.callout_count} callouts</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
