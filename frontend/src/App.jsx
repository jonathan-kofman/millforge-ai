import { useState, useEffect, useRef, lazy, Suspense } from "react";
import { Cog, Menu, X, ChevronDown } from "lucide-react";
import HowItWorks from "./components/HowItWorks";
import TrustBar from "./components/TrustBar";
import AnimatedCounter from "./components/AnimatedCounter";
import QuoteForm from "./components/QuoteForm";
import ScheduleViewer from "./components/ScheduleViewer";
import VisionDemo from "./components/VisionDemo";
import ContactForm from "./components/ContactForm";
import AuthModal from "./components/AuthModal";
import BenchmarkDemo from "./components/BenchmarkDemo";
import LightsOutWidget from "./components/LightsOutWidget";
import EnergyWidget from "./components/EnergyWidget";
import OnboardingWizard from "./components/OnboardingWizard";
import PricingPage from "./components/PricingPage";
import EnergyPage from "./components/EnergyPage";
import SuppliersPage from "./components/SuppliersPage";
import DemoChainPage from "./components/DemoChainPage";
import { API_BASE } from "./config";

// Auth-only pages — lazy loaded so they don't bloat the initial bundle
const OrdersView       = lazy(() => import("./components/OrdersView"));
const Discovery        = lazy(() => import("./pages/Discovery"));
const JobsPage         = lazy(() => import("./components/JobsPage"));
const MachinesPage     = lazy(() => import("./components/MachinesPage"));
const QCAnalyticsPage  = lazy(() => import("./components/QCAnalyticsPage"));
const DashboardPage    = lazy(() => import("./components/DashboardPage"));
const ManufacturingPage = lazy(() => import("./components/ManufacturingPage"));
const OperationsPage   = lazy(() => import("./components/OperationsPage"));
const NLSchedulerPage  = lazy(() => import("./components/NLSchedulerPage"));
const ToolWearDashboard = lazy(() => import("./components/ToolWearDashboard"));
const ToolAwareSchedule = lazy(() => import("./components/ToolAwareSchedule"));
const ARIAImport       = lazy(() => import("./components/ARIAImport"));
const QualityHub       = lazy(() => import("./components/quality/QualityHub"));

const PUBLIC_TABS = [
  { id: "quote",     label: "Instant Quote" },
  { id: "schedule",  label: "Production Schedule" },
  { id: "pricing",   label: "Pricing" },
  { id: "vision",    label: "Quality Inspection" },
  { id: "energy",    label: "Energy" },
  { id: "suppliers", label: "Suppliers" },
  { id: "contact",   label: "Get in Touch" },
  { id: "demo-chain", label: "ARIA Demo" },
];

