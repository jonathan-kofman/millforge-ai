import { useState } from "react";
import QuoteForm from "./components/QuoteForm";
import ScheduleViewer from "./components/ScheduleViewer";
import VisionDemo from "./components/VisionDemo";
import ContactForm from "./components/ContactForm";
import OrdersView from "./components/OrdersView";
import AuthModal from "./components/AuthModal";
import BenchmarkDemo from "./components/BenchmarkDemo";
import LightsOutWidget from "./components/LightsOutWidget";
import EnergyWidget from "./components/EnergyWidget";

const PUBLIC_TABS = [
  { id: "quote",    label: "Instant Quote" },
  { id: "schedule", label: "Production Schedule" },
  { id: "vision",   label: "Quality Inspection" },
  { id: "contact",  label: "Get in Touch" },
];

const AUTH_TABS = [
  { id: "orders", label: "My Orders" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("quote");
  const [showAuth, setShowAuth] = useState(false);
  const [user, setUser] = useState(() => {
    try {
      const stored = localStorage.getItem("millforge_user");
      return stored ? JSON.parse(stored) : null;
    } catch { return null; }
  });

  const handleAuthSuccess = (data) => {
    const userData = {
      token: data.access_token,
      email: data.email,
      name: data.name,
      user_id: data.user_id,
    };
    setUser(userData);
    localStorage.setItem("millforge_user", JSON.stringify(userData));
    setShowAuth(false);
    setActiveTab("orders");
  };

  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem("millforge_user");
    setActiveTab("quote");
  };

  const TABS = [...PUBLIC_TABS, ...(user ? AUTH_TABS : [])];

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Header ── */}
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⚙️</span>
            <div>
              <span className="text-xl font-bold text-white tracking-tight">Mill</span>
              <span className="text-xl font-bold text-forge-500 tracking-tight">Forge AI</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {user ? (
              <>
                <span className="text-sm text-gray-400 hidden sm:block">
                  {user.name}
                </span>
                <button onClick={handleLogout} className="btn-secondary text-sm py-1.5">
                  Sign Out
                </button>
              </>
            ) : (
              <button onClick={() => setShowAuth(true)} className="btn-primary text-sm py-1.5">
                Sign In
              </button>
            )}
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="bg-gradient-to-b from-gray-900 to-gray-950 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-16 text-center">
          {/* Pull quote */}
          <div className="max-w-2xl mx-auto mb-10 border-l-4 border-forge-500 pl-5 text-left">
            <p className="text-sm sm:text-base text-gray-300 italic leading-relaxed">
              &ldquo;Ordered 5 months ago. They just told me it&apos;ll be another 2 months. I could&apos;ve grown the aluminum myself.&rdquo;
            </p>
            <p className="mt-2 text-xs text-gray-500">— American manufacturer, 2024</p>
          </div>
          {/* Headline */}
          <h1 className="text-5xl sm:text-6xl font-extrabold text-white mb-4 leading-tight">
            MillForge AI ends the wait.
          </h1>
          {/* Subheadline */}
          <p className="text-base sm:text-lg text-gray-400 max-w-2xl mx-auto">
            AI scheduling that compresses 8 to 30 week lead times — on your existing machines, with your existing staff. No ERP replacement. Deploys in days.
          </p>
        </div>
      </section>

      {/* ── Benchmark demo ── */}
      <div className="bg-gray-950 border-b border-gray-800">
        <BenchmarkDemo />
      </div>

      {/* ── Lights-out readiness widget ── */}
      <div className="bg-gray-950">
        <div className="max-w-6xl mx-auto px-4 pt-10 pb-2">
          <p className="text-sm text-gray-500 text-center">Every milestone removes one more human touchpoint from routine production.</p>
        </div>
        <LightsOutWidget />
      </div>

      {/* ── Why we built this ── */}
      <div className="bg-gray-950 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-16 text-center">
          <p className="text-xs font-semibold tracking-widest text-orange-500 uppercase mb-8">
            Why We Built This
          </p>
          <div className="max-w-[700px] mx-auto space-y-6">
            <p className="text-white text-base sm:text-lg leading-relaxed">
              Building precision parts for aerospace propulsion systems and
              personal projects means ordering metal. And ordering metal in
              America means waiting — weeks, then months, then more months.
              It means routing orders through worse suppliers because the
              better ones are in countries you can&apos;t work with. It means
              watching your timeline collapse because a mill you never spoke
              to, running software designed in the 1990s, put your order
              behind seventeen others with no logic you can see.
            </p>
            <p className="text-[#9ca3af] text-base sm:text-lg leading-relaxed">
              Every machinist Jonathan has worked alongside has the same story.
              The scheduling is broken. The visibility is zero. The software
              doesn&apos;t match the floor. MillForge AI exists because this problem
              is everywhere, it costs real projects real time, and nobody has
              fixed it.
            </p>
          </div>
        </div>
      </div>

      {/* ── Energy intelligence ── */}
      <div className="bg-gray-950 border-b border-gray-800">
        <EnergyWidget />
      </div>

      {/* ── Tab nav ── */}
      <nav className="bg-gray-900 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-5 py-4 text-sm font-medium whitespace-nowrap border-b-2 transition-colors duration-150 ${
                activeTab === tab.id
                  ? "border-forge-500 text-forge-500"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              {tab.label}
              {tab.id === "orders" && (
                <span className="ml-1.5 text-xs bg-forge-500 text-white px-1.5 py-0.5 rounded-full">
                  new
                </span>
              )}
            </button>
          ))}
          {!user && (
            <button
              onClick={() => setShowAuth(true)}
              className="px-5 py-4 text-sm font-medium whitespace-nowrap border-b-2 border-transparent text-gray-600 hover:text-gray-400 transition-colors"
            >
              My Orders
            </button>
          )}
        </div>
      </nav>

      {/* ── Tab content ── */}
      <main className="flex-1 max-w-6xl mx-auto px-4 py-10 w-full">
        {activeTab === "quote"    && <QuoteForm />}
        {activeTab === "schedule" && <ScheduleViewer />}
        {activeTab === "vision"   && <VisionDemo />}
        {activeTab === "contact"  && <ContactForm />}
        {activeTab === "orders"   && user && <OrdersView token={user.token} />}
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-gray-800 bg-gray-950">
        <div className="max-w-6xl mx-auto px-4 py-6 text-center text-xs text-gray-600">
          MillForge AI · 2026 · Built by Jonathan Kofman, Northeastern Advanced Manufacturing
        </div>
      </footer>

      {/* ── Auth Modal ── */}
      {showAuth && (
        <AuthModal
          onSuccess={handleAuthSuccess}
          onClose={() => setShowAuth(false)}
        />
      )}
    </div>
  );
}
