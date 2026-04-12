import { useState, useRef } from "react";
import { API_BASE } from "../config";

const T = {
  bg0: "#0A0A0F", bg1: "#0F0F18", bg2: "#15151F", bg3: "#1A1A26",
  border: "rgba(255,255,255,0.06)", borderHi: "rgba(255,255,255,0.12)",
  text0: "#FAFAFA", text1: "#E5E5EA", text2: "#A1A1AA", text3: "#71717A", text4: "#52525B",
  brand: "#FF7A1A", brandGlow: "rgba(255,122,26,0.35)",
  green: "#10B981", greenGlow: "rgba(16,185,129,0.35)",
  amber: "#F59E0B", red: "#EF4444", blue: "#3B82F6", purple: "#A855F7",
  pink: "#EC4899", ai: "#00D4FF",
};

const WC_COLOR = {
  cnc_mill:          T.ai,
  lathe:             "#38BDF8",
  press_brake:       T.blue,
  laser_cutter:      T.purple,
  plasma_cutter:     "#7C3AED",
  waterjet:          "#06B6D4",
  tig_welder:        T.brand,
  mig_welder:        "#FB923C",
  deburr_bench:      T.text3,
  anodizing_line:    T.green,
  inspection_station:T.amber,
  cmm:               "#EAB308",
  powder_coat_booth: T.pink,
  heat_treat_oven:   "#F97316",
  blast_cabinet:     "#94A3B8",
};

const WC_LABEL = {
  cnc_mill:          "CNC Mill",
  lathe:             "Lathe",
  press_brake:       "Press Brake",
  laser_cutter:      "Laser Cutter",
  plasma_cutter:     "Plasma Cutter",
  waterjet:          "Waterjet",
  tig_welder:        "TIG Welder",
  mig_welder:        "MIG Welder",
  deburr_bench:      "Deburr",
  anodizing_line:    "Anodize Line",
  inspection_station:"Inspection / CMM",
  cmm:               "CMM",
  powder_coat_booth: "Powder Coat",
  heat_treat_oven:   "Heat Treat",
  blast_cabinet:     "Blast Cabinet",
};

const PIPELINE_STEPS = [
  { id: "cad",      label: "CAD Analysis",     icon: "◈",  desc: "ARIA-OS geometry & feature detection" },
  { id: "routing",  label: "Process Routing",   icon: "⊞",  desc: "Multi-process operation plan" },
  { id: "schedule", label: "Smart Schedule",    icon: "▤",  desc: "Timeline + dependency resolution" },
  { id: "cost",     label: "Cost Breakdown",    icon: "$",  desc: "Accurate per-operation costing" },
  { id: "operator", label: "Operator View",     icon: "◉",  desc: "What the shop floor sees" },
];

// ── Sample data: CNC aluminum part ─────────────────────────────────────────

const CNC_PART = {
  cad: {
    partName: "Turbine Mount Bracket",
    material:  "6061-T6 Aluminum",
    dims:      "128.4 × 84.2 × 31.7 mm",
    volume:    "342.8 cm³",
    mfgScore:  87,
    mfgWarnings: ["Deep pocket at Position C — consider reducing depth or longer tool"],
    features: [
      { icon: "⬡", label: "4 milled pockets" },
      { icon: "○", label: "8 through-holes Ø6.35mm" },
      { icon: "◎", label: "4 tapped holes M6×1.0" },
      { icon: "▭", label: "2 precision faces Ra 1.6μm" },
      { icon: "⌒", label: "1 profile cut perimeter" },
    ],
  },
  routing: {
    ops: [
      { seq: 10, name: "Rough mill pockets & bores",  wc: "cnc_mill",          machine: "HAAS VF-2",          setup: 25, run: 45, sub: false },
      { seq: 20, name: "Finish mill all features",     wc: "cnc_mill",          machine: "HAAS VF-2",          setup: 5,  run: 30, sub: false, dep: 10 },
      { seq: 30, name: "Break all sharp edges",        wc: "deburr_bench",      machine: "Manual",             setup: 0,  run: 5,  sub: false, dep: 20 },
      { seq: 40, name: "Anodize Type III Hard Coat",   wc: "anodizing_line",    machine: "ABC Anodizing Co.",  setup: 0,  run: 0,  sub: true,  dep: 30, leadDays: 2 },
      { seq: 50, name: "First article inspection",     wc: "inspection_station",machine: "ZEISS Contura CMM",  setup: 5,  run: 15, sub: false, dep: 40 },
    ],
  },
  schedule: {
    dueDate:       "Apr 19",
    completion:    "Apr 17",
    daysEarly:     2,
    totalHours:    2.8,
    note:          "Op 40 (Anodize) is subcontracted — lead time baked into timeline",
    gantt: [
      { seq: 10, name: "Rough mill",   wc: "cnc_mill",          start: 0,   width: 28 },
      { seq: 20, name: "Finish mill",  wc: "cnc_mill",          start: 28,  width: 19 },
      { seq: 30, name: "Deburr",       wc: "deburr_bench",      start: 47,  width: 3  },
      { seq: 40, name: "Anodize",      wc: "anodizing_line",    start: 50,  width: 38, sub: true },
      { seq: 50, name: "Inspection",   wc: "inspection_station",start: 88,  width: 12 },
    ],
  },
  cost: {
    material:   { label: "Material — 6061-T6 bar 2.5\"×4\"×6\"",   usd: 24.50 },
    labor:      { label: "Labor — 2.8h @ $40/h (blended rate)",      usd: 112.00,
                  lines: ["Op 10 Rough mill 45min · $30", "Op 20 Finish 30min · $20", "Op 50 Inspection 15min · $10"] },
    subcontract:{ label: "Subcontract — Anodize Type III",            usd: 18.00 },
    overhead:   { label: "Overhead — 1.5× labor",                     usd: 168.00 },
    markup:     { label: "Markup — 15%",                              usd: 48.38 },
    total:      { label: "TOTAL / part",                              usd: 370.88 },
    insight:    "Historical data: your CNC estimates run 23% under actual. Shown estimate already adjusted.",
  },
  operator: {
    part:     "Turbine Mount Bracket",
    order:    "ORD-2847",
    material: "6061-T6 Aluminum",
    priority: "HIGH",
    machine:  "HAAS VF-2 — Bay 3",
    nextOp:   "Op 10 — Rough mill pockets & bores",
    drawing:  "DRG-TM-2847-RevA",
    ops: [
      { seq: 10, name: "Rough mill",  status: "ready",    time: "45 min" },
      { seq: 20, name: "Finish mill", status: "waiting",  time: "30 min" },
      { seq: 30, name: "Deburr",      status: "waiting",  time: "5 min"  },
      { seq: 40, name: "Anodize",     status: "sub",      time: "2 days" },
      { seq: 50, name: "Inspect",     status: "waiting",  time: "15 min" },
    ],
  },
};

