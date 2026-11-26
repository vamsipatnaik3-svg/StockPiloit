"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DonutChart, EmptyChart, HorizontalBarChart, InventoryStatusChart, Sparkline, TimeSeriesChart, WasteProductChart, WasteTrendChart } from "./analytics-charts";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
type Profile = { full_name: string; email: string; company_name: string; role: string };
type Branch = { id: string; name: string; is_active: boolean };
// API response keys are intentionally open because the analytics modules have distinct schemas.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Data = Record<string, any>;
export type Section = "overview" | "sales" | "products" | "inventory" | "waste" | "purchases" | "alerts";
const nav = [
  ["Overview", "/dashboard"], ["Branches", "/dashboard/branches"],
  ["Sales Analytics", "/dashboard/analytics/sales"], ["Product Intelligence", "/dashboard/analytics/products"],
  ["Inventory Intelligence", "/dashboard/analytics/inventory"], ["Waste & Expiry", "/dashboard/analytics/waste"],
  ["Purchase Intelligence", "/dashboard/analytics/purchases"], ["Team Management", "/dashboard/team"],
  ["Data & Uploads", "/dashboard/uploads"], ["Settings", "/dashboard/settings"],
];
const sections: Record<Section, { title: string; endpoint: string }> = {
  overview: { title: "Executive Business Overview", endpoint: "overview" },
  sales: { title: "Sales Analytics", endpoint: "sales/trends" },
  products: { title: "Product Intelligence", endpoint: "products/performance" },
  inventory: { title: "Inventory Intelligence", endpoint: "inventory/overview" },
  waste: { title: "Waste & Expiry", endpoint: "waste/overview" },
  purchases: { title: "Purchase Intelligence", endpoint: "purchases/overview" },
  alerts: { title: "Business alerts", endpoint: "alerts" },
};
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const today = () => iso(new Date());
const money = (n: number | string | null | undefined, currency: string) => n == null ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(n));
const number = (n: number | string | null | undefined) => n == null ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(Number(n));

