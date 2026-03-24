import { useState } from "react";
import { API_BASE } from "../config";

const DEFAULT_FORM = {
  name: "",
  email: "",
  company: "",
  message: "",
  pilot_interest: false,
};

export default function ContactForm() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((f) => ({ ...f, [name]: type === "checkbox" ? checked : value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Submission failed");
      }
      setResult(await res.json());
      setForm(DEFAULT_FORM);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-2">Get in Touch</h2>
      <p className="text-gray-400 mb-8">
        Interested in piloting MillForge at your facility? We'd love to hear from you.
      </p>

      {result ? (
        <div className="card text-center py-12">
          <span className="text-4xl mb-4 block">🎉</span>
          <p className="text-lg font-semibold text-white mb-2">Message Received!</p>
          <p className="text-gray-400">{result.message}</p>
          <button
            onClick={() => setResult(null)}
            className="btn-secondary mt-6"
          >
            Send Another Message
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="card space-y-5">
          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="label">Name *</label>
              <input
                name="name"
                value={form.name}
                onChange={handleChange}
                className="input"
                placeholder="Jane Smith"
                required
                minLength={2}
              />
            </div>
            <div>
              <label className="label">Email *</label>
              <input
                name="email"
                type="email"
                value={form.email}
                onChange={handleChange}
                className="input"
                placeholder="jane@company.com"
                required
              />
            </div>
          </div>

          <div>
            <label className="label">Company</label>
            <input
              name="company"
              value={form.company}
              onChange={handleChange}
              className="input"
              placeholder="Acme Manufacturing"
            />
          </div>

          <div>
            <label className="label">Message *</label>
            <textarea
              name="message"
              value={form.message}
              onChange={handleChange}
              className="input h-32 resize-none"
              placeholder="Tell us about your production environment, volumes, and what challenges you're facing…"
              required
              minLength={10}
            />
          </div>

          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              name="pilot_interest"
              checked={form.pilot_interest}
              onChange={handleChange}
              className="w-4 h-4 accent-forge-500"
            />
            <span className="text-sm text-gray-300 group-hover:text-white transition-colors">
              I'm interested in joining the MillForge pilot program
            </span>
          </label>

          {error && (
            <div className="p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
              {error}
            </div>
          )}

          <button type="submit" className="btn-primary w-full" disabled={loading}>
            {loading ? "Sending…" : "Send Message"}
          </button>
        </form>
      )}
    </div>
  );
}