// ── Sample data: Fabricated steel part ─────────────────────────────────────

const FAB_PART = {
  cad: {
    partName: "Chassis Bracket",
    material:  "A36 Structural Steel",
    dims:      "300 × 150 × 6 mm sheet",
    volume:    "211.5 cm³",
    mfgScore:  93,
    mfgWarnings: [],
    features: [
      { icon: "⌒", label: "Laser-cut profile + 12 holes" },
      { icon: "↗", label: "4 press brake bends at 90°" },
      { icon: "⌁", label: "2 weld joints (gussets)" },
      { icon: "◈", label: "6mm flat sheet stock" },
    ],
  },
  routing: {
    ops: [
      { seq: 10, name: "Laser cut blank + holes",  wc: "laser_cutter",      machine: "Trumpf TruLaser",    setup: 10, run: 2,  sub: false },
      { seq: 20, name: "4 bends at 90°",           wc: "press_brake",       machine: "Amada HG-1003",      setup: 15, run: 3,  sub: false, dep: 10 },
      { seq: 30, name: "Weld 2 gussets",           wc: "tig_welder",        machine: "Miller Dynasty 210", setup: 10, run: 15, sub: false, dep: 20 },
      { seq: 40, name: "Powder coat satin black",  wc: "powder_coat_booth", machine: "Premier Coatings",   setup: 0,  run: 0,  sub: true,  dep: 30, leadDays: 3 },
      { seq: 50, name: "Final dimensional check",  wc: "inspection_station",machine: "Manual QC",          setup: 0,  run: 8,  sub: false, dep: 40 },
    ],
  },
  schedule: {
    dueDate:    "Apr 21",
    completion: "Apr 18",
    daysEarly:  3,
    totalHours: 0.6,
    note:       "Op 40 (Powder Coat) is subcontracted — 3-day lead. All in-house ops complete in < 1h.",
    gantt: [
      { seq: 10, name: "Laser cut",   wc: "laser_cutter",      start: 0,  width: 6  },
      { seq: 20, name: "Press brake", wc: "press_brake",        start: 6,  width: 9  },
      { seq: 30, name: "TIG weld",    wc: "tig_welder",         start: 15, width: 24 },
      { seq: 40, name: "Powder coat", wc: "powder_coat_booth",  start: 39, width: 50, sub: true },
      { seq: 50, name: "Inspection",  wc: "inspection_station", start: 89, width: 11 },
    ],
  },
  cost: {
    material:   { label: "Material — A36 sheet 12\"×6\"×1/4\"",      usd: 8.40 },
    labor:      { label: "Labor — 0.6h @ $35/h (blended rate)",       usd: 21.00,
                  lines: ["Laser 2min · $2", "Press brake 3min · $4", "TIG weld 15min · $9", "Inspection 8min · $5"] },
    subcontract:{ label: "Subcontract — Powder coat satin black",      usd: 14.00 },
    overhead:   { label: "Overhead — 1.5× labor",                      usd: 31.50 },
    markup:     { label: "Markup — 15%",                               usd: 11.24 },
    total:      { label: "TOTAL / part",                               usd: 86.14 },
    insight:    "Sheet metal runs predictably — your press brake estimates are within 8% of actual.",
  },
  operator: {
    part:     "Chassis Bracket",
    order:    "ORD-2848",
    material: "A36 Steel Sheet",
    priority: "NORMAL",
    machine:  "Trumpf TruLaser — Bay 1",
    nextOp:   "Op 10 — Laser cut blank + holes",
    drawing:  "DRG-CB-2848-RevB",
    ops: [
      { seq: 10, name: "Laser cut",    status: "ready",   time: "2 min"  },
      { seq: 20, name: "Press brake",  status: "waiting", time: "3 min"  },
      { seq: 30, name: "TIG weld",     status: "waiting", time: "15 min" },
      { seq: 40, name: "Powder coat",  status: "sub",     time: "3 days" },
      { seq: 50, name: "Inspect",      status: "waiting", time: "8 min"  },
    ],
  },
};

