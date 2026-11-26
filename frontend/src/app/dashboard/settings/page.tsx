"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type Profile = { full_name: string; email: string; company_name: string; role: string; must_change_password: boolean };
const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export default function SettingsPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/api/v1/auth/me`, { credentials: "include" }).then(async response => {
      if (response.status === 401) { router.replace("/login"); return; }
      if (!response.ok) throw new Error("Unable to load company settings.");
      const result: Profile = await response.json();
      if (result.must_change_password) { router.replace("/change-password"); return; }
      if (result.role !== "OWNER") { router.replace("/dashboard"); return; }
      setProfile(result);
    }).catch(e => setError(e instanceof Error ? e.message : "Unable to load settings."));
  }, [router]);
  return <main className="min-h-screen bg-slate-50 p-5 text-slate-900 sm:p-10"><div className="mx-auto max-w-3xl"><Link href="/dashboard" className="text-sm font-semibold text-blue-700">← Overview</Link><h1 className="mt-5 text-2xl font-bold">Company settings</h1><p className="mt-2 text-sm text-slate-500">Owner account and company workspace details.</p>{error && <p role="alert" className="mt-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}{profile ? <section className="mt-6 rounded-2xl border bg-white p-6"><dl className="grid gap-5 sm:grid-cols-2"><div><dt className="text-xs text-slate-500">Company</dt><dd className="mt-1 font-semibold">{profile.company_name}</dd></div><div><dt className="text-xs text-slate-500">Your role</dt><dd className="mt-1 font-semibold">{profile.role}</dd></div><div><dt className="text-xs text-slate-500">Owner</dt><dd className="mt-1 font-semibold">{profile.full_name}</dd></div><div><dt className="text-xs text-slate-500">Email</dt><dd className="mt-1 font-semibold">{profile.email}</dd></div></dl><p className="mt-6 border-t pt-4 text-sm text-slate-500">Company profile editing is not available yet. Use the existing Branches, Team Management, Product Intelligence and Data &amp; Uploads pages to manage those areas.</p></section> : !error && <p className="mt-6 text-sm text-slate-500">Loading company details…</p>}</div></main>;
}
