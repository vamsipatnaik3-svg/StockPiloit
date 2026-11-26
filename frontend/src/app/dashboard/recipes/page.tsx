"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
type MenuItem = { id: string; sku: string; product_name: string; unit_of_measure: string; is_active: boolean; latest_version: number | null; latest_effective_from: string | null };
type Ingredient = { id: string; sku: string; product_name: string; unit_of_measure: string; is_active: boolean };
type ModifierOption = { id: string; name: string; is_active: boolean };
type ModifierGroup = { id: string; name: string; selection_min: number; selection_max: number; options: ModifierOption[] };
type IngredientLine = { ingredient_product_id: string; ingredient_name: string; sku: string; quantity: string; unit: string };
type ModifierLine = { modifier_option_id: string; modifier_option: string; modifier_group: string; ingredient_product_id: string; ingredient_name: string; sku: string; quantity: string; unit: string };
type RecipeVersion = { id: string; version: number; effective_from: string; ingredients: IngredientLine[]; modifier_ingredients: ModifierLine[] };
type RecipeDetail = { menu_item: MenuItem; versions: RecipeVersion[]; modifier_groups: ModifierGroup[] };
type DraftIngredient = { productId: string; quantity: string };
type DraftModifier = { optionId: string; productId: string; quantity: string };

const emptyIngredient = (): DraftIngredient => ({ productId: "", quantity: "" });
const emptyModifier = (): DraftModifier => ({ optionId: "", productId: "", quantity: "" });

