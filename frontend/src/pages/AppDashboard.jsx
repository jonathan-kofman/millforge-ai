import { useState, useEffect, lazy, Suspense } from "react";
import { API_BASE } from "../config";

// Lazy loaded screens
const ScheduleViewer    = lazy(() => import("../components/ScheduleViewer"));
const JobsPage          = lazy(() => import("../components/JobsPage"));
const QualityHub        = lazy(() => import("../components/quality/QualityHub"));
const DashboardPage     = lazy(() => import("../components/DashboardPage"));
const QCAnalyticsPage   = lazy(() => import("../components/QCAnalyticsPage"));
const OrdersView        = lazy(() => import("../components/OrdersView"));
const MachinesPage      = lazy(() => import("../components/MachinesPage"));
const ManufacturingPage = lazy(() => import("../components/ManufacturingPage"));
const OperationsPage    = lazy(() => import("../components/OperationsPage"));
const NLSchedulerPage   = lazy(() => import("../components/NLSchedulerPage"));
const ToolWearDashboard = lazy(() => import("../components/ToolWearDashboard"));
const ToolAwareSchedule = lazy(() => import("../components/ToolAwareSchedule"));
const ARIAImport        = lazy(() => import("../components/ARIAImport"));
const Discovery         = lazy(() => import("../pages/Discovery"));
const EnergyPage        = lazy(() => import("../components/EnergyPage"));

// ─── Theme ───────────────────────────────────────────────────────────────────
const T = {
  bg0: "#0A0A0F", bg1: "#0F0F18", bg2: "#15151F", bg3: "#1A1A26",
  border: "rgba(255,255,255,0.06)", borderHi: "rgba(255,255,255,0.12)",
  text0: "#FAFAFA", text1: "#E5E5EA", text2: "#A1A1AA", text3: "#71717A", text4: "#52525B",
  brand: "#FF7A1A", brandGlow: "rgba(255,122,26,0.35)",
  green: "#10B981", greenGlow: "rgba(16,185,129,0.35)",
  amber: "#F59E0B", amberGlow: "rgba(245,158,11,0.35)",
  red: "#EF4444", redGlow: "rgba(239,68,68,0.35)",
  blue: "#3B82F6", blueGlow: "rgba(59,130,246,0.35)",
};

const NAV_GROUPS = [
  {
    id: "production", label: "Production", icon: "▦",
    tabs: [
      { id: "floor",   label: "Shop Floor" },
      { id: "orders",  label: "Orders" },
      { id: "jobs",    label: "Jobs" },
      { id: "quotes",  label: "Quotes" },
    ]
  },
  {
    id: "schedule", label: "Schedule", icon: "▤",
    tabs: [
      { id: "schedule",  label: "Schedule" },
      { id: "nlsched",   label: "NL Scheduler" },
      { id: "toolsched", label: "Tool Schedule" },
    ]
  },
  {
    id: "machines", label: "Machines", icon: "⊡",
    tabs: [
      { id: "fleet",      label: "Fleet" },
      { id: "operations", label: "Operations" },
      { id: "machhealth", label: "Machine Health" },
    ]
  },
  {
    id: "manufacturing", label: "Mfg", icon: "⚙",
    tabs: [
      { id: "processes", label: "Processes" },
      { id: "aria",      label: "ARIA Import" },
      { id: "energy",    label: "Energy" },
      { id: "materials", label: "Inventory" },
    ]
  },
  {
    id: "quality", label: "Quality", icon: "✓",
    tabs: [
      { id: "quality",   label: "Quality Suite" },
      { id: "analytics", label: "Analytics" },
      { id: "discovery", label: "Discovery" },
    ]
  },
  {
    id: "operators", label: "Operators", icon: "♟",
    tabs: [
      { id: "operators", label: "Operators" },
    ]
  },
];

// ─── Shared primitives ────────────────────────────────────────────────────────
function Sparkline({ data, color }) {
  const max = Math.max(...data), min = Math.min(...data), range = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 100},${100 - ((v - min) / range) * 100}`).join(" ");
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "32px" }}>
      <defs>
        <linearGradient id={`sg${color.replace("#","")}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.3" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,100 ${pts} 100,100`} fill={`url(#sg${color.replace("#","")})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function RingGauge({ value, size = 52 }) {
  const r = (size - 5) / 2, c = 2 * Math.PI * r;
  const color = value >= 75 ? T.green : value >= 50 ? T.amber : value > 0 ? T.red : T.text4;
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)", filter: value > 0 ? `drop-shadow(0 0 8px ${color}60)` : "none" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="3.5" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth="3.5"
          strokeDasharray={c} strokeDashoffset={c - (value / 100) * c} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", lineHeight: 1 }}>
        <div style={{ fontSize: "13px", fontWeight: 700, color, fontFeatureSettings: "'tnum'" }}>{value > 0 ? value : "—"}</div>
        <div style={{ fontSize: "7px", color: T.text4, letterSpacing: "0.1em", marginTop: "2px", fontWeight: 700 }}>OEE</div>
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, color, spark }) {
  return (
    <div style={{ position: "relative", background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, border: `1px solid ${T.border}`, borderRadius: "12px", padding: "14px 16px", overflow: "hidden", boxShadow: "0 4px 12px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04)" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "1px", background: `linear-gradient(90deg, transparent, ${color}50, transparent)` }} />
      <div style={{ fontSize: "9px", color: T.text3, letterSpacing: "0.12em", fontWeight: 700, marginBottom: "8px" }}>{label}</div>
      <div style={{ fontSize: "26px", fontWeight: 700, color: T.text0, letterSpacing: "-0.025em", lineHeight: 1, marginBottom: "3px", fontFeatureSettings: "'tnum'" }}>{value}</div>
      <div style={{ fontSize: "10px", color: T.text3, marginBottom: "8px" }}>{sub}</div>
      <Sparkline data={spark} color={color} />
    </div>
  );
}

function Badge({ label, color }) {
  return (
    <span style={{ fontSize: "9px", padding: "3px 8px", borderRadius: "100px", background: `${color}15`, color, border: `1px solid ${color}30`, fontWeight: 700, letterSpacing: "0.06em" }}>
      {label}
    </span>
  );
}

function Spinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "60px 0" }}>
      <div style={{ width: "24px", height: "24px", border: `2px solid ${T.brand}`, borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </div>
  );
}

