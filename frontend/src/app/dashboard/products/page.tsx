"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
type ProductKind = "MENU_ITEM" | "INGREDIENT" | "LEGACY";
type Product = { id: string; sku: string; product_name: string; brand: string | null; unit_of_measure: string; category_id: string | null; is_active: boolean; product_kind: ProductKind };
type Category = { id: string; name: string };

export default function ProductsPage() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [search, setSearch] = useState("");
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [unit, setUnit] = useState("EA");
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [productKind, setProductKind] = useState<ProductKind>("LEGACY");
  const [categoryName, setCategoryName] = useState("");
  const [editingId, setEditingId] = useState("");
  const [isOwner, setIsOwner] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [profile, productResponse, categoryResponse] = await Promise.all([
        fetch(`${API_URL}/api/v1/auth/me`, { credentials: "include" }),
        fetch(`${API_URL}/api/v1/products?include_inactive=true`, { credentials: "include" }),
        fetch(`${API_URL}/api/v1/products/categories`, { credentials: "include" }),
      ]);
      if (profile.status === 401) { router.replace("/login"); return; }
      if (!profile.ok || !productResponse.ok || !categoryResponse.ok) throw new Error("Unable to load the product catalogue.");
      const user = await profile.json();
      if (user.must_change_password) { router.replace("/change-password"); return; }
      setIsOwner(user.role === "OWNER");
      setProducts(await productResponse.json());
      setCategories(await categoryResponse.json());
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load the catalogue."); }
    finally { setLoading(false); }
  }, [router]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  async function createProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setSuccess("");
    try {
      const response = await fetch(`${API_URL}/api/v1/products${editingId ? `/${editingId}` : ""}`, {
        method: editingId ? "PATCH" : "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sku, product_name: name, unit_of_measure: unit, brand: brand || null, category_id: category || null, product_kind: productKind }),
      });
      const result = await response.json();
      if (response.status === 409) throw new Error(typeof result.detail === "string" ? result.detail : "That SKU already exists in this company.");
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Unable to add this product. Check the required fields.");
      setName(""); setSku(""); setBrand(""); setCategory(""); setProductKind("LEGACY"); setEditingId(""); setSuccess(editingId ? "Product updated." : "Product added to the company catalogue."); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to save product."); }
    finally { setSaving(false); }
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setSuccess("");
    const response = await fetch(`${API_URL}/api/v1/products/categories`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: categoryName }) });
    if (response.status === 409) { setError("That category already exists."); return; }
    if (!response.ok) { setError("Unable to add category."); return; }
    setCategoryName(""); setSuccess("Category added."); await load();
  }

  async function toggleActive(product: Product) {
    const response = await fetch(`${API_URL}/api/v1/products/${product.id}`, { method: "PATCH", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !product.is_active }) });
    if (!response.ok) { setError("Unable to update product status."); return; }
    await load();
  }

  function editProduct(product: Product) {
    setEditingId(product.id); setName(product.product_name); setSku(product.sku);
    setBrand(product.brand || ""); setUnit(product.unit_of_measure);
    setCategory(product.category_id || ""); setProductKind(product.product_kind || "LEGACY"); setError(""); setSuccess("");
  }

  const visibleProducts = products.filter((p) => `${p.sku} ${p.product_name} ${p.brand || ""}`.toLowerCase().includes(search.toLowerCase()));

  return <main className="min-h-screen bg-slate-50 px-5 py-8 sm:px-8">
    <div className="mx-auto max-w-6xl">
      <a href="/dashboard" className="text-sm font-semibold text-blue-700">← Dashboard</a>
      <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-xs font-bold uppercase tracking-widest text-blue-600">CATALOGUE</p><h1 className="mt-2 text-3xl font-bold text-slate-900">Menu &amp; ingredients</h1><p className="mt-2 text-sm text-slate-500">Classify each catalogue item as a menu item, ingredient or legacy product.</p>{isOwner && <a href="/dashboard/recipes" className="mt-3 inline-flex text-sm font-semibold text-blue-700">Manage recipes and modifiers →</a>}</div>
        <input aria-label="Search products" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search SKU, name or brand" className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm sm:w-80" />
      </div>
      {error && <p role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {success && <p role="status" className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{success}</p>}
      <div className="mt-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-5 py-4"><h2 className="font-semibold text-slate-900">Company products</h2><p className="mt-1 text-xs text-slate-500">{visibleProducts.length} products</p></div>
          {loading ? <p className="p-6 text-sm text-slate-500">Loading catalogue…</p> : visibleProducts.length === 0 ? <p className="p-8 text-center text-sm text-slate-500">No products match this search.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[700px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-5 py-3">Product</th><th className="px-5 py-3">SKU</th><th className="px-5 py-3">Kind</th><th className="px-5 py-3">Brand</th><th className="px-5 py-3">Unit</th><th className="px-5 py-3">Status</th>{isOwner && <th className="px-5 py-3">Action</th>}</tr></thead><tbody className="divide-y divide-slate-100">{visibleProducts.map((p) => <tr key={p.id}><td className="px-5 py-4 font-medium text-slate-900">{p.product_name}</td><td className="px-5 py-4 font-mono text-xs text-slate-600">{p.sku}</td><td className="px-5 py-4 text-xs text-slate-600">{p.product_kind.replace("_", " ")}</td><td className="px-5 py-4 text-slate-600">{p.brand || "—"}</td><td className="px-5 py-4 text-slate-600">{p.unit_of_measure}</td><td className="px-5 py-4"><span className={`rounded-full px-2.5 py-1 text-xs ${p.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{p.is_active ? "Active" : "Inactive"}</span></td>{isOwner && <td className="space-x-3 px-5 py-4"><button onClick={() => editProduct(p)} className="text-xs font-semibold text-blue-700">Edit / classify</button><button onClick={() => void toggleActive(p)} className="text-xs font-semibold text-slate-500">{p.is_active ? "Deactivate" : "Activate"}</button></td>}</tr>)}</tbody></table></div>}
        </section>
        {isOwner && <aside className="space-y-5">
          <form onSubmit={createProduct} className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-slate-900">{editingId ? "Edit product" : "Add a product"}</h2><div className="mt-4 space-y-3">{[["Product name", name, setName], ["SKU", sku, setSku], ["Brand (optional)", brand, setBrand], ["Canonical unit (e.g. pcs, g, ml)", unit, setUnit]].map(([label, value, setter]) => <label key={label as string} className="block text-xs font-medium text-slate-600">{label as string}<input required={label !== "Brand (optional)"} value={value as string} onChange={(e) => (setter as (v: string) => void)(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm" /></label>)}<label className="block text-xs font-medium text-slate-600">Kind<select required value={productKind} onChange={(e) => setProductKind(e.target.value as ProductKind)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm"><option value="MENU_ITEM">Menu item</option><option value="INGREDIENT">Ingredient</option><option value="LEGACY">Legacy / unspecified</option></select></label><label className="block text-xs font-medium text-slate-600">Category<select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm"><option value="">No category</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label></div><button disabled={saving} className="mt-4 w-full rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-60">{saving ? "Saving…" : editingId ? "Save changes" : "Add product"}</button>{editingId && <button type="button" onClick={() => { setEditingId(""); setName(""); setSku(""); setBrand(""); setCategory(""); setProductKind("LEGACY"); }} className="mt-2 w-full rounded-lg px-4 py-2 text-sm font-medium text-slate-500">Cancel</button>}</form>
          <form onSubmit={addCategory} className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-slate-900">Categories</h2><div className="mt-3 flex gap-2"><input aria-label="New category" required value={categoryName} onChange={(e) => setCategoryName(e.target.value)} placeholder="e.g. Beverages" className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"/><button className="rounded-lg border border-slate-200 px-3 text-sm font-semibold text-slate-700">Add</button></div><div className="mt-3 flex flex-wrap gap-2">{categories.map((c) => <span key={c.id} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">{c.name}</span>)}</div></form>
        </aside>}
      </div>
    </div>
  </main>;
}
