import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

type Shopping = { id: string; week_start: string; retailer: string; mode: string; estimated_total_chf: number; online_total_chf: number; online_minimum_chf: number; online_minimum_met: boolean; status: string; items: Array<{ food_name: string; quantity_label: string; estimated_chf: number; purchase_mode: string; suggested_day: string }> };
type Inventory = { id: string; food: string; quantity_estimate: number | null; quantity_label: string | null; unit: string; confidence: string; expires_on: string | null; location: string };

export function ShoppingPage() {
  const queryClient = useQueryClient();
  const [retailer, setRetailer] = useState<"Coop" | "Migros">("Coop");
  const plan = useQuery({ queryKey: ["shopping", retailer], queryFn: () => api<Shopping>(`/shopping/current?retailer=${retailer}`) });
  const inventory = useQuery({ queryKey: ["inventory"], queryFn: () => api<Inventory[]>("/inventory") });
  const purchased = useMutation({ mutationFn: () => api(`/shopping/${plan.data?.id}/mark-purchased`, { method: "POST" }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["shopping"] }); queryClient.invalidateQueries({ queryKey: ["inventory"] }); } });
  if (!plan.data) return <div className="loading">Preparing this week's list...</div>;
  return <><header className="page-header"><div><p className="eyebrow">Low-friction restocking</p><h1>Shopping</h1></div><div className="actions"><label>Retailer<select value={retailer} onChange={(event) => setRetailer(event.target.value as "Coop" | "Migros")}><option>Coop</option><option>Migros</option></select></label><button className="primary" disabled={plan.data.status === "purchased"} onClick={() => purchased.mutate()}>{plan.data.status === "purchased" ? "Purchased" : "Mark purchased"}</button></div></header>
    <section className="shopping-summary"><div><span>Retailer</span><strong>{plan.data.retailer}</strong></div><div><span>Estimated basket</span><strong>CHF {plan.data.estimated_total_chf.toFixed(0)}</strong></div><div><span>Online minimum</span><strong>{plan.data.online_minimum_met ? "Met" : `Not met · CHF ${plan.data.online_minimum_chf}`}</strong></div></section>
    <div className="shopping-grid"><section className="card"><p className="eyebrow">This week's list</p>{plan.data.items.map((item) => <div className="shopping-item" key={item.food_name}><div><strong>{item.food_name}</strong><small>{item.quantity_label} · {item.suggested_day}</small></div><span>{item.purchase_mode.replace("_", " ")} · CHF {item.estimated_chf}</span></div>)}</section><section className="card"><p className="eyebrow">Approximate inventory</p>{inventory.data?.length === 0 && <p>Mark a shopping plan purchased to initialize inventory.</p>}{inventory.data?.map((item) => <div className="shopping-item" key={item.id}><div><strong>{item.food}</strong><small>{item.quantity_label ?? `${item.quantity_estimate ?? "?"} ${item.unit}`} · {item.location}</small></div><span className={`confidence confidence-${item.confidence}`}>{item.confidence}</span></div>)}</section></div>
  </>;
}
