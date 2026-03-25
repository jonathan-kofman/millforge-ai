import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../config";

// Category → dot color
const CATEGORY_COLOR = {
  metals: "#f97316",      // orange
  plastics: "#3b82f6",    // blue
  composites: "#8b5cf6",  // purple
  wood: "#22c55e",        // green
  raw_materials: "#eab308", // yellow
};

function categoryColor(categories) {
  if (!categories || categories.length === 0) return "#f97316";
  return CATEGORY_COLOR[categories[0]] || "#f97316";
}

export default function SupplierMap() {
  const mapRef = useRef(null);
  const mapInstance = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [stats, setStats] = useState(null);
  const [material, setMaterial] = useState("");
  const [loading, setLoading] = useState(false);
  const [empty, setEmpty] = useState(false);

  // Initialize Leaflet map once — delayed so the container has height before L.map reads it
  useEffect(() => {
    const init = () => {
      if (!window.L || mapInstance.current) return;
      mapInstance.current = window.L.map(mapRef.current, {
        center: [39.5, -98.35],
        zoom: 4,
        zoomControl: true,
        scrollWheelZoom: false,
      });
      window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(mapInstance.current);
      mapInstance.current.invalidateSize();
      setMapReady(true);
    };
    const timer = setTimeout(init, 100);
    return () => clearTimeout(timer);
  }, []);

  // Fetch stats
  useEffect(() => {
    fetch(`${API_BASE}/api/suppliers/stats`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setStats(d))
      .catch(() => {});
  }, []);

  // Load suppliers and drop markers
  const loadSuppliers = async (mat) => {
    if (!mapInstance.current) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: 200, verified_only: true });
      if (mat) params.set("material", mat);
      const res = await fetch(`${API_BASE}/api/suppliers?${params}`);
      if (!res.ok) return;
      const data = await res.json();

      // Clear existing markers
      mapInstance.current.eachLayer((layer) => {
        if (layer instanceof window.L.CircleMarker) {
          mapInstance.current.removeLayer(layer);
        }
      });

      setEmpty(data.suppliers.length === 0);

      data.suppliers.forEach((s) => {
        if (s.lat == null || s.lng == null) return;
        const color = categoryColor(s.categories);
        window.L.circleMarker([s.lat, s.lng], {
          radius: 7,
          fillColor: color,
          color: "#1f2937",
          weight: 1,
          opacity: 0.9,
          fillOpacity: 0.85,
        })
          .bindPopup(
            `<b>${s.name}</b><br>${s.city}, ${s.state}<br>` +
            `<span style="color:#9ca3af;font-size:11px">${s.materials.slice(0, 4).join(", ")}</span>`
          )
          .addTo(mapInstance.current);
      });
    } catch {
      // silently ignore
    } finally {
      setLoading(false);
    }
  };

  // Initial load and on material filter change — wait for map to be ready
  useEffect(() => {
    if (!mapReady) return;
    loadSuppliers(material);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, material]);

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      {stats && (
        <div className="flex flex-wrap gap-6 text-sm text-gray-400">
          <span>
            <span className="text-white font-semibold">{stats.verified_suppliers}</span> verified US suppliers
          </span>
          <span>
            <span className="text-white font-semibold">{stats.states_covered}</span> states covered
          </span>
        </div>
      )}

      {/* Material filter */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          className="input max-w-[200px] text-sm"
          placeholder="Filter by material…"
          value={material}
          onChange={(e) => setMaterial(e.target.value)}
        />
        {loading && <span className="text-xs text-gray-500">Loading…</span>}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs text-gray-500">
        {Object.entries(CATEGORY_COLOR).map(([cat, color]) => (
          <span key={cat} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            {cat.replace("_", " ")}
          </span>
        ))}
      </div>

      {/* Map */}
      <div className="relative w-full rounded-lg border border-gray-700 overflow-hidden" style={{ height: "380px" }}>
        <div ref={mapRef} className="w-full h-full" />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/60 z-10">
            <div className="w-6 h-6 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {!loading && empty && (
          <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
            <p className="text-sm text-gray-500">Supplier data loading — check back shortly</p>
          </div>
        )}
      </div>
    </div>
  );
}