const SAMPLE_DATA = { cnc: CNC_PART, fab: FAB_PART };
const STEP_DURATIONS = [1800, 2200, 1600, 1400, 800];

// ── Reusable UI pieces ──────────────────────────────────────────────────────

function StepBadge({ label, product, color }) {
  return (
    <span style={{ padding: "2px 8px", borderRadius: "100px", border: `1px solid ${color}40`,
      background: `${color}12`, fontSize: "9px", fontWeight: 700, color, letterSpacing: "0.08em" }}>
      {product} {label}
    </span>
  );
}

function PipelineStep({ step, idx, state }) {
  const c = {
    idle:   { bg: T.bg2, border: T.border, icon: T.text4, label: T.text3 },
    active: { bg: `${T.brand}10`, border: `${T.brand}50`, icon: T.brand, label: T.text1 },
    done:   { bg: `${T.green}10`, border: `${T.green}40`, icon: T.green, label: T.text0 },
  }[state];
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "7px", flex: 1, minWidth: 0 }}>
      <div style={{ width: "44px", height: "44px", borderRadius: "12px", background: c.bg, border: `1px solid ${c.border}`,
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: "18px", color: c.icon,
        transition: "all 0.4s", boxShadow: state === "active" ? `0 0 18px ${T.brandGlow}` : state === "done" ? `0 0 10px ${T.greenGlow}` : "none",
        animation: state === "active" ? "pulse 1.5s infinite" : "none" }}>
        {state === "done" ? "✓" : step.icon}
      </div>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: "10px", fontWeight: 700, color: c.label, letterSpacing: "0.04em" }}>{step.label}</div>
        <div style={{ fontSize: "8px", color: T.text4, marginTop: "1px", display: "none" }}>{step.desc}</div>
      </div>
    </div>
  );
}

function SectionHeader({ icon, stepNum, label, badge }) {
  return (
    <div style={{ padding: "12px 18px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`,
      display: "flex", alignItems: "center", gap: "10px" }}>
      <span style={{ fontSize: "15px", color: T.text2 }}>{icon}</span>
      <span style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em" }}>STEP {stepNum}</span>
      <span style={{ fontSize: "13px", color: T.text0, fontWeight: 600 }}>{label}</span>
      {badge}
      <div style={{ marginLeft: "auto", padding: "2px 8px", borderRadius: "100px", background: `${T.green}12`,
        border: `1px solid ${T.green}30`, fontSize: "9px", color: T.green, fontWeight: 700 }}>✓ COMPLETE</div>
    </div>
  );
}

function ResultSection({ children, style = {} }) {
  return (
    <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, border: `1px solid ${T.border}`,
      borderRadius: "14px", overflow: "hidden", boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
      animation: "fadeUp 0.4s ease-out", ...style }}>
      {children}
    </div>
  );
}

function WcBadge({ wc }) {
  const color = WC_COLOR[wc] || T.text3;
  return (
    <span style={{ padding: "2px 8px", borderRadius: "6px", border: `1px solid ${color}40`,
      background: `${color}15`, fontSize: "9px", fontWeight: 700, color, letterSpacing: "0.06em",
      whiteSpace: "nowrap" }}>
      {WC_LABEL[wc] || wc}
    </span>
  );
}

// ── Step result renderers ───────────────────────────────────────────────────

function CadResult({ data, partType }) {
  const scoreColor = data.mfgScore >= 85 ? T.green : data.mfgScore >= 70 ? T.amber : T.red;
  return (
    <ResultSection>
      <SectionHeader icon="◈" stepNum="01" label="CAD Analysis"
        badge={<StepBadge product="ARIA-OS" label="AI" color={T.ai} />} />
      <div style={{ padding: "18px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
          <div>
            <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "6px" }}>PART</div>
            <div style={{ fontSize: "15px", fontWeight: 700, color: T.text0 }}>{data.partName}</div>
            <div style={{ fontSize: "12px", color: partType === "cnc" ? T.green : T.blue, marginTop: "3px" }}>{data.material}</div>
            <div style={{ fontSize: "11px", color: T.text3, marginTop: "2px" }}>{data.dims} · {data.volume}</div>
          </div>
          <div>
            <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "6px" }}>MANUFACTURABILITY</div>
            <div style={{ fontSize: "28px", fontWeight: 700, color: scoreColor, lineHeight: 1 }}>{data.mfgScore}<span style={{ fontSize: "13px", color: T.text3 }}>/100</span></div>
            {data.mfgWarnings.map((w, i) => (
              <div key={i} style={{ marginTop: "6px", padding: "5px 9px", borderRadius: "6px", background: `${T.amber}12`,
                border: `1px solid ${T.amber}30`, fontSize: "10px", color: T.amber }}>
                ⚠ {w}
              </div>
            ))}
          </div>
        </div>
        <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "8px" }}>FEATURES DETECTED</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "7px" }}>
          {data.features.map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 11px",
              borderRadius: "8px", background: T.bg3, border: `1px solid ${T.border}`,
              animation: `fadeUp 0.35s ease-out ${i * 120}ms both`, fontSize: "11px", color: T.text1 }}>
              <span style={{ fontSize: "13px", color: T.ai }}>{f.icon}</span>
              {f.label}
            </div>
          ))}
        </div>
      </div>
    </ResultSection>
  );
}

