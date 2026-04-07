import { useState, useEffect } from "react";
import { API_BASE } from "../../config";

export default function MTRUploader() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [mtrs, setMtrs] = useState([]);
  const [error, setError] = useState(null);

  const loadMTRs = () => {
    fetch(`${API_BASE}/api/quality/mtr`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : []))
      .then(setMtrs)
      .catch(() => {});
  };

  useEffect(() => { loadMTRs(); }, []);

  const handleUpload = async () => {
    if (!file) return;
    setError(null);
    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/api/quality/mtr/upload`, {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Upload failed");
      }
      const data = await res.json();
      setResult(data);
      loadMTRs();
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  const handleVerify = async (mtrId) => {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/quality/mtr/${mtrId}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
        credentials: "include",
      });
      if (!res.ok) throw new Error("Verification failed");
      const data = await res.json();
      setResult(data);
      loadMTRs();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-semibold text-white">Mill Test Reports (MTR)</h2>

      {/* Upload */}
      <div className="card p-6">
        <h3 className="text-lg font-medium text-forge-200 mb-4">Upload MTR PDF</h3>
        <div className="flex gap-4 items-center">
          <input
            type="file"
            accept=".pdf"
            onChange={(e) => setFile(e.target.files[0])}
            className="input flex-1"
          />
          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="btn-primary"
          >
            {uploading ? "Uploading..." : "Upload & Extract"}
          </button>
        </div>
        {error && <div className="mt-2 text-red-400 text-sm">{error}</div>}
      </div>

      {/* Extraction Result */}
      {result && result.chemistry && (
        <div className="card p-6">
          <h3 className="text-lg font-medium text-forge-200 mb-4">Extraction Result</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-forge-400">Spec: {result.material_spec || "N/A"}</p>
              <p className="text-sm text-forge-400">Heat #: {result.heat_number || "N/A"}</p>
              <p className="text-sm text-forge-400">Status: {result.verification_status}</p>
            </div>
            <div>
              <p className="text-sm text-forge-400 font-medium">Chemistry</p>
              {Object.entries(result.chemistry).map(([el, val]) => (
                <span key={el} className="text-xs text-forge-300 mr-3">
                  {el}: {val}%
                </span>
              ))}
            </div>
          </div>
          {result.verification_status === "pending" && (
            <button onClick={() => handleVerify(result.id)} className="btn-primary mt-4">
              Verify Against Spec
            </button>
          )}
        </div>
      )}

      {/* Verification Result */}
      {result && result.details && (
        <div className="card p-6">
          <h3 className="text-lg font-medium text-forge-200 mb-4">
            Verification: {result.overall_pass ? "PASS" : "FAIL"}
          </h3>
          <p className="text-sm text-forge-400 mb-2">Spec: {result.spec_used}</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-forge-400 border-b border-forge-700">
                <th className="py-1">Property</th>
                <th>Actual</th>
                <th>Min</th>
                <th>Max</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {result.details.map((d, i) => (
                <tr key={i} className="border-b border-forge-800">
                  <td className="py-1 text-forge-200">{d.property_name}</td>
                  <td>{d.actual_value} {d.unit}</td>
                  <td>{d.spec_min ?? "—"}</td>
                  <td>{d.spec_max ?? "—"}</td>
                  <td className={d.passed ? "text-green-400" : "text-red-400"}>
                    {d.passed ? "PASS" : "FAIL"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* MTR List */}
      <div className="card p-6">
        <h3 className="text-lg font-medium text-forge-200 mb-4">All Material Certs</h3>
        {mtrs.length === 0 ? (
          <p className="text-forge-400">No MTRs uploaded yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-forge-400 border-b border-forge-700">
                <th className="py-1">File</th>
                <th>Heat #</th>
                <th>Spec</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {mtrs.map((m) => (
                <tr key={m.id} className="border-b border-forge-800">
                  <td className="py-1 text-forge-200 truncate max-w-[200px]">{m.filename}</td>
                  <td className="text-forge-300">{m.heat_number || "—"}</td>
                  <td className="text-forge-300">{m.material_spec || "—"}</td>
                  <td>
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      m.verification_status === "pass" ? "bg-green-800 text-green-200" :
                      m.verification_status === "fail" ? "bg-red-800 text-red-200" :
                      "bg-yellow-800 text-yellow-200"
                    }`}>
                      {m.verification_status}
                    </span>
                  </td>
                  <td>
                    {m.verification_status === "pending" && (
                      <button onClick={() => handleVerify(m.id)} className="text-forge-400 hover:text-white text-xs">
                        Verify
                      </button>
                    )}
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
