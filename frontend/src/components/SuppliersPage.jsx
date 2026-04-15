import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const CATEGORY_COLORS = {
  metals:     "bg-blue-500/20 text-blue-300 border-blue-500/30",
  plastics:   "bg-purple-500/20 text-purple-300 border-purple-500/30",
  composites: "bg-green-500/20 text-green-300 border-green-500/30",
  wood:       "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
};

const CERT_OPTIONS = ["AS9100D", "ISO 9001", "ITAR", "NADCAP", "ISO 13485", "AISC Certified"];

const SEED_RFQS = [
  { rfq_id: "RFQ-001", material: "304 Stainless Steel Sheet", quantity: "500 lbs", deadline: "2026-05-01", location: "Cleveland, OH", certs: ["ISO 9001"], posted_at: null, response_count: 3 },
  { rfq_id: "RFQ-002", material: "6061 Aluminum Bar Stock", quantity: "2,000 lbs", deadline: "2026-04-25", location: "Detroit, MI", certs: [], posted_at: null, response_count: 7 },
  { rfq_id: "RFQ-003", material: "A36 Carbon Steel Plate", quantity: "10 sheets, 1\" thick", deadline: "2026-05-15", location: "Pittsburgh, PA", certs: ["AS9100D"], posted_at: null, response_count: 2 },
  { rfq_id: "RFQ-004", material: "Titanium Grade 5 Rod", quantity: "50 lbs", deadline: "2026-04-30", location: "Wichita, KS", certs: ["ITAR", "AS9100D"], posted_at: null, response_count: 1 },
  { rfq_id: "RFQ-005", material: "Copper Alloy C110", quantity: "200 lbs", deadline: "2026-05-10", location: "Cincinnati, OH", certs: [], posted_at: null, response_count: 4 },
];

function timeAgo(isoStr) {
  if (!isoStr) return null;
  const diff = (Date.now() - new Date(isoStr + "Z").getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function QuickRFQForm({ supplierName, onClose }) {
  const [form, setForm] = useState({ material: "", quantity: "", notes: "", email: "" });
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.email.split("@")[0] || "Anonymous",
          email: form.email,
          company: "",
          message: `RFQ for ${supplierName}: ${form.material}, qty: ${form.quantity}. Notes: ${form.notes}`,
          source: "marketplace_rfq",
        }),
      });
    } catch {}
    setSent(true);
    setLoading(false);
  };

  if (sent) {
    return (
      <div className="text-center py-3">
        <p className="text-sm font-semibold text-green-400">Request sent!</p>
        <p className="text-xs text-gray-500 mt-1">We'll connect you within 24 hours.</p>
        <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-300 mt-2 underline">Close</button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label">Material</label>
          <input className="input text-xs py-1.5" placeholder="steel, aluminum..." value={form.material}
            onChange={e => setForm(f => ({ ...f, material: e.target.value }))} required />
        </div>
        <div>
          <label className="label">Quantity</label>
          <input className="input text-xs py-1.5" placeholder="500 lbs, 10 sheets..." value={form.quantity}
            onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} />
        </div>
      </div>
      <div>
        <label className="label">Your email</label>
        <input type="email" className="input text-xs py-1.5" placeholder="you@company.com" value={form.email}
          onChange={e => setForm(f => ({ ...f, email: e.target.value }))} required />
      </div>
      <div>
        <label className="label">Notes</label>
        <textarea className="input text-xs py-1.5 h-14 resize-none"
          placeholder="Specs, certifications needed, deadline..." value={form.notes}
          onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={loading} className="btn-primary text-xs py-1.5 flex-1">
          {loading ? "Sending…" : "Send Request"}
        </button>
        <button type="button" onClick={onClose} className="btn-secondary text-xs py-1.5 px-3">Cancel</button>
      </div>
    </form>
  );
}