// ─── ProfileMenu ─────────────────────────────────────────────────────────────
function ProfileMenu({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const initials = (user?.name || user?.email || "?").split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
  const name = user?.name || user?.email?.split("@")[0] || "Account";
  const email = user?.email || "";
  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: "36px", height: "36px", borderRadius: "9px", border: `1px solid ${open ? T.brand : T.border}`, background: open ? `${T.brand}15` : "rgba(255,255,255,0.04)", color: open ? T.brand : T.text2, fontSize: "11px", fontWeight: 700, cursor: "pointer", transition: "all 0.15s" }}
      >{initials}</button>
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 150 }} />
          <div style={{ position: "absolute", left: "44px", bottom: 0, width: "200px", background: T.bg3, border: `1px solid ${T.borderHi}`, borderRadius: "10px", boxShadow: "0 8px 24px rgba(0,0,0,0.5)", zIndex: 200, overflow: "hidden" }}>
            <div style={{ padding: "12px 14px", borderBottom: `1px solid ${T.border}` }}>
              <div style={{ fontSize: "12px", color: T.text0, fontWeight: 600 }}>{name}</div>
              {email && <div style={{ fontSize: "10px", color: T.text3, marginTop: "2px", wordBreak: "break-all" }}>{email}</div>}
            </div>
            <button
              onClick={() => { setOpen(false); onLogout(); }}
              style={{ width: "100%", padding: "10px 14px", background: "none", border: "none", color: T.red, fontSize: "12px", fontWeight: 600, cursor: "pointer", textAlign: "left", fontFamily: "inherit" }}
              onMouseEnter={e => e.currentTarget.style.background = `${T.red}10`}
              onMouseLeave={e => e.currentTarget.style.background = "none"}
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────
function Sidebar({ activeGroup, setActiveGroup, user, onLogout }) {
  const [hover, setHover] = useState(null);
  const initials = (user?.name || user?.email || "?").split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div style={{ width: "64px", height: "100vh", position: "fixed", left: 0, top: 0, background: "rgba(15,15,24,0.85)", backdropFilter: "blur(20px)", borderRight: `1px solid ${T.border}`, display: "flex", flexDirection: "column", alignItems: "center", padding: "16px 0", zIndex: 100 }}>
      <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: `linear-gradient(135deg, ${T.brand}, ${T.brand}80)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px", color: "#fff", fontWeight: 700, marginBottom: "24px", boxShadow: `0 0 24px ${T.brandGlow}` }}>◆</div>
      <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1 }}>
        {NAV_GROUPS.map(g => (
          <div key={g.id} style={{ position: "relative" }} onMouseEnter={() => setHover(g.id)} onMouseLeave={() => setHover(null)}>
            <button
              onClick={() => setActiveGroup(g.id)}
              style={{ width: "44px", height: "44px", borderRadius: "10px", border: "none", background: activeGroup === g.id ? `linear-gradient(135deg, ${T.brand}25, ${T.brand}10)` : "transparent", color: activeGroup === g.id ? T.brand : T.text3, fontSize: "16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.2s", boxShadow: activeGroup === g.id ? `inset 0 0 0 1px ${T.brand}40, 0 0 16px ${T.brandGlow}` : "none" }}
            >{g.icon}</button>
            {hover === g.id && (
              <div style={{ position: "absolute", left: "52px", top: "50%", transform: "translateY(-50%)", padding: "6px 10px", background: T.bg3, border: `1px solid ${T.borderHi}`, borderRadius: "6px", fontSize: "11px", color: T.text1, fontWeight: 500, whiteSpace: "nowrap", pointerEvents: "none", zIndex: 200 }}>{g.label}</div>
            )}
          </div>
        ))}
      </div>
      <ProfileMenu user={user} onLogout={onLogout} />
    </div>
  );
}

// ─── SubTabBar ────────────────────────────────────────────────────────────────
function SubTabBar({ group, activeTab, setActiveTab }) {
  if (!group || group.tabs.length <= 1) return null;
  return (
    <div style={{ display: "flex", gap: "4px", padding: "0 28px", height: "42px", alignItems: "center", borderBottom: `1px solid ${T.border}`, background: "rgba(10,10,15,0.4)" }}>
      {group.tabs.map(t => (
        <button
          key={t.id}
          onClick={() => setActiveTab(t.id)}
          style={{ padding: "5px 14px", borderRadius: "7px", border: `1px solid ${activeTab === t.id ? T.brand : "transparent"}`, background: activeTab === t.id ? `${T.brand}15` : "transparent", color: activeTab === t.id ? T.brand : T.text3, fontSize: "12px", fontWeight: 600, cursor: "pointer", transition: "all 0.15s", fontFamily: "inherit" }}
          onMouseEnter={e => { if (activeTab !== t.id) { e.currentTarget.style.color = T.text1; e.currentTarget.style.background = "rgba(255,255,255,0.04)"; } }}
          onMouseLeave={e => { if (activeTab !== t.id) { e.currentTarget.style.color = T.text3; e.currentTarget.style.background = "transparent"; } }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ─── TopBar ───────────────────────────────────────────────────────────────────
function TopBar({ breadcrumb }) {
  const [time, setTime] = useState(new Date());
  useEffect(() => { const i = setInterval(() => setTime(new Date()), 1000); return () => clearInterval(i); }, []);
  return (
    <div style={{ position: "sticky", top: 0, height: "56px", padding: "0 28px", background: "rgba(10,10,15,0.7)", backdropFilter: "blur(20px)", borderBottom: `1px solid ${T.border}`, display: "flex", justifyContent: "space-between", alignItems: "center", zIndex: 50 }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px" }}>
        <span style={{ color: T.text3, fontWeight: 500 }}>MillForge</span>
        <span style={{ color: T.text4 }}>/</span>
        <span style={{ color: T.text0, fontWeight: 600 }}>{breadcrumb}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "7px 12px", borderRadius: "8px", background: "rgba(255,255,255,0.03)", border: `1px solid ${T.border}`, width: "240px" }}>
          <span style={{ color: T.text4, fontSize: "12px" }}>⌕</span>
          <span style={{ fontSize: "12px", color: T.text4 }}>Search jobs, parts, customers...</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 10px", borderRadius: "7px", background: "rgba(16,185,129,0.08)", border: `1px solid ${T.green}30` }}>
          <div style={{ width: "5px", height: "5px", borderRadius: "50%", background: T.green, boxShadow: `0 0 8px ${T.green}`, animation: "pulse 2s infinite" }} />
          <span style={{ fontSize: "10px", color: T.green, fontWeight: 700, letterSpacing: "0.06em" }}>LIVE</span>
        </div>
        <div style={{ fontSize: "12px", color: T.text2, fontFeatureSettings: "'tnum'", padding: "6px 10px", borderRadius: "7px", background: "rgba(255,255,255,0.03)", border: `1px solid ${T.border}` }}>
          {time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}
        </div>
      </div>
    </div>
  );
}

// ─── Screen: Shop Floor ───────────────────────────────────────────────────────
const STATUS_MAP = {
  running:  { label: "RUNNING",  color: T.green },
  setup:    { label: "SETUP",    color: T.amber },
  idle:     { label: "IDLE",     color: T.text3 },
  down:     { label: "DOWN",     color: T.red },
  active:   { label: "ACTIVE",   color: T.green },
  offline:  { label: "OFFLINE",  color: T.red },
  maintenance: { label: "MAINT", color: T.amber },
};

function WorkCenterCard({ wc }) {
  const [hover, setHover] = useState(false);
  const st = STATUS_MAP[wc.status] || STATUS_MAP.idle;
  const op = wc.active_operation;
  const pct = op ? Math.min(100, Math.round((op.run_started_at ? 60 : op.setup_started_at ? 20 : 0))) : 0;

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ position: "relative", background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "14px", border: `1px solid ${hover ? T.borderHi : T.border}`, overflow: "hidden", transition: "all 0.3s", boxShadow: hover ? `0 12px 32px rgba(0,0,0,0.5), 0 0 0 1px ${st.color}30` : "0 4px 16px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04)", transform: hover ? "translateY(-2px)" : "none", cursor: "pointer" }}
    >
      {wc.status === "running" || wc.status === "active" ? (
        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at top, ${st.color}08 0%, transparent 60%)`, pointerEvents: "none" }} />
      ) : null}
      <div style={{ height: "1px", background: `linear-gradient(90deg, transparent, ${st.color}80, transparent)`, opacity: wc.status === "idle" ? 0.2 : 1 }} />
      <div style={{ position: "relative", padding: "16px 18px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "3px" }}>
              <span style={{ fontSize: "14px", fontWeight: 600, color: T.text0, letterSpacing: "-0.015em" }}>{wc.name}</span>
              <div style={{ display: "flex", alignItems: "center", gap: "5px", padding: "3px 8px", borderRadius: "100px", background: `${st.color}15`, border: `1px solid ${st.color}30` }}>
                {wc.status !== "idle" && <div style={{ width: "5px", height: "5px", borderRadius: "50%", background: st.color, boxShadow: `0 0 6px ${st.color}`, animation: (wc.status === "running" || wc.status === "active") ? "pulse 2s infinite" : "none" }} />}
                <span style={{ fontSize: "9px", fontWeight: 700, color: st.color, letterSpacing: "0.08em" }}>{st.label}</span>
              </div>
            </div>
            <div style={{ fontSize: "11px", color: T.text3, fontWeight: 500 }}>{wc.category}</div>
          </div>
          <RingGauge value={wc.status === "idle" || wc.status === "offline" ? 0 : 75} />
        </div>
        {op ? (
          <>
            <div style={{ fontSize: "15px", fontWeight: 600, color: T.text0, marginBottom: "12px" }}>{op.operation_name}</div>
            {op.order_ref && (
              <div style={{ fontSize: "10px", color: T.text2, marginBottom: "10px", fontFamily: "'JetBrains Mono', monospace" }}>{op.order_ref}</div>
            )}
            <div style={{ height: "5px", background: "rgba(255,255,255,0.04)", borderRadius: "100px", overflow: "hidden", marginBottom: "8px" }}>
              <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${st.color}80, ${st.color})`, borderRadius: "100px", boxShadow: `0 0 10px ${st.color}80` }} />
            </div>
            <div style={{ fontSize: "10px", color: T.text3 }}>{op.status}</div>
          </>
        ) : (
          <div style={{ padding: "20px 0", textAlign: "center", fontSize: "11px", color: wc.status === "down" || wc.status === "offline" ? T.red : T.text3, fontWeight: 500 }}>
            {wc.status === "down" || wc.status === "offline" ? "⚠ Maintenance" : "Awaiting Assignment"}
          </div>
        )}
      </div>
      {wc.queue_depth > 0 && (
        <div style={{ padding: "8px 18px", background: "rgba(0,0,0,0.3)", borderTop: "1px solid rgba(255,255,255,0.04)", fontSize: "10px", color: T.text3, display: "flex", justifyContent: "space-between" }}>
          <span style={{ letterSpacing: "0.1em", fontWeight: 700 }}>QUEUE</span>
          <span>{wc.queue_depth} job{wc.queue_depth !== 1 ? "s" : ""} waiting</span>
        </div>
      )}
    </div>
  );
}

function ShopFloorScreen() {
  const [wcs, setWcs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/operator/work-centers`, { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then(data => { setWcs(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const running = wcs.filter(w => w.status === "running" || w.status === "active").length;
  const idle = wcs.filter(w => w.status === "idle").length;
  const down = wcs.filter(w => w.status === "down" || w.status === "offline").length;
  const queueTotal = wcs.reduce((s, w) => s + (w.queue_depth || 0), 0);

  return (
    <div style={{ padding: "24px 28px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "12px", marginBottom: "20px" }}>
        <StatCard label="WORK CENTERS" value={`${running}/${wcs.length}`} sub="active now" color={T.green} spark={[4,5,5,6,5,6,6,running]} />
        <StatCard label="RUNNING" value={running} sub="in production" color={T.green} spark={[3,4,3,5,4,5,5,running]} />
        <StatCard label="IDLE" value={idle} sub="awaiting jobs" color={T.amber} spark={[2,1,2,1,2,1,1,idle]} />
        <StatCard label="DOWN" value={down} sub="maintenance" color={T.red} spark={[0,1,0,0,1,0,0,down]} />
        <StatCard label="QUEUE DEPTH" value={queueTotal} sub="jobs waiting" color={T.blue} spark={[8,10,9,12,11,13,12,queueTotal]} />
      </div>
      {loading ? <Spinner /> : wcs.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: T.text3, fontSize: "13px" }}>
          No work centers configured.{" "}
          <button onClick={() => {}} style={{ color: T.brand, background: "none", border: "none", cursor: "pointer", fontSize: "13px" }}>Add one in Operators →</button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "14px" }}>
          {wcs.map(wc => <WorkCenterCard key={wc.id} wc={wc} />)}
        </div>
      )}
    </div>
  );
}

// ─── Screen: Schedule (existing component) ───────────────────────────────────
function ScheduleScreen() {
  return (
    <div style={{ padding: "24px 28px" }}>
      <Suspense fallback={<Spinner />}>
        <ScheduleViewer />
      </Suspense>
    </div>
  );
}

// ─── Screen: Jobs (existing component) ───────────────────────────────────────
function JobsScreen() {
  return (
    <div style={{ padding: "24px 28px" }}>
      <Suspense fallback={<Spinner />}>
        <JobsPage />
      </Suspense>
    </div>
  );
}

// ─── Screen: Quotes ───────────────────────────────────────────────────────────
const QUOTE_STATUS = {
  draft:    { label: "DRAFT",    color: T.text3 },
  sent:     { label: "SENT",     color: T.blue },
  accepted: { label: "ACCEPTED", color: T.green },
  rejected: { label: "REJECTED", color: T.red },
};

const MOCK_QUOTES = [
  { id: "Q-2241", customer: "Pratt & Whitney",   part: "Turbine Mount Bracket", qty: 24, material: "6061-T6",             value: 38400, status: "accepted", due: "Apr 22", ops: 5 },
  { id: "Q-2242", customer: "General Dynamics",  part: "Gearbox Cover",         qty: 8,  material: "4140 Steel",          value: 12800, status: "sent",     due: "Apr 25", ops: 4 },
  { id: "Q-2243", customer: "Raytheon",          part: "Sensor Housing",        qty: 50, material: "7075-T6",             value: 27500, status: "draft",    due: "Apr 30", ops: 6 },
  { id: "Q-2244", customer: "Lockheed Martin",   part: "Actuator Bracket",      qty: 12, material: "Titanium Ti-6Al-4V",  value: 54000, status: "sent",     due: "May 2",  ops: 7 },
  { id: "Q-2245", customer: "Parker Hannifin",   part: "Valve Body",            qty: 30, material: "Stainless 316L",      value: 19500, status: "rejected", due: "Apr 18", ops: 5 },
  { id: "Q-2246", customer: "Boeing",            part: "Rib Gusset",            qty: 100,material: "2024-T4",             value: 44000, status: "accepted", due: "May 8",  ops: 3 },
  { id: "Q-2247", customer: "Honeywell",         part: "Manifold Block",        qty: 6,  material: "Stainless 304",       value: 9600,  status: "draft",    due: "May 15", ops: 8 },
];

function QuotesScreen() {
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const filtered = filter === "all" ? MOCK_QUOTES : MOCK_QUOTES.filter(q => q.status === filter);
  const pipeline = MOCK_QUOTES.filter(q => q.status === "sent").reduce((s, q) => s + q.value, 0);
  const won = MOCK_QUOTES.filter(q => q.status === "accepted").reduce((s, q) => s + q.value, 0);
  const closed = MOCK_QUOTES.filter(q => ["accepted", "rejected"].includes(q.status));
  const winRate = closed.length ? Math.round(MOCK_QUOTES.filter(q => q.status === "accepted").length / closed.length * 100) : 0;
  const avgVal = Math.round(MOCK_QUOTES.reduce((s, q) => s + q.value, 0) / MOCK_QUOTES.length / 100) * 100;
  const q = selected;
  const qs = q ? QUOTE_STATUS[q.status] : null;

  return (
    <div style={{ padding: "24px 28px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "20px" }}>
        <StatCard label="OPEN PIPELINE" value={`$${(pipeline/1000).toFixed(0)}K`} sub="awaiting response" color={T.blue}  spark={[180,210,195,240,220,260,248,pipeline/1000]} />
        <StatCard label="WON THIS MONTH" value={`$${(won/1000).toFixed(0)}K`}    sub="accepted quotes"  color={T.green} spark={[40,55,48,62,58,70,75,won/1000]} />
        <StatCard label="WIN RATE"        value={`${winRate}%`}                   sub="accepted / closed" color={T.brand} spark={[58,62,55,67,60,65,68,winRate]} />
        <StatCard label="AVG QUOTE VALUE" value={`$${(avgVal/1000).toFixed(1)}K`} sub="all quotes"        color={T.amber} spark={[14,16,15,18,17,19,18,avgVal/1000]} />
      </div>

      {/* Detail panel */}
      {q && (
        <div style={{ marginBottom: "20px", background: `linear-gradient(180deg, ${T.bg3} 0%, ${T.bg2} 100%)`, borderRadius: "14px", border: `1px solid ${qs.color}30`, boxShadow: `0 0 0 1px ${qs.color}10, 0 8px 24px rgba(0,0,0,0.5)`, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "11px", color: T.text3, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700 }}>{q.id}</span>
            <span style={{ fontSize: "14px", color: T.text0, fontWeight: 600 }}>{q.part}</span>
            <Badge label={qs.label} color={qs.color} />
            <button onClick={() => setSelected(null)} style={{ marginLeft: "auto", background: "none", border: "none", color: T.text3, fontSize: "16px", cursor: "pointer", lineHeight: 1 }}>×</button>
          </div>
          <div style={{ padding: "20px", display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "16px" }}>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>CUSTOMER</div>
              <div style={{ fontSize: "14px", color: T.text0, fontWeight: 500 }}>{q.customer}</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>MATERIAL</div>
              <div style={{ fontSize: "14px", color: T.text0 }}>{q.material}</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>QTY × UNIT</div>
              <div style={{ fontSize: "14px", color: T.text0, fontFamily: "'JetBrains Mono', monospace" }}>{q.qty} × ${(q.value / q.qty / 1000).toFixed(2)}K</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>TOTAL VALUE</div>
              <div style={{ fontSize: "20px", color: T.brand, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>${(q.value / 1000).toFixed(1)}K</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>OPERATIONS</div>
              <div style={{ fontSize: "14px", color: T.text0, fontFamily: "'JetBrains Mono', monospace" }}>{q.ops} ops</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>VALID UNTIL</div>
              <div style={{ fontSize: "14px", color: T.text0 }}>{q.due}</div>
            </div>
            <div style={{ gridColumn: "3 / 5", display: "flex", gap: "8px", alignItems: "flex-end" }}>
              {q.status === "draft" && <button style={{ padding: "8px 18px", borderRadius: "8px", border: "none", background: `linear-gradient(135deg, ${T.brand}, ${T.brand}D0)`, color: "#fff", fontSize: "11px", fontWeight: 700, cursor: "pointer", boxShadow: `0 4px 12px ${T.brandGlow}` }}>Send to Customer</button>}
              {q.status === "sent"  && <button style={{ padding: "8px 18px", borderRadius: "8px", border: "none", background: `linear-gradient(135deg, ${T.green}, ${T.green}D0)`, color: "#fff", fontSize: "11px", fontWeight: 700, cursor: "pointer" }}>Mark Accepted</button>}
              <button style={{ padding: "8px 14px", borderRadius: "8px", border: `1px solid ${T.border}`, background: "transparent", color: T.text2, fontSize: "11px", cursor: "pointer" }}>Duplicate</button>
              <button style={{ padding: "8px 14px", borderRadius: "8px", border: `1px solid ${T.border}`, background: "transparent", color: T.text2, fontSize: "11px", cursor: "pointer" }}>Edit</button>
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: "6px", marginBottom: "16px" }}>
        {[{ id: "all", label: "All" }, { id: "draft", label: "Draft" }, { id: "sent", label: "Sent" }, { id: "accepted", label: "Accepted" }, { id: "rejected", label: "Rejected" }].map(f => (
          <button key={f.id} onClick={() => setFilter(f.id)} style={{ padding: "7px 14px", borderRadius: "8px", border: `1px solid ${filter === f.id ? T.brand : T.border}`, background: filter === f.id ? `${T.brand}15` : "rgba(255,255,255,0.02)", color: filter === f.id ? T.brand : T.text2, fontSize: "11px", fontWeight: 600, cursor: "pointer" }}>
            {f.label}
          </button>
        ))}
        <button style={{ marginLeft: "auto", padding: "7px 16px", borderRadius: "8px", border: "none", background: `linear-gradient(135deg, ${T.brand}, ${T.brand}D0)`, color: "#fff", fontSize: "11px", fontWeight: 700, cursor: "pointer", boxShadow: `0 4px 12px ${T.brandGlow}` }}>
          + NEW QUOTE
        </button>
      </div>
      <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "14px", border: `1px solid ${T.border}`, overflow: "hidden", boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "90px 1.5fr 2fr 70px 100px 110px 60px 110px", padding: "12px 20px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`, fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em" }}>
          <div>QUOTE #</div><div>PART</div><div>CUSTOMER</div><div>QTY</div><div>VALUE</div><div>STATUS</div><div>OPS</div><div>VALID UNTIL</div>
        </div>
        {filtered.map((row, i) => {
          const rqs = QUOTE_STATUS[row.status];
          const isSelected = selected?.id === row.id;
          return (
            <div key={row.id}
              onClick={() => setSelected(isSelected ? null : row)}
              style={{ display: "grid", gridTemplateColumns: "90px 1.5fr 2fr 70px 100px 110px 60px 110px", padding: "14px 20px", borderBottom: i < filtered.length - 1 ? `1px solid ${T.border}` : "none", alignItems: "center", cursor: "pointer", transition: "background 0.15s", background: isSelected ? `${T.brand}08` : "transparent", borderLeft: isSelected ? `2px solid ${T.brand}` : "2px solid transparent" }}
              onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.025)"; }}
              onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ fontSize: "11px", color: T.text2, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{row.id}</div>
              <div>
                <div style={{ fontSize: "13px", color: T.text0, fontWeight: 500 }}>{row.part}</div>
                <div style={{ fontSize: "10px", color: T.text4, marginTop: "1px" }}>{row.material}</div>
              </div>
              <div style={{ fontSize: "12px", color: T.text2 }}>{row.customer}</div>
              <div style={{ fontSize: "12px", color: T.text2, fontFamily: "'JetBrains Mono', monospace" }}>{row.qty}</div>
              <div style={{ fontSize: "14px", color: T.text0, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>${(row.value / 1000).toFixed(1)}K</div>
              <div><Badge label={rqs.label} color={rqs.color} /></div>
              <div style={{ fontSize: "11px", color: T.text3, fontFamily: "'JetBrains Mono', monospace" }}>{row.ops}</div>
              <div style={{ fontSize: "11px", color: T.text2 }}>{row.due}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Screen: Quality (existing component) ────────────────────────────────────
function QualityScreen() {
  return (
    <div style={{ padding: "24px 28px" }}>
      <Suspense fallback={<Spinner />}>
        <QualityHub />
      </Suspense>
    </div>
  );
}

// ─── Screen: Materials ────────────────────────────────────────────────────────
const MOCK_MATS = [
  { name: "Aluminum 6061-T6",         form: "Round Bar",  size: "2\" dia",          qty: 47, unit: "bars",   reorder: 10, cost: "$4.20/lb",  status: "ok" },
  { name: "Aluminum 7075-T6",         form: "Round Bar",  size: "3\" dia",          qty: 12, unit: "bars",   reorder: 8,  cost: "$6.80/lb",  status: "ok" },
  { name: "Aluminum 2024-T4",         form: "Sheet",      size: "0.125\"×48\"×96\"",qty: 6,  unit: "sheets", reorder: 5,  cost: "$5.40/lb",  status: "ok" },
  { name: "Stainless 304",            form: "Round Bar",  size: "1.5\" dia",        qty: 28, unit: "bars",   reorder: 8,  cost: "$9.20/lb",  status: "ok" },
  { name: "Stainless 316L",           form: "Round Bar",  size: "2\" dia",          qty: 9,  unit: "bars",   reorder: 10, cost: "$11.40/lb", status: "low" },
  { name: "4140 Steel",               form: "Round Bar",  size: "2.5\" dia",        qty: 34, unit: "bars",   reorder: 12, cost: "$2.80/lb",  status: "ok" },
  { name: "Titanium Ti-6Al-4V",       form: "Round Bar",  size: "1\" dia",          qty: 4,  unit: "bars",   reorder: 6,  cost: "$42.00/lb", status: "critical" },
  { name: "Brass 360",                form: "Hex Bar",    size: "1\" AF",           qty: 18, unit: "bars",   reorder: 6,  cost: "$5.60/lb",  status: "ok" },
  { name: "Delrin (POM)",             form: "Round Rod",  size: "2\" dia",          qty: 22, unit: "rods",   reorder: 8,  cost: "$3.20/lb",  status: "ok" },
];
const MAT_COLOR = { ok: T.green, low: T.amber, critical: T.red };

function MaterialsScreen() {
  const [selected, setSelected] = useState(null);
  const m = selected;
  const sc = m ? MAT_COLOR[m.status] : null;

  return (
    <div style={{ padding: "24px 28px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "20px" }}>
        <StatCard label="MATERIALS"       value={MOCK_MATS.length}  sub="in inventory"          color={T.blue}  spark={[7,8,8,9,8,9,9,MOCK_MATS.length]} />
        <StatCard label="LOW STOCK"       value="2"                  sub="at or below reorder"   color={T.amber} spark={[1,0,1,2,1,1,2,2]} />
        <StatCard label="CRITICAL"        value="1"                  sub="titanium — order now"  color={T.red}   spark={[0,0,1,0,0,1,1,1]} />
        <StatCard label="INVENTORY VALUE" value="$28.4K"             sub="estimated on-hand"     color={T.green} spark={[24,26,25,27,26,28,27,28]} />
      </div>

      {m && (
        <div style={{ marginBottom: "20px", background: `linear-gradient(180deg, ${T.bg3} 0%, ${T.bg2} 100%)`, borderRadius: "14px", border: `1px solid ${sc}30`, boxShadow: `0 0 0 1px ${sc}10, 0 8px 24px rgba(0,0,0,0.5)`, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "14px", color: T.text0, fontWeight: 600 }}>{m.name}</span>
            <Badge label={m.status.toUpperCase()} color={sc} />
            {m.status === "critical" && <span style={{ fontSize: "11px", color: T.red }}>⚠ Below reorder point — action required</span>}
            {m.status === "low"      && <span style={{ fontSize: "11px", color: T.amber }}>Stock approaching reorder threshold</span>}
            <button onClick={() => setSelected(null)} style={{ marginLeft: "auto", background: "none", border: "none", color: T.text3, fontSize: "16px", cursor: "pointer", lineHeight: 1 }}>×</button>
          </div>
          <div style={{ padding: "20px", display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "16px" }}>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>FORM</div>
              <div style={{ fontSize: "14px", color: T.text0 }}>{m.form}</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>SIZE</div>
              <div style={{ fontSize: "14px", color: T.text0, fontFamily: "'JetBrains Mono', monospace" }}>{m.size}</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>ON HAND</div>
              <div style={{ fontSize: "20px", color: sc, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{m.qty} <span style={{ fontSize: "12px", fontWeight: 400, color: T.text3 }}>{m.unit}</span></div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>UNIT COST</div>
              <div style={{ fontSize: "14px", color: T.text0, fontFamily: "'JetBrains Mono', monospace" }}>{m.cost}</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>REORDER POINT</div>
              <div style={{ fontSize: "14px", color: T.text3, fontFamily: "'JetBrains Mono', monospace" }}>{m.reorder} {m.unit}</div>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "5px" }}>WEEKS REMAINING</div>
              <div style={{ fontSize: "14px", color: T.text0, fontFamily: "'JetBrains Mono', monospace" }}>{m.qty > 0 ? `~${Math.max(1, Math.round(m.qty / 4))} wk` : "—"}</div>
            </div>
            <div style={{ gridColumn: "3 / 5", display: "flex", gap: "8px", alignItems: "flex-end" }}>
              {(m.status === "critical" || m.status === "low") && (
                <button style={{ padding: "8px 18px", borderRadius: "8px", border: "none", background: `linear-gradient(135deg, ${T.brand}, ${T.brand}D0)`, color: "#fff", fontSize: "11px", fontWeight: 700, cursor: "pointer", boxShadow: `0 4px 12px ${T.brandGlow}` }}>Place Reorder</button>
              )}
              <button style={{ padding: "8px 14px", borderRadius: "8px", border: `1px solid ${T.border}`, background: "transparent", color: T.text2, fontSize: "11px", cursor: "pointer" }}>Adjust Count</button>
              <button style={{ padding: "8px 14px", borderRadius: "8px", border: `1px solid ${T.border}`, background: "transparent", color: T.text2, fontSize: "11px", cursor: "pointer" }}>View History</button>
            </div>
          </div>
        </div>
      )}

      <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "14px", border: `1px solid ${T.border}`, overflow: "hidden", boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1.5fr 70px 70px 100px 80px 80px", padding: "12px 20px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`, fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em" }}>
          <div>MATERIAL</div><div>FORM</div><div>SIZE</div><div>QTY</div><div>UNIT</div><div>UNIT COST</div><div>REORDER</div><div>STATUS</div>
        </div>
        {MOCK_MATS.map((row, i) => {
          const rowColor = MAT_COLOR[row.status];
          const isSelected = selected?.name === row.name;
          return (
            <div key={row.name}
              onClick={() => setSelected(isSelected ? null : row)}
              style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1.5fr 70px 70px 100px 80px 80px", padding: "13px 20px", borderBottom: i < MOCK_MATS.length - 1 ? `1px solid ${T.border}` : "none", alignItems: "center", cursor: "pointer", transition: "background 0.15s", background: isSelected ? `${rowColor}06` : "transparent", borderLeft: isSelected ? `2px solid ${rowColor}` : "2px solid transparent" }}
              onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
              onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ fontSize: "13px", color: T.text0, fontWeight: 500 }}>{row.name}</div>
              <div style={{ fontSize: "11px", color: T.text2 }}>{row.form}</div>
              <div style={{ fontSize: "11px", color: T.text2, fontFamily: "'JetBrains Mono', monospace" }}>{row.size}</div>
              <div style={{ fontSize: "14px", color: row.status === "critical" ? T.red : row.status === "low" ? T.amber : T.text0, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{row.qty}</div>
              <div style={{ fontSize: "10px", color: T.text3 }}>{row.unit}</div>
              <div style={{ fontSize: "11px", color: T.text2, fontFamily: "'JetBrains Mono', monospace" }}>{row.cost}</div>
              <div style={{ fontSize: "11px", color: T.text3, fontFamily: "'JetBrains Mono', monospace" }}>{row.reorder}</div>
              <div><Badge label={row.status.toUpperCase()} color={rowColor} /></div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Screen: Analytics (existing components) ─────────────────────────────────
function AnalyticsScreen() {
  return (
    <div style={{ padding: "24px 28px" }}>
      <Suspense fallback={<Spinner />}>
        <DashboardPage />
        <div style={{ marginTop: "24px" }}>
          <QCAnalyticsPage />
        </div>
      </Suspense>
    </div>
  );
}

// ─── Screen: Operators ────────────────────────────────────────────────────────
function OperatorsScreen() {
  const [operators, setOperators] = useState([]);
  const [workCenters, setWorkCenters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("operators");
  const [showAddOp, setShowAddOp] = useState(false);
  const [showAddWC, setShowAddWC] = useState(false);
  const [opForm, setOpForm] = useState({ name: "", employee_id: "", pin_code: "", qualifications_json: [] });
  const [wcForm, setWcForm] = useState({ name: "", category: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const WC_CATEGORIES = ["CNC Mill", "CNC Lathe", "Laser Cutter", "Press Brake", "Welding", "Grinding", "Assembly", "Inspection"];

  const load = () => {
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/api/operator/operators`, { credentials: "include" }).then(r => r.ok ? r.json() : []),
      fetch(`${API_BASE}/api/operator/work-centers`, { credentials: "include" }).then(r => r.ok ? r.json() : []),
    ]).then(([ops, wcs]) => {
      setOperators(ops);
      setWorkCenters(wcs);
      setLoading(false);
    }).catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleAddOperator = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/operator/operators`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ ...opForm, user_id: 1 }),
      });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
      setShowAddOp(false);
      setOpForm({ name: "", employee_id: "", pin_code: "", qualifications_json: [] });
      load();
    } catch (err) { setError(err.message); }
    setSaving(false);
  };

  const handleAddWorkCenter = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/operator/work-centers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(wcForm),
      });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
      setShowAddWC(false);
      setWcForm({ name: "", category: "", description: "" });
      load();
    } catch (err) { setError(err.message); }
    setSaving(false);
  };

  const inputStyle = {
    width: "100%", background: T.bg3, border: `1px solid ${T.border}`, borderRadius: "8px",
    padding: "10px 12px", color: T.text0, fontSize: "13px", outline: "none",
  };
  const labelStyle = { fontSize: "11px", color: T.text2, fontWeight: 600, marginBottom: "6px", display: "block", letterSpacing: "0.04em" };

  return (
    <div style={{ padding: "24px 28px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px", marginBottom: "20px" }}>
        <StatCard label="OPERATORS"    value={operators.length}   sub="registered"      color={T.brand} spark={[3,4,4,5,5,6,6,operators.length]} />
        <StatCard label="WORK CENTERS" value={workCenters.length} sub="configured"      color={T.blue}  spark={[2,3,3,4,4,5,5,workCenters.length]} />
        <StatCard label="ACTIVE"       value={workCenters.filter(w => w.status === "active" || w.status === "running").length} sub="running now" color={T.green} spark={[1,2,2,3,2,3,3,2]} />
        <StatCard label="IDLE"         value={workCenters.filter(w => w.status === "idle").length} sub="available"  color={T.amber} spark={[1,1,2,1,1,2,1,1]} />
      </div>

      {/* Tab strip */}
      <div style={{ display: "flex", gap: "6px", marginBottom: "16px" }}>
        {[{ id: "operators", label: "Operators" }, { id: "workcenters", label: "Work Centers" }].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{ padding: "7px 16px", borderRadius: "8px", border: `1px solid ${tab === t.id ? T.brand : T.border}`, background: tab === t.id ? `${T.brand}15` : "rgba(255,255,255,0.02)", color: tab === t.id ? T.brand : T.text2, fontSize: "11px", fontWeight: 600, cursor: "pointer" }}>
            {t.label}
          </button>
        ))}
        <button
          onClick={() => { setError(null); tab === "operators" ? setShowAddOp(v => !v) : setShowAddWC(v => !v); }}
          style={{ marginLeft: "auto", padding: "7px 16px", borderRadius: "8px", border: "none", background: `linear-gradient(135deg, ${T.brand}, ${T.brand}D0)`, color: "#fff", fontSize: "11px", fontWeight: 700, cursor: "pointer", boxShadow: `0 4px 12px ${T.brandGlow}` }}
        >
          + ADD {tab === "operators" ? "OPERATOR" : "WORK CENTER"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div style={{ marginBottom: "12px", padding: "10px 14px", background: `${T.red}15`, border: `1px solid ${T.red}30`, borderRadius: "8px", fontSize: "12px", color: T.red }}>
          {error}
        </div>
      )}

      {/* Add Operator form */}
      {showAddOp && (
        <form onSubmit={handleAddOperator} style={{ marginBottom: "16px", background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "12px", border: `1px solid ${T.borderHi}`, padding: "20px" }}>
          <div style={{ fontSize: "12px", color: T.text1, fontWeight: 600, marginBottom: "16px" }}>New Operator</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", marginBottom: "16px" }}>
            <div>
              <label style={labelStyle}>NAME</label>
              <input style={inputStyle} required value={opForm.name} onChange={e => setOpForm(p => ({ ...p, name: e.target.value }))} placeholder="Mike Torres" />
            </div>
            <div>
              <label style={labelStyle}>EMPLOYEE ID</label>
              <input style={inputStyle} value={opForm.employee_id} onChange={e => setOpForm(p => ({ ...p, employee_id: e.target.value }))} placeholder="EMP-001" />
            </div>
            <div>
              <label style={labelStyle}>PIN CODE</label>
              <input style={inputStyle} type="password" required minLength={4} maxLength={8} value={opForm.pin_code} onChange={e => setOpForm(p => ({ ...p, pin_code: e.target.value }))} placeholder="4–8 digits" />
            </div>
          </div>
          <div style={{ marginBottom: "16px" }}>
            <label style={labelStyle}>QUALIFICATIONS</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {WC_CATEGORIES.map(cat => {
                const active = opForm.qualifications_json.includes(cat);
                return (
                  <button key={cat} type="button" onClick={() => setOpForm(p => ({ ...p, qualifications_json: active ? p.qualifications_json.filter(c => c !== cat) : [...p.qualifications_json, cat] }))}
                    style={{ padding: "5px 12px", borderRadius: "7px", border: `1px solid ${active ? T.brand : T.border}`, background: active ? `${T.brand}15` : "rgba(255,255,255,0.02)", color: active ? T.brand : T.text3, fontSize: "11px", fontWeight: 600, cursor: "pointer" }}>
                    {cat}
                  </button>
                );
              })}
            </div>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="submit" disabled={saving} style={{ padding: "8px 20px", borderRadius: "8px", border: "none", background: T.brand, color: "#fff", fontSize: "12px", fontWeight: 700, cursor: "pointer", opacity: saving ? 0.6 : 1 }}>
              {saving ? "Saving..." : "Add Operator"}
            </button>
            <button type="button" onClick={() => setShowAddOp(false)} style={{ padding: "8px 16px", borderRadius: "8px", border: `1px solid ${T.border}`, background: "transparent", color: T.text2, fontSize: "12px", cursor: "pointer" }}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Add Work Center form */}
      {showAddWC && (
        <form onSubmit={handleAddWorkCenter} style={{ marginBottom: "16px", background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "12px", border: `1px solid ${T.borderHi}`, padding: "20px" }}>
          <div style={{ fontSize: "12px", color: T.text1, fontWeight: 600, marginBottom: "16px" }}>New Work Center</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 2fr", gap: "12px", marginBottom: "16px" }}>
            <div>
              <label style={labelStyle}>NAME</label>
              <input style={inputStyle} required value={wcForm.name} onChange={e => setWcForm(p => ({ ...p, name: e.target.value }))} placeholder="HAAS VF-2" />
            </div>
            <div>
              <label style={labelStyle}>CATEGORY</label>
              <select style={{ ...inputStyle, cursor: "pointer" }} required value={wcForm.category} onChange={e => setWcForm(p => ({ ...p, category: e.target.value }))}>
                <option value="">Select...</option>
                {WC_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>DESCRIPTION</label>
              <input style={inputStyle} value={wcForm.description} onChange={e => setWcForm(p => ({ ...p, description: e.target.value }))} placeholder="Optional description" />
            </div>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="submit" disabled={saving} style={{ padding: "8px 20px", borderRadius: "8px", border: "none", background: T.brand, color: "#fff", fontSize: "12px", fontWeight: 700, cursor: "pointer", opacity: saving ? 0.6 : 1 }}>
              {saving ? "Saving..." : "Add Work Center"}
            </button>
            <button type="button" onClick={() => setShowAddWC(false)} style={{ padding: "8px 16px", borderRadius: "8px", border: `1px solid ${T.border}`, background: "transparent", color: T.text2, fontSize: "12px", cursor: "pointer" }}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading ? <Spinner /> : (
        <>
          {/* Operators table */}
          {tab === "operators" && (
            <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "14px", border: `1px solid ${T.border}`, overflow: "hidden", boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "48px 2fr 120px 1fr 2fr 100px", padding: "12px 20px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`, fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em" }}>
                <div></div><div>NAME</div><div>EMPLOYEE ID</div><div>INITIALS</div><div>QUALIFICATIONS</div><div>ACTIVE</div>
              </div>
              {operators.length === 0 ? (
                <div style={{ padding: "40px 20px", textAlign: "center", color: T.text3, fontSize: "12px" }}>No operators yet. Add one above.</div>
              ) : operators.map((op, i) => (
                <div key={op.id} style={{ display: "grid", gridTemplateColumns: "48px 2fr 120px 1fr 2fr 100px", padding: "14px 20px", borderBottom: i < operators.length - 1 ? `1px solid ${T.border}` : "none", alignItems: "center" }}>
                  <div style={{ width: "30px", height: "30px", borderRadius: "8px", background: `linear-gradient(135deg, ${T.brand}30, ${T.brand}10)`, border: `1px solid ${T.brand}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "11px", color: T.brand, fontWeight: 700 }}>
                    {op.initials}
                  </div>
                  <div style={{ fontSize: "13px", color: T.text0, fontWeight: 500 }}>{op.name}</div>
                  <div style={{ fontSize: "11px", color: T.text2, fontFamily: "'JetBrains Mono', monospace" }}>{op.employee_id || "—"}</div>
                  <div style={{ fontSize: "12px", color: T.text2, fontFamily: "'JetBrains Mono', monospace" }}>{op.initials}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                    {(op.qualifications_json || []).slice(0, 4).map(q => (
                      <span key={q} style={{ fontSize: "9px", padding: "2px 7px", borderRadius: "100px", background: `${T.blue}15`, color: T.blue, border: `1px solid ${T.blue}30`, fontWeight: 600 }}>{q}</span>
                    ))}
                    {(op.qualifications_json || []).length > 4 && (
                      <span style={{ fontSize: "9px", color: T.text3 }}>+{op.qualifications_json.length - 4}</span>
                    )}
                    {(!op.qualifications_json || op.qualifications_json.length === 0) && (
                      <span style={{ fontSize: "10px", color: T.text4 }}>All work centers</span>
                    )}
                  </div>
                  <div><Badge label={op.is_active !== false ? "ACTIVE" : "INACTIVE"} color={op.is_active !== false ? T.green : T.text3} /></div>
                </div>
              ))}
            </div>
          )}

          {/* Work Centers table */}
          {tab === "workcenters" && (
            <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, borderRadius: "14px", border: `1px solid ${T.border}`, overflow: "hidden", boxShadow: "0 8px 24px rgba(0,0,0,0.4)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1.5fr 1fr 100px 120px", padding: "12px 20px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`, fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em" }}>
                <div>NAME</div><div>CATEGORY</div><div>ACTIVE OP</div><div>QUEUE</div><div>STATUS</div>
              </div>
              {workCenters.length === 0 ? (
                <div style={{ padding: "40px 20px", textAlign: "center", color: T.text3, fontSize: "12px" }}>No work centers yet. Add one above.</div>
              ) : workCenters.map((wc, i) => {
                const st = STATUS_MAP[wc.status] || STATUS_MAP.idle;
                return (
                  <div key={wc.id} style={{ display: "grid", gridTemplateColumns: "2fr 1.5fr 1fr 100px 120px", padding: "14px 20px", borderBottom: i < workCenters.length - 1 ? `1px solid ${T.border}` : "none", alignItems: "center" }}>
                    <div style={{ fontSize: "13px", color: T.text0, fontWeight: 500 }}>{wc.name}</div>
                    <div style={{ fontSize: "12px", color: T.text2 }}>{wc.category}</div>
                    <div style={{ fontSize: "11px", color: wc.active_operation ? T.text1 : T.text4 }}>
                      {wc.active_operation ? wc.active_operation.operation_name : "None"}
                    </div>
                    <div style={{ fontSize: "13px", color: T.text0, fontFamily: "'JetBrains Mono', monospace" }}>{wc.queue_depth || 0}</div>
                    <div><Badge label={st.label} color={st.color} /></div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Lazy wrapper screens (new) ──────────────────────────────────────────────
function OrdersScreen()        { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><OrdersView /></Suspense></div>; }
function NLSchedulerScreen()   { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><NLSchedulerPage /></Suspense></div>; }
function ToolScheduleScreen()  { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><ToolAwareSchedule /></Suspense></div>; }
function FleetScreen()         { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><MachinesPage /></Suspense></div>; }
function OperationsScreen()    { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><OperationsPage /></Suspense></div>; }
function MachHealthScreen()    { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><ToolWearDashboard /></Suspense></div>; }
function ProcessesScreen()     { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><ManufacturingPage /></Suspense></div>; }
function ARIAImportScreen()    { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><ARIAImport /></Suspense></div>; }
function EnergyScreen()        { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><EnergyPage /></Suspense></div>; }
function DiscoveryScreen()     { return <div style={{ padding: "24px 28px" }}><Suspense fallback={<Spinner />}><Discovery /></Suspense></div>; }

// ─── Root ─────────────────────────────────────────────────────────────────────
const SCREEN_MAP = {
  // Production
  floor:      { title: "Shop Floor",     comp: ShopFloorScreen },
  orders:     { title: "Orders",         comp: OrdersScreen },
  jobs:       { title: "Jobs",           comp: JobsScreen },
  quotes:     { title: "Quotes",         comp: QuotesScreen },
  // Schedule
  schedule:   { title: "Schedule",       comp: ScheduleScreen },
  nlsched:    { title: "NL Scheduler",   comp: NLSchedulerScreen },
  toolsched:  { title: "Tool Schedule",  comp: ToolScheduleScreen },
  // Machines
  fleet:      { title: "Fleet",          comp: FleetScreen },
  operations: { title: "Operations",     comp: OperationsScreen },
  machhealth: { title: "Machine Health", comp: MachHealthScreen },
  // Manufacturing
  processes:  { title: "Processes",      comp: ProcessesScreen },
  aria:       { title: "ARIA Import",    comp: ARIAImportScreen },
  energy:     { title: "Energy",         comp: EnergyScreen },
  materials:  { title: "Inventory",      comp: MaterialsScreen },
  // Quality
  quality:    { title: "Quality Suite",  comp: QualityScreen },
  analytics:  { title: "Analytics",      comp: AnalyticsScreen },
  discovery:  { title: "Discovery",      comp: DiscoveryScreen },
  // Operators
  operators:  { title: "Operators",      comp: OperatorsScreen },
};

export default function AppDashboard({ user, onLogout }) {
  const [activeGroup, setActiveGroup] = useState("production");
  const [tabState, setTabState] = useState({});

  const group = NAV_GROUPS.find(g => g.id === activeGroup);
  const activeTab = tabState[activeGroup] || group.tabs[0].id;

  const handleGroupChange = (groupId) => {
    setActiveGroup(groupId);
  };

  const handleTabChange = (tabId) => {
    setTabState(prev => ({ ...prev, [activeGroup]: tabId }));
  };

  const screen = SCREEN_MAP[activeTab];
  const breadcrumb = `${group.label} / ${screen?.title || activeTab}`;
  const Screen = screen?.comp;

  return (
    <div style={{ minHeight: "100vh", background: T.bg0, fontFamily: "'Inter', system-ui, sans-serif", color: T.text0, position: "relative", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
        @keyframes pulse { 0%,100%{opacity:.6} 50%{opacity:1} }
        @keyframes spin   { to{transform:rotate(360deg)} }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,.08); border-radius: 100px; }
      `}</style>

      {/* Ambient glows */}
      <div style={{ position: "fixed", top: "-30%", left: "-20%", width: "60%", height: "60%", background: `radial-gradient(ellipse, ${T.brandGlow} 0%, transparent 60%)`, opacity: 0.06, pointerEvents: "none" }} />
      <div style={{ position: "fixed", bottom: "-30%", right: "-20%", width: "60%", height: "60%", background: `radial-gradient(ellipse, ${T.blueGlow} 0%, transparent 60%)`, opacity: 0.05, pointerEvents: "none" }} />

      <Sidebar activeGroup={activeGroup} setActiveGroup={handleGroupChange} user={user} onLogout={onLogout} />

      <div style={{ marginLeft: "64px" }}>
        <TopBar breadcrumb={breadcrumb} />
        <SubTabBar group={group} activeTab={activeTab} setActiveTab={handleTabChange} />
        {Screen ? <Screen /> : <div style={{ padding: "24px 28px", color: T.text3, fontSize: "13px" }}>Screen not found</div>}
      </div>
    </div>
  );
}
