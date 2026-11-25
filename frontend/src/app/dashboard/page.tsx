
"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type UserProfile = {
  user_id: string;
  full_name: string;
  email: string;
  company_id: string;
  company_name: string;
  role: "OWNER" | "MANAGER" | "STAFF" | "ANALYST";
};

type NavigationItem = {
  label: string;
  icon: string;
  href?: string;
  active: boolean;
};

const roleDescriptions: Record<UserProfile["role"], string> = {
  OWNER: "Company Owner",
  MANAGER: "Business Manager",
  STAFF: "Team Member",
  ANALYST: "Business Analyst",
};

const navigation: NavigationItem[] = [
  {
    label: "Overview",
    icon: "▦",
    href: "/dashboard",
    active: true,
  },
  {
    label: "Branches",
    icon: "⌂",
    href: "/dashboard/branches",
    active: false,
  },
  { label: "Inventory", icon: "▤", active: false },
  { label: "Expiry & Waste", icon: "◷", active: false },
  { label: "Sales", icon: "↗", active: false },
  { label: "AI Insights", icon: "✧", active: false },
];

const metrics = [
  {
    label: "Inventory items",
    description: "Products tracked across your business",
    icon: "▤",
  },
  {
    label: "Expiring soon",
    description: "Products approaching expiry",
    icon: "◷",
  },
  {
    label: "At-risk stock value",
    description: "Value of inventory at expiry risk",
    icon: "₹",
  },
  {
    label: "Potential waste",
    description: "Estimated inventory waste",
    icon: "◇",
  },
];

