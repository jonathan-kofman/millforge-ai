import { useState } from "react";
import { API_BASE } from "../config";

const MATERIALS = ["steel", "aluminum", "titanium", "copper"];
const SCHEDULING_METHODS = [
  { value: "fifo",   label: "FIFO (First In, First Out)" },
  { value: "edd",    label: "EDD (Earliest Due Date)" },
  { value: "manual", label: "Manual / Whiteboard" },
  { value: "erp",    label: "ERP System" },
];

export default function OnboardingWizard({ token, onComplete, onSkip }) {
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const [form, setForm] = useState({
    shop_name: "",
    machine_count: "",
    materials: [],
    weekly_order_volume: "",
    scheduling_method: "",
    baseline_otd: "",
  });

  const authHeaders = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };

  const save = async (payload, nextStep) => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/onboarding/shop-config`, {
        method: "PUT",
        headers: authHeaders,
        body: JSON.stringify({ ...payload, wizard_step: nextStep }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Save failed");
      }
      if (nextStep >= 3) {
        onComplete();
      } else {
        setStep(nextStep + 1);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const skipAll = async () => {
    // Save whatever we have so far, mark step 3 as skipped
    await save({
      shop_name: form.shop_name || null,
      machine_count: form.machine_count ? Number(form.machine_count) : null,
    }, 3);
    onSkip();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg shadow-2xl">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-800">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-lg font-bold text-white">Set up your shop</h2>
            <button
              onClick={skipAll}
              className="text-xs text-gray-500 hover:text-gray-400"
            >
              Skip setup →
            </button>
          </div>
          {/* Progress dots */}
          <div className="flex items-center gap-2 mt-3">
            {[1, 2, 3].map((s) => (
              <div
                key={s}
                className={`h-1.5 flex-1 rounded-full transition-colors ${
                  s <= step ? "bg-forge-500" : "bg-gray-700"
                }`}
              />
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-2">Step {step} of 3</p>
        </div>

        {/* Step content */}
        <div className="px-6 py-5">
          {step === 1 && (
            <Step1
              form={form}
              setForm={setForm}
              onNext={() =>
                save({
                  shop_name: form.shop_name || null,
                  machine_count: form.machine_count ? Number(form.machine_count) : null,
                }, 1)
              }
              onSkip={skipAll}
              saving={saving}
            />
          )}
          {step === 2 && (
            <Step2
              form={form}
              setForm={setForm}
              onNext={() =>
                save({
                  materials: form.materials,
                  weekly_order_volume: form.weekly_order_volume
                    ? Number(form.weekly_order_volume)
                    : null,
                }, 2)
              }
              onSkip={skipAll}
              saving={saving}
            />
          )}
          {step === 3 && (
            <Step3
              form={form}
              setForm={setForm}
              onNext={() =>
                save({
                  scheduling_method: form.scheduling_method || null,
                  baseline_otd: form.baseline_otd ? Number(form.baseline_otd) : null,
                }, 3)
              }
              onSkip={skipAll}
              saving={saving}
            />
          )}

          {error && (
            <p className="mt-3 text-xs text-red-400">{error}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function Step1({ form, setForm, onNext, onSkip, saving }) {
  return (
    <div>
      <h3 className="text-base font-semibold text-white mb-1">Shop basics</h3>
      <p className="text-sm text-gray-400 mb-4">
        Tell us about your facility so MillForge can calibrate its defaults.
      </p>
      <div className="space-y-3">
        <div>
          <label className="label">Shop name</label>
          <input
            className="input"
            placeholder="Acme Metal Works"
            value={form.shop_name}
            onChange={(e) => setForm((f) => ({ ...f, shop_name: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Number of CNC machines</label>
          <input
            type="number"
            min={1}
            className="input"
            placeholder="4"
            value={form.machine_count}
            onChange={(e) => setForm((f) => ({ ...f, machine_count: e.target.value }))}
          />
        </div>
      </div>
      <div className="flex gap-2 mt-5">
        <button className="btn-primary flex-1" onClick={onNext} disabled={saving}>
          {saving ? "Saving…" : "Next →"}
        </button>
        <button className="btn-secondary text-sm" onClick={onSkip} disabled={saving}>
          Skip
        </button>
      </div>
    </div>
  );
}

function Step2({ form, setForm, onNext, onSkip, saving }) {
  const toggleMaterial = (mat) =>
    setForm((f) => ({
      ...f,
      materials: f.materials.includes(mat)
        ? f.materials.filter((m) => m !== mat)
        : [...f.materials, mat],
    }));

  return (
    <div>
      <h3 className="text-base font-semibold text-white mb-1">Materials & volume</h3>
      <p className="text-sm text-gray-400 mb-4">
        Which materials do you run, and how many orders per week?
      </p>
      <div className="space-y-3">
        <div>
          <label className="label">Materials processed</label>
          <div className="flex flex-wrap gap-2 mt-1">
            {MATERIALS.map((mat) => (
              <button
                key={mat}
                type="button"
                onClick={() => toggleMaterial(mat)}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  form.materials.includes(mat)
                    ? "bg-forge-500 border-forge-500 text-white"
                    : "border-gray-600 text-gray-400 hover:border-gray-400"
                }`}
              >
                {mat.charAt(0).toUpperCase() + mat.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="label">Weekly order volume</label>
          <input
            type="number"
            min={0}
            className="input"
            placeholder="50"
            value={form.weekly_order_volume}
            onChange={(e) =>
              setForm((f) => ({ ...f, weekly_order_volume: e.target.value }))
            }
          />
        </div>
      </div>
      <div className="flex gap-2 mt-5">
        <button className="btn-primary flex-1" onClick={onNext} disabled={saving}>
          {saving ? "Saving…" : "Next →"}
        </button>
        <button className="btn-secondary text-sm" onClick={onSkip} disabled={saving}>
          Skip
        </button>
      </div>
    </div>
  );
}

function Step3({ form, setForm, onNext, onSkip, saving }) {
  return (
    <div>
      <h3 className="text-base font-semibold text-white mb-1">Scheduling baseline</h3>
      <p className="text-sm text-gray-400 mb-4">
        What's your current on-time rate? We'll use this as your before/after benchmark.
      </p>
      <div className="space-y-3">
        <div>
          <label className="label">Current scheduling method</label>
          <select
            className="input"
            value={form.scheduling_method}
            onChange={(e) =>
              setForm((f) => ({ ...f, scheduling_method: e.target.value }))
            }
          >
            <option value="">Select…</option>
            {SCHEDULING_METHODS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Current on-time delivery rate (%)</label>
          <input
            type="number"
            min={0}
            max={100}
            className="input"
            placeholder="65"
            value={form.baseline_otd}
            onChange={(e) =>
              setForm((f) => ({ ...f, baseline_otd: e.target.value }))
            }
          />
        </div>
      </div>
      <div className="flex gap-2 mt-5">
        <button className="btn-primary flex-1" onClick={onNext} disabled={saving}>
          {saving ? "Saving…" : "Finish setup →"}
        </button>
        <button className="btn-secondary text-sm" onClick={onSkip} disabled={saving}>
          Skip
        </button>
      </div>
    </div>
  );
}
