import { useState, useEffect } from "react";
import { API_BASE } from "../config";

const TIER_COLORS = {
  starter: "border-gray-600",
  growth: "border-forge-500",
  enterprise: "border-purple-500",
  custom: "border-yellow-500",
};

const TIER_BADGES = {
  growth: "Most Popular",
};

export default function PricingPage() {
  const [tiers, setTiers] = useState([]);
  const [billing, setBilling] = useState("annual");
  const [loading, setLoading] = useState(true);
  const [roiForm, setRoiForm] = useState({
    machine_count: 10,
    orders_per_month: 200,
    avg_order_value_usd: 1500,
    current_otd_percent: 74,
    shifts_per_day: 2,
  });
  const [roiResult, setRoiResult] = useState(null);
  const [roiLoading, setRoiLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/business/pricing-tiers`)
      .then((r) => r.json())
      .then((d) => {
        setTiers(d.tiers || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const calcROI = async (e) => {
    e.preventDefault();
    setRoiLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/business/roi-calculator`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          machine_count: Number(roiForm.machine_count),
          orders_per_month: Number(roiForm.orders_per_month),
          avg_order_value_usd: Number(roiForm.avg_order_value_usd),
          current_otd_percent: Number(roiForm.current_otd_percent),
          shifts_per_day: Number(roiForm.shifts_per_day),
        }),
      });
      if (res.ok) setRoiResult(await res.json());
    } catch {}
    setRoiLoading(false);
  };

  const fmt = (n) =>
    typeof n === "number"
      ? n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })
      : "—";

  if (loading) return <p className="text-gray-500 text-center py-10 animate-pulse">Loading...</p>;

  return (
    <div className="space-y-16">
      {/* Billing toggle */}
      <div className="text-center">
        <h2 className="text-3xl font-bold text-white mb-2">Plans that scale with your shop</h2>
        <p className="text-gray-400 text-sm mb-6">No implementation fees. No ERP replacement. Cancel anytime.</p>
        <div className="inline-flex bg-gray-800 rounded-lg p-1">
          <button
            onClick={() => setBilling("monthly")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              billing === "monthly" ? "bg-gray-700 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setBilling("annual")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              billing === "annual" ? "bg-forge-500 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Annual <span className="text-xs opacity-75">(2 months free)</span>
          </button>
        </div>
      </div>

      {/* Tier cards */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {tiers.map((tier) => {
          const badge = TIER_BADGES[tier.id];
          const color = TIER_COLORS[tier.id] || "border-gray-700";
          const price =
            billing === "annual"
              ? tier.price_annual_usd
                ? `${fmt(tier.price_annual_usd)}/yr`
                : "Contact us"
              : tier.price_monthly_usd
              ? `${fmt(tier.price_monthly_usd)}/mo`
              : "Contact us";

          return (
            <div
              key={tier.id}
              className={`relative bg-gray-900 rounded-xl border-2 ${color} p-6 flex flex-col`}
            >
              {badge && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-forge-500 text-white text-xs font-bold px-3 py-1 rounded-full">
                  {badge}
                </span>
              )}
              <h3 className="text-lg font-bold text-white mb-1">{tier.name}</h3>
              <p className="text-xs text-gray-500 mb-4">{tier.best_for}</p>
              <p className="text-2xl font-extrabold text-white mb-1">{price}</p>
              {tier.machine_limit ? (
                <p className="text-xs text-gray-500 mb-5">
                  Up to {tier.machine_limit} machines, {tier.user_limit} users
                </p>
              ) : (
                <p className="text-xs text-gray-500 mb-5">Unlimited machines and users</p>
              )}
              <ul className="space-y-2 flex-1 mb-6">
                {(tier.features || []).map((f, i) => (
                  <li key={i} className="text-sm text-gray-300 flex items-start gap-2">
                    <span className="text-forge-500 mt-0.5 flex-shrink-0">&#10003;</span>
                    {f}
                  </li>
                ))}
              </ul>
              <a
                href="https://calendly.com/jonkofm/30min"
                target="_blank"
                rel="noopener noreferrer"
                className={`text-center py-2.5 rounded-lg text-sm font-semibold transition-colors ${
                  tier.id === "growth"
                    ? "bg-forge-500 hover:bg-forge-600 text-white"
                    : "bg-gray-800 hover:bg-gray-700 text-gray-200"
                }`}
              >
                {tier.price_monthly_usd ? "Start free pilot" : "Contact sales"}
              </a>
            </div>
          );
        })}
      </div>

      {/* ROI Calculator */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-8">
        <h3 className="text-2xl font-bold text-white mb-2 text-center">ROI Calculator</h3>
        <p className="text-gray-400 text-sm text-center mb-8">
          See what MillForge saves your specific shop in year one.
        </p>
        <form onSubmit={calcROI} className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5 mb-8">
          <label className="block">
            <span className="label">Machines</span>
            <input
              type="number"
              min="1"
              max="500"
              className="input"
              value={roiForm.machine_count}
              onChange={(e) => setRoiForm((f) => ({ ...f, machine_count: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="label">Orders / month</span>
            <input
              type="number"
              min="1"
              className="input"
              value={roiForm.orders_per_month}
              onChange={(e) => setRoiForm((f) => ({ ...f, orders_per_month: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="label">Avg order value ($)</span>
            <input
              type="number"
              min="1"
              className="input"
              value={roiForm.avg_order_value_usd}
              onChange={(e) => setRoiForm((f) => ({ ...f, avg_order_value_usd: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="label">Current on-time rate (%)</span>
            <input
              type="number"
              min="0"
              max="100"
              className="input"
              value={roiForm.current_otd_percent}
              onChange={(e) => setRoiForm((f) => ({ ...f, current_otd_percent: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="label">Shifts per day</span>
            <select
              className="input"
              value={roiForm.shifts_per_day}
              onChange={(e) => setRoiForm((f) => ({ ...f, shifts_per_day: e.target.value }))}
            >
              <option value="1">1 shift</option>
              <option value="2">2 shifts</option>
              <option value="3">3 shifts</option>
            </select>
          </label>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={roiLoading}
              className="btn-primary w-full py-2.5 disabled:opacity-50"
            >
              {roiLoading ? "Calculating..." : "Calculate ROI"}
            </button>
          </div>
        </form>

        {roiResult && (
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
            <div className="bg-gray-800 rounded-lg p-5 text-center">
              <p className="text-xs text-gray-500 mb-1">On-Time Improvement</p>
              <p className="text-3xl font-bold text-forge-400">
                +{roiResult.otd_improvement?.improvement_pp}pp
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {roiResult.otd_improvement?.before_percent}% → {roiResult.otd_improvement?.after_percent}%
              </p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5 text-center">
              <p className="text-xs text-gray-500 mb-1">Annual Benefit</p>
              <p className="text-3xl font-bold text-green-400">
                {fmt(roiResult.annual_benefits_usd?.total)}
              </p>
              <p className="text-xs text-gray-500 mt-1">total savings + recovered revenue</p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5 text-center">
              <p className="text-xs text-gray-500 mb-1">MillForge Cost</p>
              <p className="text-3xl font-bold text-gray-300">
                {fmt(roiResult.millforge_cost_usd?.annual_subscription)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {roiResult.millforge_cost_usd?.recommended_tier} tier, annual
              </p>
            </div>
            <div className="bg-gray-800 rounded-lg p-5 text-center">
              <p className="text-xs text-gray-500 mb-1">ROI / Payback</p>
              <p className="text-3xl font-bold text-forge-400">
                {roiResult.summary?.roi_percent}%
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {roiResult.summary?.break_even_message}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
