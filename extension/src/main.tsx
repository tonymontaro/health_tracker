import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Settings = { apiUrl: string; appUrl: string; token: string };
type Meal = { recommendation_id: string; template_name: string };
type Exercise = { recommendation_id: string; exercise_name: string; exercise_type: string; distance_km?: number; pace_seconds_per_km?: number; duration_seconds?: number; load_kg?: number; external_load_kg?: number; reps_per_set?: number[] };
type Today = { current_status: string; nutrition: { meal_1: Meal; meal_2: Meal | null; fruits: Array<{ name: string }> }; workout: { kind: string; title: string; exercises: Exercise[] }; next_action: { action: string } | null; shopping: { action_needed: boolean; summary: string }; nutrition_status: Record<string, { status: string }> };

const defaults: Settings = { apiUrl: "https://api-health.anthonyngene.com", appUrl: "https://health.anthonyngene.com", token: "" };

function pace(seconds?: number): string {
  if (!seconds) return "";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}/km`;
}

function exerciseLine(item: Exercise): string {
  if (item.exercise_type === "run") return `${item.distance_km} km @ ${pace(item.pace_seconds_per_km)}`;
  if (item.exercise_type === "bike" || item.exercise_type === "recovery") return `${Math.round((item.duration_seconds ?? 0) / 60)} min`;
  return `${item.load_kg ?? item.external_load_kg ?? 0} kg · ${item.reps_per_set?.join("/")} reps`;
}

export function App() {
  const [settings, setSettings] = useState<Settings>(defaults);
  const [configured, setConfigured] = useState(false);
  const [today, setToday] = useState<Today | null>(null);
  const [error, setError] = useState("");

  async function load(current: Settings) {
    if (!current.token) return;
    try {
      const response = await fetch(`${current.apiUrl}/api/v1/today`, { headers: { Authorization: `Bearer ${current.token}` } });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      setToday((await response.json()) as Today);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load today's plan");
    }
  }

  useEffect(() => {
    chrome.storage.local.get(defaults).then((stored) => {
      const loaded = stored as Settings;
      setSettings(loaded);
      setConfigured(Boolean(loaded.token));
      void load(loaded);
    });
  }, []);

  async function save() {
    const origin = `${new URL(settings.apiUrl).origin}/*`;
    if (!origin.startsWith("http://localhost")) await chrome.permissions.request({ origins: [origin] });
    await chrome.storage.local.set(settings);
    setConfigured(Boolean(settings.token));
    await load(settings);
  }

  async function confirm(meal: Meal) {
    const response = await fetch(`${settings.apiUrl}/api/v1/today/nutrition/${meal.recommendation_id}/confirm`, { method: "POST", headers: { Authorization: `Bearer ${settings.token}` } });
    if (!response.ok) setError(`Could not confirm meal (${response.status})`);
    else await load(settings);
  }

  if (!configured) {
    return <main className="setup-edition">
      <header><span className="mark">HA</span><div><small>Personal field notes / Setup</small><h1>Connect your<br /><em>autopilot.</em></h1></div></header>
      <p className="standfirst">Use the URLs and revocable token from the full app's Settings page.</p>
      <label>API URL<input value={settings.apiUrl} onChange={(event) => setSettings({ ...settings, apiUrl: event.target.value.replace(/\/$/, "") })} /></label>
      <label>Web app URL<input value={settings.appUrl} onChange={(event) => setSettings({ ...settings, appUrl: event.target.value.replace(/\/$/, "") })} /></label>
      <label>Extension token<input type="password" value={settings.token} onChange={(event) => setSettings({ ...settings, token: event.target.value })} /></label>
      <button className="primary full" onClick={() => void save()}>Save and connect <span aria-hidden="true">→</span></button>
      {error && <p className="error" role="alert">{error}</p>}
    </main>;
  }
  if (!today) return <main className="loading-edition"><p role="status">{error || "Loading today's field notes..."}</p><button onClick={() => setConfigured(false)}>Settings</button></main>;
  const exercises = today.workout.exercises;
  return <main className="today-edition">
    <header><span className="mark">HA</span><div><small>Personal field notes / Today</small><h1>Daily notes</h1></div><button className="icon" aria-label="Open extension settings" onClick={() => setConfigured(false)}>•••</button></header>
    <section className="status-card"><small>Current status</small><p>{today.current_status}</p></section>
    <section className="training"><small>Exercise first</small><strong>{today.workout.kind === "rest" ? "Rest" : today.workout.title}</strong>{exercises.map((item) => <p key={item.recommendation_id}>{item.exercise_name}<br /><span>{exerciseLine(item)}</span></p>)}</section>
    <section><small>Food</small><div className="row"><div><strong>{today.nutrition.meal_1.template_name}</strong><em>{today.nutrition_status[today.nutrition.meal_1.recommendation_id]?.status ?? "planned"}</em></div><button onClick={() => void confirm(today.nutrition.meal_1)}>Done</button></div>{today.nutrition.meal_2 && <div className="row"><div><strong>{today.nutrition.meal_2.template_name}</strong><em>{today.nutrition_status[today.nutrition.meal_2.recommendation_id]?.status ?? "planned"}</em></div><button onClick={() => void confirm(today.nutrition.meal_2!)}>Done</button></div>}</section>
    <section><small>Fruit</small><p>{today.nutrition.fruits.map((item) => item.name).join(" · ")}</p></section>
    <section className="next"><small>Next action</small><strong>{today.next_action?.action ?? "Nothing needed"}</strong></section>
    {today.shopping.action_needed && <p className="warning">Shopping: {today.shopping.summary}</p>}
    <button className="primary full" onClick={() => chrome.tabs.create({ url: `${settings.appUrl}/today/exercise` })}>Open full app <span aria-hidden="true">→</span></button>
    {error && <p className="error" role="alert">{error}</p>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
