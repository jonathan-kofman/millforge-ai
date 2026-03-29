import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";

const STAGE_COLORS = {
  queued:      "bg-gray-700 text-gray-200",
  in_progress: "bg-blue-900 text-blue-200",
  qc_pending:  "bg-yellow-900 text-yellow-200",
  complete:    "bg-green-900 text-green-200",
  qc_failed:   "bg-red-900 text-red-200",
};

const SOURCE_BADGE = {
  aria_cam: "bg-purple-900 text-purple-200",
  manual:   "bg-gray-800 text-gray-400",
};

const VALID_STAGES = ["queued", "in_progress", "qc_pending", "complete", "qc_failed"];

const EMPTY_CAM = `{
  "schema_version": "1.0",
  "part_id": "ARIA-P-20240101-001",
  "machine_name": "Haas VF-2",
  "tools": [{"tool_number": 1, "description": "3/8 End Mill", "diameter_mm": 9.5}],
  "stock_dims": {"length_mm": 120.0, "width_mm": 60.0, "height_mm": 25.0},
  "cycle_time_min_estimate": 42.5,
  "second_op_required": false,
  "work_offset_recommendation": "G54",
  "fixturing_suggestion": "Kurt vise, jaw width 60mm",
  "generated_at": "2024-01-01T08:00:00",
  "material": "aluminum"
}`;

