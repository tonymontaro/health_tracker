import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfirmDialog } from "../components/field-notes/ConfirmDialog";

type ShoppingUnit = "g" | "kg" | "ml" | "item";
type InventoryUnit = "g" | "ml" | "item" | "portion" | "container";
type InventoryLocation = "fridge" | "freezer" | "pantry" | "counter" | "multiple";

type ShoppingItem = {
  food_name: string;
  quantity: number;
  unit: ShoppingUnit;
  quantity_label: string;
  estimated_chf: number;
  purchase_mode: string;
  suggested_day: string;
};

type Shopping = {
  id: string;
  week_start: string;
  retailer: string;
  mode: string;
  estimated_total_chf: number;
  online_total_chf: number;
  online_minimum_chf: number;
  online_minimum_met: boolean;
  status: string;
  items: ShoppingItem[];
};

type InventoryItem = {
  id: string;
  name: string;
  catalog_item: boolean;
  item_type: "ingredient" | "prepared_meal";
  quantity_estimate: number | null;
  quantity_label: string | null;
  unit: InventoryUnit;
  confidence: string;
  expires_on: string | null;
  location: InventoryLocation;
  notes: string | null;
  source: string;
};

type InventoryTextResponse = {
  raw_text: string;
  extraction: { summary: string; assumptions: string[] };
  inventory_items: InventoryItem[];
};

function shoppingResearchPrompt(plan: Shopping): string {
  const items = plan.items.map((item, index) => [
    `${index + 1}. ${item.food_name}`,
    `   - Needed: ${item.quantity_label}`,
    `   - Purchase mode: ${item.purchase_mode.replaceAll("_", " ")}`,
    `   - Suggested purchase day: ${item.suggested_day}`,
    `   - Estimated budget: CHF ${item.estimated_chf.toFixed(2)}`,
  ].join("\n")).join("\n");

  return `Please browse the web and turn the shopping list below into specific products I can buy in Switzerland.

Preferred retailer: ${plan.retailer}
Week starting: ${plan.week_start}
Estimated basket budget: CHF ${plan.estimated_total_chf.toFixed(2)}

Search the preferred retailer's current Swiss online store first. For every listed item:
- Find a suitable individual product and link directly to its product page, not a search-results page.
- Give the product and brand name, pack size, number of packs to buy, current price in CHF, and estimated subtotal.
- Briefly explain why it matches the requested food and quantity.
- If the exact item is unavailable, select a close nutritional and practical equivalent, clearly label it as a substitute, and explain the difference.
- Respect the requested purchase mode and suggested purchase day where possible.
- Do not invent products, prices, availability, or links. Mark anything you cannot verify.
- Do not omit any item.

Return one concise Markdown table with these columns: Requested item, Recommended product, Pack size, Quantity to buy, Price, Subtotal, Purchase timing, Direct link, Notes. Then give the estimated basket total and call out any unverified items or availability that depends on postcode.

Shopping list:
${items}`;
}

