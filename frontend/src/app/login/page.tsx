
"use client";

import Link from "next/link";
import {
  useState,
  useEffect,
  type FormEvent,
  type ChangeEvent,
} from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const initialForm = {
  email: "",
  password: "",
};

type AuthenticatedUser = {
  full_name: string;
  email: string;
};

export default function LoginPage() {
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [authenticatedUser, setAuthenticatedUser] =
    useState<AuthenticatedUser | null>(null);

  // Check whether the user already has an active session.
  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      try {
        const response = await fetch(`${API_URL}/api/v1/auth/me`, {
          method: "GET",
          credentials: "include",
        });

        if (!response.ok) return;

        const data = await response.json();

        if (!cancelled) {
          setAuthenticatedUser(data);
        }
      } catch {
        // No active session or backend unavailable.
      }
    }

    checkSession();

    return () => {
      cancelled = true;
    };
  }, []);

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setForm((previous) => ({
      ...previous,
      [event.target.name]: event.target.value,
    }));

    setError("");
    setSuccess("");
  }

  // Login
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setLoading(true);
    setError("");
    setSuccess("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/auth/login`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify(form),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        const message = Array.isArray(data.detail)
          ? data.detail
              .map((item: { msg: string }) => item.msg)
              .join(", ")
          : data.detail || "Login failed. Please try again.";

        throw new Error(message);
      }

      setAuthenticatedUser(data);

      setSuccess(
        `Welcome back, ${data.full_name}! Your login was successful.`
      );

      setForm(initialForm);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  // Logout
  async function handleLogout() {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/auth/logout`,
        {
          method: "POST",
          credentials: "include",
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Logout failed.");
      }

      setAuthenticatedUser(null);
      setSuccess("");
      setError("");
      setForm(initialForm);
      setShowPassword(false);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to sign out. Please try again."
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
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-500 text-xl font-bold shadow-lg shadow-blue-500/30">
              S
            </div>

            <div>
              <h1 className="text-xl font-bold tracking-tight">
                StockPilot
              </h1>
              <p className="text-xs text-slate-400">
                Retail Intelligence Platform
              </p>
            </div>
          </div>

          <div className="relative z-10 my-auto py-12 lg:py-0">

            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-400/10 px-3 py-1.5 text-xs font-medium text-blue-200">
              <span className="h-2 w-2 rounded-full bg-blue-400" />
              INTELLIGENCE FOR MODERN RETAIL
            </div>

            <h2 className="max-w-lg text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
              Make every store a smarter store.
            </h2>

            <p className="mt-6 max-w-md text-sm leading-7 text-slate-300 sm:text-base">
              Your retail operations, inventory insights, and
              smarter business decisions — all in one place.
            </p>

            <div className="mt-10 space-y-5">

              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-blue-300">
                  ↗
                </div>
                <div>
                  <p className="text-sm font-semibold">
                    Complete inventory visibility
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    Understand what's happening across your stores.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-blue-300">
                  ◈
                </div>
                <div>
                  <p className="text-sm font-semibold">
                    Intelligent recommendations
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    Identify opportunities before they become problems.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-blue-300">
                  ◎
                </div>
                <div>
                  <p className="text-sm font-semibold">
                    Better business decisions
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    Turn retail data into meaningful actions.
                  </p>
                </div>
              </div>

            </div>
          </div>

          <div className="relative z-10 border-t border-white/10 pt-6 text-xs text-slate-500">
            © 2026 StockPilot. All rights reserved.
          </div>
        </section>

        {/* RIGHT LOGIN PANEL */}

        <section className="flex items-center justify-center bg-white px-6 py-12 sm:px-12 lg:px-16">

          <div className="w-full max-w-md">

            <div className="mb-10">
              <p className="mb-3 text-xs font-bold tracking-[0.2em] text-blue-600">
                WELCOME BACK
              </p>

              <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
                Sign in to StockPilot
              </h2>

              <p className="mt-3 text-sm leading-6 text-slate-500">
                Enter your account details to access your retail workspace.
              </p>
            </div>

            {/* LOGIN FORM */}

            <form onSubmit={handleSubmit} className="space-y-6">

              {/* EMAIL */}

              <div>
                <label htmlFor="email" className={labelClass}>
                  EMAIL ADDRESS
                </label>

                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  placeholder="you@company.com"
                  value={form.email}
                  onChange={handleChange}
                  className={inputClass}
                />
              </div>

              {/* PASSWORD */}

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label htmlFor="password" className={labelClass + " mb-0"}>
                    PASSWORD
                  </label>
                </div>

                <div className="relative">
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    placeholder="Enter your password"
                    value={form.password}
                    onChange={handleChange}
                    className={inputClass + " pr-20"}
                  />

                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-xs font-semibold text-blue-600 transition hover:text-blue-800"
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
              </div>

              {/* ERROR MESSAGE */}

              {error && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              {/* SUCCESS MESSAGE */}

              {success && (
                <div className="rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
                  {success}
                  <p className="mt-2 text-xs">
                    Your session has been created successfully.
                    Your dashboard will be available in the next step.
                  </p>
                </div>
              )}

              {/* SUBMIT BUTTON */}

              <button
                type="submit"
                disabled={loading || authenticatedUser !== null}
                className="flex w-full items-center justify-center rounded-xl bg-blue-600 px-5 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 hover:shadow-blue-600/30 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading
                  ? "Signing in..."
                  : authenticatedUser
                    ? "Already signed in"
                    : "Sign in to your account"}
              </button>

            </form>

            {/* AUTHENTICATED USER AND LOGOUT */}

            {authenticatedUser && (
              <div className="mt-6 rounded-xl border border-blue-100 bg-blue-50 p-5">
                <p className="text-sm font-semibold text-slate-900">
                  You are signed in as {authenticatedUser.full_name}
                </p>

                <p className="mt-1 text-xs text-slate-500">
                  {authenticatedUser.email}
                </p>

                <button
                  type="button"
                  onClick={handleLogout}
                  disabled={loading}
                  className="mt-4 w-full rounded-xl border border-red-200 bg-white px-4 py-3 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-60"
                >
                  {loading ? "Signing out..." : "Sign out"}
                </button>
              </div>
            )}

            {/* REGISTER LINK */}

            <div className="mt-8 text-center">
              <p className="text-sm text-slate-500">
                Don't have a StockPilot account?{" "}
                <Link
                  href="/register"
                  className="font-semibold text-blue-600 transition hover:text-blue-800"
                >
                  Create an account
                </Link>
              </p>
            </div>

            <div className="mt-12 border-t border-slate-100 pt-6 text-center">
              <p className="text-xs text-slate-400">
                Secure access to your retail workspace.
              </p>
            </div>

          </div>
        </section>
      </div>
    </main>
  );
}