export default function RecipesPage() {
  const router = useRouter();
  const [menus, setMenus] = useState<MenuItem[]>([]);
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<RecipeDetail | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [groups, setGroups] = useState<ModifierGroup[]>([]);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [recipeLines, setRecipeLines] = useState<DraftIngredient[]>([emptyIngredient()]);
  const [modifierLines, setModifierLines] = useState<DraftModifier[]>([]);
  const [groupName, setGroupName] = useState("");
  const [optionNames, setOptionNames] = useState("");
  const [selectionMin, setSelectionMin] = useState("0");
  const [selectionMax, setSelectionMax] = useState("1");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [profileResponse, menusResponse, ingredientsResponse] = await Promise.all([
        fetch(`${API}/api/v1/auth/me`, { credentials: "include" }),
        fetch(`${API}/api/v1/recipes`, { credentials: "include" }),
        fetch(`${API}/api/v1/products?product_kind=INGREDIENT&include_inactive=true`, { credentials: "include" }),
      ]);
      if (profileResponse.status === 401) { router.replace("/login"); return; }
      if (!profileResponse.ok || !menusResponse.ok || !ingredientsResponse.ok) throw new Error("Unable to load menu and recipe data.");
      const profile = await profileResponse.json();
      if (profile.must_change_password) { router.replace("/change-password"); return; }
      setIsOwner(profile.role === "OWNER");
      const menuRows: MenuItem[] = await menusResponse.json();
      setMenus(menuRows);
      setIngredients(await ingredientsResponse.json());
      if (!selected && menuRows.length) setSelected(menuRows.find(item => item.is_active)?.id || menuRows[0].id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to load recipes."); }
    finally { setLoading(false); }
  }, [router, selected]);

  const loadDetail = useCallback(async (menuId: string) => {
    if (!menuId) { setDetail(null); setGroups([]); return; }
    const [recipeResponse, groupsResponse] = await Promise.all([
      fetch(`${API}/api/v1/recipes/menu-items/${menuId}`, { credentials: "include" }),
      fetch(`${API}/api/v1/recipes/menu-items/${menuId}/modifier-groups`, { credentials: "include" }),
    ]);
    if (!recipeResponse.ok || !groupsResponse.ok) throw new Error("Unable to load the selected menu item.");
    setDetail(await recipeResponse.json());
    setGroups(await groupsResponse.json());
  }, []);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  useEffect(() => { void Promise.resolve().then(() => loadDetail(selected)).catch(cause => setError(cause instanceof Error ? cause.message : "Unable to load recipe details.")); }, [loadDetail, selected]);

  function setRecipeLine(index: number, changes: Partial<DraftIngredient>) {
    setRecipeLines(current => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...changes } : line));
  }
  function setModifierLine(index: number, changes: Partial<DraftModifier>) {
    setModifierLines(current => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...changes } : line));
  }

  async function createVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const body = {
        effective_from: effectiveFrom,
        ingredients: recipeLines.map(line => {
          const product = ingredients.find(item => item.id === line.productId);
          return { ingredient_product_id: line.productId, quantity: line.quantity, unit: product?.unit_of_measure || "" };
        }),
        modifier_ingredients: modifierLines.map(line => {
          const product = ingredients.find(item => item.id === line.productId);
          return { modifier_option_id: line.optionId, ingredient_product_id: line.productId, quantity: line.quantity, unit: product?.unit_of_measure || "" };
        }),
      };
      const response = await fetch(`${API}/api/v1/recipes/menu-items/${selected}/versions`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Unable to create recipe version.");
      setEffectiveFrom(""); setRecipeLines([emptyIngredient()]); setModifierLines([]);
      setNotice(`Recipe version ${result.version} created. Previous versions remain unchanged.`);
      await load(); await loadDetail(selected);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to create recipe version."); }
    finally { setSaving(false); }
  }

  async function createGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API}/api/v1/recipes/menu-items/${selected}/modifier-groups`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: groupName, selection_min: Number(selectionMin), selection_max: Number(selectionMax), options: optionNames.split(",").map(value => value.trim()).filter(Boolean) }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Unable to create modifier group.");
      setGroupName(""); setOptionNames(""); setNotice("Modifier group and options created."); await loadDetail(selected);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to create modifier group."); }
    finally { setSaving(false); }
  }

  async function addOption(groupId: string, name: string) {
    setSaving(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API}/api/v1/recipes/modifier-groups/${groupId}/options`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Unable to add modifier option.");
      setNotice("Modifier option added. Add its ingredient mapping in a new recipe version."); await loadDetail(selected);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to add modifier option."); }
    finally { setSaving(false); }
  }

  const allOptions = groups.flatMap(group => group.options.map(option => ({ ...option, groupName: group.name })));

  return <main className="min-h-screen bg-slate-50 px-5 py-8 text-slate-900 sm:px-8"><div className="mx-auto max-w-6xl">
    <Link href="/dashboard/products" className="text-sm font-semibold text-blue-700">← Menu &amp; ingredients</Link>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-blue-600">CAFÉ &amp; BAKERY</p><h1 className="mt-2 text-3xl font-bold">Recipes and modifiers</h1><p className="mt-2 text-sm text-slate-500">Build recipes from canonical ingredient units and keep each published version for historical sales.</p></div>{isOwner && <Link href="/dashboard/products" className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold">Manage menu items and ingredients</Link>}</div>
    {error && <p role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    {loading ? <p className="mt-7 rounded-xl border bg-white p-5 text-sm text-slate-500">Loading menu and recipe data…</p> : menus.length === 0 ? <section className="mt-7 rounded-2xl border bg-white p-8 text-center"><h2 className="font-semibold">No menu items yet</h2><p className="mt-2 text-sm text-slate-500">Classify a catalogue product as MENU_ITEM before creating recipes.</p><Link href="/dashboard/products" className="mt-4 inline-flex text-sm font-semibold text-blue-700">Open catalogue →</Link></section> : <>
      <section className="mt-7 rounded-2xl border border-slate-200 bg-white p-5"><label className="block max-w-xl text-xs font-semibold text-slate-600">Menu item<select value={selected} onChange={event => setSelected(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm">{menus.map(item => <option key={item.id} value={item.id}>{item.product_name} · {item.sku}{item.is_active ? "" : " · inactive"}</option>)}</select></label></section>
      {detail && <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
        <div className="space-y-5">
          {isOwner && <form onSubmit={createVersion} className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">Create recipe version</h2><p className="mt-1 text-xs text-slate-500">Versions are immutable. Changes take effect on the date you select.</p></div><span className="rounded-full bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">Next v{(detail.versions[0]?.version || 0) + 1}</span></div>
            <label className="mt-4 block max-w-xs text-xs font-medium text-slate-600">Effective from<input required type="date" value={effectiveFrom} onChange={event => setEffectiveFrom(event.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm" /></label>
            <div className="mt-5"><div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold">Base ingredients</h3><button type="button" onClick={() => setRecipeLines(lines => [...lines, emptyIngredient()])} className="text-xs font-semibold text-blue-700">+ Add ingredient</button></div>
              <div className="space-y-2">{recipeLines.map((line, index) => { const chosen = ingredients.find(item => item.id === line.productId); return <div key={`ingredient-${index}`} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_120px_100px_auto]"><select required value={line.productId} onChange={event => setRecipeLine(index, { productId: event.target.value })} className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"><option value="">Choose ingredient</option>{ingredients.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.product_name} · {item.sku}</option>)}</select><input required type="number" min="0.0001" step="0.0001" value={line.quantity} onChange={event => setRecipeLine(index, { quantity: event.target.value })} placeholder="Quantity" className="rounded-lg border border-slate-200 px-3 py-2 text-sm"/><span className="self-center text-xs text-slate-500">{chosen?.unit_of_measure || "unit"}</span>{recipeLines.length > 1 && <button type="button" aria-label="Remove ingredient" onClick={() => setRecipeLines(lines => lines.filter((_, lineIndex) => lineIndex !== index))} className="px-2 text-slate-400">Remove</button>}</div>; })}</div>
            </div>
            {allOptions.length > 0 && <div className="mt-5"><div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold">Modifier ingredients</h3><button type="button" onClick={() => setModifierLines(lines => [...lines, emptyModifier()])} className="text-xs font-semibold text-blue-700">+ Add modifier mapping</button></div><p className="mb-2 text-xs text-slate-500">Map only ingredients changed or added by an option. The selection is recorded with sales in a later workbook phase.</p><div className="space-y-2">{modifierLines.map((line, index) => { const chosen = ingredients.find(item => item.id === line.productId); return <div key={`modifier-${index}`} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_100px_80px]"><select required value={line.optionId} onChange={event => setModifierLine(index, { optionId: event.target.value })} className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"><option value="">Choose option</option>{allOptions.filter(item => item.is_active).map(option => <option key={option.id} value={option.id}>{option.groupName}: {option.name}</option>)}</select><select required value={line.productId} onChange={event => setModifierLine(index, { productId: event.target.value })} className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"><option value="">Choose ingredient</option>{ingredients.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.product_name}</option>)}</select><input required type="number" min="0.0001" step="0.0001" value={line.quantity} onChange={event => setModifierLine(index, { quantity: event.target.value })} placeholder="Quantity" className="rounded-lg border border-slate-200 px-3 py-2 text-sm"/><div className="flex items-center justify-between gap-2"><span className="text-xs text-slate-500">{chosen?.unit_of_measure || "unit"}</span><button type="button" aria-label="Remove modifier mapping" onClick={() => setModifierLines(lines => lines.filter((_, lineIndex) => lineIndex !== index))} className="text-xs text-slate-400">Remove</button></div></div>; })}</div></div>}
            <button disabled={saving || !isOwner} className="mt-5 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">{saving ? "Saving…" : "Publish new version"}</button>
          </form>}
          <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Recipe history · {detail.menu_item.product_name}</h2>{detail.versions.length === 0 ? <p className="mt-4 text-sm text-slate-500">No recipe versions have been recorded.</p> : <div className="mt-4 space-y-4">{detail.versions.map(version => <article key={version.id} className="rounded-xl border border-slate-100 bg-slate-50/70 p-4"><div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold">Version {version.version}</h3><span className="text-xs text-slate-500">Effective {version.effective_from}</span></div><ul className="mt-3 grid gap-x-5 gap-y-1 sm:grid-cols-2">{version.ingredients.map((line, index) => <li key={`${line.ingredient_product_id}-${index}`} className="flex justify-between gap-2 text-sm"><span className="truncate text-slate-600">{line.ingredient_name}</span><span className="shrink-0 font-medium">{line.quantity} {line.unit}</span></li>)}</ul>{version.modifier_ingredients.length > 0 && <div className="mt-3 border-t border-slate-200 pt-3"><p className="mb-2 text-xs font-semibold text-slate-500">Modifier ingredients</p><ul className="space-y-1">{version.modifier_ingredients.map((line, index) => <li key={`${line.modifier_option_id}-${line.ingredient_product_id}-${index}`} className="flex justify-between gap-2 text-sm"><span className="truncate text-slate-600">{line.modifier_group}: {line.modifier_option} · {line.ingredient_name}</span><span className="shrink-0 font-medium">{line.quantity} {line.unit}</span></li>)}</ul></div>}</article>)}</div>}</section>
        </div>
        <aside className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Modifier groups</h2><p className="mt-1 text-xs text-slate-500">Choices such as milk type, pasta sauce or seasoning.</p>{groups.length === 0 ? <p className="mt-4 text-sm text-slate-500">No modifier groups for this item.</p> : <div className="mt-4 space-y-3">{groups.map(group => <div key={group.id} className="rounded-xl bg-slate-50 p-3"><div className="flex justify-between gap-2"><p className="text-sm font-semibold">{group.name}</p><span className="text-[10px] text-slate-500">choose {group.selection_min}–{group.selection_max}</span></div><div className="mt-2 flex flex-wrap gap-1.5">{group.options.map(option => <span key={option.id} className="rounded-full bg-white px-2.5 py-1 text-xs text-slate-600">{option.name}</span>)}</div></div>)}</div>}
            {isOwner && <form onSubmit={createGroup} className="mt-5 space-y-3 border-t border-slate-100 pt-4"><h3 className="text-sm font-semibold">Add a modifier group</h3><input required value={groupName} onChange={event => setGroupName(event.target.value)} placeholder="Group name" className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm"/><input required value={optionNames} onChange={event => setOptionNames(event.target.value)} placeholder="Options separated by commas" className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm"/><div className="grid grid-cols-2 gap-2"><label className="text-[11px] text-slate-500">Minimum<select value={selectionMin} onChange={event => setSelectionMin(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm">{[0, 1, 2].map(value => <option key={value}>{value}</option>)}</select></label><label className="text-[11px] text-slate-500">Maximum<select value={selectionMax} onChange={event => setSelectionMax(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm">{[1, 2, 3, 4].map(value => <option key={value}>{value}</option>)}</select></label></div><button disabled={saving} className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700">Add modifier group</button></form>}
          </section>
          {isOwner && groups.length > 0 && <AddOption groups={groups} saving={saving} onAdd={addOption} />}
        </aside>
      </div>}
    </>}
  </div></main>;
}

function AddOption({ groups, saving, onAdd }: { groups: ModifierGroup[]; saving: boolean; onAdd: (groupId: string, name: string) => Promise<void> }) {
  const [groupId, setGroupId] = useState(groups[0]?.id || "");
  const [name, setName] = useState("");
  const selectedGroup = groups.some(group => group.id === groupId) ? groupId : groups[0]?.id || "";
  return <form onSubmit={event => { event.preventDefault(); if (!name.trim()) return; void onAdd(selectedGroup, name.trim()).then(() => setName("")); }} className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Add option</h2><label className="mt-3 block text-xs text-slate-500">Group<select value={selectedGroup} onChange={event => setGroupId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm">{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><input required value={name} onChange={event => setName(event.target.value)} placeholder="Option name" className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm"/><button disabled={saving} className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700">Add option</button></form>;
}
