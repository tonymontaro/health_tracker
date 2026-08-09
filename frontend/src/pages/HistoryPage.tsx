import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { DailyFoodLog, EntryStatus } from "../api/types";
import { StatusPill } from "../components/StatusPill";

type HistorySummary = { date: string; summary: string; source: string };
type HistoryDay = { date: string; original_plan: Record<string, unknown> | null; current_plan: Record<string, unknown> | null; nutrition: EntryStatus[]; workouts: EntryStatus[]; profile_snapshot: { short_summary: string } | null; food_log: DailyFoodLog | null };

export function HistoryPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const history = useQuery({ queryKey: ["history"], queryFn: () => api<HistorySummary[]>("/history") });
  const day = useQuery({ queryKey: ["history", selected], queryFn: () => api<HistoryDay>(`/history/${selected}`), enabled: Boolean(selected) });
  const patch = useMutation({
    mutationFn: ({ type, id, payload }: { type: "nutrition" | "workout"; id: string; payload: Record<string, unknown> }) => api(`/history/${selected}/${type}/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["history", selected] }),
  });
  function recordWorkout(entry: EntryStatus) {
    const actual = window.prompt(`What did you actually do for ${entry.exercise_name ?? "this exercise"}?`, entry.actual?.summary as string | undefined ?? "");
    if (!actual?.trim()) return;
    const difficultyText = window.prompt("How difficult was it from 1 to 10?", String(entry.difficulty_1_to_10 ?? 5));
    if (difficultyText === null) return;
    const difficulty = Number(difficultyText);
    if (!Number.isInteger(difficulty) || difficulty < 1 || difficulty > 10) {
      window.alert("Difficulty must be a whole number from 1 to 10.");
      return;
    }
    patch.mutate({ type: "workout", id: entry.id, payload: { status: "completed", actual: { summary: actual.trim() }, difficulty_1_to_10: difficulty } });
  }
  return (
    <><header className="page-header"><div><p className="eyebrow">Planned versus actual</p><h1>History</h1></div></header>
      <div className="history-layout"><aside className="history-list card">{history.data?.map((item) => <button className={selected === item.date ? "selected" : ""} key={item.date} onClick={() => setSelected(item.date)}><strong>{new Date(`${item.date}T12:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" })}</strong><small>{item.summary}</small></button>)}{history.data?.length === 0 && <p>No plans yet.</p>}</aside>
        <section className="history-detail">{!selected && <div className="empty-state">Choose a day to inspect its original plan and actual results.</div>}{day.data && <><section className="card"><p className="eyebrow">Profile at recommendation time</p><p>{day.data.profile_snapshot?.short_summary}</p></section>{day.data.food_log && <section className="card"><p className="eyebrow">Food diary text</p><p>{day.data.food_log.raw_text}</p><small>{day.data.food_log.extraction.summary}</small></section>}<section className="card"><p className="eyebrow">Nutrition</p>{day.data.nutrition.map((entry) => <div className="history-entry" key={entry.id}><div><strong>{entry.description}</strong><StatusPill status={entry.status} /></div>{!(["matched_by_food_log", "discarded_by_food_log"].includes(entry.status)) && <div className="actions"><button className="quiet small" onClick={() => patch.mutate({ type: "nutrition", id: entry.id, payload: { status: "confirmed" } })}>Confirm</button><button className="quiet small" onClick={() => patch.mutate({ type: "nutrition", id: entry.id, payload: { status: "skipped" } })}>Mark skipped</button></div>}</div>)}</section><section className="card"><p className="eyebrow">Training</p>{day.data.workouts.length === 0 && <p>Rest day.</p>}{day.data.workouts.map((entry) => <div className="history-entry" key={entry.id}><div><strong>{entry.exercise_name ?? "Exercise"}</strong><StatusPill status={entry.status} />{entry.actual?.summary !== undefined && <small>{String(entry.actual.summary)}</small>}</div><div className="actions"><button className="quiet small" onClick={() => recordWorkout(entry)}>Record actual</button><button className="quiet small" onClick={() => patch.mutate({ type: "workout", id: entry.id, payload: { status: "skipped" } })}>Mark skipped</button></div></div>)}</section><details className="card"><summary>Original recommendation</summary><pre>{JSON.stringify(day.data.original_plan, null, 2)}</pre></details></>}</section>
      </div>{patch.error && <p className="error">{patch.error.message}</p>}</>
  );
}