function SupplierCard({ supplier, distance }) {
  const [showRFQ, setShowRFQ] = useState(false);
  const cats = supplier.categories ?? [];
  return (
    <div className="card hover:border-gray-700 transition-colors flex flex-col">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-white">{supplier.name}</p>
          <p className="text-xs text-gray-500 mt-0.5">{supplier.city}, {supplier.state}</p>
        </div>
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          {supplier.verified && (
            <span className="text-xs bg-green-500/20 text-green-400 border border-green-500/30 px-2 py-0.5 rounded-full">
              Verified
            </span>
          )}
          {distance != null && (
            <span className="text-xs text-gray-500">{distance.toFixed(0)} mi</span>
          )}
        </div>
      </div>

      {cats.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {cats.slice(0, 3).map(c => (
            <span key={c} className={`text-xs px-2 py-0.5 rounded-full border ${CATEGORY_COLORS[c] ?? "bg-gray-700 text-gray-300 border-gray-600"}`}>
              {c}
            </span>
          ))}
        </div>
      )}

      {supplier.materials?.length > 0 && (
        <p className="text-xs text-gray-500 mb-3 line-clamp-2">
          {supplier.materials.slice(0, 6).join(" · ")}
        </p>
      )}

      <div className="mt-auto pt-3 border-t border-gray-800 flex items-center justify-between gap-2">
        <div className="flex gap-3 items-center flex-wrap">
          {supplier.phone && <span className="text-xs text-gray-500">{supplier.phone}</span>}
          {supplier.website && (
            <a
              href={supplier.website.startsWith("http") ? supplier.website : `https://${supplier.website}`}
              target="_blank" rel="noopener noreferrer"
              className="text-xs text-forge-400 hover:text-forge-300"
            >
              Website →
            </a>
          )}
        </div>
        <button
          onClick={() => setShowRFQ(v => !v)}
          className="text-xs font-semibold bg-forge-500/10 hover:bg-forge-500/20 text-forge-400 border border-forge-500/30 px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap"
        >
          {showRFQ ? "Cancel" : "Request Quote"}
        </button>
      </div>

      {showRFQ && (
        <div className="mt-3 pt-3 border-t border-gray-800">
          <p className="text-xs text-gray-500 mb-2">
            Quote request to <span className="text-gray-300">{supplier.name}</span>
          </p>
          <QuickRFQForm supplierName={supplier.name} onClose={() => setShowRFQ(false)} />
        </div>
      )}
    </div>
  );
}

