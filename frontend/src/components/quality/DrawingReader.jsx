import { useState, useEffect } from "react";
import { API_BASE } from "../../config";

export default function DrawingReader() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [plan, setPlan] = useState(null);
  const [drawings, setDrawings] = useState([]);
  const [error, setError] = useState(null);

  const loadDrawings = () => {
    fetch(`${API_BASE}/api/quality/drawing`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setDrawings)
      .catch(() => {});
  };

  useEffect(() => { loadDrawings(); }, []);

  const handleUpload = async () => {
    if (!file) return;
    setError(null);
    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/api/quality/drawing/upload`, {
        method: "POST", body: formData, credentials: "include",
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Upload failed");
      setResult(await res.json());
      loadDrawings();
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  const generatePlan = async (drawingId) => {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/quality/drawing/${drawingId}/generate-plan`, {
        method: "POST", credentials: "include",
      });
      if (!res.ok) throw new Error("Plan generation failed");
      setPlan(await res.json());
      loadDrawings();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-semibold text-white">Engineering Drawings & Inspection Plans</h2>

      <div className="card p-6">
        <h3 className="text-lg font-medium text-forge-200 mb-4">Upload Drawing PDF</h3>
        <div className="flex gap-4 items-center">
          <input type="file" accept=".pdf" onChange={(e) => setFile(e.target.files[0])} className="input flex-1" />
          <button onClick={handleUpload} disabled={!file || uploading} className="btn-primary">
            {uploading ? "Uploading..." : "Upload & Extract GD&T"}
          </button>
        </div>
        {error && <div className="mt-2 text-red-400 text-sm">{error}</div>}
      </div>

      {result && (
        <div className="card p-6">
          <h3 className="text-lg font-medium text-forge-200 mb-4">
            Extracted Callouts ({result.callout_count})
          </h3>
          {result.callouts.map((c, i) => (
            <div key={i} className="text-sm text-forge-300 py-1 border-b border-forge-800">
              <span className="text-forge-200 font-medium">{c.feature_id}</span>
              {" "}{c.dimension_type}: {c.nominal} +{c.tolerance_plus}/-{c.tolerance_minus} {c.units}
              {c.datum_refs.length > 0 && <span className="text-forge-400"> (Datum: {c.datum_refs.join(", ")})</span>}
            </div>
          ))}
          <button onClick={() => generatePlan(result.id)} className="btn-primary mt-4">
            Generate Inspection Plan
          </button>
        </div>
      )}

      {plan && (
        <div className="card p-6">
          <h3 className="text-lg font-medium text-forge-200 mb-4">Inspection Plan</h3>
          <p className="text-sm text-forge-400 mb-2">
            Est. time: {plan.total_estimated_time_minutes} min | Instruments: {plan.instruments_required.join(", ")}
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-forge-400 border-b border-forge-700">
                <th className="py-1">#</th><th>Feature</th><th>Method</th><th>Instrument</th><th>Criteria</th>
              </tr>
            </thead>
            <tbody>
              {plan.steps.map((s) => (
                <tr key={s.sequence} className="border-b border-forge-800">
                  <td className="py-1">{s.sequence}</td>
                  <td className="text-forge-200">{s.feature_id}</td>
                  <td className="text-forge-300">{s.measurement_method}</td>
                  <td className="text-forge-300">{s.instrument}</td>
                  <td className="text-forge-400 text-xs">{s.acceptance_criteria}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card p-6">
        <h3 className="text-lg font-medium text-forge-200 mb-4">All Drawings</h3>
        {drawings.length === 0 ? (
          <p className="text-forge-400">No drawings uploaded yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-forge-400 border-b border-forge-700">
                <th className="py-1">File</th><th>Callouts</th><th>Status</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {drawings.map((d) => (
                <tr key={d.id} className="border-b border-forge-800">
                  <td className="py-1 text-forge-200">{d.filename}</td>
                  <td className="text-forge-300">{d.callout_count}</td>
                  <td><span className="px-2 py-0.5 rounded text-xs bg-forge-700 text-forge-300">{d.status}</span></td>
                  <td>
                    <button onClick={() => generatePlan(d.id)} className="text-forge-400 hover:text-white text-xs">
                      Generate Plan
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
