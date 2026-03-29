import { useState, useEffect } from "react";
import QuoteForm from "./components/QuoteForm";
import ScheduleViewer from "./components/ScheduleViewer";
import VisionDemo from "./components/VisionDemo";
import ContactForm from "./components/ContactForm";
import OrdersView from "./components/OrdersView";
import AuthModal from "./components/AuthModal";
import BenchmarkDemo from "./components/BenchmarkDemo";
import LightsOutWidget from "./components/LightsOutWidget";
import EnergyWidget from "./components/EnergyWidget";
import SupplierMap from "./components/SupplierMap";
import OnboardingWizard from "./components/OnboardingWizard";
import Discovery from "./pages/Discovery";
import JobsPage from "./components/JobsPage";
import MachinesPage from "./components/MachinesPage";
import QCAnalyticsPage from "./components/QCAnalyticsPage";
import { API_BASE } from "./config";

const PUBLIC_TABS = [
  { id: "quote",    label: "Instant Quote" },
  { id: "schedule", label: "Production Schedule" },
  { id: "vision",   label: "Quality Inspection" },
  { id: "contact",  label: "Get in Touch" },
];

const AUTH_TABS = [
  { id: "orders",    label: "My Orders" },
  { id: "jobs",      label: "Jobs" },
  { id: "machines",  label: "Machines" },
  { id: "analytics", label: "Analytics" },
  { id: "discovery", label: "Discovery" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("quote");
  const [showAuth, setShowAuth] = useState(false);
  const [supplierStats, setSupplierStats] = useState(null);
  const [onboardingStatus, setOnboardingStatus] = useState(null);
  const [showWizard, setShowWizard] = useState(false);
  const [user, setUser] = useState(null);
  const [navOpen, setNavOpen] = useState(false);
  const [captureEmail, setCaptureEmail] = useState("");
  const [captureSubmitted, setCaptureSubmitted] = useState(false);
  const [captureLoading, setCaptureLoading] = useState(false);

  const fetchOnboardingStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/onboarding/status`, {
        credentials: "include",
      });
      if (!res.ok) return;
      const data = await res.json();
      setOnboardingStatus(data);
      if (!data.is_complete) setShowWizard(true);
    } catch {}
  };

  const handleAuthSuccess = (data) => {
    setUser({ email: data.email, name: data.name, user_id: data.user_id });
    setShowAuth(false);
    setActiveTab("orders");
    fetchOnboardingStatus();
  };

  const handleEmailCapture = async (e) => {
    e.preventDefault();
    setCaptureLoading(true);
    try {
      await fetch(`${API_BASE}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: captureEmail, email: captureEmail, message: "Requested sample report", source: "email_capture" }),
      });
    } catch {}
    setCaptureSubmitted(true);
    setCaptureLoading(false);
  };

  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
    setNavOpen(false);
  };

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {}
    setUser(null);
    setOnboardingStatus(null);
    setShowWizard(false);
    setActiveTab("quote");
  };

  // Restore session from httpOnly cookie on page load
  useEffect(() => {
    fetch(`${API_BASE}/api/auth/me`, { credentials: "include" })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) {
          setUser({ email: data.email, name: data.name, user_id: data.user_id });
          fetchOnboardingStatus();
        }
      })
      .catch(() => {});
    fetch(`${API_BASE}/api/suppliers/stats`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setSupplierStats(d))
      .catch(() => {});
  }, []);

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

          {/* Desktop nav links */}
          <nav className="hidden sm:flex items-center gap-6">
            <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-400 hover:text-white transition-colors">How It Works</button>
            <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-400 hover:text-white transition-colors">Demo</button>
            <button onClick={() => scrollTo("suppliers-section")} className="text-sm text-gray-400 hover:text-white transition-colors">Suppliers</button>
            <button onClick={() => { setActiveTab("contact"); scrollTo("tab-nav"); }} className="text-sm text-gray-400 hover:text-white transition-colors">Contact</button>
          </nav>

          <div className="flex items-center gap-3">
            {/* Mobile hamburger */}
            <button
              className="sm:hidden text-gray-400 hover:text-white text-xl leading-none"
              onClick={() => setNavOpen(v => !v)}
              aria-label="Toggle menu"
            >
              {navOpen ? "✕" : "☰"}
            </button>
            {user ? (
              <>
                <span className="text-sm text-gray-400 hidden sm:block">{user.name}</span>
                <button onClick={handleLogout} className="btn-secondary text-sm py-1.5">Sign Out</button>
              </>
            ) : (
              <button onClick={() => setShowAuth(true)} className="btn-primary text-sm py-1.5">Sign In</button>
            )}
          </div>
        </div>

        {/* Mobile nav dropdown */}
        {navOpen && (
          <div className="sm:hidden border-t border-gray-800 bg-gray-950">
            <div className="max-w-6xl mx-auto px-4 py-3 flex flex-col gap-3">
              <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-400 hover:text-white text-left transition-colors">How It Works</button>
              <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-400 hover:text-white text-left transition-colors">Demo</button>
              <button onClick={() => scrollTo("suppliers-section")} className="text-sm text-gray-400 hover:text-white text-left transition-colors">Suppliers</button>
              <button onClick={() => { setActiveTab("contact"); scrollTo("tab-nav"); }} className="text-sm text-gray-400 hover:text-white text-left transition-colors">Contact</button>
            </div>
          </div>
        )}
      </header>

      {/* ── Hero ── */}
      <section className="bg-gradient-to-b from-gray-900 to-gray-950 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-16 text-center">
          {/* ICP */}
          <p className="text-sm sm:text-base text-forge-400 font-medium mb-3">
            For CNC job shops and metal mills drowning in backlog and rush orders.
          </p>
          {/* Headline */}
          <h1 className="text-5xl sm:text-6xl font-extrabold text-white mb-4 leading-tight">
            MillForge AI ends the wait.
          </h1>
          {/* Subheadline */}
          <p className="text-lg sm:text-xl text-gray-200 font-semibold max-w-2xl mx-auto mb-3">
            AI scheduler that lifts on-time delivery from 60% to 95%+<br className="hidden sm:block" /> using your existing machines and staff.
          </p>
          <p className="text-sm text-gray-500 max-w-xl mx-auto mb-2">
            Not an ERP. Not a quoting portal. Not a CAM package.
          </p>
          <p className="text-sm text-gray-500 max-w-xl mx-auto mb-8">
            It&apos;s a scheduling layer that sits on top of whatever you already use.
          </p>
          {/* Primary CTA */}
          <a
            href="https://calendly.com/jonkofm/30min"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block bg-forge-500 hover:bg-forge-600 text-white font-bold px-8 py-4 rounded-xl text-base transition-colors duration-150 shadow-lg"
          >
            Book a 30-minute floor review →
          </a>
          <p className="text-xs text-gray-600 mt-3 mb-8">
            No commitment. We run your order history through MillForge and show you the on-time delta.
          </p>

          {/* Email capture — lower-friction CTA */}
          <div className="mb-10">
            <p className="text-xs text-gray-500 mb-3">Not ready for a call?</p>
            {captureSubmitted ? (
              <p className="text-sm text-forge-400">Got it — we&apos;ll send the sample report shortly.</p>
            ) : (
              <form onSubmit={handleEmailCapture} className="flex flex-col sm:flex-row items-center justify-center gap-2 max-w-md mx-auto">
                <input
                  type="email"
                  required
                  value={captureEmail}
                  onChange={e => setCaptureEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-forge-500 focus:border-transparent text-sm w-full sm:w-auto"
                />
                <button
                  type="submit"
                  disabled={captureLoading}
                  className="bg-gray-700 hover:bg-gray-600 text-white font-semibold px-5 py-2.5 rounded-lg text-sm transition-colors whitespace-nowrap disabled:opacity-50"
                >
                  {captureLoading ? "Sending…" : "Get a sample report →"}
                </button>
              </form>
            )}
          </div>

          {/* Pull quote — social proof below CTA */}
          <div className="max-w-2xl mx-auto border-l-4 border-forge-500 pl-5 text-left">
            <p className="text-sm sm:text-base text-gray-300 italic leading-relaxed">
              &ldquo;Ordered 5 months ago. They just told me it&apos;ll be another 2 months. I could&apos;ve grown the aluminum myself.&rdquo;
            </p>
            <p className="mt-2 text-xs text-gray-500">— American manufacturer, 2024</p>
          </div>
        </div>
      </section>

      {/* ── Benchmark demo ── */}
      <div id="benchmark-section" className="bg-gray-950 border-b border-gray-800">
        <BenchmarkDemo />
      </div>

      {/* ── Social proof / micro-case ── */}
      <div className="bg-gray-950 border-b border-gray-800">
        <div className="max-w-4xl mx-auto px-4 py-14 text-center">
          <p className="text-xs font-bold tracking-widest text-orange-500 uppercase mb-6">
            In a Simulated 3-Machine Mill
          </p>
          <p className="text-gray-400 text-sm mb-6">
            3 anchor orders. 4 rush orders. Mixed steel, aluminum, titanium.
          </p>
          <div className="flex flex-wrap justify-center gap-8 mb-8">
            <div className="text-center">
              <p className="text-4xl font-extrabold text-gray-500">60.7%</p>
              <p className="text-xs text-gray-600 mt-1">Before MillForge: 60.7% on-time</p>
            </div>
            <div className="text-center">
              <p className="text-4xl font-extrabold text-orange-400">96.4%</p>
              <p className="text-xs text-gray-500 mt-1">After MillForge: 96.4% on-time</p>
            </div>
          </div>
          <p className="text-xs text-gray-600 mb-8">
            Same week. Same staff. Based on simulated 28-order dataset — results vary by shop configuration.
          </p>
          <div className="max-w-xl mx-auto border-l-4 border-forge-500 pl-5 text-left">
            <p className="text-sm text-gray-300 italic leading-relaxed">
              &ldquo;The scheduling is broken. The visibility is zero. The software doesn&apos;t match the floor.&rdquo;
            </p>
            <p className="mt-2 text-xs text-gray-500">— Machine shop operator feedback</p>
          </div>
        </div>
      </div>

      {/* ── Lights-out readiness widget ── */}
      <div className="bg-gray-950">
        <div className="max-w-6xl mx-auto px-4 pt-10 pb-2">
          <p className="text-sm text-gray-500 text-center">Every milestone removes one more human touchpoint from routine production.</p>
        </div>
        <LightsOutWidget />
      </div>

      {/* ── Pricing anchor ── */}
      <div className="bg-gray-950 border-b border-gray-800">
        <div className="max-w-3xl mx-auto px-4 py-14 text-center">
          <p className="text-sm font-bold tracking-widest text-orange-500 uppercase mb-4">Pricing</p>
          <h2 className="text-2xl sm:text-3xl font-extrabold text-white mb-6">Simple, transparent pricing.</h2>
          <p className="text-gray-300 text-base mb-2">Starts at <span className="text-white font-semibold">$299/month</span> for shops with up to 10 machines.</p>
          <p className="text-gray-400 text-sm mb-2">Scales with shop size. Most customers see ROI within 30 days.</p>
          <p className="text-gray-500 text-sm mb-8">No implementation fees. No ERP replacement. Cancel anytime.</p>
          <a
            href="https://calendly.com/jonkofm/30min"
            target="_blank"
            rel="noopener noreferrer"
            className="text-forge-400 hover:text-forge-300 text-sm font-medium transition-colors"
          >
            → Book a call to discuss your shop&apos;s specific needs
          </a>
        </div>
      </div>

      {/* ── Why we built this ── */}
      <div id="how-it-works" className="bg-gray-950 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-16 text-center">
          <p className="text-sm font-bold tracking-widest text-orange-500 uppercase mb-8">
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
      <div className="bg-gray-900 border-b border-gray-800">
        <EnergyWidget />
      </div>

      {/* ── Supplier sourcing section ── */}
      <div id="suppliers-section" className="bg-gray-900 border-b border-gray-800">
        <div className="max-w-6xl mx-auto px-4 py-16">
          <p className="text-sm font-bold tracking-widest text-orange-500 uppercase mb-4 text-center">
            Materials Sourcing
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold text-white text-center mb-3">
            Find materials. Schedule production. Ship faster.
          </h2>
          <p className="text-gray-400 text-center max-w-xl mx-auto mb-10">
            MillForge connects your schedule to verified US suppliers — so when stock runs low, a purchase order with the nearest qualified source is one click away.
          </p>
          <div className="grid sm:grid-cols-2 gap-10 items-start">
            {/* Left: sourcing problem copy */}
            <div className="space-y-5">
              <h3 className="text-lg font-semibold text-white">The sourcing problem</h3>
              <p className="text-gray-400 text-sm leading-relaxed">
                American mills lose weeks to supplier search. When a material runs short, a floor manager calls three distributors, waits for callbacks, manually compares lead times, and enters a PO by hand. The scheduling software doesn't know any of this is happening.
              </p>
              <p className="text-gray-400 text-sm leading-relaxed">
                MillForge's inventory agent watches stock in real time. When a reorder point is hit, it surfaces the nearest verified supplier for that material — filtered by distance, category, and current schedule — and generates the purchase order automatically. No calls. No callbacks. No delays.
              </p>
              <button
                onClick={() => setActiveTab("contact")}
                className="btn-secondary text-sm mt-2"
              >
                Submit a supplier →
              </button>
            </div>
            {/* Right: map */}
            <div>
              <SupplierMap />
            </div>
          </div>
        </div>
      </div>

      {/* ── Tab nav ── */}
      <nav id="tab-nav" className="bg-gray-900 border-b border-gray-800">
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
        {activeTab === "discovery" && user && <Discovery />}
        {activeTab === "jobs"     && user && <JobsPage />}
        {activeTab === "machines" && user && <MachinesPage />}
        {activeTab === "analytics" && user && <QCAnalyticsPage />}
        {activeTab === "orders"   && user && (
          <>
            {onboardingStatus?.configured && !onboardingStatus?.is_complete && !showWizard && (
              <div className="mb-5 flex items-center justify-between bg-forge-500/10 border border-forge-500/30 rounded-lg px-4 py-3">
                <p className="text-sm text-forge-400">Your shop setup is incomplete.</p>
                <button
                  className="text-xs font-medium text-forge-400 hover:text-forge-300 border border-forge-500/40 rounded px-3 py-1.5 transition-colors"
                  onClick={() => setShowWizard(true)}
                >
                  Complete setup →
                </button>
              </div>
            )}
            <OrdersView />
          </>
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-gray-800 bg-gray-950">
        <div className="max-w-6xl mx-auto px-4 py-6 text-center text-xs text-gray-600">
          MillForge AI · 2026 · Built by Jonathan Kofman ·{" "}
          <a
            href="https://www.linkedin.com/in/jonathan-kofman/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-500 hover:text-gray-300 transition-colors"
          >
            LinkedIn →
          </a>
        </div>
      </footer>

      {/* ── Auth Modal ── */}
      {showAuth && (
        <AuthModal
          onSuccess={handleAuthSuccess}
          onClose={() => setShowAuth(false)}
        />
      )}

      {/* ── Onboarding Wizard ── */}
      {showWizard && user && (
        <OnboardingWizard
          onComplete={() => {
            setShowWizard(false);
            setOnboardingStatus((s) => ({ ...s, is_complete: true, configured: true }));
          }}
          onSkip={() => {
            setShowWizard(false);
            setOnboardingStatus((s) => ({ ...s, configured: true }));
          }}
        />
      )}
    </div>
  );
}
