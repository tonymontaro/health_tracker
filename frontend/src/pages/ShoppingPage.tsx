import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

type Shopping = { id: string; week_start: string; retailer: string; mode: string; estimated_total_chf: number; online_total_chf: number; online_minimum_chf: number; online_minimum_met: boolean; status: string; items: Array<{ food_name: string; quantity_label: string; estimated_chf: number; purchase_mode: string; suggested_day: string }> };
type Inventory = { id: string; food: string; quantity_estimate: number | null; quantity_label: string | null; unit: string; confidence: string; expires_on: string | null; location: string };

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

export function ShoppingPage() {
  const queryClient = useQueryClient();
  const [retailer, setRetailer] = useState<"Coop" | "Migros">("Coop");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "error">("idle");
  const plan = useQuery({ queryKey: ["shopping", retailer], queryFn: () => api<Shopping>(`/shopping/current?retailer=${retailer}`) });
  const inventory = useQuery({ queryKey: ["inventory"], queryFn: () => api<Inventory[]>("/inventory") });
  const purchased = useMutation({ mutationFn: () => api(`/shopping/${plan.data?.id}/mark-purchased`, { method: "POST" }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["shopping"] }); queryClient.invalidateQueries({ queryKey: ["inventory"] }); } });
  async function copyPrompt() {
    if (!plan.data) return;
    try {
      await navigator.clipboard.writeText(shoppingResearchPrompt(plan.data));
      setCopyStatus("copied");
    } catch {
      setCopyStatus("error");
    }
  }
  if (!plan.data) return <div className="loading">Preparing this week's list...</div>;
  return <><header className="page-header"><div><p className="eyebrow">Low-friction restocking</p><h1>Shopping</h1></div><div className="actions"><label>Retailer<select value={retailer} onChange={(event) => { setRetailer(event.target.value as "Coop" | "Migros"); setCopyStatus("idle"); }}><option>Coop</option><option>Migros</option></select></label><button className="primary" disabled={plan.data.status === "purchased"} onClick={() => purchased.mutate()}>{plan.data.status === "purchased" ? "Purchased" : "Mark purchased"}</button></div></header>
    <section className="shopping-summary"><div><span>Retailer</span><strong>{plan.data.retailer}</strong></div><div><span>Estimated basket</span><strong>CHF {plan.data.estimated_total_chf.toFixed(0)}</strong></div><div><span>Online minimum</span><strong>{plan.data.online_minimum_met ? "Met" : `Not met · CHF ${plan.data.online_minimum_chf}`}</strong></div></section>
    <div className="shopping-grid"><section className="card"><div className="card-heading shopping-list-heading"><p className="eyebrow">This week's list</p><button className="quiet small" type="button" onClick={copyPrompt}>{copyStatus === "copied" ? "Prompt copied" : "Copy AI search prompt"}</button></div>{copyStatus === "copied" && <p className="success copy-feedback" role="status">Ready to paste into an AI chatbot.</p>}{copyStatus === "error" && <p className="error copy-feedback" role="alert">Clipboard access failed. Please try again.</p>}{plan.data.items.map((item) => <div className="shopping-item" key={item.food_name}><div><strong>{item.food_name}</strong><small>{item.quantity_label} · {item.suggested_day}</small></div><span>{item.purchase_mode.replace("_", " ")} · CHF {item.estimated_chf}</span></div>)}</section><section className="card"><p className="eyebrow">Approximate inventory</p>{inventory.data?.length === 0 && <p>Mark a shopping plan purchased to initialize inventory.</p>}{inventory.data?.map((item) => <div className="shopping-item" key={item.id}><div><strong>{item.food}</strong><small>{item.quantity_label ?? `${item.quantity_estimate ?? "?"} ${item.unit}`} · {item.location}</small></div><span className={`confidence confidence-${item.confidence}`}>{item.confidence}</span></div>)}</section></div>
  </>;
}