export default function JobsPage() {
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // CAM import modal
  const [showImport, setShowImport] = useState(false);
  const [camJson, setCamJson] = useState(EMPTY_CAM);
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState(null);
  const [importPreview, setImportPreview] = useState(null);

  // QC submit
  const [qcJobId, setQcJobId] = useState(null);
  const [qcFile, setQcFile] = useState(null);
  const [qcLoading, setQcLoading] = useState(false);
  const [qcResult, setQcResult] = useState(null);
  const [qcError, setQcError] = useState(null);

  // Conflict check
  const [conflictResult, setConflictResult] = useState(null);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/jobs`, { credentials: "include" });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setJobs(data.jobs);
      setTotal(data.total);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);

  // Parse JSON while user types and show preview
  useEffect(() => {
    try {
      const parsed = JSON.parse(camJson);
      setImportPreview(parsed);
      setImportError(null);
    } catch {
      setImportPreview(null);
    }
  }, [camJson]);

  const handleImport = async () => {
    setImportError(null);
    setImportLoading(true);
    try {
      const parsed = JSON.parse(camJson);
      const res = await fetch(`${API_BASE}/api/jobs/import-from-cam`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(parsed),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `${res.status}`);
      setShowImport(false);
      setCamJson(EMPTY_CAM);
      fetchJobs();
    } catch (e) {
      setImportError(e.message);
    } finally {
      setImportLoading(false);
    }
  };

  const handleStageChange = async (jobId, newStage) => {
    const res = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ stage: newStage }),
    });
    if (res.ok) fetchJobs();
  };

  const handleDelete = async (jobId) => {
    if (!window.confirm("Delete this job?")) return;
    await fetch(`${API_BASE}/api/jobs/${jobId}`, {
      method: "DELETE",
      credentials: "include",
    });
    fetchJobs();
  };

  const handleQcSubmit = async () => {
    if (!qcFile || !qcJobId) return;
    setQcLoading(true);
    setQcError(null);
    setQcResult(null);
    try {
      const form = new FormData();
      form.append("image", qcFile);
      const res = await fetch(`${API_BASE}/api/jobs/${qcJobId}/qc-submit`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `${res.status}`);
      setQcResult(data);
      fetchJobs();
    } catch (e) {
      setQcError(e.message);
    } finally {
      setQcLoading(false);
    }
  };

  const checkConflict = async (requiredType) => {
    const res = await fetch(
      `${API_BASE}/api/machines/check-conflict?required_machine_type=${encodeURIComponent(requiredType)}`,
      { credentials: "include" }
    );
    if (res.ok) setConflictResult(await res.json());
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Jobs</h2>
          <p className="text-sm text-gray-400">{total} job{total !== 1 ? "s" : ""} · ARIA CAM imports + manual</p>
        </div>
        <button className="btn-primary text-sm" onClick={() => setShowImport(true)}>
          Import from CAM
        </button>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {/* Job list */}
      {loading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : jobs.length === 0 ? (
        <div className="card text-center text-gray-400 text-sm py-12">
          No jobs yet. Import a CAM setup sheet to get started.
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <div key={job.id} className="card flex flex-col gap-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-white truncate">{job.title}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STAGE_COLORS[job.stage] || "bg-gray-700 text-gray-300"}`}>
                      {job.stage.replace("_", " ")}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${SOURCE_BADGE[job.source] || "bg-gray-800 text-gray-400"}`}>
                      {job.source === "aria_cam" ? "CAM Import" : "manual"}
                    </span>
                  </div>
                  <div className="text-xs text-gray-400 mt-1 flex gap-3 flex-wrap">
                    {job.material && <span>Material: <span className="text-gray-300">{job.material}</span></span>}
                    {job.estimated_duration_minutes && (
                      <span>Cycle: <span className="text-gray-300">{job.estimated_duration_minutes} min</span></span>
                    )}
                    {job.required_machine_type && (
                      <span>
                        Machine: <button
                          className="text-forge-400 hover:text-forge-300 underline"
                          onClick={() => checkConflict(job.required_machine_type)}
                        >
                          {job.required_machine_type}
                        </button>
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {/* Stage selector */}
                  <select
                    value={job.stage}
                    onChange={(e) => handleStageChange(job.id, e.target.value)}
                    className="input text-xs py-1 px-2"
                  >
                    {VALID_STAGES.map((s) => (
                      <option key={s} value={s}>{s.replace("_", " ")}</option>
                    ))}
                  </select>

                  {/* QC submit button when in qc_pending */}
                  {(job.stage === "qc_pending" || job.stage === "in_progress") && (
                    <button
                      className="btn-secondary text-xs"
                      onClick={() => { setQcJobId(job.id); setQcResult(null); setQcError(null); }}
                    >
                      QC Submit
                    </button>
                  )}

                  <button
                    className="text-red-500 hover:text-red-400 text-xs"
                    onClick={() => handleDelete(job.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Inline conflict result */}
              {conflictResult && job.required_machine_type === conflictResult.required_machine_type && (
                <div className={`text-xs p-2 rounded ${conflictResult.conflict ? "bg-red-900/50 text-red-300" : "bg-green-900/50 text-green-300"}`}>
                  {conflictResult.message}
                  <button className="ml-2 underline" onClick={() => setConflictResult(null)}>dismiss</button>
                </div>
              )}

              {/* QC submission form */}
              {qcJobId === job.id && (
                <div className="border-t border-gray-700 pt-3 flex items-center gap-3">
                  <input
                    type="file"
                    accept="image/*"
                    className="input text-xs py-1 flex-1"
                    onChange={(e) => setQcFile(e.target.files[0])}
                  />
                  <button
                    className="btn-primary text-xs"
                    onClick={handleQcSubmit}
                    disabled={qcLoading || !qcFile}
                  >
                    {qcLoading ? "Running…" : "Inspect"}
                  </button>
                  <button className="text-gray-400 text-xs" onClick={() => setQcJobId(null)}>cancel</button>
                </div>
              )}

              {/* QC result */}
              {qcResult && qcJobId === job.id && (
                <div className={`text-xs p-2 rounded ${qcResult.passed ? "bg-green-900/50 text-green-300" : "bg-red-900/50 text-red-300"}`}>
                  {qcResult.passed
                    ? "✓ QC passed — no defects detected"
                    : `✗ QC failed — defects: ${qcResult.defects_found.join(", ")}`}
                </div>
              )}
              {qcError && qcJobId === job.id && (
                <div className="text-xs text-red-400">{qcError}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* CAM Import Modal */}
      {showImport && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-2xl max-h-[90vh] flex flex-col gap-4 overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-white">Import from ARIA CAM</h3>
              <button className="text-gray-400 hover:text-white" onClick={() => setShowImport(false)}>✕</button>
            </div>

            <p className="text-xs text-gray-400">
              Paste the setup sheet JSON exported by ARIA-OS. Schema v1.0 required.
            </p>

            <textarea
              className="input font-mono text-xs resize-none"
              rows={14}
              value={camJson}
              onChange={(e) => setCamJson(e.target.value)}
              spellCheck={false}
            />

            {/* Live preview */}
            {importPreview && (
              <div className="text-xs bg-gray-800 rounded p-3 space-y-1">
                <div className="text-gray-300 font-medium">Preview</div>
                <div className="text-gray-400">Part: <span className="text-white">{importPreview.part_id}</span></div>
                <div className="text-gray-400">Machine: <span className="text-white">{importPreview.machine_name}</span></div>
                <div className="text-gray-400">Cycle time: <span className="text-white">{importPreview.cycle_time_min_estimate} min</span></div>
                {importPreview.material && (
                  <div className="text-gray-400">Material: <span className="text-white">{importPreview.material}</span></div>
                )}
                <div className="text-gray-400">
                  Stock: <span className="text-white">
                    {importPreview.stock_dims?.length_mm} × {importPreview.stock_dims?.width_mm} × {importPreview.stock_dims?.height_mm} mm
                  </span>
                </div>
                <div className="text-gray-400">Tools: <span className="text-white">{importPreview.tools?.length ?? 0}</span></div>
              </div>
            )}

            {importError && (
              <div className="text-red-400 text-xs">{importError}</div>
            )}

            <div className="flex gap-3 justify-end">
              <button className="btn-secondary text-sm" onClick={() => setShowImport(false)}>Cancel</button>
              <button
                className="btn-primary text-sm"
                onClick={handleImport}
                disabled={importLoading || !importPreview}
              >
                {importLoading ? "Importing…" : "Import Job"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
