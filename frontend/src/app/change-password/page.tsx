
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type UserProfile = {
  full_name: string;
  email: string;
  must_change_password: boolean;
};

export default function ChangePasswordPage() {
  const router = useRouter();

  const [user, setUser] = useState<UserProfile | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      try {
        const response = await fetch(`${API_URL}/api/v1/auth/me`, {
          credentials: "include",
        });

        if (cancelled) return;

        if (response.status === 401) {
          router.replace("/login");
          return;
        }

        if (!response.ok) {
          throw new Error("Unable to verify your account.");
        }

        const profile: UserProfile = await response.json();

        if (cancelled) return;

        if (!profile.must_change_password) {
          router.replace("/dashboard");
          return;
        }

        setUser(profile);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load your account."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadProfile();

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");
    setSuccess("");

    if (newPassword.length < 12) {
      setError("Your new password must contain at least 12 characters.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("The new passwords do not match.");
      return;
    }

    if (newPassword === currentPassword) {
      setError("Your new password must be different from the temporary password.");
      return;
    }

    setSaving(true);

    try {
      const response = await fetch(
        `${API_URL}/api/v1/auth/change-password`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "Unable to change your password."
        );
      }

      setSuccess("Password changed successfully. Opening your workspace...");

      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleLogout() {
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      router.replace("/login");
    }
  }

  const inputClass =
    "w-full rounded-xl border border-slate-200 bg-white px-4 py-3.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10";

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb]">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-blue-100 border-t-blue-600" />
          <p className="mt-4 text-sm text-slate-500">
            Verifying your account...
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb] p-5">
      <section className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-7 shadow-xl shadow-slate-200/50 sm:p-10">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-600 text-xl font-bold text-white">
            T
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Tavuno</h1>
            <p className="text-xs text-slate-400">
              Retail Intelligence Platform
            </p>
          </div>
        </div>

        <div className="mt-9">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-50 text-xl text-amber-600">
            !
          </div>

          <p className="mt-6 text-xs font-bold uppercase tracking-[0.18em] text-blue-600">
            First-time account setup
          </p>

          <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900">
            Create your new password
          </h2>

          <p className="mt-3 text-sm leading-6 text-slate-500">
            Welcome{user ? `, ${user.full_name}` : ""}. Before accessing your
            workspace, replace your temporary password with a new secure
            password.
          </p>

          {user && (
            <p className="mt-3 text-xs font-medium text-slate-400">
              {user.email}
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="mt-8 space-y-5">
          <div>
            <label className="mb-2 block text-xs font-semibold text-slate-600">
              TEMPORARY PASSWORD
            </label>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              className={inputClass}
              placeholder="Enter your temporary password"
            />
          </div>

          <div>
            <label className="mb-2 block text-xs font-semibold text-slate-600">
              NEW PASSWORD
            </label>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={128}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className={inputClass}
              placeholder="Create a new password"
            />
            <p className="mt-2 text-xs text-slate-400">
              Use at least 12 characters.
            </p>
          </div>

          <div>
            <label className="mb-2 block text-xs font-semibold text-slate-600">
              CONFIRM NEW PASSWORD
            </label>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={128}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              className={inputClass}
              placeholder="Enter your new password again"
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

          {success && (
            <div
              role="status"
              className="rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
            >
              {success}
            </div>
          )}

          <button
            type="submit"
            disabled={saving || !user}
            className="w-full rounded-xl bg-blue-600 px-5 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? "Updating password..." : "Save new password"}
          </button>
        </form>

        <div className="mt-7 border-t border-slate-100 pt-5 text-center">
          <button
            type="button"
            onClick={() => void handleLogout()}
            className="text-xs font-semibold text-slate-500 transition hover:text-red-600"
          >
            Sign out
          </button>
        </div>
      </section>
    </main>
  );
}