function ShoppingItemEditor({ planId, index, item, disabled }: { planId: string; index: number; item: ShoppingItem; disabled: boolean }) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [unit, setUnit] = useState<ShoppingUnit>(item.unit);
  const [confirmRemove, setConfirmRemove] = useState(false);
  useEffect(() => {
    setQuantity(String(item.quantity));
    setUnit(item.unit);
  }, [item.quantity, item.unit]);
  const save = useMutation({
    mutationFn: () => api<Shopping>(`/shopping/${planId}/items/${index}`, {
      method: "PATCH",
      body: JSON.stringify({ quantity: Number(quantity), unit }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["shopping"] }),
  });
  const remove = useMutation({
    mutationFn: () => api(`/shopping/${planId}/items/${index}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["shopping"] }),
  });
  const changed = Number(quantity) !== item.quantity || unit !== item.unit;
  const invalidQuantity = !Number.isFinite(Number(quantity)) || Number(quantity) <= 0;
  return <div className="shopping-editor">
    <div className="shopping-editor-heading"><div><strong>{item.food_name}</strong><small>{item.suggested_day} · {item.purchase_mode.replaceAll("_", " ")} · CHF {item.estimated_chf.toFixed(2)}</small></div><button className="text-button danger" type="button" disabled={disabled || remove.isPending} onClick={() => { remove.reset(); setConfirmRemove(true); }}>Remove</button></div>
    <div className="quantity-editor"><label>Quantity<input type="number" min="0.01" step="any" value={quantity} disabled={disabled} onChange={(event) => setQuantity(event.target.value)} /></label><label>Unit<select value={unit} disabled={disabled} onChange={(event) => setUnit(event.target.value as ShoppingUnit)}><option value="g">g</option><option value="kg">kg</option><option value="ml">ml</option><option value="item">items</option></select></label><button className="quiet small" type="button" disabled={disabled || save.isPending || !changed || invalidQuantity} onClick={() => save.mutate()}>{save.isPending ? "Saving..." : "Save"}</button></div>
    {(save.error || remove.error) && <p className="error">{save.error?.message ?? remove.error?.message}</p>}
    <ConfirmDialog open={confirmRemove} title={`Remove ${item.food_name}?`} description="This removes the item from the current shopping list. It does not change inventory." confirmLabel="Remove item" pending={remove.isPending} error={remove.error?.message} onCancel={() => setConfirmRemove(false)} onConfirm={() => remove.mutate(undefined, { onSuccess: () => setConfirmRemove(false) })} />
  </div>;
}

function InventoryEditor({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(item.name);
  const [quantity, setQuantity] = useState(item.quantity_estimate === null ? "" : String(item.quantity_estimate));
  const [unit, setUnit] = useState<InventoryUnit>(item.unit);
  const [location, setLocation] = useState<InventoryLocation>(item.location);
  const [expiresOn, setExpiresOn] = useState(item.expires_on ?? "");
  const [notes, setNotes] = useState(item.notes ?? "");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const invalidQuantity = quantity !== "" && (!Number.isFinite(Number(quantity)) || Number(quantity) < 0);
  useEffect(() => {
    setName(item.name);
    setQuantity(item.quantity_estimate === null ? "" : String(item.quantity_estimate));
    setUnit(item.unit);
    setLocation(item.location);
    setExpiresOn(item.expires_on ?? "");
    setNotes(item.notes ?? "");
  }, [item]);
  const save = useMutation({
    mutationFn: () => api<InventoryItem>(`/inventory/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        ...(!item.catalog_item ? { name } : {}),
        quantity_estimate: quantity === "" ? null : Number(quantity),
        unit,
        location,
        expires_on: expiresOn || null,
        notes: notes || null,
      }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inventory"] }),
  });
  const remove = useMutation({
    mutationFn: () => api(`/inventory/${item.id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inventory"] }),
  });
  return <article className="inventory-editor">
    <div className="inventory-editor-heading"><div>{item.catalog_item ? <strong>{item.name}</strong> : <label>Name<input value={name} maxLength={160} onChange={(event) => setName(event.target.value)} /></label>}<div className="inventory-badges"><span className="status">{item.item_type.replaceAll("_", " ")}</span><span className={`confidence confidence-${item.confidence}`}>{item.confidence}</span></div></div><button className="text-button danger" type="button" disabled={remove.isPending} onClick={() => { remove.reset(); setConfirmRemove(true); }}>Delete</button></div>
    <div className="inventory-fields"><label>Quantity<input type="number" min="0" step="any" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label><label>Unit<select value={unit} onChange={(event) => setUnit(event.target.value as InventoryUnit)}><option value="g">g</option><option value="ml">ml</option><option value="item">items</option><option value="portion">portions</option><option value="container">containers</option></select></label><label>Stored in<select value={location} onChange={(event) => setLocation(event.target.value as InventoryLocation)}><option value="fridge">Fridge</option><option value="freezer">Freezer</option><option value="pantry">Pantry</option><option value="counter">Counter</option><option value="multiple">Multiple places</option></select></label><label>Use by<input type="date" value={expiresOn} onChange={(event) => setExpiresOn(event.target.value)} /></label></div>
    <label>Notes<input value={notes} maxLength={2000} placeholder="Optional storage or preparation details" onChange={(event) => setNotes(event.target.value)} /></label>
    <div className="inventory-editor-actions"><small>Added via {item.source.replaceAll("_", " ")}</small><button className="quiet small" type="button" disabled={save.isPending || (!item.catalog_item && !name.trim()) || invalidQuantity} onClick={() => save.mutate()}>{save.isPending ? "Saving..." : "Save changes"}</button></div>
    {(save.error || remove.error) && <p className="error">{save.error?.message ?? remove.error?.message}</p>}
    <ConfirmDialog open={confirmRemove} title={`Delete ${item.name}?`} description="This permanently removes the entry from inventory." confirmLabel="Delete entry" pending={remove.isPending} error={remove.error?.message} onCancel={() => setConfirmRemove(false)} onConfirm={() => remove.mutate(undefined, { onSuccess: () => setConfirmRemove(false) })} />
  </article>;
}

export function InventoryPage() {
  const queryClient = useQueryClient();
  const [retailer, setRetailer] = useState<"Coop" | "Migros">("Coop");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "error">("idle");
  const [inventoryText, setInventoryText] = useState("");
  const [addResult, setAddResult] = useState("");
  const [purchaseResult, setPurchaseResult] = useState("");
  const plan = useQuery({ queryKey: ["shopping", retailer], queryFn: () => api<Shopping>(`/shopping/current?retailer=${retailer}`) });
  const inventory = useQuery({ queryKey: ["inventory"], queryFn: () => api<InventoryItem[]>("/inventory") });
  const purchased = useMutation({
    mutationFn: () => api<{ status: string; inventory_items_updated: number }>(`/shopping/${plan.data?.id}/mark-purchased`, { method: "POST" }),
    onSuccess: async (result) => {
      setPurchaseResult(`${result.inventory_items_updated} shopping item${result.inventory_items_updated === 1 ? "" : "s"} added to inventory.`);
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["shopping"] }), queryClient.invalidateQueries({ queryKey: ["inventory"] })]);
    },
  });
  const addFromText = useMutation({
    mutationFn: () => api<InventoryTextResponse>("/inventory/from-text", { method: "POST", body: JSON.stringify({ text: inventoryText }) }),
    onSuccess: async (result) => {
      setAddResult(result.extraction.summary);
      setInventoryText("");
      await queryClient.invalidateQueries({ queryKey: ["inventory"] });
    },
  });
  function submitInventoryText(event: FormEvent) {
    event.preventDefault();
    setAddResult("");
    addFromText.mutate();
  }
  async function copyPrompt() {
    if (!plan.data) return;
    try {
      await navigator.clipboard.writeText(shoppingResearchPrompt(plan.data));
      setCopyStatus("copied");
    } catch {
      setCopyStatus("error");
    }
  }
  return <>
    <header className="page-header"><div><p className="eyebrow">Inventory / Provisions</p><h1>Inventory</h1></div><p className="page-deck">Keep the kitchen record accurate, then review the next shopping list before it becomes inventory.</p></header>
    <section className="card inventory-add-card"><div><p className="eyebrow">Add with AI</p><h2>Describe what you have</h2><p>Include ingredients, leftovers, or complete prepared meals. Quantities and storage details can be conversational.</p></div><form onSubmit={submitInventoryText}><label>Items to add<textarea value={inventoryText} maxLength={5000} onChange={(event) => setInventoryText(event.target.value)} placeholder="For example: Add one whole pizza to the freezer, two containers of Nigerian okra soup in the fridge, and about 600 g of tomatoes." /></label><div className="food-log-submit"><small>The AI parses only this text and the food catalog, then creates validated inventory entries.</small><button className="primary" disabled={addFromText.isPending || !inventoryText.trim()}>{addFromText.isPending ? "Parsing..." : "Parse and add"}</button></div></form>{addResult && <p className="success standalone" role="status">{addResult}</p>}{addFromText.error && <p className="error" role="alert">{addFromText.error.message}</p>}</section>
    <section className="inventory-section"><div className="section-heading"><div><p className="eyebrow">Fridge, freezer, pantry, and counter</p><h2>Current inventory</h2></div><span>{inventory.data?.length ?? 0} entries</span></div>{inventory.isLoading && <div className="card" role="status">Loading inventory...</div>}{inventory.error && <p className="error" role="alert">{inventory.error.message}</p>}{inventory.data?.length === 0 && <div className="card empty-inventory"><p>No inventory entries yet.</p><small>Add items above or mark a shopping list purchased below.</small></div>}<div className="inventory-list">{inventory.data?.map((item) => <InventoryEditor item={item} key={item.id} />)}</div></section>
    <section className="shopping-section"><div className="section-heading"><div><p className="eyebrow">Weekly recommendations</p><h2>Shopping list</h2></div><label>Retailer<select value={retailer} onChange={(event) => { setRetailer(event.target.value as "Coop" | "Migros"); setCopyStatus("idle"); }}><option>Coop</option><option>Migros</option></select></label></div>
      {plan.isLoading && <div className="card" role="status">Preparing this week's list...</div>}
      {plan.error && <p className="error" role="alert">{plan.error.message}</p>}
      {!plan.isLoading && !plan.error && !plan.data && <div className="card empty-inventory">No shopping plan is available.</div>}
      {plan.data && <><section className="shopping-summary"><div><span>Retailer</span><strong>{plan.data.retailer}</strong></div><div><span>Estimated basket</span><strong>CHF {plan.data.estimated_total_chf.toFixed(0)}</strong></div><div><span>Online minimum</span><strong>{plan.data.online_minimum_met ? "Met" : `Not met · CHF ${plan.data.online_minimum_chf}`}</strong></div></section>
        <section className="card"><div className="card-heading shopping-list-heading"><div><p className="eyebrow">Review before purchase</p><small>{plan.data.status === "purchased" ? "This list has already been added to inventory." : "Change quantities or remove anything you did not buy before marking the list purchased."}</small></div><button className="quiet small" type="button" onClick={copyPrompt}>{copyStatus === "copied" ? "Prompt copied" : "Copy AI search prompt"}</button></div>{copyStatus === "copied" && <p className="success copy-feedback" role="status">Ready to paste into an AI chatbot.</p>}{copyStatus === "error" && <p className="error copy-feedback" role="alert">Clipboard access failed. Please try again.</p>}<div className="shopping-edit-list">{plan.data.items.map((item, index) => <ShoppingItemEditor planId={plan.data.id} index={index} item={item} disabled={plan.data.status === "purchased"} key={item.food_name} />)}</div>{plan.data.items.length === 0 && <p>No items remain on this shopping list.</p>}<div className="purchase-actions"><div>{purchaseResult && <p className="success" role="status">{purchaseResult}</p>}{purchased.error && <p className="error">{purchased.error.message}</p>}</div><button className="primary" disabled={plan.data.status === "purchased" || purchased.isPending} onClick={() => purchased.mutate()}>{plan.data.status === "purchased" ? "Purchased and added" : purchased.isPending ? "Adding to inventory..." : "Mark purchased and add to inventory"}</button></div></section></>}
    </section>
  </>;
}
