import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const SHOP_SIZES = ["1-5", "6-20", "21-100", "100+"];
const ROLES = ["owner", "ops_manager", "estimator", "machinist", "other"];
const ROLE_LABELS = {
  owner: "Owner",
  ops_manager: "Ops Manager",
  estimator: "Estimator",
  machinist: "Machinist",
  other: "Other",
};
const CATEGORY_COLORS = {
  pain_point: "bg-red-500/20 text-red-300 border-red-500/30",
  current_tool: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  wtp_signal: "bg-green-500/20 text-green-300 border-green-500/30",
  workflow: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  quote: "bg-purple-500/20 text-purple-300 border-purple-500/30",
};
const SEVERITY_LABELS = { 1: "Mild", 2: "Moderate", 3: "Critical" };
const SEVERITY_COLORS = {
  1: "bg-gray-700 text-gray-400",
  2: "bg-yellow-500/20 text-yellow-300",
  3: "bg-red-500/20 text-red-300",
};
const FEATURE_TAG_COLORS = {
  scheduling: "bg-forge-500/20 text-forge-300",
  quoting: "bg-blue-500/20 text-blue-300",
  supplier: "bg-green-500/20 text-green-300",
  defect_detection: "bg-orange-500/20 text-orange-300",
  energy: "bg-yellow-500/20 text-yellow-300",
  onboarding: "bg-purple-500/20 text-purple-300",
  other: "bg-gray-700 text-gray-400",
};

function SeverityBadge({ severity }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${SEVERITY_COLORS[severity] || SEVERITY_COLORS[1]}`}>
      {SEVERITY_LABELS[severity] || "Mild"}
    </span>
  );
}

function CategoryBadge({ category }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${CATEGORY_COLORS[category] || "bg-gray-700 text-gray-400 border-gray-600"}`}>
      {category.replace("_", " ")}
    </span>
  );
}

// ── Tab 1: Log Interview ──────────────────────────────────────────────────────

