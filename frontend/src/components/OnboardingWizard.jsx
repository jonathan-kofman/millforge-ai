import { useState } from "react";
import { API_BASE } from "../config";

const SCHEDULING_METHODS = [
  { value: "fifo",   label: "FIFO (First In, First Out)" },
  { value: "edd",    label: "EDD (Earliest Due Date)" },
  { value: "manual", label: "Manual / Whiteboard" },
  { value: "erp",    label: "ERP System" },
];

export default function OnboardingWizard({ onComplete, onSkip }) {
  const [step, setStep] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const [form, setForm] = useState({
    shop_name: "",
    shifts_per_day: "2",
    hours_per_shift: "8",
    weekly_order_volume: "",
    scheduling_method: "",
    baseline_otd: "",
  });

  const save = async (payload, nextStep) => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/onboarding/shop-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ ...payload, wizard_step: nextStep }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Save failed");
      }
      if (nextStep >= 2) {
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
    await save({ shop_name: form.shop_name || null }, 2);
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
          {/* Progress bar */}
          <div className="flex items-center gap-2 mt-3">
            {[1, 2].map((s) => (
              <div
                key={s}
                className={`h-1.5 flex-1 rounded-full transition-colors ${
                  s <= step ? "bg-forge-500" : "bg-gray-700"
                }`}
              />
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-2">Step {step} of 2</p>
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
                  shifts_per_day: form.shifts_per_day ? Number(form.shifts_per_day) : null,
                  hours_per_shift: form.hours_per_shift ? Number(form.hours_per_shift) : null,
                  weekly_order_volume: form.weekly_order_volume ? Number(form.weekly_order_volume) : null,
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
                  scheduling_method: form.scheduling_method || null,
                  baseline_otd: form.baseline_otd ? Number(form.baseline_otd) : null,
                }, 2)
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
          <label className="label">Shifts per day</label>
          <select
            className="input"
            value={form.shifts_per_day}
            onChange={(e) => setForm((f) => ({ ...f, shifts_per_day: e.target.value }))}
          >
            <option value="1">1 shift</option>
            <option value="2">2 shifts</option>
            <option value="3">3 shifts (24h)</option>
          </select>
        </div>
        <div>
          <label className="label">Hours per shift</label>
          <select
            className="input"
            value={form.hours_per_shift}
            onChange={(e) => setForm((f) => ({ ...f, hours_per_shift: e.target.value }))}
          >
            <option value="8">8 hours</option>
            <option value="10">10 hours</option>
            <option value="12">12 hours</option>
          </select>
        </div>
        <div>
          <label className="label">Weekly order volume</label>
          <input
            type="number"
            min={0}
            className="input"
            placeholder="50"
            value={form.weekly_order_volume}
            onChange={(e) => setForm((f) => ({ ...f, weekly_order_volume: e.target.value }))}
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
