import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const STATUS_CONFIG = {
  automated:  { label: "automated",  dot: "bg-green-500",  text: "text-green-400" },
  pretrained: { label: "pretrained", dot: "bg-blue-500",   text: "text-blue-400"  },
  mock:       { label: "mock",       dot: "bg-yellow-500", text: "text-yellow-400" },
};

const TOUCHPOINT_LABELS = {
  scheduling:           "Scheduling",
  quoting:              "Quoting",
  quality_inspection:   "Quality Inspection",
  energy_optimization:  "Energy Optimization",
  inventory_management: "Inventory Management",
  production_planning:  "Production Planning",
  rework_dispatch:      "Rework Dispatch",
};

export default function LightsOutWidget() {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(r => r.json())
      .then(setData)
      .catch(() => {});
  }, []);

  if (!data?.lights_out_readiness) return null;

  const { lights_out_readiness, readiness_percent, automated_touchpoints, total_touchpoints } = data;

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 border-b border-gray-800">
      <div className="flex flex-col sm:flex-row sm:items-center gap-6">
        {/* Progress bar block */}
        <div className="flex-shrink-0 w-full sm:w-56">
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="text-sm font-semibold text-white">
              Lights-out readiness
            </span>
            <span className="text-lg font-bold text-forge-500">{readiness_percent}%</span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-forge-500 rounded-full transition-all duration-700"
              style={{ width: `${readiness_percent}%` }}
            />
          </div>
          <p className="text-xs text-gray-600 mt-1.5">
            {automated_touchpoints} of {total_touchpoints} touchpoints automated
          </p>
          <p className="text-xs text-gray-600 mt-0.5">
            Each milestone removes one more human from routine production.
          </p>
        </div>

        {/* Checklist */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-2 flex-1">
          {Object.entries(lights_out_readiness).map(([key, status]) => {
            const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.mock;
            return (
              <div key={key} className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
                <span className="text-xs text-gray-400 truncate">
                  {TOUCHPOINT_LABELS[key] || key}
                </span>
              </div>
            );
          })}
        </div>

        {/* Legend */}
        <div className="flex-shrink-0 flex flex-row sm:flex-col gap-3 text-xs">
          {Object.entries(STATUS_CONFIG).map(([k, v]) => (
            <div key={k} className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${v.dot}`} />
              <span className={v.text}>{v.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
