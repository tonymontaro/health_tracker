import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import type { DailyFoodLog, DailyWorkoutLog, EntryStatus } from "../api/types";
import { StatusPill } from "../components/StatusPill";

type HistorySection = "nutrition" | "exercise";

type HistorySummary = {
  date: string;
  summary: string;
  source: string;
  nutrition_count: number;
  workout_count: number;
  strava_activity_count: number;
  has_food_log: boolean;
  has_workout_log: boolean;
};

type HistoryDay = {
  date: string;
  original_plan: Record<string, unknown> | null;
  current_plan: Record<string, unknown> | null;
  nutrition: EntryStatus[];
  workouts: EntryStatus[];
  profile_snapshot: { short_summary: string } | null;
  food_log: DailyFoodLog | null;
  workout_log: DailyWorkoutLog | null;
};

function workoutActualText(actual?: Record<string, unknown> | null): string {
  if (!actual) return "";
  if (typeof actual.summary === "string") return actual.summary;
  const parts: string[] = [];
  if (typeof actual.distance_km === "number") parts.push(`${actual.distance_km.toFixed(2)} km`);
  if (typeof actual.duration_seconds === "number") parts.push(`${Math.round(actual.duration_seconds / 60)} min`);
  if (typeof actual.elevation_gain_m === "number") parts.push(`${Math.round(actual.elevation_gain_m)} m elevation`);
  if (typeof actual.load_kg === "number") parts.push(`${actual.load_kg} kg`);
  if (Array.isArray(actual.reps_per_set)) parts.push(`${actual.reps_per_set.join(" / ")} reps`);
  if (typeof actual.average_power_watts === "number") parts.push(`${Math.round(actual.average_power_watts)} W avg`);
  if (typeof actual.average_heartrate_bpm === "number") parts.push(`${Math.round(actual.average_heartrate_bpm)} bpm avg`);
  if (typeof actual.device_name === "string") parts.push(actual.device_name);
  return parts.join(" · ");
}

function stravaActivityId(entry: EntryStatus): number | null {
  const strava = entry.actual?.strava;
  if (!strava || typeof strava !== "object" || !("activity_id" in strava)) return null;
  return typeof strava.activity_id === "number" ? strava.activity_id : null;
}

function sourceLabel(entry: EntryStatus): string {
  if (entry.source === "strava" || stravaActivityId(entry)) return "Imported from Strava";
  if (entry.source === "workout_log" || entry.source === "ai_workout_log") return "Recorded from workout diary";
  if (entry.source === "history_correction") return "Manually corrected";
  if (entry.source === "manual") return "Recorded manually";
  return entry.source.replaceAll("_", " ");
}

function dateLabel(value: string): string {
  return new Date(`${value}T12:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

function NutritionHistory({
  day,
  onPatch,
}: {
  day: HistoryDay;
  onPatch: (id: string, payload: Record<string, unknown>) => void;
}) {
  return (
    <>
      {day.food_log && <section className="card"><p className="eyebrow">Daily food diary</p><p>{day.food_log.raw_text}</p><small>{day.food_log.extraction.summary}</small></section>}
      <section className="card">
        <p className="eyebrow">Food & nutrition</p>
        {day.nutrition.length === 0 && <p>No food or nutrition entries were recorded for this day.</p>}
        {day.nutrition.map((entry) => <div className="history-entry" key={entry.id}><div><div className="history-entry-title"><strong>{entry.description}</strong><StatusPill status={entry.status} /></div><small>{entry.source.replaceAll("_", " ")}</small></div>{!("matched_by_food_log" === entry.status || "discarded_by_food_log" === entry.status) && <div className="actions"><button className="quiet small" onClick={() => onPatch(entry.id, { status: "confirmed" })}>Confirm</button><button className="quiet small" onClick={() => onPatch(entry.id, { status: "skipped" })}>Mark skipped</button></div>}</div>)}
      </section>
    </>
  );
}

function ExerciseHistory({
  day,
  onPatch,
  onRecord,
}: {
  day: HistoryDay;
  onPatch: (id: string, payload: Record<string, unknown>) => void;
  onRecord: (entry: EntryStatus) => void;
}) {
  return (
    <>
      {day.workout_log && <section className="card"><p className="eyebrow">Workout diary</p><p>{day.workout_log.raw_text}</p><small>{day.workout_log.extraction.summary}</small></section>}
      <section className="card">
        <p className="eyebrow">Exercise history</p>
        {day.workouts.length === 0 && <p>No exercise was recorded for this day.</p>}
        {day.workouts.map((entry) => {
          const activityId = stravaActivityId(entry);
          const hasEvaluation = entry.difficulty_1_to_10 != null || entry.pain_flag;
          return <div className="history-entry" key={entry.id}><div><div className="history-entry-title"><strong>{entry.exercise_name ?? "Exercise"}</strong><StatusPill status={entry.status} /></div><span className={`provenance ${activityId ? "provenance-strava" : ""}`}>{sourceLabel(entry)}</span>{workoutActualText(entry.actual) && <small>{workoutActualText(entry.actual)}</small>}{hasEvaluation && <div className="meta recorded-evaluation">{entry.difficulty_1_to_10 != null && <span>Self-evaluated difficulty {entry.difficulty_1_to_10}/10</span>}{entry.pain_flag && <span>Pain recorded</span>}</div>}{entry.notes && <p className="recorded-notes"><strong>Notes:</strong> {entry.notes}</p>}{activityId && <a className="strava-link" href={`https://www.strava.com/activities/${activityId}`} target="_blank" rel="noreferrer">View activity on Strava</a>}</div><div className="actions"><button className="quiet small" onClick={() => onRecord(entry)}>{activityId ? "Correct record" : "Record actual"}</button><button className="quiet small" onClick={() => onPatch(entry.id, { status: "skipped" })}>Mark skipped</button></div></div>;
        })}
      </section>
    </>
  );
}