function RoutingResult({ data }) {
  return (
    <ResultSection>
      <SectionHeader icon="⊞" stepNum="02" label="Multi-Process Routing"
        badge={<StepBadge product="ARIA-OS" label="AI" color={T.ai} />} />
      <div style={{ padding: "14px 18px 18px" }}>
        <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "10px" }}>
          OPERATION SEQUENCE — {data.ops.length} WORK CENTER TYPES
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {data.ops.map((op, i) => {
            const color = WC_COLOR[op.wc] || T.text3;
            const totalMin = op.setup + op.run;
            return (
              <div key={op.seq} style={{ display: "flex", alignItems: "flex-start", gap: "10px",
                animation: `fadeUp 0.35s ease-out ${i * 150}ms both` }}>
                {/* Connector line */}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: "4px" }}>
                  <div style={{ width: "28px", height: "28px", borderRadius: "8px", background: `${color}18`,
                    border: `1px solid ${color}50`, display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: "10px", fontWeight: 700, color }}>
                    {op.seq}
                  </div>
                  {i < data.ops.length - 1 && (
                    <div style={{ width: "1px", height: "16px", background: T.border, margin: "2px 0" }} />
                  )}
                </div>
                {/* Card */}
                <div style={{ flex: 1, padding: "9px 12px", borderRadius: "10px", background: T.bg3,
                  border: `1px solid ${op.sub ? `${color}40` : T.border}`,
                  borderLeft: `3px solid ${color}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <span style={{ fontSize: "12px", fontWeight: 600, color: T.text0, flex: 1 }}>{op.name}</span>
                    <WcBadge wc={op.wc} />
                    {op.sub && (
                      <span style={{ padding: "2px 7px", borderRadius: "6px", background: `${T.amber}15`,
                        border: `1px solid ${T.amber}40`, fontSize: "9px", color: T.amber, fontWeight: 700 }}>
                        SUBCONTRACTED
                      </span>
                    )}
                  </div>
                  <div style={{ marginTop: "4px", fontSize: "10px", color: T.text3, display: "flex", gap: "12px", flexWrap: "wrap" }}>
                    <span>{op.machine}</span>
                    {op.sub ? (
                      <span style={{ color: T.amber }}>Lead time: {op.leadDays}d</span>
                    ) : (
                      <span>Setup {op.setup}min · Run {op.run}min · Total {totalMin}min</span>
                    )}
                    {op.dep && <span style={{ color: T.text4 }}>→ after Op {op.dep}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </ResultSection>
  );
}

function ScheduleResult({ data }) {
  return (
    <ResultSection>
      <SectionHeader icon="▤" stepNum="03" label="Smart Scheduling"
        badge={<StepBadge product="MillForge" label="AI" color={T.brand} />} />
      <div style={{ padding: "14px 18px 18px" }}>
        {/* Key metric */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px", marginBottom: "16px" }}>
          {[
            { label: "COMPLETION", value: data.completion, color: T.green },
            { label: "DUE DATE",   value: data.dueDate,    color: T.text2 },
            { label: "AHEAD BY",   value: `${data.daysEarly} days`, color: T.green },
          ].map(m => (
            <div key={m.label} style={{ padding: "10px 12px", borderRadius: "10px", background: T.bg3, border: `1px solid ${T.border}` }}>
              <div style={{ fontSize: "8px", color: T.text4, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "4px" }}>{m.label}</div>
              <div style={{ fontSize: "16px", fontWeight: 700, color: m.color }}>{m.value}</div>
            </div>
          ))}
        </div>
        {/* Gantt */}
        <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "8px" }}>PRODUCTION TIMELINE</div>
        <div style={{ background: T.bg3, borderRadius: "10px", padding: "12px", border: `1px solid ${T.border}` }}>
          {data.gantt.map((bar, i) => {
            const color = WC_COLOR[bar.wc] || T.text3;
            return (
              <div key={bar.seq} style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: i < data.gantt.length - 1 ? "6px" : 0 }}>
                <div style={{ width: "70px", fontSize: "9px", color: T.text3, textAlign: "right", flexShrink: 0 }}>{bar.name}</div>
                <div style={{ flex: 1, height: "20px", borderRadius: "4px", background: `${T.bg1}`, position: "relative", overflow: "hidden" }}>
                  <div style={{
                    position: "absolute", left: `${bar.start}%`, width: `${bar.width}%`, height: "100%",
                    background: bar.sub ? `repeating-linear-gradient(45deg, ${color}30, ${color}30 3px, ${color}15 3px, ${color}15 8px)` : `${color}40`,
                    border: `1px solid ${color}50`, borderRadius: "3px",
                    animation: `expandWidth 0.5s ease-out ${i * 80}ms both`,
                  }} />
                </div>
                {bar.sub && <span style={{ fontSize: "8px", color: T.amber, whiteSpace: "nowrap" }}>sub</span>}
              </div>
            );
          })}
          <div style={{ marginTop: "8px", fontSize: "9px", color: T.text4, borderTop: `1px solid ${T.border}`, paddingTop: "8px" }}>
            {data.note}
          </div>
        </div>
      </div>
    </ResultSection>
  );
}

function CostResult({ data }) {
  const fmtUSD = n => `$${n.toFixed(2)}`;
  return (
    <ResultSection>
      <SectionHeader icon="$" stepNum="04" label="Live Cost Breakdown"
        badge={<StepBadge product="MillForge" label="AI" color={T.brand} />} />
      <div style={{ padding: "14px 18px 18px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "3px", marginBottom: "12px" }}>
          {[data.material, data.labor, data.subcontract, data.overhead, data.markup].map((line, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "7px 10px", borderRadius: "7px",
              background: i % 2 === 0 ? T.bg3 : "transparent",
              animation: `fadeUp 0.3s ease-out ${i * 90}ms both` }}>
              <span style={{ fontSize: "11px", color: T.text2 }}>{line.label}</span>
              <span style={{ fontSize: "13px", fontWeight: 600, color: T.text0, fontFeatureSettings: "'tnum'" }}>
                {fmtUSD(line.usd)}
              </span>
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "10px 10px", borderRadius: "7px", marginTop: "4px",
            background: `${T.brand}12`, border: `1px solid ${T.brand}30` }}>
            <span style={{ fontSize: "12px", fontWeight: 700, color: T.text0 }}>{data.total.label}</span>
            <span style={{ fontSize: "20px", fontWeight: 700, color: T.brand, fontFeatureSettings: "'tnum'" }}>
              {fmtUSD(data.total.usd)}
            </span>
          </div>
        </div>
        {/* Historical accuracy insight */}
        <div style={{ padding: "9px 12px", borderRadius: "8px", background: `${T.ai}08`, border: `1px solid ${T.ai}25`,
          fontSize: "10px", color: T.ai, display: "flex", alignItems: "flex-start", gap: "7px" }}>
          <span style={{ flexShrink: 0 }}>◈</span>
          <span>{data.insight}</span>
        </div>
      </div>
    </ResultSection>
  );
}

function OperatorResult({ data }) {
  const statusColor = { ready: T.green, waiting: T.text3, sub: T.amber };
  return (
    <ResultSection>
      <SectionHeader icon="◉" stepNum="05" label="Operator View"
        badge={<StepBadge product="MillForge" label="AI" color={T.brand} />} />
      <div style={{ padding: "14px 18px 18px" }}>
        <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "8px" }}>
          WHAT YOUR NEW HIRE SEES INSTEAD OF ASKING YOUR SENIOR MACHINIST
        </div>
        {/* Job card */}
        <div style={{ padding: "12px 14px", borderRadius: "10px", background: T.bg3, border: `1px solid ${T.border}`,
          marginBottom: "10px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
            <div style={{ padding: "2px 8px", borderRadius: "6px",
              background: data.priority === "HIGH" ? `${T.red}18` : `${T.text3}15`,
              border: `1px solid ${data.priority === "HIGH" ? `${T.red}40` : T.border}`,
              fontSize: "9px", fontWeight: 700, color: data.priority === "HIGH" ? T.red : T.text3 }}>
              {data.priority}
            </div>
            <span style={{ fontSize: "13px", fontWeight: 700, color: T.text0 }}>{data.part}</span>
            <span style={{ fontSize: "10px", color: T.text3 }}>{data.order}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", fontSize: "10px", color: T.text2, marginBottom: "10px" }}>
            <div><span style={{ color: T.text4 }}>Material: </span>{data.material}</div>
            <div><span style={{ color: T.text4 }}>Machine: </span>{data.machine}</div>
            <div><span style={{ color: T.text4 }}>Next op: </span><span style={{ color: T.text1 }}>{data.nextOp}</span></div>
            <div><span style={{ color: T.text4 }}>Drawing: </span>{data.drawing}</div>
          </div>
          <button style={{ width: "100%", padding: "8px", borderRadius: "7px", background: `${T.green}18`,
            border: `1px solid ${T.green}40`, color: T.green, fontSize: "11px", fontWeight: 700, cursor: "pointer",
            fontFamily: "inherit", letterSpacing: "0.04em" }}>
            ▶ START SETUP — TAP TO BEGIN TIMER
          </button>
        </div>
        {/* Op queue */}
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          {data.ops.map((op, i) => (
            <div key={op.seq} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "6px 10px",
              borderRadius: "7px", background: i === 0 ? `${T.green}08` : "transparent",
              border: i === 0 ? `1px solid ${T.green}25` : `1px solid transparent`,
              animation: `fadeUp 0.3s ease-out ${i * 80}ms both` }}>
              <div style={{ width: "6px", height: "6px", borderRadius: "50%",
                background: statusColor[op.status] || T.text4 }} />
              <span style={{ fontSize: "10px", color: i === 0 ? T.text0 : T.text3, flex: 1 }}>Op {op.seq} — {op.name}</span>
              <span style={{ fontSize: "9px", color: T.text4 }}>{op.time}</span>
              {op.status === "sub" && <span style={{ fontSize: "8px", color: T.amber }}>subcontracted</span>}
            </div>
          ))}
        </div>
      </div>
    </ResultSection>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];

export default function DemoChainPage() {
  const [sampleType, setSampleType]   = useState(null);     // "cnc" | "fab" | null
  const [file, setFile]               = useState(null);
  const [material, setMaterial]       = useState("steel");
  const [quantity, setQuantity]       = useState(200);
  const [priority, setPriority]       = useState(3);
  const [dueDays, setDueDays]         = useState(14);
  const [loading, setLoading]         = useState(false);
  const [activeStep, setActiveStep]   = useState(-1);
  const [stepResults, setStepResults] = useState({});       // { 0: data, 1: data, ... }
  const [liveResult, setLiveResult]   = useState(null);     // from real API call
  const [error, setError]             = useState(null);
  const [dragOver, setDragOver]       = useState(false);
  const fileRef = useRef(null);

  const delay = ms => new Promise(r => setTimeout(r, ms));

  const handleFile = f => { if (f?.name?.endsWith(".stl")) setFile(f); };
  const handleDrop = e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); };

  const handleSampleDemo = async (type) => {
    setSampleType(type);
    setError(null);
    setLiveResult(null);
    setStepResults({});
    setActiveStep(0);
    setLoading(true);

    const data = SAMPLE_DATA[type];
    const keys = ["cad", "routing", "schedule", "cost", "operator"];

    for (let i = 0; i < 5; i++) {
      setActiveStep(i);
      await delay(STEP_DURATIONS[i]);
      setStepResults(prev => ({ ...prev, [i]: data[keys[i]] }));
    }

    setActiveStep(5);
    setLoading(false);
  };

  const handleSubmit = async e => {
    e.preventDefault();
    if (!file) { setError("Select an STL file first, or click a sample demo button above."); return; }
    setSampleType(null);
    setError(null);
    setLiveResult(null);
    setStepResults({});
    setLoading(true);

    // Animate through CAD → routing (mock) → schedule → cost → operator
    const animKeys = ["cad", "routing", "schedule", "cost", "operator"];
    for (let i = 0; i < 5; i++) {
      setActiveStep(i);
      await delay(STEP_DURATIONS[i]);
    }

    const form = new FormData();
    form.append("file", file instanceof File ? file : new Blob([]), file.name || "part.stl");
    form.append("material", material);
    form.append("quantity", String(quantity));
    form.append("priority", String(priority));
    form.append("due_date_days", String(dueDays));

    try {
      const res = await fetch(`${API_BASE}/api/demo/cad-to-quote`, { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setLiveResult(await res.json());
      setActiveStep(5);
    } catch (err) {
      setError(err.message);
      setActiveStep(-1);
    } finally {
      setLoading(false);
    }
  };

  const stepState = i => {
    if (activeStep < 0) return "idle";
    if (activeStep > i || activeStep === 5) return "done";
    if (i === activeStep) return "active";
    return "idle";
  };

  const inputStyle = {
    width: "100%", background: T.bg3, border: `1px solid ${T.border}`, borderRadius: "8px",
    padding: "10px 12px", color: T.text0, fontSize: "13px", outline: "none", fontFamily: "inherit",
  };
  const labelStyle = {
    fontSize: "10px", color: T.text2, fontWeight: 700, letterSpacing: "0.1em", display: "block", marginBottom: "7px",
  };

  return (
    <div style={{ fontFamily: "'Inter', system-ui, sans-serif", color: T.text0, maxWidth: "960px", margin: "0 auto" }}>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:.6} 50%{opacity:1} }
        @keyframes fadeUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes expandWidth { from{width:0} }
        input:focus, select:focus { border-color: ${T.brand} !important; outline: none; }
        @media(max-width:600px) {
          .demo-params { grid-template-columns: 1fr 1fr !important; }
          .gantt-label { display: none !important; }
        }
      `}</style>

      {/* Header */}
      <div style={{ marginBottom: "24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
          <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: T.ai,
            boxShadow: `0 0 8px ${T.ai}`, animation: "pulse 2s infinite" }} />
          <span style={{ fontSize: "10px", color: T.ai, fontWeight: 700, letterSpacing: "0.12em" }}>ARIA-OS × MILLFORGE — LIVE DEMO</span>
        </div>
        <h2 style={{ fontSize: "24px", fontWeight: 700, color: T.text0, letterSpacing: "-0.02em", marginBottom: "6px" }}>
          Part → Plan → Schedule → Quote → Shop Floor
        </h2>
        <p style={{ fontSize: "13px", color: T.text2, lineHeight: 1.6, maxWidth: "600px" }}>
          ARIA-OS detects features and plans the operations. MillForge schedules across every work center type,
          builds the quote from actual costs, and puts the job on the operator's tablet — zero human coordination.
        </p>
      </div>

      {/* Pipeline visualizer */}
      <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, border: `1px solid ${T.border}`,
        borderRadius: "14px", padding: "20px 24px", marginBottom: "16px", boxShadow: "0 4px 16px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: "0" }}>
          {PIPELINE_STEPS.map((step, i) => (
            <div key={step.id} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <PipelineStep step={step} idx={i} state={stepState(i)} />
              {i < PIPELINE_STEPS.length - 1 && (
                <div style={{ flex: 0, width: "28px", height: "1px", margin: "0 4px", marginTop: "-16px",
                  background: stepState(i) === "done" ? T.green : T.border, transition: "background 0.4s",
                  boxShadow: stepState(i) === "done" ? `0 0 6px ${T.green}60` : "none" }} />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Sample toggle + upload form */}
      <div style={{ background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`, border: `1px solid ${T.border}`,
        borderRadius: "14px", padding: "20px 24px", marginBottom: "14px", boxShadow: "0 4px 16px rgba(0,0,0,0.3)" }}>

        {/* Sample demo buttons */}
        <div style={{ marginBottom: "18px" }}>
          <div style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em", marginBottom: "8px" }}>
            TRY A SAMPLE — NO FILE NEEDED
          </div>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <button
              type="button" disabled={loading}
              onClick={() => handleSampleDemo("cnc")}
              style={{ padding: "9px 18px", borderRadius: "9px", border: `1px solid ${sampleType === "cnc" ? T.ai : T.ai + "50"}`,
                background: sampleType === "cnc" ? `${T.ai}20` : `${T.ai}08`, color: T.ai,
                fontSize: "11px", fontWeight: 700, cursor: loading ? "not-allowed" : "pointer",
                letterSpacing: "0.05em", transition: "all 0.15s", fontFamily: "inherit" }}>
              ▶ ALUMINUM CNC PART
            </button>
            <button
              type="button" disabled={loading}
              onClick={() => handleSampleDemo("fab")}
              style={{ padding: "9px 18px", borderRadius: "9px", border: `1px solid ${sampleType === "fab" ? T.blue : T.blue + "50"}`,
                background: sampleType === "fab" ? `${T.blue}20` : `${T.blue}08`, color: T.blue,
                fontSize: "11px", fontWeight: 700, cursor: loading ? "not-allowed" : "pointer",
                letterSpacing: "0.05em", transition: "all 0.15s", fontFamily: "inherit" }}>
              ▶ STEEL FABRICATED PART
            </button>
          </div>
          {sampleType && !loading && (
            <div style={{ marginTop: "7px", fontSize: "10px", color: T.text4 }}>
              Showing: {sampleType === "cnc" ? "Turbine Mount Bracket — 6061-T6 Aluminum (CNC + Anodize)" : "Chassis Bracket — A36 Steel (Laser + Bend + Weld + Powder Coat)"}
            </div>
          )}
        </div>

        {/* Divider */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "18px" }}>
          <div style={{ flex: 1, height: "1px", background: T.border }} />
          <span style={{ fontSize: "9px", color: T.text4, fontWeight: 700, letterSpacing: "0.1em" }}>OR UPLOAD YOUR OWN</span>
          <div style={{ flex: 1, height: "1px", background: T.border }} />
        </div>

        {/* Upload form */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "16px" }}>
            <label style={labelStyle}>STL FILE</label>
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              style={{ border: `2px dashed ${file ? T.green : dragOver ? T.brand : T.border}`, borderRadius: "10px",
                padding: "22px", textAlign: "center", cursor: "pointer", transition: "all 0.2s",
                background: file ? `${T.green}06` : dragOver ? `${T.brand}06` : "transparent" }}>
              {file ? (
                <div>
                  <div style={{ fontSize: "20px", marginBottom: "4px" }}>◈</div>
                  <div style={{ fontSize: "13px", color: T.green, fontWeight: 600 }}>{file.name}</div>
                  <div style={{ fontSize: "10px", color: T.text3, marginTop: "2px" }}>{(file.size / 1024).toFixed(1)} KB · click to replace</div>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: "22px", color: T.text4, marginBottom: "6px" }}>▲</div>
                  <div style={{ fontSize: "12px", color: T.text2 }}>Drop STL here or click to browse</div>
                  <div style={{ fontSize: "10px", color: T.text4, marginTop: "3px" }}>Binary or ASCII · any geometry</div>
                </div>
              )}
            </div>
            <input ref={fileRef} type="file" accept=".stl" style={{ display: "none" }}
              onChange={e => handleFile(e.target.files?.[0] || null)} />
          </div>

          <div className="demo-params" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "12px", marginBottom: "14px" }}>
            <div>
              <label style={labelStyle}>MATERIAL</label>
              <select style={inputStyle} value={material} onChange={e => setMaterial(e.target.value)}>
                {MATERIALS.map(m => <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>QUANTITY</label>
              <input type="number" style={inputStyle} min={1} max={100000} value={quantity} onChange={e => setQuantity(Number(e.target.value))} />
            </div>
            <div>
              <label style={labelStyle}>PRIORITY</label>
              <input type="number" style={inputStyle} min={1} max={10} value={priority} onChange={e => setPriority(Number(e.target.value))} />
              <div style={{ fontSize: "9px", color: T.text4, marginTop: "3px" }}>1 = urgent</div>
            </div>
            <div>
              <label style={labelStyle}>DUE (DAYS)</label>
              <input type="number" style={inputStyle} min={1} max={365} value={dueDays} onChange={e => setDueDays(Number(e.target.value))} />
            </div>
          </div>

          {error && (
            <div style={{ marginBottom: "12px", padding: "10px 14px", background: `${T.red}12`,
              border: `1px solid ${T.red}30`, borderRadius: "9px", fontSize: "12px", color: T.red }}>
              {error}
            </div>
          )}

          <button type="submit" disabled={loading}
            style={{ width: "100%", padding: "12px", borderRadius: "9px", border: "none",
              background: loading ? `${T.brand}50` : `linear-gradient(135deg, ${T.brand}, #E85D04)`,
              color: "#fff", fontSize: "13px", fontWeight: 700, cursor: loading ? "not-allowed" : "pointer",
              boxShadow: loading ? "none" : `0 4px 20px ${T.brandGlow}`, transition: "all 0.2s",
              fontFamily: "inherit", letterSpacing: "0.02em" }}>
            {loading ? "Running pipeline…" : "▶ Run ARIA → MillForge Pipeline"}
          </button>
        </form>
      </div>

      {/* Step-by-step results — appear as each step completes */}
      {Object.keys(stepResults).length > 0 && sampleType && (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {stepResults[0] && <CadResult data={stepResults[0]} partType={sampleType} />}
          {stepResults[1] && <RoutingResult data={stepResults[1]} />}
          {stepResults[2] && <ScheduleResult data={stepResults[2]} />}
          {stepResults[3] && <CostResult data={stepResults[3]} />}
          {stepResults[4] && <OperatorResult data={stepResults[4]} />}
        </div>
      )}

      {/* Live API result (from real STL upload) */}
      {liveResult && (
        <div style={{ marginTop: "12px" }}>
          <div style={{ padding: "12px 18px", borderRadius: "12px", marginBottom: "14px",
            background: liveResult.on_time ? `${T.green}12` : `${T.red}12`,
            border: `1px solid ${liveResult.on_time ? T.green : T.red}30`,
            display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{ width: "7px", height: "7px", borderRadius: "50%", flexShrink: 0,
              background: liveResult.on_time ? T.green : T.red, boxShadow: `0 0 8px ${liveResult.on_time ? T.green : T.red}` }} />
            <span style={{ fontSize: "13px", fontWeight: 600, color: liveResult.on_time ? T.green : T.red }}>
              {liveResult.on_time ? "On-Time" : "Late"}
            </span>
            <span style={{ fontSize: "12px", color: T.text2 }}>{liveResult.summary}</span>
          </div>
          {/* 4-step results for live run */}
          {[
            { step: "01", label: "CAD Parse", icon: "◈", color: T.ai,
              cards: [
                { label: "DIMENSIONS", value: liveResult.cad_parse.dimensions },
                { label: "COMPLEXITY", value: `${liveResult.cad_parse.complexity} / 10`, color: liveResult.cad_parse.complexity > 7 ? T.red : T.green },
                { label: "VOLUME", value: `${liveResult.cad_parse.estimated_volume_cm3?.toFixed(1)} cm³` },
                { label: "TRIANGLES", value: liveResult.cad_parse.triangle_count?.toLocaleString() },
              ]},
            { step: "02", label: "Schedule", icon: "▤", color: T.green,
              cards: [
                { label: "MACHINE", value: `M-${liveResult.scheduled_order?.machine_id}` },
                { label: "MATERIAL", value: liveResult.scheduled_order?.material },
                { label: "PROCESSING", value: `${((liveResult.scheduled_order?.processing_minutes||0)/60).toFixed(1)}h` },
                { label: "SETUP", value: `${liveResult.scheduled_order?.setup_minutes}min` },
              ]},
            { step: "03", label: "Energy", icon: "⚡", color: T.amber,
              cards: [
                { label: "CONSUMPTION", value: `${liveResult.energy?.estimated_kwh?.toFixed(2)} kWh`, color: T.amber },
                { label: "COST", value: `$${liveResult.energy?.estimated_cost_usd?.toFixed(2)}` },
                { label: "SOURCE", value: liveResult.energy?.data_source },
                { label: "TIP", value: liveResult.energy?.recommendation, color: T.green },
              ]},
            { step: "04", label: "Quote", icon: "$", color: T.brand,
              cards: [
                { label: "UNIT PRICE", value: `$${liveResult.quote?.unit_price_usd?.toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
                { label: "TOTAL", value: `$${liveResult.quote?.total_price_usd?.toLocaleString("en-US", { minimumFractionDigits: 2 })}`, color: T.brand },
                { label: "LEAD TIME", value: `${liveResult.quote?.estimated_lead_time_days}d` },
                { label: "CARBON", value: `${liveResult.quote?.carbon_footprint_kg_co2?.toFixed(1)} kg CO₂`, color: T.green },
              ]},
          ].map(sec => (
            <div key={sec.step} style={{ marginBottom: "12px", background: `linear-gradient(180deg, ${T.bg2} 0%, ${T.bg1} 100%)`,
              border: `1px solid ${T.border}`, borderRadius: "14px", overflow: "hidden", boxShadow: "0 4px 16px rgba(0,0,0,0.25)" }}>
              <div style={{ padding: "12px 18px", background: "rgba(0,0,0,0.3)", borderBottom: `1px solid ${T.border}`,
                display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ fontSize: "14px", color: sec.color }}>{sec.icon}</span>
                <span style={{ fontSize: "9px", color: T.text3, fontWeight: 700, letterSpacing: "0.1em" }}>STEP {sec.step}</span>
                <span style={{ fontSize: "13px", fontWeight: 600, color: T.text0 }}>{sec.label}</span>
                <div style={{ marginLeft: "auto", padding: "2px 8px", borderRadius: "100px", background: `${T.green}12`,
                  border: `1px solid ${T.green}30`, fontSize: "9px", color: T.green, fontWeight: 700 }}>✓ COMPLETE</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1px", background: T.border }}>
                {sec.cards.map(card => (
                  <div key={card.label} style={{ background: T.bg1, padding: "14px 16px" }}>
                    <div style={{ fontSize: "8px", color: T.text4, fontWeight: 700, letterSpacing: "0.12em", marginBottom: "6px" }}>{card.label}</div>
                    <div style={{ fontSize: "14px", fontWeight: 700, color: card.color || T.text0 }}>{card.value || "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
