import { useState, useEffect } from "react";
import { API_BASE } from "../../config";

export default function ShopFloorLogbook() {
  const [entries, setEntries] = useState([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState("note");
  const [severity, setSeverity] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const loadEntries = () => {
    fetch(`${API_BASE}/api/logbook/entries`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setEntries)
      .catch(() => {});
  };

  useEffect(() => { loadEntries(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/api/logbook/entries`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title, body, category,
          severity: severity || null,
        }),
        credentials: "include",
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
      setTitle("");
      setBody("");
      loadEntries();
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-semibold text-white">Shop Floor Logbook</h2>

      {/* New Entry Form */}
      <form onSubmit={handleSubmit} className="card p-6 space-y-4">
        <h3 className="text-lg font-medium text-forge-200">New Entry</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="input w-full">
              <option value="note">Note</option>
              <option value="issue">Issue</option>
              <option value="observation">Observation</option>
              <option value="handover">Handover</option>
            </select>
          </div>
          {category === "issue" && (
            <div>
              <label className="label">Severity</label>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="input w-full">
                <option value="">—</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          )}
        </div>
        <div>
          <label className="label">Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className="input w-full" required />
        </div>
        <div>
          <label className="label">Details</label>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} className="input w-full h-24" required />
        </div>
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Saving..." : "Log Entry"}
        </button>
        {error && <div className="text-red-400 text-sm">{error}</div>}
      </form>

      {/* Entry List */}
      <div className="card p-6">
        <h3 className="text-lg font-medium text-forge-200 mb-4">Recent Entries</h3>
        {entries.length === 0 ? (
          <p className="text-forge-400">No entries yet.</p>
        ) : (
          <div className="space-y-3">
            {entries.map((e) => (
              <div key={e.id} className="border border-forge-700 rounded p-3">
                <div className="flex justify-between items-start mb-1">
                  <span className="text-forge-200 font-medium">{e.title}</span>
                  <div className="flex gap-2 items-center">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      e.category === "issue" ? "bg-red-800 text-red-200" :
                      e.category === "handover" ? "bg-blue-800 text-blue-200" :
                      "bg-forge-700 text-forge-300"
                    }`}>
                      {e.category}
                    </span>
                    {e.severity && (
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        e.severity === "critical" ? "bg-red-800 text-red-200" :
                        e.severity === "warning" ? "bg-yellow-800 text-yellow-200" :
                        "bg-forge-700 text-forge-300"
                      }`}>
                        {e.severity}
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-sm text-forge-300">{e.body}</p>
                <div className="text-xs text-forge-500 mt-1">
                  {e.machine_name && `Machine: ${e.machine_name} | `}
                  {new Date(e.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