function LogInterview({ onInterviewLogged }) {
  const [form, setForm] = useState({
    contact_name: "",
    shop_name: "",
    shop_size: "6-20",
    role: "owner",
    date: new Date().toISOString().split("T")[0],
    raw_transcript: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/discovery/interviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
      onInterviewLogged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const groupedInsights = result?.insights
    ? result.insights.reduce((acc, ins) => {
        (acc[ins.category] = acc[ins.category] || []).push(ins);
        return acc;
      }, {})
    : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">Log Interview</h2>
        <p className="text-sm text-gray-400">Paste the conversation transcript — Claude will extract structured insights automatically.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Contact Name</label>
            <input className="input" value={form.contact_name} onChange={e => setForm(f => ({ ...f, contact_name: e.target.value }))} placeholder="John Smith" required />
          </div>
          <div>
            <label className="label">Shop Name</label>
            <input className="input" value={form.shop_name} onChange={e => setForm(f => ({ ...f, shop_name: e.target.value }))} placeholder="Acme Machining" required />
          </div>
          <div>
            <label className="label">Shop Size (employees)</label>
            <select className="input" value={form.shop_size} onChange={e => setForm(f => ({ ...f, shop_size: e.target.value }))}>
              {SHOP_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Role</label>
            <select className="input" value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
              {ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Interview Date</label>
            <input className="input" type="date" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))} required />
          </div>
        </div>

        <div>
          <label className="label">Transcript</label>
          <textarea
            className="input min-h-[200px] font-mono text-xs"
            value={form.raw_transcript}
            onChange={e => setForm(f => ({ ...f, raw_transcript: e.target.value }))}
            placeholder="Paste your interview notes or transcript here…"
            required
          />
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button type="submit" disabled={loading} className="btn-primary disabled:opacity-50">
          {loading ? "Extracting insights…" : "Log interview →"}
        </button>
      </form>

      {result && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-white">Extracted insights — {result.insights.length} found</h3>
            <span className="text-xs text-gray-500">{result.interview.shop_name} · {result.interview.role}</span>
          </div>

          {groupedInsights && Object.entries(groupedInsights).map(([category, insights]) => (
            <div key={category}>
              <div className="flex items-center gap-2 mb-2">
                <CategoryBadge category={category} />
                <span className="text-xs text-gray-500">{insights.length}</span>
              </div>
              <div className="space-y-2 pl-2">
                {insights.map(ins => (
                  <div key={ins.id} className="bg-gray-800/50 rounded-lg px-3 py-2">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm text-gray-200">{ins.content}</p>
                      <SeverityBadge severity={ins.severity} />
                    </div>
                    {ins.quote && (
                      <p className="text-xs text-gray-500 italic mt-1.5 border-l-2 border-gray-600 pl-2">
                        &ldquo;{ins.quote}&rdquo;
                      </p>
                    )}
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

// ── Tab 2: Patterns ───────────────────────────────────────────────────────────

function Patterns({ interviewCount }) {
  const [patterns, setPatterns] = useState(null);
  const [synthesizing, setSynthesizing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [synthMeta, setSynthMeta] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/discovery/patterns`, { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then(data => setPatterns(Array.isArray(data) ? data : []))
      .catch(() => setPatterns([]))
      .finally(() => setLoading(false));
  }, []);

  const handleSynthesize = async () => {
    setError(null);
    setSynthesizing(true);
    try {
      const res = await fetch(`${API_BASE}/api/discovery/synthesize`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${res.status}`);
      }
      const data = await res.json();
      setPatterns(data.patterns || []);
      setSynthMeta({ interviews: data.interviews_analyzed, insights: data.insights_analyzed });
    } catch (err) {
      setError(err.message);
    } finally {
      setSynthesizing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">Patterns</h2>
          <p className="text-sm text-gray-400">
            Recurring themes across {interviewCount} interview{interviewCount !== 1 ? "s" : ""}.
            {synthMeta && <span className="ml-1 text-gray-500">Last synthesis: {synthMeta.interviews} interviews, {synthMeta.insights} insights.</span>}
          </p>
        </div>
        <button onClick={handleSynthesize} disabled={synthesizing || interviewCount === 0} className="btn-primary text-sm whitespace-nowrap disabled:opacity-50">
          {synthesizing ? "Synthesizing…" : "Run Synthesis →"}
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {loading && <p className="text-sm text-gray-500">Loading patterns…</p>}

      {!loading && patterns?.length === 0 && (
        <div className="card text-center py-10">
          <p className="text-gray-500 text-sm">No patterns yet.</p>
          <p className="text-gray-600 text-xs mt-1">Log at least one interview, then click "Run Synthesis".</p>
        </div>
      )}

      {patterns?.map(p => (
        <div key={p.id} className="card space-y-3">
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-semibold text-white">{p.label}</h3>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${FEATURE_TAG_COLORS[p.feature_tag] || FEATURE_TAG_COLORS.other}`}>
              {p.feature_tag}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex-1 bg-gray-800 rounded-full h-2">
              <div
                className="bg-forge-500 h-2 rounded-full"
                style={{ width: `${Math.round(p.frequency * 100)}%` }}
              />
            </div>
            <span className="text-xs text-gray-400 shrink-0">{Math.round(p.frequency * 100)}% of interviews</span>
          </div>

          {p.evidence_quotes?.length > 0 && (
            <div className="space-y-1.5">
              {p.evidence_quotes.slice(0, 3).map((q, i) => (
                <p key={i} className="text-xs text-gray-400 italic border-l-2 border-gray-700 pl-2">
                  &ldquo;{q}&rdquo;
                </p>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Tab 3: Next Questions ─────────────────────────────────────────────────────

function NextQuestions({ interviewCount }) {
  const [questions, setQuestions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleGenerate = async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/discovery/next-questions`, {
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${res.status}`);
      }
      const data = await res.json();
      setQuestions(data.questions || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">Next Questions</h2>
          <p className="text-sm text-gray-400">
            Claude generates targeted questions based on what you've learned across {interviewCount} interview{interviewCount !== 1 ? "s" : ""} so far.
          </p>
        </div>
        <button onClick={handleGenerate} disabled={loading} className="btn-primary text-sm whitespace-nowrap disabled:opacity-50">
          {loading ? "Generating…" : "Generate Questions →"}
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {!questions && !loading && (
        <div className="card text-center py-10">
          <p className="text-gray-500 text-sm">Click "Generate Questions" to get AI-suggested interview questions.</p>
          <p className="text-gray-600 text-xs mt-1">Questions are tailored to pattern gaps and hypothesis coverage.</p>
        </div>
      )}

      {questions?.map((q, i) => (
        <div key={i} className="card space-y-3">
          <div className="flex items-start gap-3">
            <span className="text-2xl font-bold text-forge-500 shrink-0 leading-none">{i + 1}</span>
            <div className="space-y-2">
              <p className="text-white font-medium">{q.question}</p>
              <p className="text-sm text-gray-400">{q.rationale}</p>
              {q.follow_up && (
                <p className="text-xs text-gray-500 italic border-l-2 border-gray-700 pl-2">
                  Follow up: {q.follow_up}
                </p>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main Discovery page ───────────────────────────────────────────────────────

const DISC_TABS = [
  { id: "log", label: "Log Interview" },
  { id: "patterns", label: "Patterns" },
  { id: "questions", label: "Next Questions" },
];

export default function Discovery() {
  const [activeTab, setActiveTab] = useState("log");
  const [interviewCount, setInterviewCount] = useState(0);

  const refreshCount = () => {
    fetch(`${API_BASE}/api/discovery/interviews`, { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then(data => setInterviewCount(Array.isArray(data) ? data.length : 0))
      .catch(() => {});
  };

  useEffect(() => {
    refreshCount();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Customer Discovery</h1>
          <p className="text-sm text-gray-400 mt-0.5">{interviewCount} interview{interviewCount !== 1 ? "s" : ""} logged</p>
        </div>
      </div>

      {/* Sub-tab nav */}
      <nav className="flex gap-1 border-b border-gray-800">
        {DISC_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-forge-500 text-forge-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {activeTab === "log" && <LogInterview onInterviewLogged={refreshCount} />}
      {activeTab === "patterns" && <Patterns interviewCount={interviewCount} />}
      {activeTab === "questions" && <NextQuestions interviewCount={interviewCount} />}
    </div>
  );
}
