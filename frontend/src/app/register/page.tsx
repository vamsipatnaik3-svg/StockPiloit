
"use client";

import { useState, type FormEvent, type ChangeEvent } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const initialForm = {
  full_name: "",
  email: "",
  password: "",
  company_name: "",
  industry: "grocery",
  country_code: "IN",
  currency: "INR",
  timezone: "Asia/Kolkata",
};

export default function RegisterPage() {
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  function handleChange(
    event: ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) {
    setForm((previous) => ({
      ...previous,
      [event.target.name]: event.target.value,
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/auth/register`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        const message = Array.isArray(data.detail)
          ? data.detail.map((item: { msg: string }) => item.msg).join(", ")
          : data.detail || "Registration failed.";

        throw new Error(message);
      }

      setSuccess(
        `Your company, ${data.company_name}, has been registered successfully.`
      );
      setForm(initialForm);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Something went wrong."
      );
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "w-full rounded-xl border border-slate-200 bg-white px-4 py-3.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10";

  const labelClass =
    "mb-2 block text-xs font-semibold tracking-wide text-slate-600";

  return (
    <main className="min-h-screen bg-[#f5f7fb] p-3 sm:p-5 lg:p-8">
      <div className="mx-auto grid min-h-[calc(100vh-64px)] max-w-7xl overflow-hidden rounded-[28px] bg-white shadow-xl shadow-slate-200/60 lg:grid-cols-[0.95fr_1.05fr]">

        {/* LEFT BRAND PANEL */}

        <section className="relative flex min-h-[340px] flex-col overflow-hidden bg-[#101b35] p-7 text-white sm:p-10 lg:p-12">

          <div className="pointer-events-none absolute -right-24 top-20 h-80 w-80 rounded-full bg-blue-500/20 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-28 -left-20 h-80 w-80 rounded-full bg-indigo-500/20 blur-3xl" />

          <div className="relative z-10 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-500 shadow-lg shadow-blue-500/20">
              <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6">
                <path
                  d="M4 19V11M10 19V5M16 19V9M22 19V3"
                  stroke="white"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />
              </svg>
            </div>

            <span className="text-2xl font-bold tracking-tight">
              Tavuno
            </span>
          </div>

          <div className="relative z-10 my-auto py-12">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-300/20 bg-blue-400/10 px-4 py-2 text-xs font-medium text-blue-200">
              <span className="h-2 w-2 rounded-full bg-blue-400" />
              INTELLIGENCE FOR MODERN RETAIL
            </div>

            <h1 className="max-w-lg text-4xl font-semibold leading-[1.15] tracking-tight sm:text-5xl">
              Make every store a{" "}
              <span className="text-blue-400">
                smarter store.
              </span>
            </h1>

            <p className="mt-6 max-w-md text-base leading-7 text-slate-300">
              Bring your retail operations together. Understand your
              inventory, discover opportunities and make confident
              decisions with intelligent insights.
            </p>

            {/* Product feature card */}

            <div className="mt-10 max-w-md rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur-sm">
              <p className="text-xs font-semibold tracking-widest text-blue-300">
                BUILT FOR RETAIL GROWTH
              </p>

              <div className="mt-5 space-y-5">
                {[
                  {
                    icon: "▦",
                    title: "Complete inventory visibility",
                    description: "See what is happening across your stores.",
                  },
                  {
                    icon: "✧",
                    title: "Intelligent recommendations",
                    description: "Find opportunities hidden in your data.",
                  },
                  {
                    icon: "↗",
                    title: "Better business decisions",
                    description: "Turn information into meaningful action.",
                  },
                ].map((item) => (
                  <div key={item.title} className="flex gap-4">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-500/15 text-xl text-blue-300">
                      {item.icon}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white">
                        {item.title}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-400">
                        {item.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="relative z-10 flex justify-between text-xs text-slate-400">
            <span>Tavuno · Retail intelligence</span>
            <span>© 2026</span>
          </div>
        </section>

        {/* RIGHT REGISTRATION PANEL */}

        <section className="flex items-center justify-center px-6 py-12 sm:px-12 lg:px-16 lg:py-14">
          <div className="w-full max-w-lg">

            <div className="mb-9">
              <p className="mb-3 text-xs font-bold tracking-[0.2em] text-blue-600">
                GET STARTED
              </p>

              <h2 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
                Create your account
              </h2>

              <p className="mt-3 text-sm leading-6 text-slate-500">
                Set up your business workspace and bring all your
                retail operations together.
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">

              {/* Personal information */}

              <div>
                <h3 className="mb-4 text-sm font-semibold text-slate-900">
                  Personal information
                </h3>

                <div className="space-y-4">
                  <div>
                    <label className={labelClass}>FULL NAME</label>
                    <input
                      className={inputClass}
                      name="full_name"
                      value={form.full_name}
                      onChange={handleChange}
                      placeholder="Enter your full name"
                      minLength={2}
                      maxLength={150}
                      autoComplete="name"
                      required
                    />
                  </div>

                  <div>
                    <label className={labelClass}>WORK EMAIL</label>
                    <input
                      className={inputClass}
                      type="email"
                      name="email"
                      value={form.email}
                      onChange={handleChange}
                      placeholder="you@company.com"
                      autoComplete="email"
                      required
                    />
                  </div>

                  <div>
                    <label className={labelClass}>PASSWORD</label>
                    <div className="relative">
                      <input
                        className={`${inputClass} pr-16`}
                        type={showPassword ? "text" : "password"}
                        name="password"
                        value={form.password}
                        onChange={handleChange}
                        placeholder="Minimum 12 characters"
                        minLength={12}
                        maxLength={128}
                        autoComplete="new-password"
                        required
                      />

                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-4 top-1/2 -translate-y-1/2 text-xs font-semibold text-blue-600 hover:text-blue-800"
                      >
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                    <p className="mt-2 text-xs text-slate-400">
                      Use at least 12 characters.
                    </p>
                  </div>
                </div>
              </div>

              {/* Company information */}

              <div className="border-t border-slate-100 pt-6">
                <h3 className="mb-4 text-sm font-semibold text-slate-900">
                  Business information
                </h3>

                <div className="space-y-4">
                  <div>
                    <label className={labelClass}>COMPANY NAME</label>
                    <input
                      className={inputClass}
                      name="company_name"
                      value={form.company_name}
                      onChange={handleChange}
                      placeholder="Your retail business name"
                      minLength={2}
                      maxLength={150}
                      required
                    />
                  </div>

                  <div>
                    <label className={labelClass}>INDUSTRY</label>
                    <select
                      className={inputClass}
                      name="industry"
                      value={form.industry}
                      onChange={handleChange}
                    >
                      <option value="grocery">Grocery & Supermarkets</option>
                      <option value="pharmacy">Pharmacy</option>
                      <option value="fashion">Fashion & Apparel</option>
                      <option value="electronics">Electronics</option>
                      <option value="general_retail">General Retail</option>
                      <option value="other">Other</option>
                    </select>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className={labelClass}>COUNTRY CODE</label>
                      <input
                        className={inputClass}
                        name="country_code"
                        value={form.country_code}
                        onChange={handleChange}
                        maxLength={2}
                        required
                      />
                    </div>

                    <div>
                      <label className={labelClass}>CURRENCY</label>
                      <input
                        className={inputClass}
                        name="currency"
                        value={form.currency}
                        onChange={handleChange}
                        maxLength={3}
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <label className={labelClass}>TIMEZONE</label>
                    <input
                      className={inputClass}
                      name="timezone"
                      value={form.timezone}
                      onChange={handleChange}
                      placeholder="Asia/Kolkata"
                      required
                    />
                  </div>
                </div>
              </div>

              {/* Feedback */}

              {error && (
                <div
                  role="alert"
                  className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
                >
                  {error}
                </div>
              )}

              {success && (
                <div
                  role="status"
                  className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"
                >
                  <p className="font-semibold">Account created successfully!</p>
                  <p className="mt-1">{success}</p>
                </div>
              )}

              {/* Submit */}

              <button
                type="submit"
                disabled={loading || Boolean(success)}
                className="group flex w-full items-center justify-center gap-3 rounded-xl bg-blue-600 px-5 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition duration-200 hover:-translate-y-0.5 hover:bg-blue-700 hover:shadow-xl hover:shadow-blue-600/25 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
              >
                {loading
                  ? "Creating your account..."
                  : success
                    ? "Account created"
                    : "Create company account"}

                {!loading && !success && (
                  <span className="transition-transform group-hover:translate-x-1">
                    →
                  </span>
                )}
              </button>

              <p className="text-center text-xs leading-5 text-slate-400">
                By creating an account, you agree to our Terms of
                Service and Privacy Policy.
              </p>

<div className="mt-8 text-center">
  <p className="text-sm text-slate-500">
    Already have a Tavuno account?{" "}
    <a
      href="/login"
      className="font-semibold text-blue-600 transition hover:text-blue-800"
    >
      Sign in
    </a>
  </p>
</div>

            </form>

            <div className="mt-8 border-t border-slate-100 pt-6 text-center">
              <p className="text-xs text-slate-400">
                © 2026 Tavuno. Built for smarter retail.
              </p>
            </div>

          </div>
        </section>
      </div>
    </main>
  );
}
