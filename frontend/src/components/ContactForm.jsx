import { useState } from "react";
import { API_BASE } from "../config";

const DEFAULT_FORM = { name: "", email: "", company: "", message: "" };

export default function ContactForm() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((f) => ({ ...f, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, pilot_interest: true }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Submission failed");
      }
      setSubmitted(true);
      setForm(DEFAULT_FORM);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-2">Get in Touch</h2>
      <p className="text-gray-400 mb-8">
        Interested in piloting MillForge AI at your facility? Reach out directly or fill out the form.
      </p>

      <div className="grid sm:grid-cols-2 gap-8">
        {/* ── Left: contact form ── */}
        <div>
          {submitted ? (
            <div className="card text-center py-10">
              <p className="text-lg font-semibold text-white mb-2">Message received.</p>
              <p className="text-gray-400 text-sm">Thanks — I'll get back to you within 24 hours.</p>
              <button onClick={() => setSubmitted(false)} className="btn-secondary mt-6 text-sm">
                Send another message
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="card space-y-4">
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

              <div>
                <label className="label">Company or Shop Name</label>
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
                  className="input h-28 resize-none"
                  placeholder="Tell us about your production environment and what challenges you're facing…"
                  required
                  minLength={10}
                />
              </div>

              {error && (
                <div className="p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
                  {error}
                </div>
              )}

              <button type="submit" className="btn-primary w-full" disabled={loading}>
                {loading ? "Sending…" : "Submit"}
              </button>
            </form>
          )}
        </div>

        {/* ── Right: direct contact info ── */}
        <div className="space-y-6 pt-2">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Email</p>
            <a
              href="mailto:kofman.j@northeastern.edu"
              className="text-forge-400 hover:text-forge-300 transition-colors text-sm"
            >
              kofman.j@northeastern.edu
            </a>
          </div>

          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Schedule a call</p>
            <a
              href="https://calendly.com/jonathan-kofman"
              target="_blank"
              rel="noopener noreferrer"
              className="text-forge-400 hover:text-forge-300 transition-colors text-sm"
            >
              Book a 20-minute call →
            </a>
          </div>

          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Location</p>
            <p className="text-gray-300 text-sm">
              Based in Boston, MA — serving mills and job shops across the US.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
