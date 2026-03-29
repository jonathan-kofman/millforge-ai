import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";

export default function MachinesPage() {
  const [machines, setMachines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({ name: "", machine_type: "", is_available: true, notes: "" });
  const [formLoading, setFormLoading] = useState(false);
  const [formError, setFormError] = useState(null);
  const [editId, setEditId] = useState(null);

  const fetchMachines = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/machines`, { credentials: "include" });
      if (!res.ok) throw new Error(`${res.status}`);
      setMachines(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchMachines(); }, [fetchMachines]);

  const handleSubmit = async () => {
    setFormError(null);
    if (!formData.name.trim() || !formData.machine_type.trim()) {
      setFormError("Name and machine type are required.");
      return;
    }
    setFormLoading(true);
    try {
      const url = editId ? `${API_BASE}/api/machines/${editId}` : `${API_BASE}/api/machines`;
      const method = editId ? "PATCH" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(formData),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `${res.status}`);
      setShowForm(false);
      setFormData({ name: "", machine_type: "", is_available: true, notes: "" });
      setEditId(null);
      fetchMachines();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setFormLoading(false);
    }
  };

  const handleEdit = (m) => {
    setFormData({ name: m.name, machine_type: m.machine_type, is_available: m.is_available, notes: m.notes || "" });
    setEditId(m.id);
    setShowForm(true);
    setFormError(null);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Remove this machine?")) return;
    await fetch(`${API_BASE}/api/machines/${id}`, { method: "DELETE", credentials: "include" });
    fetchMachines();
  };

  const MACHINE_TYPE_COLORS = {
    VMC:     "bg-blue-900 text-blue-200",
    Lathe:   "bg-green-900 text-green-200",
    EDM:     "bg-purple-900 text-purple-200",
    Grinder: "bg-yellow-900 text-yellow-200",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Machines</h2>
          <p className="text-sm text-gray-400">{machines.length} registered · matched against CAM job requirements</p>
        </div>
        <button className="btn-primary text-sm" onClick={() => { setShowForm(true); setEditId(null); setFormError(null); setFormData({ name: "", machine_type: "", is_available: true, notes: "" }); }}>
          Add Machine
        </button>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {loading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : machines.length === 0 ? (
        <div className="card text-center text-gray-400 text-sm py-12">
          No machines registered. Add your shop floor machines to enable machine-aware scheduling.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {machines.map((m) => {
            const colorClass = MACHINE_TYPE_COLORS[m.machine_type] || "bg-gray-700 text-gray-200";
            return (
              <div key={m.id} className="card flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-white">{m.name}</span>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colorClass}`}>
                      {m.machine_type}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${m.is_available ? "bg-green-900 text-green-300" : "bg-gray-700 text-gray-400"}`}>
                      {m.is_available ? "available" : "unavailable"}
                    </span>
                  </div>
                </div>
                {m.notes && <p className="text-xs text-gray-400">{m.notes}</p>}
                <div className="flex gap-2 text-xs justify-end">
                  <button className="text-gray-400 hover:text-white" onClick={() => handleEdit(m)}>Edit</button>
                  <button className="text-red-500 hover:text-red-400" onClick={() => handleDelete(m.id)}>Remove</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-white">{editId ? "Edit Machine" : "Add Machine"}</h3>
              <button className="text-gray-400 hover:text-white" onClick={() => setShowForm(false)}>✕</button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="label">Machine Name</label>
                <input
                  className="input"
                  placeholder="e.g. Haas VF-2"
                  value={formData.name}
                  onChange={(e) => setFormData(d => ({ ...d, name: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Machine Type</label>
                <input
                  className="input"
                  placeholder="e.g. VMC, Lathe, EDM, Grinder"
                  value={formData.machine_type}
                  onChange={(e) => setFormData(d => ({ ...d, machine_type: e.target.value }))}
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is_available"
                  checked={formData.is_available}
                  onChange={(e) => setFormData(d => ({ ...d, is_available: e.target.checked }))}
                />
                <label htmlFor="is_available" className="label cursor-pointer">Available for scheduling</label>
              </div>
              <div>
                <label className="label">Notes (optional)</label>
                <input
                  className="input"
                  placeholder="e.g. 4th axis installed, max Z 20in"
                  value={formData.notes}
                  onChange={(e) => setFormData(d => ({ ...d, notes: e.target.value }))}
                />
              </div>
            </div>

            {formError && <div className="text-red-400 text-xs">{formError}</div>}

            <div className="flex gap-3 justify-end">
              <button className="btn-secondary text-sm" onClick={() => setShowForm(false)}>Cancel</button>
              <button className="btn-primary text-sm" onClick={handleSubmit} disabled={formLoading}>
                {formLoading ? "Saving…" : editId ? "Update" : "Add Machine"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
