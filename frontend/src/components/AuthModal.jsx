import { useState } from "react";
import { API_BASE } from "../config";

const T = {
  bg0: "#0A0A0F", bg1: "#0F0F18", bg2: "#15151F", bg3: "#1A1A26",
  border: "rgba(255,255,255,0.06)", borderHi: "rgba(255,255,255,0.12)",
  text0: "#FAFAFA", text1: "#E5E5EA", text2: "#A1A1AA", text3: "#71717A", text4: "#52525B",
  brand: "#FF7A1A", brandGlow: "rgba(255,122,26,0.35)",
  green: "#10B981", amber: "#F59E0B", red: "#EF4444", blue: "#3B82F6",
};

const STATS = [
  { label: "On-Time Delivery", value: "96.4%", sub: "SA optimizer", color: T.green },
  { label: "Improvement", value: "+35.7pp", sub: "over FIFO baseline", color: T.brand },
  { label: "Schedule Latency", value: "<200ms", sub: "28-order dataset", color: T.blue },
];

const MACHINES = [
  { name: "HAAS VF-2",     status: "running", oee: 78, job: "Turbine Mount" },
  { name: "HAAS ST-20Y",   status: "running", oee: 82, job: "Shaft Coupling" },
  { name: "Trumpf 3030",   status: "running", oee: 88, job: "Chassis Panels" },
  { name: "Amada HFE",     status: "setup",   oee: 65, job: "Gearbox Cover" },
  { name: "Miller Dynasty",status: "running", oee: 64, job: "Roll Cage" },
  { name: "HAAS VF-2SS",   status: "idle",    oee: 0,  job: null },
];

const STATUS_DOT = {
  running: T.green,
  setup:   T.amber,
  idle:    T.text4,
};

