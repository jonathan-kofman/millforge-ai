import { useState } from "react";
import MTRUploader from "./MTRUploader";
import DrawingReader from "./DrawingReader";
import ShopFloorLogbook from "./ShopFloorLogbook";
import AS9100Dashboard from "./AS9100Dashboard";
import QualityOverview from "./QualityOverview";

const QUALITY_SUBTABS = [
  { id: "overview",  label: "Overview" },
  { id: "mtr",       label: "Material Certs" },
  { id: "drawings",  label: "Inspection Plans" },
  { id: "logbook",   label: "Shift Logbook" },
  { id: "as9100",    label: "AS9100 Certification" },
];

export default function QualityHub() {
  const [activeSubTab, setActiveSubTab] = useState("overview");

  return (
    <div className="max-w-6xl mx-auto">
      {/* Sub-tab navigation */}
      <div className="flex gap-1 mb-6 border-b border-gray-800">
        {QUALITY_SUBTABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeSubTab === tab.id
                ? "border-forge-500 text-forge-500"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      {activeSubTab === "overview" && <QualityOverview />}
      {activeSubTab === "mtr" && <MTRUploader />}
      {activeSubTab === "drawings" && <DrawingReader />}
      {activeSubTab === "logbook" && <ShopFloorLogbook />}
      {activeSubTab === "as9100" && <AS9100Dashboard />}
    </div>
  );
}
