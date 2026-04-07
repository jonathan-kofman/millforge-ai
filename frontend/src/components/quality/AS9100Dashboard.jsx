import { useState, useEffect } from "react";
import { API_BASE } from "../../config";

export default function AS9100Dashboard() {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [syncMessage, setSyncMessage] = useState(null);
  const [initializing, setInitializing] = useState(false);

  const loadDashboard = () => {
    setLoading(true);
    fetch(`${API_BASE}/api/quality/as9100/dashboard`, { credentials: "include" })
      .then((r) => {
        if (r.ok) return r.json();
        throw new Error("Not initialized");
      })
      .then((data) => {
        setDashboard(data);
        setLoading(false);
      })
      .catch(() => {
        setDashboard(null);
        setLoading(false);
      });
  };

  useEffect(() => { loadDashboard(); }, []);

  const initialize = async () => {
    setInitializing(true);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/quality/as9100/initialize`, {
        method: "POST", credentials: "include",
      });
      loadDashboard();
    } catch (e) {
      setError(e.message);
    } finally {
      setInitializing(false);
    }
  };

  const syncEvidence = async () => {
    setSyncMessage(null);
    try {
      const res = await fetch(`${API_BASE}/api/quality/as9100/sync`, {
        method: "POST", credentials: "include",
      });
      if (res.ok) {
        const data = await res.json();
        setSyncMessage(`Synced: ${data.ingested.mtr} MTRs, ${data.ingested.inspection} inspections, ${data.ingested.logbook} logbook entries`);
        loadDashboard();
      }
    } catch (e) {
      setError(e.message);
    }
  };

  if (loading) return <div className="p-6 text-gray-500 animate-pulse">Loading...</div>;

  if (!dashboard || dashboard.total_clauses === 0) {
    return (
      <div className="p-6">
        <div className="card p-6 text-center">
          <h3 className="text-lg font-medium text-white mb-4">AS9100D Certification</h3>
          <p className="text-forge-300 mb-4">
            Initialize your AS9100D compliance tracking to start your certification journey.
          </p>
          <button onClick={initialize} disabled={initializing} className="btn-primary">
            {initializing ? "Initializing..." : "Initialize AS9100D Clauses"}
          </button>
          {error && <div className="mt-2 text-red-400 text-sm">{error}</div>}
        </div>
      </div>
    );
  }

  const statusColors = {
    not_started: "bg-gray-700 text-gray-300",
    in_progress: "bg-blue-800 text-blue-200",
    documented: "bg-yellow-800 text-yellow-200",
    verified: "bg-green-800 text-green-200",
    non_conforming: "bg-red-800 text-red-200",
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold text-white">AS9100D Compliance</h2>
        <button onClick={syncEvidence} className="btn-primary text-sm">
          Sync Evidence from Modules
        </button>
      </div>

      {error && <div className="alert-error">{error}</div>}
      {syncMessage && <div className="alert-success">{syncMessage}</div>}

      {/* Progress Bar */}
      <div className="card p-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-forge-200">Overall Readiness</span>
          <span className="text-2xl font-bold text-forge-400">{dashboard.overall_percent.toFixed(0)}%</span>
        </div>
        <div className="w-full bg-forge-800 rounded-full h-3">
          <div
            className="bg-forge-500 h-3 rounded-full transition-all"
            style={{ width: `${dashboard.overall_percent}%` }}
          />
        </div>
        <div className="flex gap-4 mt-2 text-sm text-forge-400">
          <span>{dashboard.documented_count} documented</span>
          <span>{dashboard.verified_count} verified</span>
          <span>{dashboard.total_clauses - dashboard.documented_count} remaining</span>
        </div>
      </div>

      {/* Next Actions */}
      {dashboard.next_actions.length > 0 && (
        <div className="card p-6">
          <h3 className="text-lg font-medium text-forge-200 mb-3">Next Steps</h3>
          <ul className="space-y-2">
            {dashboard.next_actions.map((action, i) => (
              <li key={i} className="text-sm text-forge-300 flex items-start gap-2">
                <span className="text-forge-500 mt-0.5">-</span>
                {action}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Clause List */}
      <div className="card p-6">
        <h3 className="text-lg font-medium text-forge-200 mb-4">Clauses</h3>
        <div className="space-y-2">
          {dashboard.clauses.map((c) => (
            <div key={c.clause_id} className="flex items-center justify-between py-2 border-b border-forge-800">
              <div>
                <span className="text-forge-200 font-medium">{c.clause_number}</span>
                <span className="text-forge-300 ml-2">{c.clause_title}</span>
              </div>
              <div className="flex items-center gap-3">
                {c.evidence_count > 0 && (
                  <span className="text-xs text-forge-400">{c.evidence_count} evidence</span>
                )}
                <span className={`px-2 py-0.5 rounded text-xs ${statusColors[c.status] || statusColors.not_started}`}>
                  {c.status.replace("_", " ")}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
