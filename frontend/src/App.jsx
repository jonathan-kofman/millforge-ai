import { useState } from "react";
import QuoteForm from "./components/QuoteForm";
import ScheduleViewer from "./components/ScheduleViewer";
import VisionDemo from "./components/VisionDemo";
import ContactForm from "./components/ContactForm";
import OrdersView from "./components/OrdersView";
import AuthModal from "./components/AuthModal";
import BenchmarkDemo from "./components/BenchmarkDemo";

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
              <span className="text-xl font-bold text-forge-500 tracking-tight">Forge</span>
              <span className="ml-2 text-xs bg-forge-500/20 text-forge-500 px-2 py-0.5 rounded-full font-medium">POC</span>
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
        <div className="max-w-6xl mx-auto px-4 py-14 text-center">
          <h1 className="text-4xl sm:text-5xl font-extrabold text-white mb-3">
            MillForge —{" "}
            <span className="text-forge-500">AI scheduling for metal manufacturing</span>
          </h1>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto">
            Same machines. Same staff. From 62% on-time to 94%.
          </p>
        </div>
      </section>

      {/* ── Benchmark demo ── */}
      <div className="bg-gray-950 border-b border-gray-800">
        <BenchmarkDemo />
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
              My Orders 🔒
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
          MillForge Proof of Concept · Not for production use · © 2025
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
