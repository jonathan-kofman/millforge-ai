import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const CIRCUIT_COLORS = {
  closed:   "bg-green-900 text-green-300",
  degraded: "bg-yellow-900 text-yellow-300",
  open:     "bg-red-900 text-red-300",
  unknown:  "bg-gray-700 text-gray-400",
};

const STAGE_LABELS = {
  job_received:        "Job received",
  feedback_stored:     "Feedback stored",
  auto_feedback_stored:"Auto-feedback",
  circuit_open:        "Circuit opened",
  submission_error:    "Submission error",
};

export default function PipelineHealth() {
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [expanded, setExpanded] = useState(null);

  const load = () => {
    fetch(`${API_BASE}/health`, { credentials: "include" })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setHealth(d.pipeline || null))
      .catch(() => {});

    fetch(`${API_BASE}/api/health/pipeline-events?limit=10`, { credentials: "include" })
      .then((r) => r.ok ? r.json() : { events: [] })
      .then((d) => setEvents(d.events || []))
      .catch(() => {});
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const circuit = health?.circuit_state || "unknown";
  const queueDepth = events.filter((e) => e.event_type === "circuit_open").length;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-forge-200">ARIA Pipeline</h3>
        <button
          onClick={load}
          className="text-xs text-forge-400 hover:text-forge-200 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Circuit state + stats */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${CIRCUIT_COLORS[circuit] || CIRCUIT_COLORS.unknown}`}>
          Circuit: {circuit}
        </span>
        {health && (
          <>
            <span className="text-xs text-forge-400">
              {health.recent_event_count} events
            </span>
            <span className={`text-xs ${health.aria_bridge_configured ? "text-green-400" : "text-forge-500"}`}>
              {health.aria_bridge_configured ? "Bridge configured" : "Bridge not configured"}
            </span>
          </>
        )}
      </div>

      {/* Recent events */}
      {events.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-forge-500 uppercase tracking-wide">Recent events</div>
          {events.slice(0, 6).map((ev, i) => (
            <div key={i}>
              <button
                className="w-full text-left flex items-center justify-between py-1 px-2 rounded hover:bg-forge-800 transition-colors"
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    ev.event_type === "circuit_open" || ev.event_type === "submission_error"
                      ? "bg-red-400"
                      : "bg-green-400"
                  }`} />
                  <span className="text-xs text-forge-300 truncate">
                    {STAGE_LABELS[ev.event_type] || ev.event_type}
                  </span>
                  {ev.job_id && (
                    <span className="text-xs text-forge-500 flex-shrink-0">#{ev.job_id}</span>
                  )}
                </div>
                <span className="text-xs text-forge-500 flex-shrink-0 ml-2">
                  {new Date(ev.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              </button>
              {expanded === i && (
                <pre className="mt-1 mx-2 p-2 bg-forge-900 rounded text-xs text-forge-400 overflow-x-auto">
                  {JSON.stringify(ev, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {events.length === 0 && (
        <p className="text-xs text-forge-500">No pipeline events recorded yet.</p>
      )}
    </div>
  );
}
