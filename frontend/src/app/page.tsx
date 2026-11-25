
"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function HomePage() {
  const router = useRouter();
  const [error, setError] = useState("");

  const checkAuthentication = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/me`, {
        method: "GET",
        credentials: "include",
      });

      if (response.ok || response.status === 409) {
        router.replace("/dashboard");
        return;
      }

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      throw new Error("Unable to verify your session.");
    } catch {
      setError("Tavuno is currently unable to connect to the server.");
    }
  }, [router]);

  useEffect(() => {
  let cancelled = false;

  async function initializeHome() {
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/me`, {
        method: "GET",
        credentials: "include",
      });

      if (cancelled) return;

      if (response.ok || response.status === 409) {
        router.replace("/dashboard");
        return;
      }

      if (response.status === 401) {
        router.replace("/login");
        return;
      }

      throw new Error("Unable to verify your session.");
    } catch {
      if (!cancelled) {
        setError("Tavuno is currently unable to connect to the server.");
      }
    }
  }

  void initializeHome();

  return () => {
    cancelled = true;
  };
}, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f5f7fb] p-6">
      <div className="w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-xl shadow-slate-200/50">
        {error ? (
          <>
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-red-50 text-xl text-red-600">
              !
            </div>

            <h1 className="mt-5 text-xl font-bold text-slate-900">
              Connection unavailable
            </h1>

            <p className="mt-3 text-sm leading-6 text-slate-500">
              {error}
            </p>

            <button
              onClick={() => void checkAuthentication()}
              className="mt-6 w-full rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700"
            >
              Try again
            </button>
          </>
        ) : (
          <>
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-2xl font-bold text-white">
              S
            </div>

            <h1 className="mt-5 text-xl font-bold text-slate-900">
              Tavuno
            </h1>

            <p className="mt-2 text-sm text-slate-500">
              Preparing your retail workspace...
            </p>

            <div className="mx-auto mt-6 h-8 w-8 animate-spin rounded-full border-4 border-blue-100 border-t-blue-600" />
          </>
        )}
      </div>
    </main>
  );
}
