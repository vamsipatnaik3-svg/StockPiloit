
"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/api/v1/auth/forgot-password`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            email: email.trim().toLowerCase(),
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        const message = Array.isArray(data.detail)
          ? data.detail.map((item: { msg: string }) => item.msg).join(", ")
          : data.detail || "Unable to process your request.";

        throw new Error(message);
      }

      setSubmitted(true);
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

  const inputClass =
    "w-full rounded-xl border border-slate-200 bg-white px-4 py-3.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10";

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb] p-4">
      <div className="w-full max-w-md rounded-[28px] bg-white p-7 shadow-xl shadow-slate-200/60 sm:p-10">

        {/* BRAND */}

        <Link href="/login" className="mb-10 inline-flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-600 text-xl font-bold text-white shadow-lg shadow-blue-600/20">
            S
          </div>

          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900">
              Tavuno
            </h1>
            <p className="text-xs text-slate-400">
              Retail Intelligence Platform
            </p>
          </div>
        </Link>

        {!submitted ? (
          <>
            {/* HEADING */}

            <div className="mb-8">
              <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-2xl text-blue-600">
                ↗
              </div>

              <p className="mb-3 text-xs font-bold tracking-[0.2em] text-blue-600">
                ACCOUNT RECOVERY
              </p>

              <h2 className="text-3xl font-bold tracking-tight text-slate-900">
                Forgot your password?
              </h2>

              <p className="mt-3 text-sm leading-6 text-slate-500">
                No worries. Enter the email address associated with your
                Tavuno account and we&apos;ll send you a password reset link.
              </p>
            </div>

            {/* FORM */}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <label
                  htmlFor="email"
                  className="mb-2 block text-xs font-semibold tracking-wide text-slate-600"
                >
                  EMAIL ADDRESS
                </label>

                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  maxLength={254}
                  placeholder="you@company.com"
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value);
                    setError("");
                  }}
                  className={inputClass}
                />
              </div>

              {error && (
                <div
                  role="alert"
                  className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
                >
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="flex w-full items-center justify-center rounded-xl bg-blue-600 px-5 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? "Sending reset link..." : "Send reset link"}
              </button>
            </form>
          </>
        ) : (
          /* SUCCESS STATE */

          <div className="py-5 text-center">
            <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-green-50 text-3xl text-green-600">
              ✓
            </div>

            <p className="mb-3 text-xs font-bold tracking-[0.2em] text-green-600">
              REQUEST RECEIVED
            </p>

            <h2 className="text-3xl font-bold tracking-tight text-slate-900">
              Check your email
            </h2>

            <p className="mt-4 text-sm leading-7 text-slate-500">
              If an account exists with that email address, a password
              reset link will be sent. Please check your inbox.
            </p>

            <button
              type="button"
              onClick={() => {
                setSubmitted(false);
                setEmail("");
              }}
              className="mt-7 text-sm font-semibold text-blue-600 transition hover:text-blue-800"
            >
              Try another email
            </button>
          </div>
        )}

        <div className="mt-10 border-t border-slate-100 pt-6 text-center">
          <Link
            href="/login"
            className="text-sm font-semibold text-blue-600 transition hover:text-blue-800"
          >
            ← Back to sign in
          </Link>
        </div>
      </div>
    </main>
  );
}