export default function DashboardPage() {
  const router = useRouter();

  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState("");

  const loadUser = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/api/v1/auth/me`, {
        method: "GET",
        credentials: "include",
      });

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      if (response.status === 409) {
        throw new Error(
          "You belong to multiple companies. Company selection will be available in a future update."
        );
      }

      if (!response.ok) {
        throw new Error("Unable to load your workspace.");
      }

      const data: UserProfile = await response.json();
      setUser(data);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    let cancelled = false;

    async function initializeDashboard() {
      try {
        const response = await fetch(`${API_URL}/api/v1/auth/me`, {
          method: "GET",
          credentials: "include",
        });

        if (cancelled) return;

        if (response.status === 401) {
          router.replace("/login");
          return;
        }

        if (response.status === 409) {
          setError(
            "You belong to multiple companies. Company selection will be available in a future update."
          );
          return;
        }

        if (!response.ok) {
          throw new Error("Unable to load your workspace.");
        }

        const data: UserProfile = await response.json();

        if (!cancelled) {
          setUser(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Something went wrong. Please try again."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void initializeDashboard();

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleLogout() {
    setLoggingOut(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error("Unable to sign out. Please try again.");
      }

      router.replace("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Logout failed.");
      setLoggingOut(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb]">
        <div className="text-center">
          <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-blue-100 border-t-blue-600" />
          <p className="mt-4 text-sm font-medium text-slate-500">
            Loading your workspace...
          </p>
        </div>
      </main>
    );
  }

  if (error && !user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb] p-6">
        <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-8 shadow-xl">
          <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-red-50 text-xl text-red-600">
            !
          </div>

          <h1 className="text-xl font-bold text-slate-900">
            Workspace unavailable
          </h1>

          <p className="mt-3 text-sm leading-6 text-slate-500">{error}</p>

          <button
            onClick={() => void loadUser()}
            className="mt-6 w-full rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700"
          >
            Try again
          </button>

          <button
            onClick={() => router.replace("/login")}
            className="mt-3 w-full rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
          >
            Return to login
          </button>
        </div>
      </main>
    );
  }

  if (!user) return null;

  const firstName = user.full_name.trim().split(/\s+/)[0];

  const initials = user.full_name
    .trim()
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <main className="min-h-screen bg-[#f5f7fb] text-slate-900">
      <div className="flex min-h-screen">
        {/* DESKTOP SIDEBAR */}
        <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-5 py-7 lg:flex">
          <div className="flex items-center gap-3 px-2">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-600 text-xl font-bold text-white shadow-lg shadow-blue-600/20">
              S
            </div>

            <div>
              <h1 className="text-xl font-bold tracking-tight">Tavuno</h1>
              <p className="text-[11px] text-slate-400">
                Retail Intelligence
              </p>
            </div>
          </div>

          <div className="mt-12">
            <p className="px-3 text-[10px] font-bold tracking-[0.18em] text-slate-400">
              WORKSPACE
            </p>

            <nav className="mt-4 space-y-1">
              {navigation.map((item) => (
                <div key={item.label}>
                  {item.href ? (
                    <Link
                      href={item.href}
                      aria-current={item.active ? "page" : undefined}
                      className={`flex items-center rounded-xl px-4 py-3 text-sm transition ${
                        item.active
                          ? "bg-blue-50 font-semibold text-blue-700"
                          : "font-medium text-slate-600 hover:bg-slate-50 hover:text-blue-700"
                      }`}
                    >
                      <span className="mr-3">{item.icon}</span>
                      {item.label}
                    </Link>
                  ) : (
                    <div
                      title="This module is planned for a future release"
                      className="flex cursor-not-allowed items-center justify-between rounded-xl px-4 py-3 text-sm text-slate-400"
                    >
                      <span>
                        <span className="mr-3">{item.icon}</span>
                        {item.label}
                      </span>

                      <span className="text-[9px] font-semibold uppercase tracking-wide">
                        Soon
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </nav>
          </div>

          {/* ACCOUNT */}
          <div className="mt-10">
            <p className="px-3 text-[10px] font-bold tracking-[0.18em] text-slate-400">
              YOUR ACCOUNT
            </p>

            <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-100 text-sm font-bold text-blue-700">
                {initials}
              </div>

              <p className="mt-3 truncate text-sm font-semibold">
                {user.full_name}
              </p>

              <p className="mt-1 truncate text-xs text-slate-500">
                {roleDescriptions[user.role]}
              </p>

              <p className="mt-2 truncate text-[11px] text-slate-400">
                {user.email}
              </p>
            </div>
          </div>

          {/* LOGOUT */}
          <div className="mt-auto border-t border-slate-100 pt-6">
            <button
              onClick={handleLogout}
              disabled={loggingOut}
              className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium text-slate-500 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
            >
              <span>↪</span>
              {loggingOut ? "Signing out..." : "Sign out"}
            </button>

            <p className="mt-5 px-3 text-[11px] text-slate-400">
              Tavuno · 2026
            </p>
          </div>
        </aside>

        {/* MAIN CONTENT */}
        <section className="min-w-0 flex-1">
          {/* HEADER */}
          <header className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4 sm:px-8 lg:px-10">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 font-bold text-white lg:hidden">
                S
              </div>

              <div>
                <h2 className="text-lg font-bold tracking-tight">
                  {user.company_name}
                </h2>
                <p className="text-xs text-slate-400">
                  Business workspace
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <span className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">
                {user.role}
              </span>

              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
                {initials}
              </div>

              <button
                onClick={handleLogout}
                disabled={loggingOut}
                className="rounded-lg px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-red-50 hover:text-red-600 lg:hidden"
              >
                {loggingOut ? "Signing out..." : "Sign out"}
              </button>
            </div>
          </header>

          {/* MOBILE NAVIGATION */}
          <nav className="flex gap-2 overflow-x-auto border-b border-slate-200 bg-white px-5 py-3 lg:hidden">
            {navigation.map((item) => (
              <div key={item.label}>
                {item.href ? (
                  <Link
                    href={item.href}
                    aria-current={item.active ? "page" : undefined}
                    className={`block shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition ${
                      item.active
                        ? "bg-blue-50 text-blue-700"
                        : "text-slate-600 hover:bg-slate-50 hover:text-blue-700"
                    }`}
                  >
                    {item.icon} {item.label}
                  </Link>
                ) : (
                  <span className="block shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium text-slate-400">
                    {item.icon} {item.label} · Soon
                  </span>
                )}
              </div>
            ))}
          </nav>

          <div className="mx-auto max-w-[1500px] px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            {/* PAGE INTRODUCTION */}
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">
                  BUSINESS OVERVIEW
                </p>

                <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
                  Welcome back, {firstName}.
                </h1>

                <p className="mt-2 text-sm text-slate-500">
                  Here&apos;s an overview of your retail workspace.
                </p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  COMPANY
                </p>
                <p className="mt-1 text-sm font-semibold text-slate-800">
                  {user.company_name}
                </p>
              </div>
            </div>

            {/* KPI CARDS */}
            <section className="mt-8">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {metrics.map((metric) => (
                  <div
                    key={metric.label}
                    className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-sm font-medium text-slate-500">
                          {metric.label}
                        </p>
                        <p className="mt-4 text-3xl font-bold tracking-tight text-slate-800">
                          —
                        </p>
                      </div>

                      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-xl text-blue-600">
                        {metric.icon}
                      </div>
                    </div>

                    <div className="mt-4 border-t border-slate-100 pt-3">
                      <p className="text-xs leading-5 text-slate-400">
                        {metric.description}
                      </p>
                      <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        No data yet
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* INVENTORY AND EXPIRY SECTIONS */}
            <section className="mt-8 grid gap-5 xl:grid-cols-3">
              <div className="rounded-2xl border border-slate-200 bg-white p-6 xl:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-base font-bold text-slate-900">
                      Inventory health
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      Understand the current state of your stock.
                    </p>
                  </div>

                  <span className="rounded-full bg-slate-100 px-3 py-1.5 text-[10px] font-semibold text-slate-500">
                    AWAITING DATA
                  </span>
                </div>

                <div className="mt-8 flex min-h-52 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-5 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-white text-2xl text-blue-600 shadow-sm">
                    ▤
                  </div>

                  <h3 className="mt-4 text-sm font-semibold text-slate-800">
                    Your inventory workspace is empty
                  </h3>

                  <p className="mt-2 max-w-sm text-xs leading-6 text-slate-500">
                    Inventory information will appear here once your business
                    data is connected to Tavuno.
                  </p>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-6">
                <h2 className="text-base font-bold text-slate-900">
                  Expiry & waste
                </h2>

                <p className="mt-1 text-xs text-slate-500">
                  Monitor products at risk of expiry.
                </p>

                <div className="mt-8 flex min-h-52 flex-col items-center justify-center rounded-xl bg-amber-50/60 px-5 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-white text-2xl text-amber-600 shadow-sm">
                    ◷
                  </div>

                  <h3 className="mt-4 text-sm font-semibold text-slate-800">
                    No expiry data available
                  </h3>

                  <p className="mt-2 text-xs leading-6 text-slate-500">
                    Expiry alerts and waste-risk information will appear
                    when inventory data is available.
                  </p>
                </div>
              </div>
            </section>

            {/* BUSINESS ACTIVITY */}
            <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-bold text-slate-900">
                    Business activity
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Stay informed about changes in your workspace.
                  </p>
                </div>

                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  RECENT ACTIVITY
                </span>
              </div>

              <div className="mt-6 flex min-h-24 items-center justify-center rounded-xl bg-slate-50 px-4 text-center">
                <p className="text-xs text-slate-400">
                  No business activity to display yet.
                </p>
              </div>
            </section>

            {/* FOOTER */}
            <footer className="mt-10 border-t border-slate-200 pt-6 text-xs text-slate-400">
              © 2026 Tavuno. Built for smarter retail.
            </footer>
          </div>
        </section>
      </div>
    </main>
  );
}