export default function AuthModal({ onSuccess, onClose }) {
  // mode: "login" | "register" | "forgot"
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", name: "", company: "" });
  const [rememberMe, setRememberMe] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [forgotSent, setForgotSent] = useState(false);

  const handleChange = (e) => setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    // Forgot password flow
    if (mode === "forgot") {
      try {
        await fetch(`${API_BASE}/api/auth/forgot-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: form.email }),
        });
        setForgotSent(true);
      } catch {
        setForgotSent(true); // show success even on network error — prevents enumeration
      } finally {
        setLoading(false);
      }
      return;
    }

    // Login / register flow
    const url = mode === "login" ? `${API_BASE}/api/auth/login` : `${API_BASE}/api/auth/register`;
    const body = mode === "login"
      ? { email: form.email, password: form.password, remember_me: rememberMe }
      : { email: form.email, password: form.password, name: form.name, company: form.company || undefined };
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const text = await res.text();
      const data = text ? JSON.parse(text) : {};
      if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);
      onSuccess(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (m) => { setMode(m); setError(null); setForgotSent(false); };

  const inputStyle = {
    width: "100%",
    background: T.bg3,
    border: `1px solid ${T.border}`,
    borderRadius: "10px",
    padding: "12px 14px",
    color: T.text0,
    fontSize: "14px",
    outline: "none",
    transition: "border-color 0.15s",
    fontFamily: "inherit",
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: T.bg0, display: "flex", fontFamily: "'Inter', system-ui, sans-serif", zIndex: 9999 }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        @keyframes pulse { 0%,100%{opacity:.5} 50%{opacity:1} }
        @keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
        * { box-sizing: border-box; }
        input::placeholder { color: ${T.text4}; }
        input:focus { border-color: ${T.brand} !important; box-shadow: 0 0 0 3px ${T.brandGlow}30; }
      `}</style>

      {/* ── Left panel — dashboard preview ── */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", display: "flex", flexDirection: "column", justifyContent: "center", padding: "60px 56px", borderRight: `1px solid ${T.border}` }}>

        {/* Ambient glows */}
        <div style={{ position: "absolute", top: "-20%", left: "-10%", width: "70%", height: "70%", background: `radial-gradient(ellipse, ${T.brandGlow} 0%, transparent 65%)`, opacity: 0.12, pointerEvents: "none" }} />
        <div style={{ position: "absolute", bottom: "-20%", right: "-10%", width: "60%", height: "60%", background: `radial-gradient(ellipse, rgba(59,130,246,0.35) 0%, transparent 65%)`, opacity: 0.08, pointerEvents: "none" }} />

        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "48px" }}>
          <div style={{ width: "40px", height: "40px", borderRadius: "12px", background: `linear-gradient(135deg, ${T.brand}, ${T.brand}80)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "18px", color: "#fff", fontWeight: 700, boxShadow: `0 0 28px ${T.brandGlow}` }}>◆</div>
          <div>
            <span style={{ fontSize: "20px", fontWeight: 700, color: T.text0, letterSpacing: "-0.02em" }}>Mill</span>
            <span style={{ fontSize: "20px", fontWeight: 700, color: T.brand, letterSpacing: "-0.02em" }}>Forge AI</span>
          </div>
        </div>

        {/* Headline */}
        <h1 style={{ fontSize: "36px", fontWeight: 700, color: T.text0, lineHeight: 1.15, letterSpacing: "-0.03em", marginBottom: "16px", maxWidth: "440px" }}>
          The intelligence layer for lights-out metal mills.
        </h1>
        <p style={{ fontSize: "15px", color: T.text2, lineHeight: 1.6, marginBottom: "40px", maxWidth: "400px" }}>
          AI scheduling, real-time shop floor visibility, and automated quoting — on top of your existing machines.
        </p>

        {/* Stats */}
        <div style={{ display: "flex", gap: "12px", marginBottom: "36px" }}>
          {STATS.map(s => (
            <div key={s.label} style={{ flex: 1, background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, border: `1px solid ${T.border}`, borderRadius: "12px", padding: "14px 16px", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "1px", background: `linear-gradient(90deg, transparent, ${s.color}60, transparent)` }} />
              <div style={{ fontSize: "22px", fontWeight: 700, color: s.color, letterSpacing: "-0.02em", fontFeatureSettings: "'tnum'", marginBottom: "4px" }}>{s.value}</div>
              <div style={{ fontSize: "11px", color: T.text0, fontWeight: 600, marginBottom: "2px" }}>{s.label}</div>
              <div style={{ fontSize: "10px", color: T.text3 }}>{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Mini machine grid */}
        <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "10px" }}>LIVE SHOP FLOOR</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px" }}>
          {MACHINES.map(m => {
            const dot = STATUS_DOT[m.status];
            const oeeColor = m.oee >= 75 ? T.green : m.oee >= 50 ? T.amber : m.oee > 0 ? T.red : T.text4;
            return (
              <div key={m.name} style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, border: `1px solid ${T.border}`, borderRadius: "10px", padding: "10px 12px", animation: m.status === "running" ? "float 4s ease-in-out infinite" : "none", animationDelay: `${MACHINES.indexOf(m) * 0.4}s` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                  <span style={{ fontSize: "10px", color: T.text1, fontWeight: 600 }}>{m.name}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <div style={{ width: "5px", height: "5px", borderRadius: "50%", background: dot, boxShadow: m.status === "running" ? `0 0 6px ${dot}` : "none", animation: m.status === "running" ? "pulse 2s infinite" : "none" }} />
                  </div>
                </div>
                {m.job ? (
                  <div style={{ fontSize: "10px", color: T.text3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.job}</div>
                ) : (
                  <div style={{ fontSize: "10px", color: T.text4 }}>Idle</div>
                )}
                {m.oee > 0 && (
                  <div style={{ marginTop: "6px", height: "3px", background: "rgba(255,255,255,0.04)", borderRadius: "100px", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${m.oee}%`, background: oeeColor, borderRadius: "100px" }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Right panel — auth form ── */}
      <div style={{ width: "440px", flexShrink: 0, display: "flex", flexDirection: "column", justifyContent: "center", padding: "60px 48px", background: T.bg1 }}>

        {/* Back link */}
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: T.text3, fontSize: "12px", cursor: "pointer", textAlign: "left", marginBottom: "40px", display: "flex", alignItems: "center", gap: "6px", padding: 0, fontFamily: "inherit" }}
          onMouseEnter={e => e.currentTarget.style.color = T.text1}
          onMouseLeave={e => e.currentTarget.style.color = T.text3}
        >
          ← Back to site
        </button>

        {/* ── Forgot password view ── */}
        {mode === "forgot" ? (
          <>
            <button
              onClick={() => switchMode("login")}
              style={{ background: "none", border: "none", color: T.text3, fontSize: "12px", cursor: "pointer", textAlign: "left", marginBottom: "24px", display: "flex", alignItems: "center", gap: "6px", padding: 0, fontFamily: "inherit" }}
            >
              ← Back to sign in
            </button>

            <h2 style={{ fontSize: "24px", fontWeight: 700, color: T.text0, letterSpacing: "-0.02em", marginBottom: "6px" }}>Reset your password</h2>
            <p style={{ fontSize: "13px", color: T.text3, marginBottom: "28px", lineHeight: 1.5 }}>
              Enter your email and we&apos;ll send a reset link if an account exists.
            </p>

            {forgotSent ? (
              <div style={{ padding: "20px", borderRadius: "12px", background: `${T.green}12`, border: `1px solid ${T.green}30`, textAlign: "center" }}>
                <div style={{ fontSize: "24px", marginBottom: "10px" }}>✓</div>
                <p style={{ fontSize: "14px", color: T.green, fontWeight: 600, marginBottom: "6px" }}>Check your inbox</p>
                <p style={{ fontSize: "12px", color: T.text3, lineHeight: 1.5 }}>
                  If <strong style={{ color: T.text1 }}>{form.email}</strong> has an account, a reset link is on its way.
                </p>
                <button
                  onClick={() => switchMode("login")}
                  style={{ marginTop: "16px", background: "none", border: `1px solid ${T.border}`, borderRadius: "8px", color: T.text2, fontSize: "12px", fontWeight: 600, padding: "8px 16px", cursor: "pointer", fontFamily: "inherit" }}
                >
                  Back to sign in
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div>
                  <label style={{ fontSize: "11px", color: T.text2, fontWeight: 600, letterSpacing: "0.04em", display: "block", marginBottom: "7px" }}>EMAIL *</label>
                  <input name="email" type="email" value={form.email} onChange={handleChange} style={inputStyle} placeholder="jane@company.com" required />
                </div>
                {error && (
                  <div style={{ padding: "10px 14px", background: `${T.red}12`, border: `1px solid ${T.red}30`, borderRadius: "8px", fontSize: "13px", color: T.red }}>
                    {error}
                  </div>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  style={{ padding: "13px", borderRadius: "10px", border: "none", background: loading ? `${T.brand}60` : `linear-gradient(135deg, ${T.brand}, #E85D04)`, color: "#fff", fontSize: "14px", fontWeight: 700, cursor: loading ? "not-allowed" : "pointer", boxShadow: loading ? "none" : `0 4px 20px ${T.brandGlow}`, transition: "all 0.2s", fontFamily: "inherit" }}
                >
                  {loading ? "Sending…" : "Send reset link →"}
                </button>
              </form>
            )}
          </>
        ) : (
          <>
            {/* Mode toggle */}
            <div style={{ display: "flex", background: T.bg3, borderRadius: "10px", padding: "3px", marginBottom: "32px", border: `1px solid ${T.border}` }}>
              {["login", "register"].map(m => (
                <button
                  key={m}
                  onClick={() => switchMode(m)}
                  style={{ flex: 1, padding: "9px", borderRadius: "8px", border: "none", background: mode === m ? `linear-gradient(135deg, ${T.brand}20, ${T.brand}10)` : "transparent", color: mode === m ? T.brand : T.text3, fontSize: "13px", fontWeight: 600, cursor: "pointer", transition: "all 0.2s", fontFamily: "inherit", boxShadow: mode === m ? `inset 0 0 0 1px ${T.brand}40` : "none" }}
                >
                  {m === "login" ? "Sign In" : "Register"}
                </button>
              ))}
            </div>

            <h2 style={{ fontSize: "24px", fontWeight: 700, color: T.text0, letterSpacing: "-0.02em", marginBottom: "6px" }}>
              {mode === "login" ? "Welcome back" : "Create your account"}
            </h2>
            <p style={{ fontSize: "13px", color: T.text3, marginBottom: "28px", lineHeight: 1.5 }}>
              {mode === "login"
                ? "Sign in to access your shop floor dashboard."
                : "Get started with AI-powered production scheduling."}
            </p>

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {mode === "register" && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <div>
                    <label style={{ fontSize: "11px", color: T.text2, fontWeight: 600, letterSpacing: "0.04em", display: "block", marginBottom: "7px" }}>NAME *</label>
                    <input name="name" value={form.name} onChange={handleChange} style={inputStyle} placeholder="Jane Smith" required minLength={2} />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: T.text2, fontWeight: 600, letterSpacing: "0.04em", display: "block", marginBottom: "7px" }}>COMPANY</label>
                    <input name="company" value={form.company} onChange={handleChange} style={inputStyle} placeholder="Acme Mfg" />
                  </div>
                </div>
              )}

              <div>
                <label style={{ fontSize: "11px", color: T.text2, fontWeight: 600, letterSpacing: "0.04em", display: "block", marginBottom: "7px" }}>EMAIL *</label>
                <input name="email" type="email" value={form.email} onChange={handleChange} style={inputStyle} placeholder="jane@company.com" required />
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "7px" }}>
                  <label style={{ fontSize: "11px", color: T.text2, fontWeight: 600, letterSpacing: "0.04em" }}>PASSWORD *</label>
                  {mode === "login" && (
                    <button
                      type="button"
                      onClick={() => switchMode("forgot")}
                      style={{ background: "none", border: "none", color: T.brand, fontSize: "11px", fontWeight: 600, cursor: "pointer", fontFamily: "inherit", padding: 0 }}
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <input name="password" type="password" value={form.password} onChange={handleChange} style={inputStyle}
                  placeholder={mode === "register" ? "Min 8 characters" : "Enter your password"}
                  required minLength={mode === "register" ? 8 : 1} />
              </div>

              {mode === "login" && (
                <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}>
                  <div
                    onClick={() => setRememberMe(v => !v)}
                    style={{ width: "18px", height: "18px", borderRadius: "5px", border: `1.5px solid ${rememberMe ? T.brand : T.border}`, background: rememberMe ? `${T.brand}20` : "transparent", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.15s", cursor: "pointer" }}
                  >
                    {rememberMe && <span style={{ color: T.brand, fontSize: "11px", fontWeight: 700, lineHeight: 1 }}>✓</span>}
                  </div>
                  <span style={{ fontSize: "13px", color: T.text2, userSelect: "none" }} onClick={() => setRememberMe(v => !v)}>Keep me signed in for 30 days</span>
                </label>
              )}

              {error && (
                <div style={{ padding: "10px 14px", background: `${T.red}12`, border: `1px solid ${T.red}30`, borderRadius: "8px", fontSize: "13px", color: T.red, lineHeight: 1.4 }}>
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                style={{ padding: "13px", borderRadius: "10px", border: "none", background: loading ? `${T.brand}60` : `linear-gradient(135deg, ${T.brand}, #E85D04)`, color: "#fff", fontSize: "14px", fontWeight: 700, cursor: loading ? "not-allowed" : "pointer", boxShadow: loading ? "none" : `0 4px 20px ${T.brandGlow}`, transition: "all 0.2s", fontFamily: "inherit", marginTop: "4px" }}
              >
                {loading ? "Please wait…" : mode === "login" ? "Sign In →" : "Create Account →"}
              </button>
            </form>

            <p style={{ fontSize: "12px", color: T.text3, textAlign: "center", marginTop: "24px" }}>
              {mode === "login" ? "No account?" : "Already registered?"}{" "}
              <button
                onClick={() => switchMode(mode === "login" ? "register" : "login")}
                style={{ background: "none", border: "none", color: T.brand, fontSize: "12px", fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}
              >
                {mode === "login" ? "Register free" : "Sign in"}
              </button>
            </p>
          </>
        )}

        <div style={{ paddingTop: "40px", borderTop: `1px solid ${T.border}`, marginTop: "48px" }}>
          <p style={{ fontSize: "11px", color: T.text4, textAlign: "center", lineHeight: 1.6 }}>
            By signing in you agree to our terms of service.<br />
            Session stored in an httpOnly cookie — no localStorage.
          </p>
        </div>
      </div>
    </div>
  );
}
