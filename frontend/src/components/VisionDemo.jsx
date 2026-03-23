import { useState } from "react";

const DEMO_IMAGES = [
  { label: "Steel Plate",     url: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400" },
  { label: "Aluminum Rod",    url: "https://images.unsplash.com/photo-1565193566173-7a0ee3dbe261?w=400" },
  { label: "Titanium Billet", url: "https://images.unsplash.com/photo-1581092160607-ee22731c9c96?w=400" },
];

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];

export default function VisionDemo() {
  const [imageUrl, setImageUrl] = useState(DEMO_IMAGES[0].url);
  const [material, setMaterial] = useState("steel");
  const [orderId, setOrderId] = useState("ORD-001");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleInspect = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/vision/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_url: imageUrl, material, order_id: orderId }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Inspection failed");
      }
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-2">Quality Inspection</h2>
      <p className="text-gray-400 mb-8">
        Simulate AI-driven visual quality inspection. In production, this calls a fine-tuned
        computer vision model. Currently returns a simulated assessment.
      </p>

      <div className="grid sm:grid-cols-2 gap-6">
        {/* Controls */}
        <div className="card space-y-4">
          <div>
            <label className="label">Demo Images</label>
            <div className="space-y-2">
              {DEMO_IMAGES.map((img) => (
                <button
                  key={img.url}
                  onClick={() => setImageUrl(img.url)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                    imageUrl === img.url
                      ? "bg-forge-500/20 text-forge-400 border border-forge-500/40"
                      : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                  }`}
                >
                  {img.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="label">Or enter image URL</label>
            <input
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
              className="input text-xs"
              placeholder="https://..."
            />
          </div>

          <div>
            <label className="label">Material</label>
            <select
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
              className="input"
            >
              {MATERIALS.map((m) => (
                <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Order ID (optional)</label>
            <input
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
              className="input"
              placeholder="ORD-001"
            />
          </div>

          <button onClick={handleInspect} className="btn-primary w-full" disabled={loading}>
            {loading ? "Inspecting…" : "Run Inspection"}
          </button>
        </div>

        {/* Preview + Result */}
        <div className="space-y-4">
          <div className="card p-0 overflow-hidden">
            <img
              src={imageUrl}
              alt="Part to inspect"
              className="w-full h-48 object-cover"
              onError={(e) => { e.target.src = "https://placehold.co/400x200?text=Image+not+found"; }}
            />
          </div>

          {error && (
            <div className="p-4 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
              {error}
            </div>
          )}

          {result && (
            <div className={`card border ${result.passed ? "border-green-700" : "border-red-700"}`}>
              <div className="flex items-center gap-3 mb-4">
                <span className={`text-3xl`}>{result.passed ? "✅" : "❌"}</span>
                <div>
                  <p className={`text-lg font-bold ${result.passed ? "text-green-400" : "text-red-400"}`}>
                    {result.passed ? "PASSED" : "FAILED"}
                  </p>
                  <p className="text-xs text-gray-500">
                    Confidence: {(result.confidence * 100).toFixed(1)}%
                  </p>
                </div>
              </div>

              {result.defects_detected.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs text-gray-500 mb-1">Defects detected:</p>
                  <div className="flex flex-wrap gap-1">
                    {result.defects_detected.map((d) => (
                      <span key={d} className="text-xs bg-red-900/50 text-red-300 px-2 py-0.5 rounded-full">
                        {d.replace(/_/g, " ")}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <p className="text-sm text-gray-300">{result.recommendation}</p>

              <p className="text-xs text-gray-600 mt-3">
                Inspector: {result.inspector_version}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