export function HistoryPage({ section }: { section: HistorySection }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const history = useQuery({ queryKey: ["history"], queryFn: () => api<HistorySummary[]>("/history") });
  const visibleHistory = (history.data ?? []).filter((item) => section === "nutrition"
    ? item.nutrition_count > 0 || item.has_food_log
    : item.workout_count > 0 || item.has_workout_log);
  const selectedDate = visibleHistory.some((item) => item.date === selected) ? selected : visibleHistory[0]?.date ?? null;
  const day = useQuery({ queryKey: ["history", selectedDate], queryFn: () => api<HistoryDay>(`/history/${selectedDate}`), enabled: Boolean(selectedDate) });
  const patch = useMutation({
    mutationFn: ({ type, id, payload }: { type: "nutrition" | "workout"; id: string; payload: Record<string, unknown> }) => api(`/history/${selectedDate}/${type}/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["history"] }),
  });

  function recordWorkout(entry: EntryStatus) {
    const currentSummary = typeof entry.actual?.summary === "string" ? entry.actual.summary : workoutActualText(entry.actual);
    const actual = window.prompt(`What did you actually do for ${entry.exercise_name ?? "this exercise"}?`, currentSummary);
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

  if (history.isLoading) return <div className="loading">Loading history...</div>;
  if (history.error) return <div className="error-panel"><h1>History is unavailable</h1><p>{history.error.message}</p></div>;

  return (
    <>
      <header className="page-header"><div><p className="eyebrow">Recorded health activity</p><h1>History</h1></div></header>
      <nav className="page-tabs" aria-label="History sections">
        <NavLink to="/history/nutrition">Food & nutrition</NavLink>
        <NavLink to="/history/exercise">Exercise</NavLink>
      </nav>
      <div className="history-layout">
        <aside className="history-list card">
          {visibleHistory.map((item) => <button aria-current={selectedDate === item.date ? "date" : undefined} className={selectedDate === item.date ? "selected" : ""} key={item.date} onClick={() => setSelected(item.date)}><strong>{dateLabel(item.date)}</strong><small>{section === "nutrition" ? `${item.nutrition_count} nutrition entries${item.has_food_log ? " · food diary" : ""}` : `${item.workout_count} exercises${item.strava_activity_count ? ` · ${item.strava_activity_count} from Strava` : ""}`}</small></button>)}
          {visibleHistory.length === 0 && <p>No {section === "nutrition" ? "food or nutrition" : "exercise"} history yet.</p>}
        </aside>
        <section className="history-detail">
          {!selectedDate && <div className="empty-state">No entries are available in this history section yet.</div>}
          {selectedDate && day.isLoading && <div className="loading">Loading {dateLabel(selectedDate)}...</div>}
          {day.error && <div className="error-panel"><p>{day.error.message}</p></div>}
          {day.data && <>
            {section === "nutrition"
              ? <NutritionHistory day={day.data} onPatch={(id, payload) => patch.mutate({ type: "nutrition", id, payload })} />
              : <ExerciseHistory day={day.data} onPatch={(id, payload) => patch.mutate({ type: "workout", id, payload })} onRecord={recordWorkout} />}
            {day.data.profile_snapshot && <section className="card compact"><p className="eyebrow">Profile at recommendation time</p><p>{day.data.profile_snapshot.short_summary}</p></section>}
            {day.data.original_plan && <details className="card"><summary>Original daily recommendation</summary><pre>{JSON.stringify(day.data.original_plan, null, 2)}</pre></details>}
          </>}
        </section>
      </div>
      {patch.error && <p className="error">{patch.error.message}</p>}
    </>
  );
}
