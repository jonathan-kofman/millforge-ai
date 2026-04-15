import { useState, useEffect, useRef, lazy, Suspense } from "react";
import { Cog, Menu, X, ChevronDown } from "lucide-react";
import AppDashboard from "./pages/AppDashboard";
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
import PipelineHealth from "./components/PipelineHealth";

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

const AUTH_TAB_IDS = new Set(AUTH_TABS.map((t) => t.id));

/** Deep links from ARIA dashboard: `/?tab=jobs&job=42` — cookie session unchanged (opens same app origin). */
function readMillforgeUrlIntent() {
  if (typeof window === "undefined") return { tab: null, jobId: null };
  const p = new URLSearchParams(window.location.search);
  const tab = p.get("tab");
  const jobRaw = p.get("job");
  const jobId = jobRaw ? parseInt(jobRaw, 10) : NaN;
  return {
    tab: tab && AUTH_TAB_IDS.has(tab) ? tab : null,
    jobId: Number.isFinite(jobId) ? jobId : null,
  };
}

export default function App() {
  const urlIntentRef = useRef(readMillforgeUrlIntent());
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

  // Public deep link: /?tab=pricing — Stripe return URLs use this
  useEffect(() => {
    const tab = new URLSearchParams(window.location.search).get("tab");
    if (tab === "pricing") {
      setActiveTab("pricing");
      requestAnimationFrame(() => {
        document.getElementById("tab-nav")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
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

  // ARIA (or bookmarks): /?tab=jobs&job=123 — switch tab after session restores; does not clear login.
  useEffect(() => {
    const { tab, jobId } = urlIntentRef.current;
    if (!tab || !user) return;
    setActiveTab(tab);
    if (jobId != null) {
      requestAnimationFrame(() => {
        document.getElementById("tab-nav")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [user]);

  // Authenticated users get the full dark dashboard experience
  if (user) {
    return <AppDashboard user={user} onLogout={handleLogout} />;
  }

  // Auth flow — full-page, matches dashboard aesthetic
  if (showAuth) {
    return <AuthModal onSuccess={handleAuthSuccess} onClose={() => setShowAuth(false)} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-950">
      {/* ── Header ── */}
      <header className="bg-gray-950/90 backdrop-blur-md sticky top-0 z-20" style={{ boxShadow: "0 1px 0 rgba(249,115,22,0.15), 0 4px 24px rgba(0,0,0,0.4)" }}>
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          {/* Wordmark */}
          <div className="flex items-center gap-2.5">
            <Cog className="w-6 h-6 text-forge-500" />
            <span className="text-xl font-extrabold tracking-tight">
              <span className="text-white">Mill</span><span className="text-forge-500">Forge</span>
            </span>
          </div>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-8">
            <button onClick={() => scrollTo("how-it-works-section")} className="text-sm text-gray-400 hover:text-white transition-colors font-medium">How it works</button>
            <button onClick={() => scrollTo("pricing-section")} className="text-sm text-gray-400 hover:text-white transition-colors font-medium">Pricing</button>
            <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-400 hover:text-white transition-colors font-medium">Demo</button>
            <button onClick={() => { setActiveTab("contact"); scrollTo("tab-nav"); }} className="text-sm text-gray-400 hover:text-white transition-colors font-medium">Contact</button>
          </nav>

          <div className="flex items-center gap-3">
            <button
              className="md:hidden text-gray-400 hover:text-white"
              onClick={() => setNavOpen(v => !v)}
              aria-label="Toggle menu"
            >
              {navOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
            {user ? (
              <button onClick={handleLogout} className="text-sm font-medium text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 rounded-lg px-4 py-2 transition-colors">Sign Out</button>
            ) : (
              <button onClick={() => setShowAuth(true)} className="text-sm font-semibold text-white border border-gray-600 hover:border-forge-500/60 hover:text-forge-400 rounded-lg px-4 py-2 transition-colors">Log in</button>
            )}
          </div>
        </div>

        {/* Mobile nav */}
        {navOpen && (
          <div className="md:hidden border-t border-gray-800/60 bg-gray-950">
            <div className="max-w-7xl mx-auto px-6 py-4 flex flex-col gap-4">
              <button onClick={() => scrollTo("how-it-works-section")} className="text-sm text-gray-400 hover:text-white text-left transition-colors">How it works</button>
              <button onClick={() => scrollTo("pricing-section")} className="text-sm text-gray-400 hover:text-white text-left transition-colors">Pricing</button>
              <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-400 hover:text-white text-left transition-colors">Demo</button>
              <button onClick={() => { setActiveTab("contact"); scrollTo("tab-nav"); }} className="text-sm text-gray-400 hover:text-white text-left transition-colors">Contact</button>
            </div>
          </div>
        )}
      </header>

      {/* ── Hero ── */}
      <section className="relative overflow-hidden bg-gray-950">
        {/* Primary radial — forge orange, top center */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(ellipse 75% 45% at 50% -5%, rgba(249,115,22,0.14) 0%, transparent 68%)" }} />
        {/* Secondary radial — amber, bottom right */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(ellipse 40% 30% at 92% 110%, rgba(251,191,36,0.07) 0%, transparent 60%)" }} />
        {/* Grid overlay */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-[0.06]" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.4) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.4) 1px, transparent 1px)", backgroundSize: "48px 48px" }} />

        <div className="relative max-w-5xl mx-auto px-6 pt-24 pb-16 text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 bg-forge-500/10 border border-forge-500/25 rounded-full px-4 py-1.5 mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-forge-400 animate-pulse" />
            <span className="text-xs font-semibold text-forge-400 tracking-widest uppercase">Lights-out manufacturing intelligence</span>
          </div>

          {/* Headline */}
          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-extrabold mb-6 leading-[1.04] tracking-tighter">
            <span className="text-white">Your mill runs</span>
            <br />
            <span className="bg-gradient-to-r from-forge-500 via-orange-400 to-amber-300 bg-clip-text text-transparent">while you sleep.</span>
          </h1>

          {/* Sub */}
          <p className="text-lg sm:text-xl text-gray-300 max-w-2xl mx-auto mb-2 leading-relaxed">
            MillForge AI replaces manual production coordination — scheduling, quoting, quality inspection, and energy optimization — so your floor runs at full capacity with no one watching.
          </p>
          <p className="text-xs text-gray-600 max-w-xl mx-auto mb-10">
            Sits on top of what you already use. No ERP replacement. No rip-and-replace.
          </p>

          {/* Stat cards */}
          <div className="flex flex-wrap justify-center gap-3 sm:gap-4 mb-10">
            {[
              { val: "96.4%", label: "On-time delivery", sub: "vs 60.7% FIFO baseline" },
              { val: "+35.7pp", label: "OTD improvement", sub: "same machines, same staff" },
              { val: "9 of 10", label: "Touchpoints automated", sub: "scheduling → sourcing" },
            ].map(({ val, label, sub }) => (
              <div key={label} className="bg-gray-900/80 border border-gray-800 rounded-2xl px-6 py-4 text-center min-w-[140px] backdrop-blur-sm">
                <p className="text-2xl font-extrabold text-forge-400">{val}</p>
                <p className="text-xs font-semibold text-gray-300 mt-0.5">{label}</p>
                <p className="text-[10px] text-gray-600 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>

          {/* CTA row */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-3">
            <a href="https://calendly.com/jonkofm/30min" target="_blank" rel="noopener noreferrer" className="btn-gradient">
              Book a 30-minute floor review →
            </a>
            <button onClick={() => { setActiveTab("schedule"); scrollTo("tab-nav"); }} className="text-gray-400 hover:text-gray-200 text-sm font-medium transition-colors border border-gray-700 hover:border-gray-600 rounded-lg px-5 py-2.5">
              See the live benchmark →
            </button>
          </div>
          <p className="text-xs text-gray-600 mb-10">
            No commitment. We run your order history through MillForge and show you the on-time delta.
          </p>

          {/* Email capture */}
          <div className="mb-12">
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
                  className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-forge-500 focus:border-transparent text-sm w-full sm:w-auto"
                />
                <button type="submit" disabled={captureLoading} className="bg-gray-800 hover:bg-gray-700 text-white font-semibold px-5 py-2.5 rounded-lg text-sm transition-colors whitespace-nowrap disabled:opacity-50 border border-gray-700">
                  {captureLoading ? "Sending…" : "Get a sample report →"}
                </button>
              </form>
            )}
            <p className="text-[11px] text-gray-700 mt-2">No spam. Sample 28-order benchmark analysis.</p>
          </div>

          {/* Trusted-by strip */}
          <div className="border-t border-gray-800/60 pt-8">
            <p className="text-[11px] font-semibold tracking-widest text-gray-600 uppercase mb-3">Built for</p>
            <p className="text-sm text-gray-500 font-medium">
              Tier-2 aerospace suppliers&nbsp;&nbsp;·&nbsp;&nbsp;Job shops&nbsp;&nbsp;·&nbsp;&nbsp;Metal distributors&nbsp;&nbsp;·&nbsp;&nbsp;Defense contractors
            </p>
          </div>
        </div>
      </section>

      {/* ── 6-Feature Grid ── */}
      <section id="how-it-works-section" className="bg-gray-950 border-t border-b border-gray-800/60">
        <div className="max-w-6xl mx-auto px-6 py-20">
          <div className="text-center mb-14">
            <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-3">Platform capabilities</p>
            <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-3 tracking-tight">9 automated touchpoints. Zero manual coordination.</h2>
            <p className="text-gray-400 max-w-xl mx-auto text-base">Every routine production task runs without a human in the loop. Exceptions are the only thing left for your team.</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {[
              { icon: "⚡", title: "AI Scheduling", desc: "SA optimizer sequences jobs across machines — 96.4% on-time vs 60.7% FIFO baseline.", badge: "Automated", badgeColor: "bg-forge-500/15 text-forge-400 border-forge-500/30" },
              { icon: "💬", title: "Instant Quoting", desc: "Material, complexity, and shift calendar produce a binding quote in under 2 seconds.", badge: "Automated", badgeColor: "bg-forge-500/15 text-forge-400 border-forge-500/30" },
              { icon: "🔬", title: "Vision Inspection", desc: "YOLOv8n (mAP50=0.759) classifies surface defects — crazing, pitting, inclusions — without a QC tech.", badge: "Live", badgeColor: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
              { icon: "🚨", title: "Anomaly Detection", desc: "Duplicate IDs and impossible deadlines are caught and held before they hit the schedule.", badge: "Automated", badgeColor: "bg-forge-500/15 text-forge-400 border-forge-500/30" },
              { icon: "⚡", title: "Energy Optimization", desc: "Jobs shift to off-peak windows automatically. EIA live grid pricing. No human decides when to run.", badge: "Live", badgeColor: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" },
              { icon: "🏭", title: "Supplier Sourcing", desc: "1,100+ verified US suppliers. When stock runs low, the nearest match and a PO are one click away.", badge: "Automated", badgeColor: "bg-forge-500/15 text-forge-400 border-forge-500/30" },
            ].map(({ icon, title, desc, badge, badgeColor }) => (
              <div key={title} className="group bg-gray-900/70 border border-gray-800 hover:border-gray-700 rounded-2xl p-6 transition-all duration-200 hover:bg-gray-900">
                <div className="flex items-start justify-between mb-4">
                  <span className="text-2xl">{icon}</span>
                  <span className={`text-[10px] font-bold tracking-wider uppercase px-2.5 py-1 rounded-full border ${badgeColor}`}>{badge}</span>
                </div>
                <h3 className="text-base font-bold text-white mb-2">{title}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Hidden legacy components — kept for imports ── */}
      {false && <HowItWorks />}
      {false && <TrustBar />}

      {/* ── Benchmark Demo ── */}
      <div id="benchmark-section" className="bg-gray-950 border-b border-gray-800/60">
        <BenchmarkDemo />
      </div>

      {/* ── Comparison Table ── */}
      <section className="bg-gray-950 border-b border-gray-800/60">
        <div className="max-w-4xl mx-auto px-6 py-20">
          <div className="text-center mb-12">
            <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-3">Benchmark — 28-order simulated dataset</p>
            <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">How MillForge stacks up</h2>
            <p className="text-gray-500 text-sm mt-2">3 machines · mixed steel, aluminum, titanium · 4 rush orders</p>
          </div>

          {/* Animated counters above table */}
          <div className="flex flex-wrap justify-center gap-10 mb-12">
            <div className="text-center">
              <p className="text-5xl font-extrabold text-gray-600"><AnimatedCounter target={60.7} suffix="%" /></p>
              <p className="text-xs text-gray-600 mt-1.5">FIFO baseline</p>
            </div>
            <div className="flex items-center text-gray-700 text-3xl font-light">→</div>
            <div className="text-center">
              <p className="text-5xl font-extrabold text-forge-400"><AnimatedCounter target={96.4} suffix="%" /></p>
              <p className="text-xs text-gray-500 mt-1.5">MillForge SA</p>
            </div>
          </div>

          {/* Comparison table */}
          <div className="overflow-x-auto rounded-2xl border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-5 py-4 text-gray-500 font-semibold bg-gray-900/50 w-1/3"></th>
                  <th className="px-5 py-4 text-center text-gray-400 font-semibold bg-gray-900/50">FIFO (Baseline)</th>
                  <th className="px-5 py-4 text-center text-gray-400 font-semibold bg-gray-900/50">EDD Rule</th>
                  <th className="px-5 py-4 text-center font-bold bg-forge-500/10 border-l border-r border-forge-500/20" style={{ color: "#f97316" }}>
                    MillForge SA ✓
                  </th>
                </tr>
              </thead>
              <tbody>
                {[
                  { metric: "On-time delivery", fifo: "60.7%", edd: "82.1%", sa: "96.4%", highlight: true },
                  { metric: "Schedule latency", fifo: "Manual", edd: "~1 s", sa: "<200 ms", highlight: false },
                  { metric: "Rush order handling", fifo: "Manual", edd: "Rule-based", sa: "AI-prioritized", highlight: false },
                  { metric: "Anomaly detection", fifo: "None", edd: "None", sa: "Automated gate", highlight: false },
                  { metric: "Energy awareness", fifo: "None", edd: "None", sa: "Live grid pricing", highlight: false },
                ].map(({ metric, fifo, edd, sa, highlight }) => (
                  <tr key={metric} className="border-b border-gray-800/60 last:border-0">
                    <td className="px-5 py-4 text-gray-300 font-medium bg-gray-900/30">{metric}</td>
                    <td className="px-5 py-4 text-center text-gray-500 bg-gray-900/20">{fifo}</td>
                    <td className="px-5 py-4 text-center text-gray-400 bg-gray-900/20">{edd}</td>
                    <td className={`px-5 py-4 text-center font-bold bg-forge-500/5 border-l border-r border-forge-500/15 ${highlight ? "text-forge-400 text-base" : "text-white"}`}>{sa}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-700 text-center mt-4">Based on simulated 28-order dataset. Results vary by shop configuration.</p>
        </div>
      </section>

      {/* ── Lights-out widget ── */}
      <div className="bg-gray-950 border-b border-gray-800/60">
        <div className="max-w-6xl mx-auto px-6 pt-10 pb-2">
          <p className="text-sm text-gray-500 text-center">Every milestone removes one more human touchpoint from routine production.</p>
        </div>
        <LightsOutWidget />
      </div>

      {/* ── 3-Tier Pricing ── */}
      <section id="pricing-section" className="bg-gray-950 border-b border-gray-800/60">
        <div className="max-w-6xl mx-auto px-6 py-20">
          <div className="text-center mb-14">
            <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-3">Pricing</p>
            <h2 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight mb-3">Transparent, machine-based pricing.</h2>
            <p className="text-gray-400 max-w-md mx-auto text-base">No implementation fees. No ERP replacement. Most shops see ROI within 30 days. Cancel anytime.</p>
          </div>
          <div className="grid sm:grid-cols-3 gap-6 items-stretch">
            {/* Starter */}
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-7 flex flex-col">
              <p className="text-xs font-bold tracking-widest text-gray-500 uppercase mb-2">Starter</p>
              <p className="text-4xl font-extrabold text-white mb-1">$299<span className="text-base font-medium text-gray-500">/mo</span></p>
              <p className="text-sm text-gray-500 mb-6">Up to 3 machines</p>
              <ul className="space-y-2.5 mb-8 flex-1">
                {["AI scheduling (EDD + SA)", "Instant quoting engine", "Order anomaly detection", "Supplier directory access", "Email support"].map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm text-gray-300">
                    <span className="text-forge-500 mt-0.5 flex-shrink-0">✓</span>{f}
                  </li>
                ))}
              </ul>
              <button onClick={() => { setActiveTab("pricing"); scrollTo("tab-nav"); }} className="w-full border border-gray-700 hover:border-gray-600 text-gray-300 hover:text-white font-semibold py-2.5 rounded-xl text-sm transition-colors">
                Get started →
              </button>
            </div>

            {/* Professional — highlighted */}
            <div className="bg-gray-900 border-2 border-forge-500/60 rounded-2xl p-7 flex flex-col relative" style={{ boxShadow: "0 0 40px rgba(249,115,22,0.12)" }}>
              <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 bg-forge-500 text-white text-[10px] font-bold tracking-widest uppercase px-3 py-1 rounded-full">Most popular</div>
              <p className="text-xs font-bold tracking-widest text-forge-400 uppercase mb-2">Professional</p>
              <p className="text-4xl font-extrabold text-white mb-1">$499<span className="text-base font-medium text-gray-500">/mo</span></p>
              <p className="text-sm text-gray-500 mb-6">Up to 10 machines</p>
              <ul className="space-y-2.5 mb-8 flex-1">
                {["Everything in Starter", "Vision quality inspection (YOLOv8n)", "Energy optimization (live grid)", "Inventory reorder automation", "Priority support + onboarding call"].map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm text-gray-300">
                    <span className="text-forge-400 mt-0.5 flex-shrink-0">✓</span>{f}
                  </li>
                ))}
              </ul>
              <button onClick={() => { setActiveTab("pricing"); scrollTo("tab-nav"); }} className="w-full bg-forge-500 hover:bg-forge-600 text-white font-bold py-2.5 rounded-xl text-sm transition-colors">
                Start free trial →
              </button>
            </div>

            {/* Enterprise */}
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-7 flex flex-col">
              <p className="text-xs font-bold tracking-widest text-gray-500 uppercase mb-2">Enterprise</p>
              <p className="text-4xl font-extrabold text-white mb-1">Custom</p>
              <p className="text-sm text-gray-500 mb-6">Unlimited machines</p>
              <ul className="space-y-2.5 mb-8 flex-1">
                {["Everything in Professional", "White-glove onboarding", "Custom ERP / MES integrations", "Dedicated success manager", "SLA + uptime guarantees"].map(f => (
                  <li key={f} className="flex items-start gap-2.5 text-sm text-gray-300">
                    <span className="text-forge-500 mt-0.5 flex-shrink-0">✓</span>{f}
                  </li>
                ))}
              </ul>
              <a href="https://calendly.com/jonkofm/30min" target="_blank" rel="noopener noreferrer" className="w-full border border-gray-700 hover:border-gray-600 text-gray-300 hover:text-white font-semibold py-2.5 rounded-xl text-sm transition-colors text-center block">
                Talk to us →
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Why we built this — 2-col layout ── */}
      <section id="how-it-works" className="bg-gray-950 border-b border-gray-800/60">
        <div className="max-w-6xl mx-auto px-6 py-20">
          <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-12 text-center">Why we built this</p>
          <div className="grid md:grid-cols-2 gap-14 items-start">
            {/* Left: pull quote */}
            <div>
              <blockquote className="border-l-4 border-forge-500 pl-7">
                <p className="text-2xl sm:text-3xl font-extrabold text-white leading-tight mb-4">
                  &ldquo;Ordered 5 months ago. They told me another 2 months. I could&apos;ve grown the aluminum myself.&rdquo;
                </p>
                <p className="text-sm text-gray-500">— American manufacturer, aerospace supply chain, 2024</p>
              </blockquote>
              <p className="text-gray-400 mt-8 leading-relaxed text-base">
                Every machinist Jonathan worked alongside had the same story. The scheduling is broken. The visibility is zero. The software doesn&apos;t match the floor. MillForge exists because this problem is everywhere and nobody has fixed it.
              </p>
            </div>
            {/* Right: 3 specific problems */}
            <div className="space-y-7">
              {[
                {
                  num: "01",
                  title: "The scheduling software doesn't match the floor.",
                  body: "Floor managers maintain parallel spreadsheets because their ERP doesn't reflect actual machine state. Rush orders get handled by whoever's loudest, not by data.",
                },
                {
                  num: "02",
                  title: "Supplier search costs 2–4 weeks per material shortage.",
                  body: "When stock runs low, a manager calls three distributors, waits for callbacks, compares quotes manually. The scheduling system doesn't know any of this is happening.",
                },
                {
                  num: "03",
                  title: "Late delivery is the default, not the exception.",
                  body: "FIFO scheduling delivers 60.7% of orders on time. That's not a staffing problem — it's an optimization problem. MillForge SA closes that gap to 96.4%.",
                },
              ].map(({ num, title, body }) => (
                <div key={num} className="flex gap-5">
                  <span className="text-forge-500/40 font-extrabold text-2xl leading-tight flex-shrink-0 w-8">{num}</span>
                  <div>
                    <p className="text-white font-bold mb-1.5">{title}</p>
                    <p className="text-sm text-gray-400 leading-relaxed">{body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Energy intelligence ── */}
      <div className="bg-gray-900 border-b border-gray-800/60">
        <EnergyWidget />
      </div>

      {/* ── Supplier sourcing section ── */}
      <div id="suppliers-section" className="bg-gray-900 border-b border-gray-800/60">
        <div className="max-w-6xl mx-auto px-6 py-16">
          <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-4 text-center">Materials Sourcing</p>
          <h2 className="text-3xl sm:text-4xl font-bold text-white text-center mb-3 tracking-tight">Find materials. Schedule production. Ship faster.</h2>
          <p className="text-gray-400 text-center max-w-xl mx-auto mb-12 text-base">
            MillForge connects your schedule to verified US suppliers — so when stock runs low, a purchase order with the nearest qualified source is one click away.
          </p>
          <div className="grid sm:grid-cols-2 gap-12 items-start">
            <div className="space-y-5">
              <h3 className="text-lg font-bold text-white">The sourcing problem</h3>
              <p className="text-gray-400 text-sm leading-relaxed">
                American mills lose weeks to supplier search. When a material runs short, a floor manager calls three distributors, waits for callbacks, manually compares lead times, and enters a PO by hand. The scheduling software doesn&apos;t know any of this is happening.
              </p>
              <p className="text-gray-400 text-sm leading-relaxed">
                MillForge&apos;s inventory agent watches stock in real time. When a reorder point is hit, it surfaces the nearest verified supplier — filtered by distance, category, and current schedule — and generates the PO automatically.
              </p>
              <button onClick={() => setActiveTab("contact")} className="btn-secondary text-sm mt-2">Submit a supplier →</button>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {[
                [supplierStats?.total_suppliers ?? "1,100+", "Verified US Suppliers"],
                [supplierStats?.states_covered ?? "48", "States Covered"],
                ["4", "Material Categories"],
              ].map(([val, label]) => (
                <div key={label} className="bg-gray-800 rounded-2xl p-5 text-center border border-gray-700">
                  <p className="text-2xl font-bold text-forge-400">{val}</p>
                  <p className="text-xs text-gray-500 mt-1.5">{label}</p>
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
        {activeTab === "pricing"        && <PricingPage user={user} />}
        {activeTab === "vision"         && <VisionDemo />}
        {activeTab === "energy"         && <EnergyPage />}
        {activeTab === "suppliers"      && <SuppliersPage />}
        {activeTab === "contact"        && <ContactForm />}
        {activeTab === "dashboard" && user && (
          <div className="space-y-4 p-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2"><DashboardPage /></div>
              <PipelineHealth />
            </div>
          </div>
        )}
        {activeTab === "discovery"      && user && <Discovery />}
        {activeTab === "quality"        && user && <QualityHub />}
        {activeTab === "jobs"           && user && (
          <JobsPage focusJobId={urlIntentRef.current.jobId} />
        )}
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
      <footer className="border-t border-gray-800/60 bg-gray-950">
        <div className="max-w-7xl mx-auto px-6 py-12">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-8">
            {/* Left: brand */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Cog className="w-5 h-5 text-forge-500" />
                <span className="text-lg font-extrabold tracking-tight">
                  <span className="text-white">Mill</span><span className="text-forge-500">Forge</span>
                </span>
              </div>
              <p className="text-xs text-gray-600 font-medium tracking-wide">Built for American manufacturing.</p>
            </div>
            {/* Center: links */}
            <nav className="flex flex-wrap gap-x-8 gap-y-2">
              <button onClick={() => scrollTo("pricing-section")} className="text-sm text-gray-500 hover:text-gray-300 transition-colors">Pricing</button>
              <button onClick={() => scrollTo("benchmark-section")} className="text-sm text-gray-500 hover:text-gray-300 transition-colors">Demo</button>
              <button onClick={() => { setActiveTab("contact"); scrollTo("tab-nav"); }} className="text-sm text-gray-500 hover:text-gray-300 transition-colors">Contact</button>
              <a href="https://www.linkedin.com/in/jonathan-kofman/" target="_blank" rel="noopener noreferrer" className="text-sm text-gray-500 hover:text-gray-300 transition-colors">LinkedIn</a>
            </nav>
            {/* Right: legal */}
            <p className="text-xs text-gray-700">© 2026 MillForge AI</p>
          </div>
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
