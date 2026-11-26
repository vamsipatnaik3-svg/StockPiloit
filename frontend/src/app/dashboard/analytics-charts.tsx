"use client";

import { useId, useState } from "react";

type Scalar = string | number | null | undefined;
export type TimePoint = { date: string; value: Scalar };
export type TimeSeries = { label: string; color: string; points: TimePoint[] };

const formatCurrency = (value: number, currency: string, compact = false) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency", currency, maximumFractionDigits: compact ? 1 : 2,
    ...(compact ? { notation: "compact" as const } : {}),
  }).format(value);
const formatQuantity = (value: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value);
const parse = (value: Scalar) => value == null || value === "" ? null : Number(value);
const dateLabel = (value: string, short = false) => {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", short ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" }).format(new Date(year, month - 1, day));
};

export function TimeSeriesChart({ series, currency = "INR", grain = "daily", reportedDays, singleBusinessDate, valueUnit = "currency", minHeight = "h-[260px]" }: {
  series: TimeSeries[]; currency?: string; grain?: string; reportedDays?: number;
  singleBusinessDate?: string | null; valueUnit?: "currency" | "quantity"; minHeight?: string;
}) {
  const gradientId = useId().replaceAll(":", "");
  const normalized = series.map(line => ({ ...line, points: line.points.map(point => ({ ...point, numeric: parse(point.value) })) }));
  const allPoints = normalized.flatMap(line => line.points).filter(point => point.numeric != null);
  const dates = [...new Set(normalized.flatMap(line => line.points.map(point => point.date)))].sort();
  const validDates = [...new Set(allPoints.map(point => point.date))].sort();
  const formatter = (value: number) => valueUnit === "currency" ? formatCurrency(value, currency) : formatQuantity(value);

  if (!allPoints.length) return <EmptyChart title="No recorded values" detail="No validated data is available for this selection." minHeight={minHeight} />;
  if (validDates.length === 1) {
    const oneBusinessDate = reportedDays === 1;
    return <div className={`flex ${minHeight} flex-col justify-center rounded-xl bg-gradient-to-br from-blue-50/80 to-slate-50 px-6 py-5 sm:px-8`}>
      <p className="text-xs font-semibold uppercase tracking-widest text-blue-700">{oneBusinessDate ? "Single reported business date" : "Single reported period"}</p>
      <p className="mt-2 text-sm text-slate-500">{dateLabel(oneBusinessDate && singleBusinessDate ? singleBusinessDate : validDates[0])}</p>
      <div className="mt-3 flex flex-wrap gap-x-7 gap-y-2">{normalized.map(line => {
        const point = line.points.find(item => item.date === validDates[0] && item.numeric != null);
        return point ? <p key={line.label} className="text-xl font-bold text-slate-950"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: line.color }} />{line.label}: {formatter(point.numeric!)}</p> : null;
      })}</div>
      <p className="mt-4 text-xs text-slate-500">Only one reported date is available. A trend line needs at least two dates.</p>
    </div>;
  }

  const width = 900; const height = 300; const left = 92; const right = 20; const top = 20; const bottom = 50;
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const values = allPoints.map(point => point.numeric!);
  const minValue = Math.min(0, ...values); const maxValue = Math.max(0, ...values); const span = maxValue - minValue || 1;
  const xAt = (index: number) => left + index / Math.max(dates.length - 1, 1) * plotWidth;
  const yAt = (value: number) => top + (1 - (value - minValue) / span) * plotHeight;
  const yTicks = [0, 1, 2, 3].map(index => maxValue - index / 3 * span);
  const labels = [...new Set([0, Math.round((dates.length - 1) / 3), Math.round(2 * (dates.length - 1) / 3), dates.length - 1])];
  const unitFormatter = (value: number) => valueUnit === "currency" ? formatCurrency(value, currency, true) : formatQuantity(value);
  const gridX = new Map(dates.map((date, index) => [date, xAt(index)]));

  return <div className="w-full">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap gap-x-4 gap-y-1">{normalized.map(line => <span key={line.label} className="inline-flex items-center gap-1.5 text-xs text-slate-600"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: line.color }} />{line.label}</span>)}</div><span className="text-xs text-slate-400">{dates.length} reported dates · {grain}</span></div>
    <div className="w-full overflow-x-auto"><svg role="img" aria-label={`${normalized.map(line => line.label).join(" and ")} chart across ${dates.length} reported dates`} viewBox={`0 0 ${width} ${height}`} className="h-[250px] min-w-[700px] w-full sm:h-[285px]" preserveAspectRatio="none">
      <defs><linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#3b82f6" stopOpacity=".18" /><stop offset="100%" stopColor="#3b82f6" stopOpacity=".01" /></linearGradient></defs>
      {yTicks.map((value, index) => { const y = top + index / 3 * plotHeight; return <g key={`y-${index}`}><line x1={left} x2={width - right} y1={y} y2={y} stroke="#e8edf4" strokeDasharray={index === 3 ? "0" : "3 5"} /><text x={left - 12} y={y + 4} textAnchor="end" className="fill-slate-400" fontSize="12">{unitFormatter(value)}</text></g>; })}
      {normalized.map((line, lineIndex) => {
        const lookup = new Map(line.points.map(point => [point.date, point.numeric!]));
        const segments: Array<Array<{ date: string; value: number }>> = [];
        let segment: Array<{ date: string; value: number }> = [];
        for (const date of dates) {
          const value = lookup.get(date);
          if (value == null) { if (segment.length) segments.push(segment); segment = []; }
          else segment.push({ date, value });
        }
        if (segment.length) segments.push(segment);
        return <g key={line.label}>
          {lineIndex === 0 && segments.map((part, index) => part.length > 1 ? <path key={`area-${index}`} d={`${part.map((point, i) => `${i === 0 ? "M" : "L"}${gridX.get(point.date)},${yAt(point.value)}`).join(" ")} L${gridX.get(part.at(-1)!.date)},${top + plotHeight} L${gridX.get(part[0].date)},${top + plotHeight} Z`} fill={`url(#${gradientId})`} /> : null)}
          {segments.map((part, index) => <path key={`line-${index}`} d={part.map((point, i) => `${i === 0 ? "M" : "L"}${gridX.get(point.date)},${yAt(point.value)}`).join(" ")} fill="none" stroke={line.color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />)}
          {line.points.filter(point => point.numeric != null).map(point => <circle key={`${point.date}-${line.label}`} cx={gridX.get(point.date)} cy={yAt(point.numeric!)} r="5" fill="white" stroke={line.color} strokeWidth="2.5" vectorEffect="non-scaling-stroke"><title>{`${dateLabel(point.date)} · ${line.label}: ${formatter(point.numeric!)}`}</title></circle>)}
        </g>;
      })}
      {labels.map(index => <text key={`x-${index}`} x={xAt(index)} y={height - 16} textAnchor={index === 0 ? "start" : index === dates.length - 1 ? "end" : "middle"} className="fill-slate-400" fontSize="12">{dateLabel(dates[index], true)}</text>)}
    </svg></div>
    <p className="mt-1 text-[11px] text-slate-400">Missing dates and unpriced periods remain gaps; no values are interpolated.</p>
  </div>;
}