function RespondForm({ rfqId, onClose, onSuccess }) {
  const [form, setForm] = useState({ supplier_name: "", email: "", message: "", price_indication: "", lead_time_indication: "" });
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/rfqs/${rfqId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
      setSent(true);
      onSuccess?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (sent) {
    return (
      <div className="text-center py-3">
        <p className="text-sm font-semibold text-green-400">Response sent!</p>
        <p className="text-xs text-gray-500 mt-1">The buyer will receive your contact details.</p>
        <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-300 mt-2 underline">Close</button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label">Your company *</label>
          <input className="input text-xs py-1.5" placeholder="Acme Steel LLC" value={form.supplier_name}
            onChange={e => setForm(f => ({ ...f, supplier_name: e.target.value }))} required />
        </div>
        <div>
          <label className="label">Your email *</label>
          <input type="email" className="input text-xs py-1.5" placeholder="you@company.com" value={form.email}
            onChange={e => setForm(f => ({ ...f, email: e.target.value }))} required />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="label">Price indication</label>
          <input className="input text-xs py-1.5" placeholder="$1.20/lb, $850 total…" value={form.price_indication}
            onChange={e => setForm(f => ({ ...f, price_indication: e.target.value }))} />
        </div>
        <div>
          <label className="label">Lead time</label>
          <input className="input text-xs py-1.5" placeholder="3–5 business days" value={form.lead_time_indication}
            onChange={e => setForm(f => ({ ...f, lead_time_indication: e.target.value }))} />
        </div>
      </div>
      <div>
        <label className="label">Message</label>
        <textarea className="input text-xs py-1.5 h-14 resize-none"
          placeholder="Certifications held, min order qty, any questions…" value={form.message}
          onChange={e => setForm(f => ({ ...f, message: e.target.value }))} />
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={loading} className="btn-primary text-xs py-1.5 flex-1">
          {loading ? "Sending…" : "Submit Response"}
        </button>
        <button type="button" onClick={onClose} className="btn-secondary text-xs py-1.5 px-3">Cancel</button>
      </div>
    </form>
  );
}

function RFQCard({ rfq, onResponded }) {
  const [showRespond, setShowRespond] = useState(false);
  const ago = timeAgo(rfq.posted_at);

  return (
    <div className="card hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="text-xs text-gray-600 font-mono">{rfq.rfq_id}</span>
            {ago && <><span className="text-gray-700">·</span><span className="text-xs text-gray-500">{ago}</span></>}
            {rfq.location && <><span className="text-gray-700">·</span><span className="text-xs text-gray-500">{rfq.location}</span></>}
            {!rfq.posted_at && <span className="text-xs text-gray-700 italic">example</span>}
          </div>
          <p className="font-semibold text-white">{rfq.material}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {rfq.quantity && `${rfq.quantity} · `}
            {rfq.deadline && `Need by ${rfq.deadline}`}
          </p>
          {rfq.certs?.length > 0 && (
            <div className="flex gap-1 mt-2 flex-wrap">
              {rfq.certs.map(c => (
                <span key={c} className="text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded-full">{c}</span>
              ))}
            </div>
          )}
        </div>
        <div className="text-right flex-shrink-0">
          <p className="text-xl font-bold text-forge-400">{rfq.response_count}</p>
          <p className="text-xs text-gray-500 mb-2">responses</p>
          <button
            onClick={() => setShowRespond(v => !v)}
            className="text-xs font-semibold text-forge-400 border border-forge-500/30 bg-forge-500/10 hover:bg-forge-500/20 px-3 py-1.5 rounded-lg transition-colors"
          >
            {showRespond ? "Cancel" : "Respond →"}
          </button>
        </div>
      </div>
      {showRespond && (
        <div className="mt-3 pt-3 border-t border-gray-800">
          <p className="text-xs text-gray-500 mb-2">
            Responding to <span className="text-gray-300">{rfq.rfq_id} — {rfq.material}</span>
          </p>
          <RespondForm
            rfqId={rfq.rfq_id}
            onClose={() => setShowRespond(false)}
            onSuccess={() => { setShowRespond(false); onResponded?.(); }}
          />
        </div>
      )}
    </div>
  );
}

function RFQBoard() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ material: "", quantity: "", deadline: "", location: "", certs: [], notes: "", email: "" });
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rfqs, setRfqs] = useState(SEED_RFQS);
  const [rfqsLoaded, setRfqsLoaded] = useState(false);

  const loadRFQs = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/rfqs`);
      if (res.ok) {
        const data = await res.json();
        setRfqs(data.length > 0 ? data : SEED_RFQS);
        setRfqsLoaded(true);
      }
    } catch {}
  };

  useEffect(() => { loadRFQs(); }, []);

  const toggleCert = (cert) => {
    setForm(f => ({
      ...f,
      certs: f.certs.includes(cert) ? f.certs.filter(c => c !== cert) : [...f.certs, cert],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/rfqs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          material: form.material,
          quantity: form.quantity || undefined,
          deadline: form.deadline || undefined,
          location: form.location || undefined,
          certs: form.certs,
          notes: form.notes || undefined,
          email: form.email,
        }),
      });
      if (res.ok) {
        const created = await res.json();
        setRfqs(prev => [created, ...prev.filter(r => r.posted_at !== null)]);
        setRfqsLoaded(true);
      }
    } catch {}
    setSubmitted(true);
    setLoading(false);
  };

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-6">
        <p className="text-sm text-gray-400 max-w-xl">
          Active material requests from US manufacturers. Post a need and qualified suppliers respond directly.
        </p>
        <button onClick={() => setShowForm(v => !v)} className="btn-primary text-sm whitespace-nowrap flex-shrink-0">
          {showForm ? "Cancel" : "+ Post Request"}
        </button>
      </div>

      {showForm && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-white mb-4">Post a Material Request</h3>
          {submitted ? (
            <div className="text-center py-6">
              <div className="w-10 h-10 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mx-auto mb-3">
                <span className="text-green-400">✓</span>
              </div>
              <p className="font-semibold text-white mb-1">Request posted!</p>
              <p className="text-sm text-gray-400">Matching suppliers will be notified.</p>
              <button onClick={() => { setSubmitted(false); setShowForm(false); setForm({ material: "", quantity: "", deadline: "", location: "", certs: [], notes: "", email: "" }); }} className="btn-secondary text-sm mt-4">
                Post another
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="label">Material needed *</label>
                  <input className="input" placeholder="304 Stainless Steel Sheet" value={form.material}
                    onChange={e => setForm(f => ({ ...f, material: e.target.value }))} required />
                </div>
                <div>
                  <label className="label">Quantity</label>
                  <input className="input" placeholder="500 lbs, 10 sheets..." value={form.quantity}
                    onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} />
                </div>
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="label">Deadline needed by</label>
                  <input type="date" className="input" value={form.deadline}
                    onChange={e => setForm(f => ({ ...f, deadline: e.target.value }))} />
                </div>
                <div>
                  <label className="label">Your location (city, state)</label>
                  <input className="input" placeholder="Cleveland, OH" value={form.location}
                    onChange={e => setForm(f => ({ ...f, location: e.target.value }))} />
                </div>
              </div>
              <div>
                <label className="label">Required certifications</label>
                <div className="flex flex-wrap gap-2 mt-1.5">
                  {CERT_OPTIONS.map(cert => (
                    <button
                      type="button" key={cert}
                      onClick={() => toggleCert(cert)}
                      className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                        form.certs.includes(cert)
                          ? "bg-forge-500/20 text-forge-400 border-forge-500/40"
                          : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                      }`}
                    >
                      {cert}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">Additional notes</label>
                <textarea className="input h-20 resize-none"
                  placeholder="Tolerances, finish, test certs, quantity flexibility..."
                  value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
              </div>
              <div>
                <label className="label">Your email *</label>
                <input type="email" className="input" placeholder="you@company.com" value={form.email}
                  onChange={e => setForm(f => ({ ...f, email: e.target.value }))} required />
              </div>
              <button type="submit" disabled={loading} className="btn-primary w-full">
                {loading ? "Posting…" : "Post Request"}
              </button>
            </form>
          )}
        </div>
      )}

      <div className="space-y-3">
        {rfqs.map(rfq => (
          <RFQCard key={rfq.rfq_id} rfq={rfq} onResponded={loadRFQs} />
        ))}
      </div>
    </div>
  );
}

