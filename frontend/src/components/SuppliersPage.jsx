import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const CATEGORY_COLORS = {
  metals: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  plastics: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  composites: "bg-green-500/20 text-green-300 border-green-500/30",
  wood: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
};

function SupplierCard({ supplier, distance }) {
  const cats = supplier.categories ?? [];
  return (
    <div className="card hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <p className="font-semibold text-white text-sm">{supplier.name}</p>
          <p className="text-xs text-gray-500">{supplier.city}, {supplier.state}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {supplier.verified && (
            <span className="text-xs bg-green-500/20 text-green-400 border border-green-500/30 px-2 py-0.5 rounded-full">
              verified
            </span>
          )}
          {distance != null && (
            <span className="text-xs text-gray-500">{distance.toFixed(0)} mi</span>
          )}
        </div>
      </div>

      {cats.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {cats.slice(0, 3).map(c => (
            <span key={c} className={`text-xs px-2 py-0.5 rounded-full border ${CATEGORY_COLORS[c] ?? "bg-gray-700 text-gray-300 border-gray-600"}`}>
              {c}
            </span>
          ))}
        </div>
      )}

      {supplier.materials?.length > 0 && (
        <p className="text-xs text-gray-500 truncate">
          {supplier.materials.slice(0, 5).join(" · ")}
        </p>
      )}

      {(supplier.phone || supplier.website) && (
        <div className="flex gap-3 mt-3 pt-3 border-t border-gray-800">
          {supplier.phone && <span className="text-xs text-gray-500">{supplier.phone}</span>}
          {supplier.website && (
            <a
              href={supplier.website.startsWith("http") ? supplier.website : `https://${supplier.website}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-forge-400 hover:text-forge-300"
            >
              Website →
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export default function SuppliersPage() {
  const [stats, setStats] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [results, setResults] = useState([]);
  const [searched, setSearched] = useState(false);
  const [nearbyResults, setNearbyResults] = useState([]);
  const [nearbySearched, setNearbySearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [nearbyLoading, setNearbyLoading] = useState(false);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState("search"); // "search" | "nearby"

  // Search form
  const [searchForm, setSearchForm] = useState({ name: "", material: "", state: "", category: "", verified_only: false });
  // Nearby form
  const [nearbyForm, setNearbyForm] = useState({ lat: "", lng: "", radius_miles: "250", material: "" });
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState(null);

  const handleUseMyLocation = () => {
    if (!navigator.geolocation) { setGeoError("Geolocation not supported by this browser."); return; }
    setGeoLoading(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setNearbyForm(f => ({ ...f, lat: pos.coords.latitude.toFixed(4), lng: pos.coords.longitude.toFixed(4) }));
        setGeoLoading(false);
      },
      () => { setGeoError("Location access denied. Enter coordinates manually."); setGeoLoading(false); }
    );
  };

  useEffect(() => {
    fetch(`${API_BASE}/api/suppliers/stats`)
      .then(r => r.json()).then(setStats).catch(() => {});
    fetch(`${API_BASE}/api/suppliers/materials`)
      .then(r => r.json())
      .then(d => setMaterials(d?.all_materials ?? []))
      .catch(() => {});
  }, []);

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "24" });
      if (searchForm.name) params.set("name", searchForm.name);
      if (searchForm.material) params.set("material", searchForm.material);
      if (searchForm.state) params.set("state", searchForm.state.toUpperCase());
      if (searchForm.category) params.set("category", searchForm.category);
      if (searchForm.verified_only) params.set("verified_only", "true");
      const res = await fetch(`${API_BASE}/api/suppliers?${params}`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      setResults(data.suppliers ?? data ?? []);
      setSearched(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleNearby = async (e) => {
    e.preventDefault();
    setNearbyLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        lat: nearbyForm.lat,
        lng: nearbyForm.lng,
        radius_miles: nearbyForm.radius_miles,
        limit: "20",
      });
      if (nearbyForm.material) params.set("material", nearbyForm.material);
      const res = await fetch(`${API_BASE}/api/suppliers/nearby?${params}`);
      if (!res.ok) throw new Error("Nearby search failed");
      const data = await res.json();
      setNearbyResults(data.results ?? data ?? []);
      setNearbySearched(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setNearbyLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white mb-1">Supplier Directory</h2>
        <p className="text-gray-400 text-sm">
          No human searches for suppliers — MillForge matches your reorder needs to the nearest verified US source automatically.
        </p>
      </div>

      {/* Stats banner */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          {[
            { label: "Total Suppliers", val: stats.total_suppliers?.toLocaleString() },
            { label: "Verified", val: stats.verified_suppliers?.toLocaleString() },
            { label: "States Covered", val: stats.states_covered },
            { label: "Data Sources", val: "PMPA · MSCI · Manual" },
          ].map(s => (
            <div key={s.label} className="bg-gray-800 rounded-lg p-4">
              <p className="text-xs text-gray-500 mb-1">{s.label}</p>
              <p className="text-lg font-bold text-forge-500">{s.val}</p>
            </div>
          ))}
        </div>
      )}

      {/* Mode toggle */}
      <div className="flex gap-2 mb-6">
        {[{ id: "search", label: "Search" }, { id: "nearby", label: "Near Me" }].map(m => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              mode === m.id ? "bg-forge-500 text-white" : "bg-gray-800 text-gray-400 hover:text-white"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {mode === "search" && (
        <>
          <form onSubmit={handleSearch} className="card mb-6">
            <div className="grid sm:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="label">Supplier Name</label>
                <input
                  className="input"
                  placeholder="Ryerson, Olympic Steel…"
                  value={searchForm.name}
                  onChange={e => setSearchForm(f => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Material</label>
                <input
                  className="input"
                  placeholder="steel, aluminum…"
                  value={searchForm.material}
                  onChange={e => setSearchForm(f => ({ ...f, material: e.target.value }))}
                  list="material-list"
                />
                <datalist id="material-list">
                  {materials.slice(0, 40).map(m => <option key={m} value={m} />)}
                </datalist>
              </div>
            </div>
            <div className="grid sm:grid-cols-4 gap-4">
              <div>
                <label className="label">State</label>
                <input
                  className="input"
                  placeholder="OH, MI, TX…"
                  maxLength={2}
                  value={searchForm.state}
                  onChange={e => setSearchForm(f => ({ ...f, state: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Category</label>
                <select
                  className="input"
                  value={searchForm.category}
                  onChange={e => setSearchForm(f => ({ ...f, category: e.target.value }))}
                >
                  <option value="">All categories</option>
                  <option value="metals">Metals</option>
                  <option value="plastics">Plastics</option>
                  <option value="composites">Composites</option>
                  <option value="wood">Wood</option>
                </select>
              </div>
              <div className="flex flex-col justify-end col-span-2">
                <label className="flex items-center gap-2 text-sm text-gray-400 mb-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={searchForm.verified_only}
                    onChange={e => setSearchForm(f => ({ ...f, verified_only: e.target.checked }))}
                    className="accent-forge-500"
                  />
                  Verified only
                </label>
                <button type="submit" disabled={loading} className="btn-primary">
                  {loading ? "Searching…" : "Search"}
                </button>
              </div>
            </div>
          </form>

          {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

          {results.length > 0 ? (
            <div>
              <p className="text-sm text-gray-500 mb-3">{results.length} results</p>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {results.map(s => <SupplierCard key={s.id} supplier={s} />)}
              </div>
            </div>
          ) : searched && !loading && (
            <div className="card text-center py-10 text-gray-500 text-sm">
              No suppliers found. Try broadening your search or removing filters.
            </div>
          )}
        </>
      )}

      {mode === "nearby" && (
        <>
          <form onSubmit={handleNearby} className="card mb-6">
            <div className="flex items-center justify-between mb-4">
              <p className="text-xs text-gray-500">Find verified suppliers within a radius of your location.</p>
              <button
                type="button"
                onClick={handleUseMyLocation}
                disabled={geoLoading}
                className="text-xs text-forge-400 border border-forge-500/40 rounded px-3 py-1.5 hover:bg-forge-500/10 transition-colors disabled:opacity-50"
              >
                {geoLoading ? "Detecting…" : "Use My Location"}
              </button>
            </div>
            {geoError && <p className="text-xs text-red-400 mb-3">{geoError}</p>}
            <div className="grid sm:grid-cols-4 gap-4">
              <div>
                <label className="label">Latitude</label>
                <input
                  className="input"
                  placeholder="e.g. 41.49"
                  value={nearbyForm.lat}
                  onChange={e => setNearbyForm(f => ({ ...f, lat: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Longitude</label>
                <input
                  className="input"
                  placeholder="e.g. -81.69"
                  value={nearbyForm.lng}
                  onChange={e => setNearbyForm(f => ({ ...f, lng: e.target.value }))}
                />
              </div>
              <div>
                <label className="label">Radius (miles)</label>
                <input
                  className="input"
                  type="number"
                  min="1"
                  value={nearbyForm.radius_miles}
                  onChange={e => setNearbyForm(f => ({ ...f, radius_miles: e.target.value }))}
                />
              </div>
              <div className="flex flex-col justify-end gap-2">
                <div>
                  <label className="label">Material (optional)</label>
                  <input
                    className="input"
                    placeholder="steel…"
                    value={nearbyForm.material}
                    onChange={e => setNearbyForm(f => ({ ...f, material: e.target.value }))}
                  />
                </div>
              </div>
            </div>
            <button type="submit" disabled={nearbyLoading} className="btn-primary mt-4">
              {nearbyLoading ? "Searching…" : "Find Nearby Suppliers"}
            </button>
          </form>

          {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

          {nearbyResults.length > 0 ? (
            <div>
              <p className="text-sm text-gray-500 mb-3">{nearbyResults.length} suppliers found, sorted by distance</p>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {nearbyResults.map(item => {
                  const supplier = item.supplier ?? item;
                  const distance = item.distance_miles ?? null;
                  return <SupplierCard key={supplier.id} supplier={supplier} distance={distance} />;
                })}
              </div>
            </div>
          ) : nearbySearched && !nearbyLoading && (
            <div className="card text-center py-10 text-gray-500 text-sm">
              No suppliers found within that radius. Try expanding the search area.
            </div>
          )}
        </>
      )}
    </div>
  );
}