export function Sparkline({ points, color = "#2563eb" }: { points: Scalar[]; color?: string }) {
  const values = points.map(parse).filter((value): value is number => value != null);
  if (values.length < 2) return null;
  const low = Math.min(...values); const high = Math.max(...values); const range = high - low || 1;
  const coords = values.map((value, index) => `${(index / (values.length - 1)) * 100},${26 - ((value - low) / range) * 22}`).join(" ");
  return <svg aria-label="Recent trend" role="img" viewBox="0 0 100 30" className="h-8 w-20"><polyline points={coords} fill="none" stroke={color} strokeWidth="2.5" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export type BarDatum = { id: string; label: string; value: Scalar; detail?: string; change?: Scalar };
export function HorizontalBarChart({ data, currency = "INR", valueUnit = "currency", onSelect, emptyLabel = "No validated data for this selection." }: {
  data: BarDatum[]; currency?: string; valueUnit?: "currency" | "quantity"; onSelect?: (id: string) => void; emptyLabel?: string;
}) {
  const rows = data.map(row => ({ ...row, numeric: parse(row.value) })).filter((row): row is typeof row & { numeric: number } => row.numeric != null);
  if (!rows.length) return <EmptyChart title="Nothing to compare yet" detail={emptyLabel} minHeight="h-52" />;
  const max = Math.max(...rows.map(row => Math.abs(row.numeric)), 1);
  const formatter = valueUnit === "currency" ? (value: number) => formatCurrency(value, currency) : formatQuantity;
  return <div className="space-y-4">{rows.map(row => <button key={row.id} type="button" onClick={() => onSelect?.(row.id)} disabled={!onSelect} className={`block w-full text-left ${onSelect ? "group cursor-pointer" : "cursor-default"}`} title={`${row.label}: ${formatter(row.numeric)}`}>
    <div className="mb-1.5 flex items-baseline justify-between gap-3"><span className="truncate text-sm font-medium text-slate-700">{row.label}</span><span className="shrink-0 text-sm font-semibold text-slate-900">{formatter(row.numeric)}</span></div>
    <div className="h-2.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full bg-blue-600 transition-all ${onSelect ? "group-hover:bg-blue-700" : ""}`} style={{ width: `${Math.max(row.numeric === 0 ? 0 : 3, Math.abs(row.numeric) / max * 100)}%` }} /></div>
    <div className="mt-1 flex justify-between gap-2 text-[11px] text-slate-400"><span className="truncate">{row.detail || ""}</span>{row.change != null && <span className="shrink-0">{Number(row.change) > 0 ? "+" : ""}{formatQuantity(Number(row.change))}% vs prior</span>}</div>
  </button>)}{onSelect && rows.length === 1 && <p className="text-xs text-slate-400">Only one branch is in this selection; no branch comparison is available.</p>}</div>;
}

const donutColors = ["#2563eb", "#0f766e", "#7c3aed", "#d97706", "#db2777", "#0891b2", "#4f46e5", "#65a30d"];
export function DonutChart({ data, currency = "INR" }: { data: Array<{ id: string; label: string; value: Scalar }>; currency?: string }) {
  const parsed = data.map(item => ({ ...item, numeric: parse(item.value) }));
  const rows = parsed.filter((item): item is typeof item & { numeric: number } => item.numeric != null && item.numeric > 0);
  const excluded = parsed.filter(item => item.numeric != null && item.numeric <= 0);
  const total = rows.reduce((sum, item) => sum + item.numeric, 0);
  if (!rows.length || total <= 0) return <div><EmptyChart title="No positive category contribution" detail="No positive validated category revenue was reported." minHeight="h-56" />{excluded.length > 0 && <ul className="mt-3 space-y-1">{excluded.map(row => <li key={row.id} className="flex justify-between gap-3 text-xs text-slate-500"><span className="truncate">{row.label}</span><span>{formatCurrency(row.numeric!, currency)}</span></li>)}</ul>}</div>;
  const circumference = 2 * Math.PI * 42;
  const slices = rows.map((row, index) => ({
    row,
    index,
    length: row.numeric / total * circumference,
    start: rows.slice(0, index).reduce((sum, previous) => sum + previous.numeric / total * circumference, 0),
  }));
  return <div className="grid items-center gap-5 sm:grid-cols-[180px_1fr]">
    <div className="relative mx-auto h-44 w-44"><svg viewBox="0 0 100 100" role="img" aria-label="Category revenue contribution donut chart" className="h-full w-full -rotate-90"><circle cx="50" cy="50" r="42" fill="none" stroke="#eef2f7" strokeWidth="12" />{slices.map(({ row, index, length, start }) => <circle key={row.id} cx="50" cy="50" r="42" fill="none" stroke={donutColors[index % donutColors.length]} strokeWidth="12" strokeDasharray={`${length} ${circumference - length}`} strokeDashoffset={-start} strokeLinecap="butt"><title>{`${row.label}: ${formatCurrency(row.numeric, currency)}`}</title></circle>)}</svg><div className="absolute inset-0 flex flex-col items-center justify-center"><span className="text-[10px] uppercase tracking-wide text-slate-400">Categories</span><span className="mt-1 text-xl font-bold text-slate-900">{rows.length}</span></div></div>
    <div><ul className="space-y-2.5">{rows.map((row, index) => <li key={row.id} className="flex items-center justify-between gap-3 text-sm"><span className="flex min-w-0 items-center gap-2"><i className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: donutColors[index % donutColors.length] }} /><span className="truncate text-slate-600">{row.label}</span></span><span className="shrink-0 font-semibold text-slate-800">{formatCurrency(row.numeric, currency)}</span></li>)}</ul>{excluded.length > 0 && <div className="mt-3 border-t border-slate-100 pt-2"><p className="mb-1 text-[10px] font-medium text-slate-400">Zero or negative revenue (not represented as positive slices)</p>{excluded.map(row => <p key={row.id} className="flex justify-between gap-3 text-xs text-slate-500"><span className="truncate">{row.label}</span><span>{formatCurrency(row.numeric!, currency)}</span></p>)}</div>}</div>
  </div>;
}

