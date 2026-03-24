import { useState } from "react";
import { API_BASE } from "../config";

export default function AuthModal({ onSuccess, onClose }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [form, setForm] = useState({ email: "", password: "", name: "", company: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) =>
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const url = mode === "login" ? `${API_BASE}/api/auth/login` : `${API_BASE}/api/auth/register`;
    const body = mode === "login"
      ? { email: form.email, password: form.password }
      : { email: form.email, password: form.password, name: form.name, company: form.company || undefined };
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Authentication failed");
      onSuccess(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="card w-full max-w-md relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-500 hover:text-white text-xl"
        >
          ×
        </button>

        <h2 className="text-xl font-bold text-white mb-1">
          {mode === "login" ? "Sign In" : "Create Account"}
        </h2>
        <p className="text-sm text-gray-400 mb-6">
          {mode === "login"
            ? "Access your orders and production schedule."
            : "Create an account to manage orders and schedules."}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "register" && (
            <>
              <div>
                <label className="label">Name *</label>
                <input name="name" value={form.name} onChange={handleChange}
                  className="input" placeholder="Jane Smith" required minLength={2} />
              </div>
              <div>
                <label className="label">Company</label>
                <input name="company" value={form.company} onChange={handleChange}
                  className="input" placeholder="Acme Manufacturing" />
              </div>
            </>
          )}
          <div>
            <label className="label">Email *</label>
            <input name="email" type="email" value={form.email} onChange={handleChange}
              className="input" placeholder="jane@company.com" required />
          </div>
          <div>
            <label className="label">Password *</label>
            <input name="password" type="password" value={form.password} onChange={handleChange}
              className="input" placeholder={mode === "register" ? "Min 8 characters" : ""}
              required minLength={mode === "register" ? 8 : 1} />
          </div>

          {error && (
            <p className="text-sm text-red-400 bg-red-900/30 border border-red-800 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button type="submit" className="btn-primary w-full" disabled={loading}>
            {loading ? "Please wait…" : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        <p className="text-sm text-center text-gray-500 mt-4">
          {mode === "login" ? "Don't have an account?" : "Already have an account?"}{" "}
          <button
            className="text-forge-400 hover:text-forge-300 font-medium"
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
          >
            {mode === "login" ? "Register" : "Sign In"}
          </button>
        </p>
      </div>
    </div>
  );
}
