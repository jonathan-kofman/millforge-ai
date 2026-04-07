import { CheckCircle } from "lucide-react";

const BADGES = [
  "AS9100D Ready",
  "ISO 9001 Compatible",
  "ITAR Anomaly Gate",
  "EIA Grid Pricing",
  "NEU-DET Vision (mAP 0.76)",
];

export default function TrustBar() {
  return (
    <div className="bg-gray-950 border-b border-gray-800">
      <div className="max-w-6xl mx-auto px-4 py-6">
        <div className="flex flex-wrap justify-center gap-3">
          {BADGES.map((b) => (
            <span
              key={b}
              className="flex items-center gap-1.5 border border-gray-700 rounded-full px-4 py-1.5 text-xs text-gray-400"
            >
              <CheckCircle className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
              {b}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