const DEFAULT_LISTING = {
  name: "", city: "", state: "", address: "",
  materials: "", website: "", phone: "",
  certifications: [], capacity: "", lead_time: "", notes: "",
};

function ListYourShop() {
  const [form, setForm] = useState(DEFAULT_LISTING);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const toggleCert = (cert) => {
    setForm(f => ({
      ...f,
      certifications: f.certifications.includes(cert)
        ? f.certifications.filter(c => c !== cert)
        : [...f.certifications, cert],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const materialsArr = form.materials.split(",").map(m => m.trim().toLowerCase()).filter(Boolean);
      const res = await fetch(`${API_BASE}/api/suppliers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          city: form.city,
          state: form.state,
          address: form.address || undefined,
          materials: materialsArr,
          website: form.website || undefined,
          phone: form.phone || undefined,
          verified: false,
          data_source: "user_submitted",
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Submission failed");
      }
      setSubmitted(true);
      setForm(DEFAULT_LISTING);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="max-w-lg mx-auto text-center py-16">
        <div className="w-12 h-12 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center mx-auto mb-4">
          <span className="text-green-400 text-xl">✓</span>
        </div>
        <h3 className="text-xl font-bold text-white mb-2">Listing submitted</h3>
        <p className="text-gray-400 text-sm mb-6">
          We'll verify your shop and add it to the directory within 48 hours. Verified suppliers appear first in buyer searches and receive RFQ notifications.
        </p>
        <button onClick={() => setSubmitted(false)} className="btn-secondary text-sm">Submit another</button>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <h3 className="text-lg font-bold text-white mb-1">List Your Shop</h3>
        <p className="text-sm text-gray-400">
          Verified listings appear first in buyer searches and receive automatic RFQ notifications when buyers post requests matching your materials.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="card space-y-6">
        {/* Company info */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Company Info</p>
          <div className="space-y-3">
            <div>
              <label className="label">Company name *</label>
              <input className="input" placeholder="Olympic Steel" value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))} required minLength={2} />
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="label">City *</label>
                <input className="input" placeholder="Cleveland" value={form.city}
                  onChange={e => setForm(f => ({ ...f, city: e.target.value }))} required />
              </div>
              <div>
                <label className="label">State *</label>
                <input className="input" placeholder="OH" maxLength={2} value={form.state}
                  onChange={e => setForm(f => ({ ...f, state: e.target.value }))} required />
              </div>
            </div>
            <div>
              <label className="label">Street address</label>
              <input className="input" placeholder="123 Industrial Blvd" value={form.address}
                onChange={e => setForm(f => ({ ...f, address: e.target.value }))} />
            </div>
          </div>
        </div>

        {/* Materials & capabilities */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Materials & Capabilities</p>
          <div className="space-y-3">
            <div>
              <label className="label">Materials offered (comma-separated)</label>
              <input className="input" placeholder="steel, aluminum, stainless_steel, titanium" value={form.materials}
                onChange={e => setForm(f => ({ ...f, materials: e.target.value }))} />
            </div>
            <div>
              <label className="label">Certifications held</label>
              <div className="flex flex-wrap gap-2 mt-1.5">
                {CERT_OPTIONS.map(cert => (
                  <button
                    type="button" key={cert}
                    onClick={() => toggleCert(cert)}
                    className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                      form.certifications.includes(cert)
                        ? "bg-forge-500/20 text-forge-400 border-forge-500/40"
                        : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                    }`}
                  >
                    {cert}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="label">Typical capacity</label>
                <input className="input" placeholder="50,000 lbs/mo steel" value={form.capacity}
                  onChange={e => setForm(f => ({ ...f, capacity: e.target.value }))} />
              </div>
              <div>
                <label className="label">Standard lead time</label>
                <input className="input" placeholder="3–5 business days" value={form.lead_time}
                  onChange={e => setForm(f => ({ ...f, lead_time: e.target.value }))} />
              </div>
            </div>
          </div>
        </div>

        {/* Contact */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Contact</p>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="label">Website</label>
              <input className="input" placeholder="https://yoursupplier.com" value={form.website}
                onChange={e => setForm(f => ({ ...f, website: e.target.value }))} />
            </div>
            <div>
              <label className="label">Phone</label>
              <input className="input" placeholder="+1 (555) 000-0000" value={form.phone}
                onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} />
            </div>
          </div>
        </div>

        <div>
          <label className="label">Additional notes</label>
          <textarea className="input h-20 resize-none"
            placeholder="Specialties, min order quantities, geographic service area..."
            value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
        </div>

        {error && (
          <div className="p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">{error}</div>
        )}

        <div>
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? "Submitting…" : "Submit for Verification"}
          </button>
          <p className="text-xs text-gray-600 text-center mt-2">
            Listings reviewed within 48 hours. Verified listings appear first in search results.
          </p>
        </div>
      </form>
    </div>
  );
}

export default function SuppliersPage() {
  const [stats, setStats] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [results, setResults] = useState([]);
  const [searched, setSearched] = useState(false);
  const [nearbyResults, setNearbyResults] = useState([]);
  const [nearbySearched, setNearbySearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [nearbyLoading, setNearbyLoading] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("find");
  const [findMode, setFindMode] = useState("search");
  const [searchForm, setSearchForm] = useState({ name: "", material: "", state: "", category: "", verified_only: false });
  const [nearbyForm, setNearbyForm] = useState({ lat: "", lng: "", radius_miles: "250", material: "" });
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState(null);

  const handleUseMyLocation = () => {
    if (!navigator.geolocation) { setGeoError("Geolocation not supported."); return; }
    setGeoLoading(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      pos => { setNearbyForm(f => ({ ...f, lat: pos.coords.latitude.toFixed(4), lng: pos.coords.longitude.toFixed(4) })); setGeoLoading(false); },
      () => { setGeoError("Location access denied. Enter coordinates manually."); setGeoLoading(false); }
    );
  };

  useEffect(() => {
    fetch(`${API_BASE}/api/suppliers/stats`).then(r => r.json()).then(setStats).catch(() => {});
    fetch(`${API_BASE}/api/suppliers/materials`).then(r => r.json()).then(d => setMaterials(d?.all_materials ?? [])).catch(() => {});
  }, []);

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "24" });
      if (searchForm.name) params.set("name", searchForm.name);
      if (searchForm.material) params.set("material", searchForm.material);
      if (searchForm.state) params.set("state", searchForm.state.toUpperCase());
      if (searchForm.category) params.set("category", searchForm.category);
      if (searchForm.verified_only) params.set("verified_only", "true");
      const res = await fetch(`${API_BASE}/api/suppliers?${params}`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      setResults(data.suppliers ?? data ?? []);
      setSearched(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleNearby = async (e) => {
    e.preventDefault();
    setNearbyLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ lat: nearbyForm.lat, lng: nearbyForm.lng, radius_miles: nearbyForm.radius_miles, limit: "20" });
      if (nearbyForm.material) params.set("material", nearbyForm.material);
      const res = await fetch(`${API_BASE}/api/suppliers/nearby?${params}`);
      if (!res.ok) throw new Error("Nearby search failed");
      const data = await res.json();
      setNearbyResults(data.results ?? data ?? []);
      setNearbySearched(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setNearbyLoading(false);
    }
  };

  const TABS = [
    { id: "find",  label: "Find Suppliers" },
    { id: "rfq",   label: "Post a Request" },
    { id: "list",  label: "List Your Shop" },
  ];

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <p className="text-xs font-bold tracking-widest text-forge-500 uppercase mb-1">Materials Marketplace</p>
        <h2 className="text-2xl font-bold text-white mb-1">US Manufacturing Supplier Network</h2>
        <p className="text-gray-400 text-sm">
          Connect buyers and sellers across the US metals supply chain. Find verified suppliers, post material requests, or list your shop.
        </p>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          {[
            { label: "Total Suppliers", val: stats.total_suppliers?.toLocaleString() },
            { label: "Verified", val: stats.verified_suppliers?.toLocaleString() },
            { label: "States Covered", val: stats.states_covered },
            { label: "Material Categories", val: "4" },
          ].map(s => (
            <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">{s.label}</p>
              <p className="text-xl font-bold text-forge-400">{s.val}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tab nav */}
      <div className="flex gap-1 border-b border-gray-800 mb-6">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors duration-150 -mb-px ${
              tab === t.id ? "border-forge-500 text-forge-400" : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Find Suppliers */}
      {tab === "find" && (
        <div>
          <div className="flex gap-2 mb-5">
            {[{ id: "search", label: "Search" }, { id: "nearby", label: "Near Me" }].map(m => (
              <button
                key={m.id}
                onClick={() => setFindMode(m.id)}
                className={`px-4 py-2 text-sm font-medium rounded-lg border transition-colors ${
                  findMode === m.id
                    ? "bg-forge-500/20 text-forge-400 border-forge-500/30"
                    : "bg-transparent text-gray-400 border-gray-700 hover:text-white hover:border-gray-600"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>

          {findMode === "search" && (
            <>
              <form onSubmit={handleSearch} className="card mb-6">
                <div className="grid sm:grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="label">Supplier name</label>
                    <input className="input" placeholder="Ryerson, Olympic Steel…"
                      value={searchForm.name} onChange={e => setSearchForm(f => ({ ...f, name: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Material</label>
                    <input className="input" placeholder="steel, aluminum…"
                      value={searchForm.material} onChange={e => setSearchForm(f => ({ ...f, material: e.target.value }))} list="material-list" />
                    <datalist id="material-list">
                      {materials.slice(0, 40).map(m => <option key={m} value={m} />)}
                    </datalist>
                  </div>
                </div>
                <div className="grid sm:grid-cols-4 gap-4 items-end">
                  <div>
                    <label className="label">State</label>
                    <input className="input" placeholder="OH, MI, TX…" maxLength={2}
                      value={searchForm.state} onChange={e => setSearchForm(f => ({ ...f, state: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Category</label>
                    <select className="input" value={searchForm.category} onChange={e => setSearchForm(f => ({ ...f, category: e.target.value }))}>
                      <option value="">All</option>
                      <option value="metals">Metals</option>
                      <option value="plastics">Plastics</option>
                      <option value="composites">Composites</option>
                      <option value="wood">Wood</option>
                    </select>
                  </div>
                  <div className="flex items-center">
                    <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                      <input type="checkbox" checked={searchForm.verified_only}
                        onChange={e => setSearchForm(f => ({ ...f, verified_only: e.target.checked }))}
                        className="accent-forge-500" />
                      Verified only
                    </label>
                  </div>
                  <button type="submit" disabled={loading} className="btn-primary">
                    {loading ? "Searching…" : "Search"}
                  </button>
                </div>
              </form>

              {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

              {results.length > 0 ? (
                <div>
                  <p className="text-sm text-gray-500 mb-3">{results.length} results</p>
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {results.map(s => <SupplierCard key={s.id} supplier={s} />)}
                  </div>
                </div>
              ) : searched && !loading && (
                <div className="card text-center py-10 text-gray-500 text-sm">
                  No suppliers found. Try broadening your search or removing filters.
                </div>
              )}
            </>
          )}

          {findMode === "nearby" && (
            <>
              <form onSubmit={handleNearby} className="card mb-6">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-xs text-gray-500">Find verified suppliers within a radius of your location.</p>
                  <button type="button" onClick={handleUseMyLocation} disabled={geoLoading}
                    className="text-xs text-forge-400 border border-forge-500/40 rounded-lg px-3 py-1.5 hover:bg-forge-500/10 transition-colors disabled:opacity-50">
                    {geoLoading ? "Detecting…" : "Use My Location"}
                  </button>
                </div>
                {geoError && <p className="text-xs text-red-400 mb-3">{geoError}</p>}
                <div className="grid sm:grid-cols-4 gap-4">
                  <div>
                    <label className="label">Latitude</label>
                    <input className="input" placeholder="41.49" value={nearbyForm.lat}
                      onChange={e => setNearbyForm(f => ({ ...f, lat: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Longitude</label>
                    <input className="input" placeholder="-81.69" value={nearbyForm.lng}
                      onChange={e => setNearbyForm(f => ({ ...f, lng: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Radius (miles)</label>
                    <input className="input" type="number" min="1" value={nearbyForm.radius_miles}
                      onChange={e => setNearbyForm(f => ({ ...f, radius_miles: e.target.value }))} />
                  </div>
                  <div>
                    <label className="label">Material (optional)</label>
                    <input className="input" placeholder="steel…" value={nearbyForm.material}
                      onChange={e => setNearbyForm(f => ({ ...f, material: e.target.value }))} />
                  </div>
                </div>
                <button type="submit" disabled={nearbyLoading} className="btn-primary mt-4">
                  {nearbyLoading ? "Searching…" : "Find Nearby"}
                </button>
              </form>

              {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

              {nearbyResults.length > 0 ? (
                <div>
                  <p className="text-sm text-gray-500 mb-3">{nearbyResults.length} suppliers, sorted by distance</p>
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {nearbyResults.map(item => {
                      const supplier = item.supplier ?? item;
                      const distance = item.distance_miles ?? null;
                      return <SupplierCard key={supplier.id} supplier={supplier} distance={distance} />;
                    })}
                  </div>
                </div>
              ) : nearbySearched && !nearbyLoading && (
                <div className="card text-center py-10 text-gray-500 text-sm">
                  No suppliers found within that radius. Try expanding the search area.
                </div>
              )}
            </>
          )}
        </div>
      )}

      {tab === "rfq"  && <RFQBoard />}
      {tab === "list" && <ListYourShop />}
    </div>
  );
}