export default function OwnerDashboard({ user, section = "overview" }: { user: Profile; section?: Section }) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branch, setBranch] = useState("");
  const [start, setStart] = useState(() => { const d = new Date(); d.setDate(d.getDate() - 29); return iso(d); });
  const [end, setEnd] = useState(today);
  const [range, setRange] = useState("30");
  const [data, setData] = useState<Record<string, Data>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const router = useRouter();
  const currency = data.overview?.currency || data[section]?.currency || "INR";
  const title = sections[section].title;

  const applyRange = (value: string) => {
    const now = new Date(); const endDate = new Date(now); const startDate = new Date(now);
    if (value === "today") { /* same day */ }
    if (value === "yesterday") { startDate.setDate(startDate.getDate() - 1); endDate.setDate(endDate.getDate() - 1); }
    if (value === "7" || value === "30") startDate.setDate(startDate.getDate() - Number(value) + 1);
    if (value === "month") startDate.setDate(1);
    if (value === "lastmonth") { startDate.setMonth(startDate.getMonth() - 1, 1); endDate.setDate(0); }
    setRange(value); setStart(iso(startDate)); setEnd(iso(endDate));
  };

  const load = useCallback(async () => {
    setLoading(true); setError("");
    const q = new URLSearchParams({ start_date: start, end_date: end });
    if (branch) q.set("branch_id", branch);
    try {
      const requested: [string, string][] = section === "overview" ? [
        ["overview", "overview"], ["trends", "sales/trends"], ["branches", "branches/performance"],
        ["products", "products/performance"], ["inventory", "inventory/overview"],
        ["waste", "waste/overview"], ["purchases", "purchases/overview"], ["alerts", "alerts"],
      ] : [[section, sections[section].endpoint]];
      const responses = await Promise.all(requested.map(async ([key, path]) => {
        const params = new URLSearchParams(q);
        if (path === "inventory/overview") { params.delete("start_date"); params.delete("end_date"); params.set("as_of_date", end); }
        const r = await fetch(`${API}/api/v1/analytics/${path}?${params}`, { credentials: "include" });
        if (!r.ok) throw new Error(`Unable to load ${key.replaceAll("_", " ")} (${r.status}).`);
        return [key, await r.json()] as const;
      }));
      setData(Object.fromEntries(responses));
    } catch (e) { setError(e instanceof Error ? e.message : "Analytics could not be loaded."); }
    finally { setLoading(false); }
  }, [branch, end, section, start]);

  useEffect(() => { fetch(`${API}/api/v1/branches`, { credentials: "include" }).then(r => r.ok ? r.json() : []).then((rows: Branch[]) => setBranches(rows.filter(b => b.is_active))).catch(() => setBranches([])); }, []);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);

  const cards = useMemo(() => {
    const o = data.overview || {};
    const wasteByUnit = o.waste_by_unit || [];
    const wasteValue = o.waste_value?.current;
    const wasteHasOneUnit = o.waste_quantity != null && o.waste_unit;
    return [
      { label: "Revenue", value: money(o.revenue?.current, currency), change: o.revenue?.change_percent, detail: "Validated net sales", icon: "₹", tone: "blue" },
      { label: "Transactions", value: number(o.transaction_count?.current), change: o.transaction_count?.change_percent, detail: o.transaction_count?.current == null ? "No transaction-level records" : "Actual transaction records", icon: "↗", tone: "violet" },
      { label: "Active branches", value: number(o.active_branches), change: null, detail: "In the selected scope", icon: "⌂", tone: "cyan" },
      { label: "Recorded waste", value: wasteHasOneUnit ? `${number(o.waste_quantity)} ${o.waste_unit}` : wasteValue != null ? money(wasteValue, currency) : "—", change: wasteValue != null ? o.waste_value?.change_percent : null,
        detail: wasteHasOneUnit ? (wasteValue == null ? "Recorded quantity · valuation unavailable" : `Recorded value ${money(wasteValue, currency)}`)
          : wasteByUnit.length ? wasteByUnit.map((item: { quantity: number | string; unit: string }) => `${number(item.quantity)} ${item.unit}`).join(" · ")
          : wasteValue != null ? "Reliable recorded waste value" : "No waste quantity or reliable valuation", icon: "◇", tone: "amber" },
    ];
  }, [currency, data.overview]);

  const initials = user.full_name.split(/\s+/).slice(0, 2).map(x => x[0]).join("").toUpperCase();
  const signOut = async () => {
    setLoggingOut(true);
    try {
      const response = await fetch(`${API}/api/v1/auth/logout`, { method: "POST", credentials: "include" });
      if (!response.ok) throw new Error("Unable to sign out. Please try again.");
      router.replace("/login");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to sign out."); }
    finally { setLoggingOut(false); }
  };
  return <main className="min-h-screen bg-slate-50 text-slate-900"><div className="flex min-h-screen">
    <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-5 py-7 lg:flex">
      <Link href="/dashboard" className="flex items-center gap-3 px-2"><span className="grid h-11 w-11 place-items-center rounded-2xl bg-blue-600 text-xl font-bold text-white">T</span><span><b className="block text-xl">Tavuno</b><small className="text-slate-400">Retail Intelligence</small></span></Link>
      <nav className="mt-10 space-y-1">{nav.map(([label, href]) => <Link key={href} href={href} className={`block rounded-xl px-4 py-3 text-sm ${((href === "/dashboard" && section === "overview") || href === `/dashboard/analytics/${section}`) ? "bg-blue-50 font-semibold text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}>{label}</Link>)}</nav>
      <div className="mt-auto rounded-xl border bg-slate-50 p-4"><b>{user.full_name}</b><p className="mt-1 truncate text-xs text-slate-500">{user.email}</p><p className="mt-2 text-xs text-blue-700">Company Owner</p></div>
    </aside>
    <section className="min-w-0 flex-1">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 sm:px-8"><div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Tavuno · Owner workspace</p><h1 className="mt-1 text-base font-bold text-slate-900">{user.company_name}</h1></div><div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-full bg-slate-900 text-sm font-semibold text-white">{initials}</span><button onClick={() => void signOut()} disabled={loggingOut} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-50">{loggingOut ? "Signing out…" : "Sign out"}</button></div></header>
      <nav className="flex gap-2 overflow-x-auto border-b bg-white p-3 lg:hidden">{nav.map(([label, href]) => <Link key={href} href={href} className="whitespace-nowrap rounded-lg px-3 py-2 text-xs text-slate-600">{label}</Link>)}</nav>
      <div className="mx-auto max-w-[1540px] space-y-6 p-5 sm:p-8 xl:px-10">
        <div className="flex flex-wrap items-end justify-between gap-5"><div className="min-w-[250px]"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Owner workspace</p><h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">{title}</h2><p className="mt-2 text-sm text-slate-500">A clear view of business performance across your retail operation.</p></div>
          <div className="flex flex-wrap items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
            <label className="px-2 text-[11px] font-medium text-slate-500">Period<select value={range} onChange={e => applyRange(e.target.value)} className="mt-1 block rounded-lg border-0 bg-slate-50 px-2.5 py-2 text-sm font-semibold text-slate-800 outline-none ring-1 ring-slate-200"><option value="today">Today</option><option value="yesterday">Yesterday</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="month">This month</option><option value="lastmonth">Last month</option><option value="custom">Custom range</option></select></label>
            <label className="px-2 text-[11px] font-medium text-slate-500">From<input aria-label="Start date" type="date" value={start} onChange={e => { setRange("custom"); setStart(e.target.value); }} className="mt-1 block rounded-lg border-0 bg-slate-50 px-2 py-2 text-sm font-semibold text-slate-800 outline-none ring-1 ring-slate-200" /></label>
            <label className="px-2 text-[11px] font-medium text-slate-500">To<input aria-label="End date" type="date" value={end} onChange={e => { setRange("custom"); setEnd(e.target.value); }} className="mt-1 block rounded-lg border-0 bg-slate-50 px-2 py-2 text-sm font-semibold text-slate-800 outline-none ring-1 ring-slate-200" /></label>
            <label className="px-2 text-[11px] font-medium text-slate-500">Branch<select value={branch} onChange={e => setBranch(e.target.value)} className="mt-1 block min-w-36 rounded-lg border-0 bg-slate-50 px-2.5 py-2 text-sm font-semibold text-slate-800 outline-none ring-1 ring-slate-200"><option value="">All branches</option>{branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
          </div>
        </div>
        {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}<button onClick={() => void load()} className="ml-3 font-semibold underline">Retry</button></div>}
        {loading && <div className="rounded-xl border bg-white p-4 text-sm text-slate-500">Loading validated business data…</div>}
        {!loading && !error && section === "overview" && <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{cards.map(card => <article key={card.label} className="group min-h-[172px] rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_10px_rgba(15,23,42,0.03)] transition hover:-translate-y-0.5 hover:shadow-md"><div className="flex items-center justify-between"><p className="text-sm font-semibold text-slate-600">{card.label}</p><span className={`grid h-10 w-10 place-items-center rounded-xl text-lg font-semibold ${card.tone === "blue" ? "bg-blue-50 text-blue-700" : card.tone === "violet" ? "bg-violet-50 text-violet-700" : card.tone === "cyan" ? "bg-cyan-50 text-cyan-700" : "bg-amber-50 text-amber-700"}`}>{card.icon}</span></div><div className="mt-3 flex items-center justify-between gap-2"><p className="truncate text-[clamp(1.45rem,2vw,2rem)] font-bold tracking-tight text-slate-950" title={card.value}>{card.value}</p>{card.label === "Revenue" && <Sparkline points={(data.trends?.points || []).map((point: Data) => point.revenue)} />}</div><div className="mt-3 flex min-h-5 items-center justify-between gap-2"><p className="truncate text-xs text-slate-500" title={card.detail}>{card.detail}</p>{card.change != null && <span className={`shrink-0 text-xs font-semibold ${Number(card.change) >= 0 ? "text-emerald-700" : "text-rose-700"}`}>{Number(card.change) > 0 ? "+" : ""}{number(card.change)}%</span>}</div>{card.change != null && <p className="mt-1 text-[10px] text-slate-400">vs previous equivalent period</p>}</article>)}</div>
          <div className="grid items-start gap-5 xl:grid-cols-3"><Panel title="Sales performance" href="/dashboard/analytics/sales"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-slate-500">{data.trends?.grain || "Daily"} view · {number(data.overview?.coverage?.sales_days)} business days reported</p><span className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-700">{money(data.trends?.current_revenue, currency)} current</span></div><TimeSeriesChart currency={currency} grain={data.trends?.grain} reportedDays={data.overview?.coverage?.sales_days} singleBusinessDate={data.overview?.coverage?.latest_sales_date} series={[{ label: "Revenue", color: "#2563eb", points: (data.trends?.points || []).map((point: Data) => ({ date: point.period_start, value: point.revenue })) }]} /></Panel><AlertPanel alerts={data.alerts?.alerts || []} branches={branches} /></div>
          <div className="grid items-start gap-5 xl:grid-cols-2"><Panel title="Branch performance" href="/dashboard/branches"><HorizontalBarChart currency={currency} data={(data.branches?.branches || []).map((row: Data) => ({ id: row.branch_id, label: row.branch_name, value: row.revenue, change: row.change_percent, detail: row.transaction_count == null ? "" : `${number(row.transaction_count)} transactions` }))} onSelect={setBranch} emptyLabel="No validated branch sales for this period." />{(data.branches?.branches || []).length > 1 && <p className="mt-3 text-xs text-slate-500">Ranked by revenue · highest {data.branches.branches[0].branch_name} · lowest {data.branches.branches.at(-1).branch_name}</p>}</Panel><Panel title="Top products by revenue" href="/dashboard/analytics/products"><HorizontalBarChart currency={currency} data={(data.products?.top_products || []).map((row: Data) => ({ id: row.product_id, label: row.product_name, value: row.revenue, detail: `${number(row.quantity)} ${row.unit} sold` }))} onSelect={() => router.push("/dashboard/analytics/products")} emptyLabel="No validated product sales for this period." /></Panel></div>
          <div className="grid items-start gap-5 xl:grid-cols-2"><Panel title="Category contribution" href="/dashboard/analytics/products"><DonutChart currency={currency} data={(data.products?.categories || []).map((row: Data) => ({ id: row.category_id, label: row.category, value: row.revenue }))} /></Panel><Panel title="Inventory health" href="/dashboard/analytics/inventory"><InventoryStatusChart total={data.inventory?.products?.length || 0} expiring={data.inventory?.expiring_batches?.length || 0} expired={data.inventory?.expired_batches?.length || 0} /><p className="mt-3 text-xs text-slate-400">Low-stock thresholds {data.inventory?.low_stock_thresholds_configured ? "are configured" : "are not configured"}.</p></Panel></div>
          <div className="grid items-start gap-5 xl:grid-cols-2"><Panel title="Waste trend by unit" href="/dashboard/analytics/waste"><WasteTrendChart rows={data.waste?.trend || []} /></Panel><Panel title="Waste by product" href="/dashboard/analytics/waste"><WasteProductChart data={data.waste?.wasted_by_product || []} units={[...new Set<string>((data.waste?.wasted_by_product || []).map((row: Data) => String(row.unit)))].sort()} /><p className="mt-3 text-xs text-slate-400">{data.waste?.recorded_value == null ? "Financial value unavailable without complete cost coverage." : `Recorded value ${money(data.waste.recorded_value, currency)}`}</p></Panel></div>
          <div className="grid items-start gap-5 xl:grid-cols-2"><Panel title="Purchase spending" href="/dashboard/analytics/purchases">{data.purchases?.trend?.length > 1 ? <TimeSeriesChart currency={currency} grain="daily" series={[{ label: "Spend", color: "#0f766e", points: data.purchases.trend.map((point: Data) => ({ date: point.business_date, value: point.spend })) }]} /> : <p className="py-5 text-sm text-slate-500">{data.purchases?.trend?.length ? `One reported purchase date: ${money(data.purchases.trend[0].spend, currency)}.` : "No purchase spending history for this period."}</p>}<p className="mt-2 text-xs text-slate-500">Supplier spend {money(data.purchases?.spend, currency)} · {number(data.purchases?.total_lines)} validated lines</p></Panel><Panel title="Supplier purchases" href="/dashboard/analytics/purchases"><Rows rows={data.purchases?.supplier_purchases || []} empty="No validated supplier purchases." render={x => <div className="flex justify-between gap-3"><span className="truncate">{x.supplier}</span><b>{money(x.spend, currency)}</b></div>} /></Panel></div>
          <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm"><div><p className="text-sm font-semibold text-slate-800">Data coverage</p><p className="mt-1 text-xs text-slate-500">{number(data.overview?.coverage?.sales_lines)} validated sales lines · {number(data.overview?.coverage?.sales_days)} business days · Latest sales {data.overview?.coverage?.latest_sales_date || "not available"} · Latest successful upload {data.overview?.coverage?.latest_upload_date || "not available"}</p></div><CoverageSummary alerts={data.alerts?.alerts || []} branches={branches} /></section>
          {data.overview?.unsupported_metrics?.length > 0 && <p className="text-xs text-slate-400">Unavailable from current data: {data.overview.unsupported_metrics.join(" ")}</p>}
        </>}
        {!loading && !error && section !== "overview" && <Detail section={section} data={data[section]} currency={currency} branches={branches} />}
        <footer className="flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-4 text-xs text-slate-400"><span>Tavuno · Validated current uploads</span><span>Quantity units are shown as recorded.</span></footer>
      </div>
    </section>
  </div></main>;
}

function Panel({ title, href, children }: { title: string; href: string; children: ReactNode }) { return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_10px_rgba(15,23,42,0.03)]"><div className="mb-4 flex items-center justify-between gap-3"><h3 className="font-semibold tracking-tight text-slate-900">{title}</h3><Link href={href} className="shrink-0 text-xs font-semibold text-blue-700 hover:text-blue-900">View details <span aria-hidden="true">→</span></Link></div>{children}</section>; }
function rowKey(row: Data, index: number) {
  const dimensions = ["id", "branch_id", "product_id", "batch_number", "business_date", "unit", "sku", "supplier", "category"];
  const identity = dimensions.flatMap(key => row[key] == null ? [] : [`${key}=${String(row[key])}`]).join("|");
  return `${identity || "row"}:${index}`;
}

function Rows({ rows, empty, render }: { rows: Data[]; empty: string; render: (row: Data) => ReactNode }) { return rows.length ? <div className="divide-y divide-slate-100">{rows.slice(0, 8).map((r, i) => <div key={rowKey(r, i)} className="py-3 first:pt-0 last:pb-0">{render(r)}</div>)}</div> : <p className="py-6 text-center text-sm text-slate-400">{empty}</p>; }

function formatDate(value: string, short = false) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return new Intl.DateTimeFormat("en-IN", short ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function AlertPanel({ alerts, branches, showAll = false }: { alerts: Data[]; branches: Branch[]; showAll?: boolean }) {
  const severityRank: Record<string, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 };
  const ordered = [...alerts].sort((a, b) => (severityRank[a.severity] ?? 3) - (severityRank[b.severity] ?? 3));
  const critical = ordered.filter(item => item.severity === "CRITICAL").length;
  const warning = ordered.filter(item => item.severity === "WARNING").length;
  const groups = new Map<string, number>();
  for (const item of alerts) groups.set(String(item.kind), (groups.get(String(item.kind)) || 0) + 1);
  const branchById = new Map(branches.map(item => [item.id, item.name]));
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_2px_10px_rgba(15,23,42,0.03)]"><div className="mb-4 flex items-center justify-between gap-3"><div><h3 className="font-semibold tracking-tight text-slate-900">Business alerts</h3><p className="mt-1 text-xs text-slate-500">Prioritized from current operational records</p></div>{!showAll && <Link href="/dashboard/analytics/alerts" className="shrink-0 text-xs font-semibold text-blue-700">View all →</Link>}</div>
    <div className="mb-3 flex gap-2 text-[11px]">{critical > 0 && <span className="rounded-full bg-rose-50 px-2.5 py-1 font-semibold text-rose-700">{critical} critical</span>}{warning > 0 && <span className="rounded-full bg-amber-50 px-2.5 py-1 font-semibold text-amber-800">{warning} attention</span>}{alerts.length === 0 && <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-700">All clear</span>}</div>
    <div className="mb-3 flex flex-wrap gap-1.5">{[...groups.entries()].slice(0, 4).map(([kind, count]) => <span key={kind} className="rounded-md bg-slate-100 px-2 py-1 text-[10px] text-slate-500">{alertLabel(kind)} · {count}</span>)}</div>
    {ordered.length ? <div className="divide-y divide-slate-100">{(showAll ? ordered : ordered.slice(0, 3)).map((item, index) => <div key={`${String(item.id || "alert")}:${String(item.branch_id || "company")}:${String(item.product_id || "")}:${index}`} className="flex gap-3 py-3 first:pt-1"><span className={`mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full ${item.severity === "CRITICAL" ? "bg-rose-500" : item.severity === "WARNING" ? "bg-amber-500" : "bg-blue-500"}`} /><div className="min-w-0"><p className="text-sm font-semibold text-slate-800">{item.title}</p><p className="mt-0.5 line-clamp-2 text-xs leading-5 text-slate-500">{item.description}</p><p className="mt-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">{branchById.get(item.branch_id) || "Company-wide"} · {item.severity.toLowerCase()}</p></div></div>)}</div> : <div className="rounded-xl bg-slate-50 px-4 py-6 text-center"><p className="text-sm font-medium text-slate-600">No current alerts</p><p className="mt-1 text-xs text-slate-400">No expiry, upload or reconciliation alerts were returned for this scope.</p></div>}
  </section>;
}

function alertLabel(kind: string) { return ({ EXPIRED_STOCK: "Expired", EXPIRING_STOCK: "Expiring", INVENTORY_DISCREPANCY: "Reconciliation", MISSING_UPLOAD: "Missing upload", OUTDATED_UPLOAD: "Outdated upload" } as Record<string, string>)[kind] || kind.replaceAll("_", " ").toLowerCase(); }

function CoverageSummary({ alerts, branches }: { alerts: Data[]; branches: Branch[] }) {
  const missing = alerts.filter(alert => alert.kind === "MISSING_UPLOAD").length;
  const stale = alerts.filter(alert => alert.kind === "OUTDATED_UPLOAD").length;
  if (branches.length === 0) return <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600">No active branches to report</span>;
  if (!missing && !stale) return <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700">All {branches.length} branches current</span>;
  return <div className="flex flex-wrap gap-2">{missing > 0 && <span className="rounded-full bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-700">{missing} missing</span>}{stale > 0 && <span className="rounded-full bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800">{stale} outdated</span>}</div>;
}

function groupBatches(rows: Data[]): Data[] {
  const grouped = new Map<string, Data>();
  for (const row of rows) {
    const key = `${row.branch_id}:${row.product_id}:${row.unit}`;
    const current = grouped.get(key);
    if (current) {
      current.quantity = Number(current.quantity) + Number(row.quantity);
      current.batch_count += 1;
      if (row.expiry_date && (!current.expiry_date || row.expiry_date < current.expiry_date)) current.expiry_date = row.expiry_date;
    } else grouped.set(key, { ...row, quantity: Number(row.quantity), batch_count: 1 });
  }
  return [...grouped.values()].sort((a, b) => String(a.product_name).localeCompare(String(b.product_name)));
}

function productTrendSeries(products: Data[], trendRows: Data[]) {
  const colors = ["#2563eb", "#0f766e", "#7c3aed", "#d97706", "#db2777"];
  return products.slice(0, 5).map((product, index) => ({
    label: product.product_name,
    color: colors[index % colors.length],
    points: trendRows.filter(row => row.product_id === product.product_id)
      .map(row => ({ date: row.business_date, value: row.revenue })),
  })).filter(series => new Set(series.points.map(point => point.date)).size > 1);
}

function Detail({ section, data, currency, branches }: { section: Section; data?: Data; currency: string; branches: Branch[] }) {
  if (!data) return <p className="rounded-xl border bg-white p-5 text-sm text-slate-500">No validated records are available for this date range.</p>;
  if (section === "sales") return <Panel title="Revenue trend" href="/dashboard"><div className="mb-3 flex flex-wrap justify-between gap-2 text-sm"><span className="text-slate-500">Current {money(data.current_revenue, currency)} · Previous {money(data.previous_revenue, currency)}</span><span className="font-medium text-slate-500">{data.grain} buckets</span></div><TimeSeriesChart currency={currency} grain={data.grain} series={[{ label: "Revenue", color: "#2563eb", points: (data.points || []).map((point: Data) => ({ date: point.period_start, value: point.revenue })) }]} /></Panel>;
  if (section === "alerts") return <AlertPanel alerts={data.alerts || []} branches={branches} showAll />;
  const configs: Record<Exclude<Section, "overview" | "sales" | "alerts">, { title: string; rows: Data[]; empty: string; render: (x: Data) => ReactNode }> = {
    products: { title: "Products by revenue", rows: data.top_products || [], empty: "No validated product sales.", render: x => <div className="flex justify-between"><span>{x.product_name} · {x.sku} · {number(x.quantity)} {x.unit}</span><b>{money(x.revenue, currency)}</b></div> },
    inventory: { title: "Current batches", rows: data.products || [], empty: "No current inventory snapshots.", render: x => <div className="flex justify-between"><span>{x.product_name} · {x.branch_name} · {x.batch_number || "No batch"}</span><b>{x.quantity} {x.unit}</b></div> },
    waste: { title: "Waste by product", rows: data.wasted_by_product || [], empty: "No waste records for this period.", render: x => <div className="flex justify-between"><span>{x.product_name} · {x.unit}</span><b>Damaged {x.damaged} · Wasted {x.wasted}</b></div> },
    purchases: { title: "Purchase products", rows: data.products || [], empty: "No validated purchase records.", render: x => <div className="flex justify-between"><span>{x.product_name} · {x.quantity} {x.unit}</span><b>{money(x.spend, currency)}</b></div> },
  };
  const config = configs[section as Exclude<Section, "overview" | "sales" | "alerts">];
  return <><Panel title={config.title} href="/dashboard">{<Rows rows={config.rows} empty={config.empty} render={config.render} />}</Panel>
    {section === "products" && <><Panel title="Ranked product revenue" href="/dashboard/products"><HorizontalBarChart currency={currency} data={(data.top_products || []).map((row: Data) => ({ id: row.product_id, label: row.product_name, value: row.revenue, detail: `${number(row.quantity)} ${row.unit} sold` }))} emptyLabel="No validated product sales." /></Panel><Panel title="Product sales trends" href="/dashboard/products"><TimeSeriesChart currency={currency} grain="daily" series={productTrendSeries(data.top_products || [], data.product_trends || [])} /></Panel><div className="grid gap-5 xl:grid-cols-2"><Panel title="Lowest revenue products" href="/dashboard/products"><Rows rows={data.lowest_revenue_products || []} empty="No validated product sales." render={x => <div className="flex justify-between"><span>{x.product_name} · {number(x.quantity)} {x.unit}</span><b>{money(x.revenue, currency)}</b></div>} /></Panel><Panel title="Category contribution" href="/dashboard/products"><DonutChart currency={currency} data={(data.categories || []).map((row: Data) => ({ id: row.category_id, label: row.category, value: row.revenue }))} /><Link href="/dashboard/products" className="mt-4 inline-block text-sm font-semibold text-blue-700">Manage product catalogue →</Link></Panel></div></>}
    {section === "inventory" && <><Panel title="Inventory status" href="/dashboard"><InventoryStatusChart total={data.products?.length || 0} expiring={data.expiring_batches?.length || 0} expired={data.expired_batches?.length || 0} /><p className="mt-2 text-xs text-slate-400">Low-stock thresholds {data.low_stock_thresholds_configured ? "are configured" : "are not configured"}.</p></Panel><Panel title="Expiring batches · next 30 days" href="/dashboard/analytics/alerts"><Rows rows={groupBatches(data.expiring_batches || [])} empty="No batches approaching expiry." render={x => <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold text-slate-800">{x.product_name}</p><p className="mt-1 text-xs text-slate-500">{x.branch_name} · {x.batch_count} batches · earliest {formatDate(x.expiry_date)}</p></div><span className="rounded-lg bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">{number(x.quantity)} {x.unit}</span></div>} /></Panel><Panel title="Expired stock" href="/dashboard/analytics/alerts"><Rows rows={groupBatches(data.expired_batches || [])} empty="No expired stock on hand." render={x => <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold text-slate-800">{x.product_name}</p><p className="mt-1 text-xs text-slate-500">{x.branch_name} · {x.batch_count} batches</p></div><span className="rounded-lg bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">{number(x.quantity)} {x.unit}</span></div>} /></Panel><Panel title="Inventory reconciliation" href="/dashboard/uploads"><Rows rows={data.reconciliation_discrepancies || []} empty="No recent reconciliation issues." render={x => <div>{x.branch_name} · {formatDate(x.business_date)} · {x.message}</div>} /></Panel></>}
    {section === "waste" && <><Panel title="Damaged versus wasted trend" href="/dashboard"><WasteTrendChart rows={data.trend || []} /></Panel><Panel title="Product comparison" href="/dashboard"><WasteProductChart data={data.wasted_by_product || []} units={[...new Set<string>((data.wasted_by_product || []).map((row: Data) => String(row.unit)))].sort()} /></Panel><div className="grid gap-5 xl:grid-cols-2"><Panel title="Waste by branch" href="/dashboard/branches"><Rows rows={data.by_branch || []} empty="No waste records by branch." render={x => <div className="flex justify-between"><span>{x.branch_name}</span><b>Damaged {number(x.damaged)} · Wasted {number(x.wasted)}</b></div>} /></Panel><Panel title="Recorded waste value" href="/dashboard">{data.recorded_value == null ? "Unavailable: one or more waste records lack unit cost." : money(data.recorded_value, currency)}<p className="mt-2 text-xs text-slate-500">{data.cost_coverage_complete ? "Complete cost coverage" : "Not all positive waste rows have a recorded unit cost"}</p></Panel></div></>}
    {section === "purchases" && <><Panel title="Purchase spending over time" href="/dashboard">{(data.trend || []).length > 1 ? <TimeSeriesChart currency={currency} grain="daily" series={[{ label: "Spend", color: "#0f766e", points: (data.trend || []).map((point: Data) => ({ date: point.business_date, value: point.spend })) }]} /> : <EmptyChart title={data.trend?.length ? "One reported purchase date" : "No purchase trend history"} detail={data.trend?.length ? `${formatDate(data.trend[0].business_date)} · ${money(data.trend[0].spend, currency)}. A trend needs at least two dates.` : "No validated purchase spending is available for this period."} />}</Panel><Panel title="Supplier purchases" href="/dashboard"><Rows rows={data.supplier_purchases || []} empty="No supplier purchases." render={x => <div className="flex justify-between"><span>{x.supplier} · {x.lines} lines</span><b>{money(x.spend, currency)}</b></div>} /></Panel></>}
  </>;
}

export function OwnerAnalyticsPage({ section }: { section: Section }) {
  const router = useRouter();
  const [user, setUser] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/api/v1/auth/me`, { credentials: "include" }).then(async r => {
      if (r.status === 401) { router.replace("/login"); return; }
      if (!r.ok) throw new Error("Unable to load your workspace.");
      const profile = await r.json();
      if (profile.role !== "OWNER") { router.replace("/dashboard"); return; }
      setUser(profile);
    }).catch(e => setError(e instanceof Error ? e.message : "Workspace unavailable."));
  }, [router]);
  if (error) return <main className="p-8 text-sm text-red-700">{error}</main>;
  if (!user) return <main className="p-8 text-sm text-slate-500">Loading your workspace…</main>;
  return <OwnerDashboard user={user} section={section} />;
}