const AUTH_TABS = [
  { id: "dashboard",      label: "Dashboard" },
  { id: "orders",         label: "My Orders" },
  { id: "jobs",           label: "Jobs" },
  { id: "machines",       label: "Machines" },
  { id: "analytics",      label: "Analytics" },
  { id: "manufacturing",  label: "Manufacturing" },
  { id: "operations",     label: "Operations" },
  { id: "nl-scheduler",   label: "NL Scheduler" },
  { id: "machine-health", label: "Machine Health" },
  { id: "tool-schedule",  label: "Tool-Aware Schedule" },
  { id: "aria-import",    label: "Import from Scan" },
  { id: "discovery",      label: "Discovery" },
  { id: "quality",        label: "Quality & Compliance" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("quote");
  const [showAuth, setShowAuth] = useState(false);
  const [supplierStats, setSupplierStats] = useState(null);
  const [onboardingStatus, setOnboardingStatus] = useState(null);
  const [showWizard, setShowWizard] = useState(false);
  const [user, setUser] = useState(null);
  const [navOpen, setNavOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const dropdownRef = useRef(null);
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
        body: JSON.stringify({ name: captureEmail.split("@")[0], email: captureEmail, message: "Requested sample report", source: "email_capture" }),
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

  // Close account dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setAccountOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

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

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Header ── */}
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Cog className="w-7 h-7 text-forge-500" />
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
              {navOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
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
          <h1 className="text-5xl sm:text-6xl font-extrabold mb-4 leading-tight tracking-tighter">
            <span className="text-white">MillForge AI </span>
            <span className="bg-gradient-to-r from-forge-500 to-orange-400 bg-clip-text text-transparent">
              ends the wait.
            </span>
          </h1>
          {/* Subheadline */}
          <p className="text-lg sm:text-xl text-gray-200 font-semibold max-w-2xl mx-auto mb-3">
            AI scheduler that lifts on-time delivery from 60% to 95%+<br className="hidden sm:block" /> using your existing machines and staff.
          </p>
          <p className="text-xs text-gray-500 max-w-xl mx-auto mb-6 mt-1">
            Not an ERP. Not a quoting portal. A scheduling layer that sits on top of what you already use.
          </p>
          {/* Stat strip */}
          <div className="flex flex-wrap justify-center gap-6 sm:gap-10 mb-8">
            {[
              ["96.4%", "On-time delivery (SA optimizer)"],
              ["+35.7pp", "Improvement over FIFO baseline"],
              ["< 200ms", "Schedule latency per 28 orders"],
            ].map(([val, label]) => (
              <div key={label} className="text-center">
                <p className="text-2xl font-extrabold text-forge-400">{val}</p>
                <p className="text-xs text-gray-500 mt-0.5">{label}</p>
              </div>
            ))}
          </div>
          {/* Primary CTA */}
          <a
            href="https://calendly.com/jonkofm/30min"
            target="_blank"
            rel="noopener noreferrer"
            className="btn-gradient"
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

      {/* ── How It Works ── */}
      <HowItWorks />

      {/* ── Trust / credential bar ── */}
      <TrustBar />

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
              <p className="text-4xl font-extrabold text-gray-500">
                <AnimatedCounter target={60.7} suffix="%" />
              </p>
              <p className="text-xs text-gray-600 mt-1">Before MillForge: 60.7% on-time</p>
            </div>
            <div className="text-center">
              <p className="text-4xl font-extrabold text-orange-400">
                <AnimatedCounter target={96.4} suffix="%" />
              </p>
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
          <p className="text-gray-300 text-base mb-2">Starts at <span className="text-white font-semibold">$499/month</span> for shops with up to 5 machines.</p>
          <p className="text-gray-400 text-sm mb-2">Scales with shop size. Most customers see ROI within 30 days.</p>
          <p className="text-gray-500 text-sm mb-8">No implementation fees. No ERP replacement. Cancel anytime.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <button
              onClick={() => { setActiveTab("pricing"); scrollTo("tab-nav"); }}
              className="bg-forge-500 hover:bg-forge-600 text-white font-semibold px-6 py-2.5 rounded-lg text-sm transition-colors"
            >
              See all plans →
            </button>
            <a
              href="https://calendly.com/jonkofm/30min"
              target="_blank"
              rel="noopener noreferrer"
              className="text-forge-400 hover:text-forge-300 text-sm font-medium transition-colors"
            >
              or book a call →
            </a>
          </div>
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
            {/* Right: supplier stats */}
            <div className="grid grid-cols-3 gap-4">
              {[
                [supplierStats?.total_suppliers ?? "1,100+", "Verified US Suppliers"],
                [supplierStats?.states_covered ?? "48", "States Covered"],
                ["4", "Material Categories"],
              ].map(([val, label]) => (
                <div key={label} className="bg-gray-800 rounded-xl p-4 text-center border border-gray-700">
                  <p className="text-2xl font-bold text-forge-400">{val}</p>
                  <p className="text-xs text-gray-500 mt-1">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Tab nav ── */}
      <nav id="tab-nav" className="bg-gray-900 border-b border-gray-800 sticky top-[73px] z-10">
        <div className="max-w-6xl mx-auto px-4 flex items-center">
          {/* Scrollable public tabs */}
          <div className="flex gap-1 overflow-x-auto flex-1 min-w-0">
            {PUBLIC_TABS.map((tab) => (
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
              </button>
            ))}
          </div>

          {/* Account dropdown — outside overflow container so it's never clipped */}
          {user ? (
            <div className="relative flex-shrink-0 pl-2 py-2" ref={dropdownRef}>
              <button
                onClick={() => setAccountOpen(o => !o)}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  AUTH_TABS.some(t => t.id === activeTab)
                    ? "bg-forge-500/20 text-forge-400"
                    : "text-gray-400 hover:text-white hover:bg-gray-800"
                }`}
              >
                {user.email?.split("@")[0] || "Account"}
                <ChevronDown className={`w-3.5 h-3.5 transition-transform duration-150 ${accountOpen ? "rotate-180" : ""}`} />
              </button>
              {accountOpen && (
                <div className="absolute right-0 top-full mt-1 w-52 bg-gray-900 border border-gray-700 rounded-xl shadow-xl z-50 py-1">
                  {AUTH_TABS.map(tab => (
                    <button
                      key={tab.id}
                      onClick={() => { setActiveTab(tab.id); setAccountOpen(false); }}
                      className={`w-full text-left text-sm px-4 py-2 transition-colors ${
                        activeTab === tab.id
                          ? "text-forge-400 bg-forge-500/10"
                          : "text-gray-300 hover:bg-gray-800 hover:text-white"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                  <hr className="border-gray-800 my-1" />
                  <button
                    onClick={() => { handleLogout(); setAccountOpen(false); }}
                    className="w-full text-left text-sm px-4 py-2 text-red-400 hover:bg-gray-800 transition-colors"
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={() => setShowAuth(true)}
              className="flex-shrink-0 px-4 py-2 text-sm font-medium whitespace-nowrap text-gray-600 hover:text-gray-400 transition-colors"
            >
              Sign in for more →
            </button>
          )}
        </div>
      </nav>

      {/* ── Tab content ── */}
      <main className="flex-1 max-w-6xl mx-auto px-4 py-10 w-full">
        <Suspense fallback={<div className="flex items-center justify-center py-24"><div className="w-6 h-6 border-2 border-forge-500 border-t-transparent rounded-full animate-spin" /></div>}>
        {activeTab === "quote"          && <QuoteForm />}
        {activeTab === "schedule"       && <ScheduleViewer />}
        {activeTab === "pricing"        && <PricingPage />}
        {activeTab === "vision"         && <VisionDemo />}
        {activeTab === "energy"         && <EnergyPage />}
        {activeTab === "suppliers"      && <SuppliersPage />}
        {activeTab === "contact"        && <ContactForm />}
        {activeTab === "dashboard"      && user && <DashboardPage />}
        {activeTab === "discovery"      && user && <Discovery />}
        {activeTab === "quality"        && user && <QualityHub />}
        {activeTab === "jobs"           && user && <JobsPage />}
        {activeTab === "machines"       && user && <MachinesPage />}
        {activeTab === "analytics"      && user && <QCAnalyticsPage onNavigate={setActiveTab} />}
        {activeTab === "manufacturing"  && user && <ManufacturingPage />}
        {activeTab === "operations"     && user && <OperationsPage />}
        {activeTab === "nl-scheduler"   && user && <NLSchedulerPage />}
        {activeTab === "machine-health" && user && <ToolWearDashboard />}
        {activeTab === "tool-schedule"  && user && <ToolAwareSchedule />}
        {activeTab === "aria-import"    && user && <ARIAImport />}
        {activeTab === "demo-chain"     && <DemoChainPage />}
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
        </Suspense>
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
