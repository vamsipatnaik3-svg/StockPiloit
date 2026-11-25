
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const token = searchParams.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");

    if (!token) {
      setError("This password reset link is missing its token.");
      return;
    }

    if (password.length < 12) {
      setError("Your password must contain at least 12 characters.");
      return;
    }

    if (password.length > 128) {
      setError("Your password cannot exceed 128 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Your passwords do not match.");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(
        `${API_URL}/api/v1/auth/reset-password`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            token,
            new_password: password,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        const message = Array.isArray(data.detail)
          ? data.detail.map((item: { msg: string }) => item.msg).join(", ")
          : data.detail || "Unable to reset your password.";

        throw new Error(message);
      }

      setSuccess(true);
      setPassword("");
      setConfirmPassword("");
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

        {success ? (
          <div className="py-5 text-center">
            <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-green-50 text-3xl text-green-600">
              ✓
            </div>

            <p className="mb-3 text-xs font-bold tracking-[0.2em] text-green-600">
              PASSWORD UPDATED
            </p>

            <h2 className="text-3xl font-bold tracking-tight text-slate-900">
              You&apos;re all set!
            </h2>

            <p className="mt-4 text-sm leading-7 text-slate-500">
              Your password has been changed successfully. You can now
              sign in using your new password.
            </p>

            <button
              type="button"
              onClick={() => router.replace("/login")}
              className="mt-8 flex w-full items-center justify-center rounded-xl bg-blue-600 px-5 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700"
            >
              Continue to sign in
            </button>
          </div>
        ) : (
          <>
            <div className="mb-8">
              <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-2xl text-blue-600">
                🔒
              </div>

              <p className="mb-3 text-xs font-bold tracking-[0.2em] text-blue-600">
                ACCOUNT SECURITY
              </p>

              <h2 className="text-3xl font-bold tracking-tight text-slate-900">
                Create a new password
              </h2>

              <p className="mt-3 text-sm leading-6 text-slate-500">
                Choose a strong password to secure your Tavuno account.
              </p>
            </div>

            {!token && (
              <div
                role="alert"
                className="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              >
                This password reset link is missing its token. Please
                request a new reset link.
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="password"
                  className="mb-2 block text-xs font-semibold tracking-wide text-slate-600"
                >
                  NEW PASSWORD
                </label>

                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    required
                    minLength={12}
                    maxLength={128}
                    placeholder="Enter your new password"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setError("");
                    }}
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

                <p className="mt-2 text-xs text-slate-400">
                  Use at least 12 characters.
                </p>
              </div>

              <div>
                <label
                  htmlFor="confirmPassword"
                  className="mb-2 block text-xs font-semibold tracking-wide text-slate-600"
                >
                  CONFIRM NEW PASSWORD
                </label>

                <input
                  id="confirmPassword"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={12}
                  maxLength={128}
                  placeholder="Re-enter your new password"
                  value={confirmPassword}
                  onChange={(event) => {
                    setConfirmPassword(event.target.value);
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
                disabled={loading || !token}
                className="flex w-full items-center justify-center rounded-xl bg-blue-600 px-5 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? "Updating password..." : "Reset password"}
              </button>
            </form>
          </>
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

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb]">
          <p className="text-sm text-slate-500">
            Loading password reset...
          </p>
        </main>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
