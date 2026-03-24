import { useState } from "react";
import { API_BASE } from "../config";

const DEFAULT_FORM = { name: "", email: "", company: "", cnc_machines: "", primary_materials: [], avg_lead_time: "", message: "" };
const DEFAULT_SUPPLIER = { name: "", city: "", state: "", address: "", materials: "", website: "", phone: "" };

export default function ContactForm() {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Supplier submission state
  const [showSupplierForm, setShowSupplierForm] = useState(false);
  const [supplierForm, setSupplierForm] = useState(DEFAULT_SUPPLIER);
  const [supplierSubmitted, setSupplierSubmitted] = useState(false);
  const [supplierLoading, setSupplierLoading] = useState(false);
  const [supplierError, setSupplierError] = useState(null);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    if (type === "checkbox") {
      setForm((f) => ({
        ...f,
        primary_materials: checked
          ? [...f.primary_materials, value]
          : f.primary_materials.filter((m) => m !== value),
      }));
    } else {
      setForm((f) => ({ ...f, [name]: value }));
    }
  };

  const handleSupplierChange = (e) => {
    const { name, value } = e.target;
    setSupplierForm((f) => ({ ...f, [name]: value }));
  };

  const handleSupplierSubmit = async (e) => {
    e.preventDefault();
    setSupplierLoading(true);
    setSupplierError(null);
    try {
      const materialsArr = supplierForm.materials
        .split(",")
        .map((m) => m.trim().toLowerCase())
        .filter(Boolean);
      const res = await fetch(`${API_BASE}/api/suppliers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: supplierForm.name,
          city: supplierForm.city,
          state: supplierForm.state,
          address: supplierForm.address || undefined,
          materials: materialsArr,
          website: supplierForm.website || undefined,
          phone: supplierForm.phone || undefined,
          verified: false,
          data_source: "user_submitted",
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Submission failed");
      }
      setSupplierSubmitted(true);
      setSupplierForm(DEFAULT_SUPPLIER);
    } catch (err) {
      setSupplierError(err.message);
    } finally {
      setSupplierLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          email: form.email,
          company: form.company,
          message: `${form.message ? form.message + "\n\n" : ""}CNC machines: ${form.cnc_machines || "not specified"}\nMaterials: ${form.primary_materials.join(", ") || "not specified"}\nAvg lead time: ${form.avg_lead_time || "not specified"}`,
          pilot_interest: true,
        }),
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
        Interested in piloting MillForge AI at your facility? Book a call or send a message below.
      </p>

      {/* ── Primary CTA — Calendly ── */}
      <div className="mb-10 text-center">
        <a
          href="https://calendly.com/jonkofm/30min"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block bg-forge-500 hover:bg-forge-600 text-white font-bold px-10 py-4 rounded-xl text-base transition-colors duration-150 shadow-lg"
        >
          Book a 30-minute floor review →
        </a>
        <p className="text-xs text-gray-600 mt-3">
          Starts in shadow mode — MillForge proposes schedules, your planners approve.<br />
          No changes to machines or ERP until you&apos;re ready.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-8">
        {/* ── Left: contact form ── */}
        <div>
          <p className="text-sm text-gray-500 mb-4">Or send a message</p>
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
                <label className="label">Number of CNC machines</label>
                <select
                  name="cnc_machines"
                  value={form.cnc_machines}
                  onChange={handleChange}
                  className="input"
                >
                  <option value="">Select range…</option>
                  <option value="1-5">1–5</option>
                  <option value="6-15">6–15</option>
                  <option value="16-50">16–50</option>
                  <option value="50+">50+</option>
                </select>
              </div>

              <div>
                <label className="label">Primary materials</label>
                <div className="flex flex-wrap gap-3 mt-1">
                  {["Steel", "Aluminum", "Titanium", "Other"].map((m) => (
                    <label key={m} className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                      <input
                        type="checkbox"
                        value={m}
                        checked={form.primary_materials.includes(m)}
                        onChange={handleChange}
                        className="accent-orange-500"
                      />
                      {m}
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <label className="label">Average quoted lead time</label>
                <select
                  name="avg_lead_time"
                  value={form.avg_lead_time}
                  onChange={handleChange}
                  className="input"
                >
                  <option value="">Select…</option>
                  <option value="Under 2 weeks">Under 2 weeks</option>
                  <option value="2-8 weeks">2–8 weeks</option>
                  <option value="8+ weeks">8+ weeks</option>
                </select>
              </div>

              <div>
                <label className="label">Message</label>
                <textarea
                  name="message"
                  value={form.message}
                  onChange={handleChange}
                  className="input h-24 resize-none"
                  placeholder="Anything else you'd like us to know…"
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
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Location</p>
            <p className="text-gray-300 text-sm">
              Based in Boston, MA — serving mills and job shops across the US.
            </p>
          </div>

          {/* ── Submit a supplier ── */}
          <div className="border-t border-gray-800 pt-6">
            <button
              onClick={() => { setShowSupplierForm((v) => !v); setSupplierSubmitted(false); setSupplierError(null); }}
              className="btn-secondary text-sm w-full"
            >
              {showSupplierForm ? "Hide supplier form" : "Submit a supplier →"}
            </button>

            {showSupplierForm && (
              <div className="mt-4">
                {supplierSubmitted ? (
                  <div className="card text-center py-6">
                    <p className="text-white font-semibold mb-1">Supplier submitted.</p>
                    <p className="text-gray-400 text-sm">We'll verify and add it to the directory.</p>
                    <button onClick={() => setSupplierSubmitted(false)} className="btn-secondary mt-4 text-xs">
                      Submit another
                    </button>
                  </div>
                ) : (
                  <form onSubmit={handleSupplierSubmit} className="card space-y-3">
                    <p className="text-xs text-gray-500">Know a US metal supplier that should be listed? Add them here.</p>
                    <div>
                      <label className="label">Supplier name *</label>
                      <input name="name" value={supplierForm.name} onChange={handleSupplierChange} className="input" placeholder="Olympic Steel" required minLength={2} />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="label">City *</label>
                        <input name="city" value={supplierForm.city} onChange={handleSupplierChange} className="input" placeholder="Cleveland" required />
                      </div>
                      <div>
                        <label className="label">State *</label>
                        <input name="state" value={supplierForm.state} onChange={handleSupplierChange} className="input" placeholder="OH" required maxLength={50} />
                      </div>
                    </div>
                    <div>
                      <label className="label">Street address</label>
                      <input name="address" value={supplierForm.address} onChange={handleSupplierChange} className="input" placeholder="123 Industrial Blvd" />
                    </div>
                    <div>
                      <label className="label">Materials (comma-separated)</label>
                      <input name="materials" value={supplierForm.materials} onChange={handleSupplierChange} className="input" placeholder="steel, aluminum, stainless_steel" />
                    </div>
                    <div>
                      <label className="label">Website</label>
                      <input name="website" value={supplierForm.website} onChange={handleSupplierChange} className="input" placeholder="https://supplier.com" />
                    </div>
                    <div>
                      <label className="label">Phone</label>
                      <input name="phone" value={supplierForm.phone} onChange={handleSupplierChange} className="input" placeholder="+1 (555) 000-0000" />
                    </div>
                    {supplierError && (
                      <div className="p-2 bg-red-900/40 border border-red-700 rounded text-red-300 text-xs">{supplierError}</div>
                    )}
                    <button type="submit" className="btn-primary w-full text-sm" disabled={supplierLoading}>
                      {supplierLoading ? "Submitting…" : "Submit supplier"}
                    </button>
                  </form>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
