"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
type Branch = { id: string; name: string; code: string | null };
type Upload = { id: string; branch_id: string; business_date: string; original_filename: string; version: number; is_current: boolean; processing_status: string; rows_read: number; rows_accepted: number; rows_rejected: number; warning_count: number; error_count: number };
type Issue = { severity: string; sheet: string; row: number | null; code: string; message: string };
type ImportJob = { id: string; status: string; total_files: number; completed_files: number; failed_files: number; skipped_files: number; progress_percent: number; date_start: string | null; date_end: string | null };

export default function UploadsPage() {
  const router = useRouter();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [branch, setBranch] = useState("");
  const [businessDate, setBusinessDate] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [canUpload, setCanUpload] = useState(false);
  const [selectedUploads, setSelectedUploads] = useState<string[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<{ job: ImportJob; files: { filename: string; business_date: string; status: string; error_message: string | null }[] } | null>(null);

  const load = useCallback(async () => {
    try {
      const [profile, branchResponse, uploadResponse, importResponse] = await Promise.all([
        fetch(`${API_URL}/api/v1/auth/me`, { credentials: "include" }),
        fetch(`${API_URL}/api/v1/branches`, { credentials: "include" }),
        fetch(`${API_URL}/api/v1/uploads`, { credentials: "include" }),
        fetch(`${API_URL}/api/v1/historical-imports`, { credentials: "include" }),
      ]);
      if (profile.status === 401) { router.replace("/login"); return; }
      if (!profile.ok || !branchResponse.ok || !uploadResponse.ok || !importResponse.ok) throw new Error("Unable to load upload workspace.");
      const user = await profile.json();
      if (user.must_change_password) { router.replace("/change-password"); return; }
      setCanUpload(user.role === "OWNER" || user.role === "MANAGER");
      const nextBranches: Branch[] = await branchResponse.json();
      setBranches(nextBranches);
      if (!branch && nextBranches.length) setBranch(nextBranches[0].id);
      setUploads(await uploadResponse.json());
      setJobs(await importResponse.json());
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load uploads."); }
  }, [router, branch]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  function selectFile(event: ChangeEvent<HTMLInputElement>) { setFile(event.target.files?.[0] || null); }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError(""); setNotice(""); setIssues([]);
    try {
      const form = new FormData(); form.append("branch_id", branch); form.append("business_date", businessDate); form.append("file", file);
      const created = await fetch(`${API_URL}/api/v1/uploads`, { method: "POST", credentials: "include", body: form });
      if (created.status === 409) throw new Error("This exact workbook has already been uploaded for this branch and date.");
      if (!created.ok) throw new Error((await created.json()).detail || "Unable to upload workbook.");
      const item: Upload = await created.json();
      const processed = await fetch(`${API_URL}/api/v1/uploads/${item.id}/process`, { method: "POST", credentials: "include" });
      if (!processed.ok) throw new Error("Workbook uploaded, but processing could not start.");
      const result: Upload = await processed.json();
      const report = await fetch(`${API_URL}/api/v1/uploads/${item.id}/validation-report`, { credentials: "include" });
      if (report.ok) setIssues((await report.json()).issues);
      setNotice(result.processing_status === "COMPLETED" ? "Workbook processed and made current." : "Workbook has validation errors. The previous current version was kept.");
      setFile(null); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed."); }
    finally { setBusy(false); }
  }

  async function reprocess(item: Upload) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/uploads/${item.id}/process`, { method: "POST", credentials: "include" });
      if (!response.ok) throw new Error("Unable to process workbook.");
      const report = await fetch(`${API_URL}/api/v1/uploads/${item.id}/validation-report`, { credentials: "include" });
      if (report.ok) setIssues((await report.json()).issues);
      setNotice("Workbook reprocessed."); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Reprocessing failed."); }
    finally { setBusy(false); }
  }

  async function startHistoricalImport() {
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API_URL}/api/v1/historical-imports`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ upload_ids: selectedUploads }) });
      if (!response.ok) throw new Error("Unable to start historical import.");
      setSelectedUploads([]); setNotice("Historical import queued. Refresh to see processing progress."); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to start import."); }
    finally { setBusy(false); }
  }

  async function inspectJob(job: ImportJob) {
    const response = await fetch(`${API_URL}/api/v1/historical-imports/${job.id}`, { credentials: "include" });
    if (response.ok) setSelectedJob(await response.json());
  }

  async function retryJob(job: ImportJob) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/historical-imports/${job.id}/retry`, { method: "POST", credentials: "include" });
      if (!response.ok) throw new Error("This import has no retryable failed files.");
      setNotice("Failed files queued for retry."); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to retry import."); }
    finally { setBusy(false); }
  }

  return <main className="min-h-screen bg-slate-50 px-5 py-8 sm:px-8"><div className="mx-auto max-w-6xl">
    <a href="/dashboard" className="text-sm font-semibold text-blue-700">← Dashboard</a>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-blue-600">DAILY DATA</p><h1 className="mt-2 text-3xl font-bold text-slate-900">Workbook uploads</h1><p className="mt-2 text-sm text-slate-500">Validate sales, inventory, purchases and stock movements before they become current.</p></div><div className="flex flex-wrap gap-2"><a href="/templates/tavuno_standard_template_v1.xlsx" download className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700">Download v1 template</a><a href="/templates/tavuno_cafe_template_v2.xlsx" download className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-800">Download café v2 template</a><a href="/templates/tavuno_cafe_template_v3.xlsx" download className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-semibold text-indigo-800">Download café v3 template</a></div></div>
    {error && <p role="alert" className="mt-5 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}{notice && <p role="status" className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {canUpload && <form onSubmit={submit} className="mt-7 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
      <label className="text-xs font-medium text-slate-600">Branch<select required value={branch} onChange={(e) => setBranch(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm">{branches.map((b) => <option key={b.id} value={b.id}>{b.name}{b.code ? ` · ${b.code}` : ""}</option>)}</select></label>
      <label className="text-xs font-medium text-slate-600">Business date<input required type="date" value={businessDate} onChange={(e) => setBusinessDate(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm" /></label>
      <label className="text-xs font-medium text-slate-600">Excel workbook<input required type="file" accept=".xlsx" onChange={selectFile} className="mt-1.5 block w-full text-xs text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-blue-50 file:px-3 file:py-2 file:font-semibold file:text-blue-700" /></label>
      <button disabled={busy || !branch} className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-60">{busy ? "Processing…" : "Upload and validate"}</button>
      <p className="text-xs leading-5 text-slate-500 sm:col-span-2 lg:col-span-4">Use the standard workbook, match Branch Reference to the branch code (or branch UUID if no code is set), and register every SKU in Products first. A failed correction leaves the previous current workbook in place.</p>
    </form>}
    <section className="mt-7 overflow-hidden rounded-2xl border border-slate-200 bg-white"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4"><div><h2 className="font-semibold text-slate-900">Upload history</h2><p className="mt-1 text-xs text-slate-500">Select workbooks across dates and branches to run a historical import job.</p></div>{canUpload && selectedUploads.length > 0 && <button onClick={() => void startHistoricalImport()} disabled={busy} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white">Import {selectedUploads.length} selected</button>}</div>{uploads.length === 0 ? <p className="p-8 text-center text-sm text-slate-500">No workbooks uploaded yet.</p> : <div className="divide-y divide-slate-100">{uploads.map((item) => { const branchName = branches.find((b) => b.id === item.branch_id)?.name || "Branch"; return <article key={item.id} className="flex flex-wrap items-center justify-between gap-4 px-5 py-4">{canUpload && <input aria-label={`Select ${item.original_filename} for historical import`} type="checkbox" checked={selectedUploads.includes(item.id)} onChange={(event) => setSelectedUploads((ids) => event.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} className="h-4 w-4 accent-blue-600" />}<div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-slate-900">{item.original_filename} <span className="ml-1 text-xs font-normal text-slate-500">v{item.version}</span></p><p className="mt-1 text-xs text-slate-500">{branchName} · {item.business_date} · {item.rows_accepted}/{item.rows_read} rows accepted</p><p className="mt-1 text-xs text-slate-500">{item.error_count} errors · {item.warning_count} warnings</p></div><div className="flex items-center gap-3"><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${item.processing_status === "COMPLETED" ? "bg-emerald-50 text-emerald-700" : item.processing_status === "VALIDATION_FAILED" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{item.processing_status}</span>{item.is_current && <span className="text-xs font-semibold text-blue-700">Current</span>}{canUpload && !["COMPLETED", "SKIPPED"].includes(item.processing_status) && <button disabled={busy} onClick={() => void reprocess(item)} className="text-xs font-semibold text-blue-700 disabled:opacity-50">Retry</button>}</div></article>; })}</div>}</section>
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white"><div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="font-semibold text-slate-900">Historical import jobs</h2><p className="mt-1 text-xs text-slate-500">Background jobs retain file level success and failure details.</p></div><button onClick={() => void load()} className="text-xs font-semibold text-blue-700">Refresh</button></div>{jobs.length === 0 ? <p className="p-5 text-sm text-slate-500">No historical jobs submitted.</p> : <div className="divide-y divide-slate-100">{jobs.map((job) => <div key={job.id} className="flex flex-wrap items-center gap-4 px-5 py-4"><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-slate-800">{job.date_start || "—"} to {job.date_end || "—"}</p><p className="mt-1 text-xs text-slate-500">{job.completed_files} complete · {job.skipped_files} skipped · {job.failed_files} failed · {job.total_files} files</p><div className="mt-2 h-1.5 w-full max-w-xs rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-blue-600" style={{ width: `${job.progress_percent}%` }} /></div></div><span className="text-xs font-semibold text-slate-600">{job.status}</span><button onClick={() => void inspectJob(job)} className="text-xs font-semibold text-blue-700">Details</button>{canUpload && job.failed_files > 0 && <button disabled={busy} onClick={() => void retryJob(job)} className="text-xs font-semibold text-blue-700">Retry failed</button>}</div>)}</div>}</section>
    {selectedJob && <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5"><div className="flex justify-between"><h2 className="font-semibold text-slate-900">Import file results</h2><button onClick={() => setSelectedJob(null)} className="text-sm text-slate-500">Close</button></div><ul className="mt-3 divide-y divide-slate-100">{selectedJob.files.map((entry) => <li key={`${entry.filename}-${entry.business_date}`} className="py-3 text-sm"><span className="font-medium text-slate-800">{entry.filename}</span><span className="ml-2 text-xs text-slate-500">{entry.business_date} · {entry.status}</span>{entry.error_message && <p className="mt-1 text-xs text-red-700">{entry.error_message}</p>}</li>)}</ul></section>}
    {issues.length > 0 && <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-slate-900">Latest validation report</h2><ul className="mt-3 space-y-2">{issues.map((issue, index) => <li key={`${issue.code}-${issue.row}-${index}`} className="rounded-lg bg-slate-50 px-3 py-2 text-sm"><span className={`mr-2 text-xs font-bold ${issue.severity === "ERROR" ? "text-red-700" : "text-amber-700"}`}>{issue.severity}</span><span className="font-medium text-slate-700">{issue.sheet}{issue.row ? ` · row ${issue.row}` : ""} · {issue.code}</span><p className="mt-1 text-xs text-slate-500">{issue.message}</p></li>)}</ul></section>}
  </div></main>;
}
