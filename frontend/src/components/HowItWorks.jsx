import { UploadCloud, ScanSearch, CalendarClock, PackageCheck } from "lucide-react";

const STEPS = [
  {
    icon: UploadCloud,
    num: "01",
    title: "Upload Orders",
    desc: "Paste in your pending jobs or connect your order backlog. CSV, JSON, or manual entry.",
  },
  {
    icon: ScanSearch,
    num: "02",
    title: "Anomaly Scan",
    desc: "MillForge flags duplicate IDs, impossible deadlines, and quantity spikes before they hit the floor.",
  },
  {
    icon: CalendarClock,
    num: "03",
    title: "AI Scheduling",
    desc: "Simulated annealing optimizer sequences every job. 96.4% on-time on the benchmark dataset.",
  },
  {
    icon: PackageCheck,
    num: "04",
    title: "Deliver & Learn",
    desc: "Live Gantt chart, PDF export, energy-aware timing windows. Feedback loop calibrates future runs.",
  },
];

export default function HowItWorks() {
  return (
    <section className="bg-gray-950 border-b border-gray-800">
      <div className="max-w-6xl mx-auto px-4 py-16">
        <p className="text-xs font-bold tracking-widest text-forge-500 uppercase text-center mb-3">
          How It Works
        </p>
        <h2 className="text-2xl sm:text-3xl font-extrabold text-white text-center mb-12 tracking-tight">
          From backlog chaos to scheduled production in minutes.
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 relative">
          {/* Connector line — desktop only */}
          <div className="hidden lg:block absolute top-8 left-[12.5%] right-[12.5%] h-px bg-gradient-to-r from-transparent via-gray-700 to-transparent" />
          {STEPS.map(({ icon: Icon, num, title, desc }) => (
            <div key={num} className="flex flex-col items-center text-center relative">
              <div className="w-16 h-16 rounded-2xl bg-gray-800 border border-gray-700 flex items-center justify-center mb-4 relative z-10">
                <Icon className="w-7 h-7 text-forge-500" />
              </div>
              <span className="text-xs font-bold text-gray-600 mb-1">{num}</span>
              <h3 className="text-sm font-bold text-white mb-2">{title}</h3>
              <p className="text-xs text-gray-500 leading-relaxed max-w-[200px]">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