export function InventoryStatusChart({ total, expiring, expired }: { total: number; expiring: number; expired: number }) {
  const maximum = Math.max(total, expiring, expired, 1);
  const rows = [{ label: "Snapshot batches", value: total, color: "bg-blue-600" }, { label: "Expiring within 30 days", value: expiring, color: "bg-amber-500" }, { label: "Expired on hand", value: expired, color: "bg-rose-500" }];
  if (!total && !expiring && !expired) return <EmptyChart title="No inventory snapshots" detail="Validated inventory records are not available for this selection." minHeight="h-52" />;
  return <div className="space-y-4">{rows.map(row => <div key={row.label}><div className="mb-1.5 flex justify-between text-sm"><span className="text-slate-600">{row.label}</span><b className="text-slate-900">{formatQuantity(row.value)}</b></div><div className="h-2.5 rounded-full bg-slate-100"><div className={`h-2.5 rounded-full ${row.color}`} style={{ width: `${row.value === 0 ? 0 : Math.max(3, row.value / maximum * 100)}%` }} /></div></div>)}<p className="text-[11px] text-slate-400">Status counts can overlap: expiring and expired are subsets of snapshot batches.</p></div>;
}

export function WasteProductChart({ data, units }: { data: Array<{ product_id: string; product_name: string; sku: string; unit: string; damaged: Scalar; wasted: Scalar }>; units: string[] }) {
  const [selectedUnit, setSelectedUnit] = useState(units[0] || "");
  const unit = units.includes(selectedUnit) ? selectedUnit : units[0] || "";
  const visible = data.filter(item => item.unit === unit);
  const maximum = Math.max(...visible.flatMap(item => [parse(item.damaged) || 0, parse(item.wasted) || 0]), 1);
  if (!data.length) return <EmptyChart title="No recorded waste" detail="No damaged or wasted quantities were recorded for these dates." minHeight="h-52" />;
  return <div>
    {units.length > 1 && <label className="mb-4 flex items-center gap-2 text-xs font-medium text-slate-500">Unit<select value={unit} onChange={event => setSelectedUnit(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700">{units.map(item => <option key={item} value={item}>{item}</option>)}</select></label>}
    {visible.length === 1 && <p className="mb-3 text-xs text-slate-400">Only one product is available in {unit}; shown as a product summary.</p>}
    <div className="mb-3 flex gap-4 text-xs"><span className="flex items-center gap-1.5 text-slate-600"><i className="h-2 w-2 rounded-full bg-amber-500" />Damaged</span><span className="flex items-center gap-1.5 text-slate-600"><i className="h-2 w-2 rounded-full bg-rose-500" />Wasted</span></div>
    <div className="space-y-4">{visible.map(item => <div key={item.product_id}><div className="mb-1.5 flex justify-between gap-3 text-sm"><span className="truncate font-medium text-slate-700">{item.product_name}</span><span className="shrink-0 text-xs text-slate-500">{unit}</span></div>{([ ["Damaged", parse(item.damaged) || 0, "bg-amber-500"], ["Wasted", parse(item.wasted) || 0, "bg-rose-500"] ] as const).map(([label, value, color]) => <div key={label} className="mb-1 flex items-center gap-2"><span className="w-14 text-[10px] text-slate-400">{label}</span><div className="h-2 flex-1 rounded-full bg-slate-100"><div className={`h-2 rounded-full ${color}`} style={{ width: `${value === 0 ? 0 : Math.max(3, value / maximum * 100)}%` }} /></div><span className="w-16 text-right text-xs font-semibold text-slate-700">{formatQuantity(value)}</span></div>)}</div>)}</div>
  </div>;
}

export function WasteTrendChart({ rows }: { rows: Array<{ business_date: string; unit: string; damaged: Scalar; wasted: Scalar }> }) {
  const units = [...new Set(rows.map(row => row.unit))].sort();
  const [selectedUnit, setSelectedUnit] = useState(units[0] || "");
  const unit = units.includes(selectedUnit) ? selectedUnit : units[0] || "";
  if (!rows.length) return <EmptyChart title="No waste trend data" detail="No damaged or wasted quantities were recorded for this period." minHeight="h-56" />;
  const selected = rows.filter(row => row.unit === unit);
  return <div>
    {units.length > 1 && <label className="mb-3 flex items-center gap-2 text-xs font-medium text-slate-500">Unit<select value={unit} onChange={event => setSelectedUnit(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700">{units.map(item => <option key={item} value={item}>{item}</option>)}</select></label>}
    <TimeSeriesChart valueUnit="quantity" grain="daily" series={[
      { label: "Damaged", color: "#d97706", points: selected.map(row => ({ date: row.business_date, value: row.damaged })) },
      { label: "Wasted", color: "#e11d48", points: selected.map(row => ({ date: row.business_date, value: row.wasted })) },
    ]} />
  </div>;
}

export function EmptyChart({ title, detail, minHeight = "h-56" }: { title: string; detail: string; minHeight?: string }) {
  return <div className={`flex ${minHeight} flex-col items-center justify-center rounded-xl bg-slate-50 px-5 text-center`}><span aria-hidden="true" className="text-2xl text-slate-300">⌁</span><p className="mt-2 text-sm font-semibold text-slate-600">{title}</p><p className="mt-1 max-w-sm text-xs leading-5 text-slate-400">{detail}</p></div>;
}
