import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type CSSProperties, type FormEvent, type MouseEvent, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Exercise, ExtractedWorkout, Meal, RecedingHorizonOutlook, StravaSyncResult, Today, WorkoutLogExtraction } from "../api/types";
import { ExerciseFigure } from "../components/exercise/ExerciseFigure";
import { MealFigure } from "../components/food/MealFigure";
import { StatusPill } from "../components/StatusPill";

function datedPath(path: string, date: string): string {
  return `${path}?date=${encodeURIComponent(date)}`;
}

function recordingDateLabel(value: string, index: number): string {
  const formatted = new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  if (index === 0) return `Today - ${formatted}`;
  if (index === 1) return `Yesterday - ${formatted}`;
  return formatted;
}

function pace(seconds?: number | null): string {
  if (!seconds) return "";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}/km`;
}

function exerciseText(exercise: Omit<Exercise, "recommendation_id">): string {
  if (exercise.exercise_type === "run") {
    return `${exercise.distance_km?.toFixed(1)} km @ ${pace(exercise.pace_seconds_per_km)}`;
  }
  if (exercise.exercise_type === "bike" || exercise.exercise_type === "recovery") {
    const minutes = Math.round((exercise.duration_seconds ?? 0) / 60);
    const power = exercise.target_power_min_watts
      ? ` · ${exercise.target_power_min_watts}-${exercise.target_power_max_watts} W`
      : "";
    return `${minutes} min${power}`;
  }
  const load = exercise.exercise_type === "bodyweight" ? exercise.external_load_kg : exercise.load_kg;
  return `${load ?? 0} kg · ${exercise.reps_per_set?.join(" / ")} reps · ${exercise.rest_seconds}s rest`;
}

function preparationSteps(preparation: string): string[] {
  const numberedSteps = preparation
    .split(/\s+(?=\d+\.\s)/)
    .map((step) => step.replace(/^\d+\.\s*/, "").trim())
    .filter(Boolean);
  return numberedSteps.length > 1 ? numberedSteps : [preparation.trim()].filter(Boolean);
}

function MealCard({ meal, slot, index, today }: { meal: Meal; slot: string; index: number; today: Today }) {
  const queryClient = useQueryClient();
  const recipe = useRef<HTMLDialogElement>(null);
  const status = today.nutrition_status[meal.recommendation_id]?.status ?? "planned";
  const foodLogLocked = today.food_log !== null;
  const recipeSteps = preparationSteps(meal.preparation);
  const action = useMutation({
    mutationFn: (kind: "confirm" | "skip") =>
      api(datedPath(`/today/nutrition/${meal.recommendation_id}/${kind}`, today.date), { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["today"] }),
  });
  return (
    <section className="card meal-card story-card">
      <MealFigure seed={today.date} offset={index - 1} />
      <div className="card-heading"><p className="eyebrow">{foodLogLocked ? `Original suggestion · ${slot}` : slot}</p><StatusPill status={status} /></div>
      <h2>{meal.template_name}</h2>
      <p>{meal.description}</p>
      <div className="meta"><span>{meal.estimated_protein_g} g protein</span><span>{meal.hands_on_minutes} active min</span><span>{meal.suggested_window}</span></div>
      <button className="ink-button" type="button" onClick={() => recipe.current?.showModal()}>Recipe and method <span aria-hidden="true">→</span></button>
      <dialog className="detail-sheet recipe-sheet" ref={recipe} aria-labelledby={`recipe-${meal.recommendation_id}`}>
        <form method="dialog"><button className="sheet-close" aria-label={`Close recipe for ${meal.template_name}`}>Close ×</button></form>
        <p className="eyebrow">{slot} / {meal.suggested_window}</p>
        <h2 id={`recipe-${meal.recommendation_id}`}>{meal.template_name}</h2>
        <div className="meta"><span>{meal.estimated_protein_g} g protein</span><span>{meal.hands_on_minutes} active min</span></div>
        <div className="recipe-content recipe-columns">
          <div>
          {meal.ingredients.length > 0 && <><h3>Ingredients</h3><ul>{meal.ingredients.map((ingredient, index) => <li key={`${ingredient}-${index}`}>{ingredient}</li>)}</ul></>}
          </div>
          <div>
          <h3>Method</h3>
          <ol className="recipe-steps">{recipeSteps.map((step, index) => <li key={`${step}-${index}`}>{step}</li>)}</ol>
          </div>
        </div>
      </dialog>
      <div className="actions">
        <button className="primary small" disabled={foodLogLocked || action.isPending || status === "confirmed"} onClick={() => action.mutate("confirm")}>Done</button>
        <button className="quiet small" disabled={foodLogLocked || action.isPending} onClick={() => action.mutate("skip")}>Skip</button>
      </div>
      {foodLogLocked && <p className="locked-note">Actions are locked because this day's food text is the actual record.</p>}
      {action.error && <p className="error">{action.error.message}</p>}
    </section>
  );
}

function NutritionSuggestionActions({
  recommendationId,
  today,
}: {
  recommendationId: string;
  today: Today;
}) {
  const queryClient = useQueryClient();
  const status = today.nutrition_status[recommendationId]?.status ?? "planned";
  const foodLogLocked = today.food_log !== null;
  const action = useMutation({
    mutationFn: (kind: "confirm" | "skip") =>
      api(datedPath(`/today/nutrition/${recommendationId}/${kind}`, today.date), {
        method: "POST",
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
      ]);
    },
  });
  return <>
    <div className="actions">
      <button className="primary small" disabled={foodLogLocked || action.isPending || status === "confirmed"} onClick={() => action.mutate("confirm")}>Done</button>
      <button className="quiet small" disabled={foodLogLocked || action.isPending || status === "skipped"} onClick={() => action.mutate("skip")}>Skip</button>
    </div>
    {action.error && <p className="error">{action.error.message}</p>}
  </>;
}

function FoodLogCard({ today }: { today: Today }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(today.food_log?.raw_text ?? "");
  const foodLog = today.food_log;
  const save = useMutation({
    mutationFn: () => api(datedPath("/today/nutrition/food-log", today.date), {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["inventory"] }),
      ]);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim()) save.mutate();
  }
  return (
    <section className="card food-log-card" id="record-food">
      <div className="card-heading"><p className="eyebrow">What I ate</p>{foodLog && <StatusPill status="processed" />}</div>
      <h2>Record the day in your own words</h2>
      <p>Submitting this text treats it as the actual record, discards that day's food suggestions, and uses AI to estimate average portions and nutrients.</p>
      <form onSubmit={submit}>
        <label>Food and drinks<textarea value={text} maxLength={5000} onChange={(event) => setText(event.target.value)} placeholder="Chicken curry with rice, two kiwis, and a bowl of skyr." /></label>
        <div className="food-log-submit"><small>Only this text, that day's food suggestions, and the food catalog are sent for analysis. Your workout is unaffected.</small><button className="primary" disabled={save.isPending || !text.trim()}>{save.isPending ? "Analyzing..." : foodLog ? "Re-analyze and replace record" : "Analyze and record"}</button></div>
      </form>
      {save.error && <p className="error">{save.error.message}</p>}
      {foodLog && <div className="extraction-result">
        <p className="extraction-summary">{foodLog.extraction.summary}</p>
        {foodLog.extraction.ate_nothing && <p>No meals were recorded.</p>}
        {foodLog.extraction.meals.map((meal, index) => <article className="recorded-meal" key={`${meal.meal_name}-${index}`}>
          <div className="card-heading"><div><small>{meal.meal_slot.replace("_", " ")}</small><h3>{meal.meal_name}</h3></div><strong>{meal.quantity_label}</strong></div>
          <p>{meal.description}</p>
          <div className="meta"><span>~{Math.round(meal.estimated_calories_kcal)} kcal</span><span>~{Math.round(meal.estimated_protein_g)} g protein</span><span>~{Math.round(meal.estimated_fiber_g)} g fiber</span>{meal.matched_recommendation_id && <span>Followed a suggestion · {Math.round(meal.match_confidence * 100)}% confidence</span>}</div>
          <ul className="component-list">{meal.components.map((component, componentIndex) => <li key={`${component.name}-${componentIndex}`}><span>{component.name}</span><strong>{component.quantity_label}</strong>{component.quantity_is_assumed && <small>average portion</small>}</li>)}</ul>
          {meal.assumptions.length > 0 && <small>Assumptions: {meal.assumptions.join(" ")}</small>}
        </article>)}
        {foodLog.extraction.assumptions.length > 0 && <p className="assumption-note"><strong>Overall assumptions:</strong> {foodLog.extraction.assumptions.join(" ")}</p>}
      </div>}
    </section>
  );
}

function MealRegenerationCard({ today }: { today: Today }) {
  const queryClient = useQueryClient();
  const [preference, setPreference] = useState("");
  const [showPreference, setShowPreference] = useState(false);
  const meals = [today.nutrition.meal_1, today.nutrition.meal_2].filter((meal): meal is Meal => meal !== null);
  const unresolved = meals.every((meal) => (today.nutrition_status[meal.recommendation_id]?.status ?? "planned") === "planned");
  const regenerate = useMutation({
    mutationFn: () => api("/today/nutrition/regenerate", {
      method: "POST",
      body: JSON.stringify({ preference: preference.trim() || null }),
    }),
    onSuccess: async () => {
      setPreference("");
      setShowPreference(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
      ]);
    },
  });
  const disabledReason = today.food_log
    ? "Today's food diary is already the actual record."
    : !unresolved
      ? "Meals can only be regenerated before they are confirmed or skipped."
      : null;
  function submit(event: FormEvent) {
    event.preventDefault();
    regenerate.mutate();
  }
  function togglePreference() {
    if (showPreference) setPreference("");
    setShowPreference(!showPreference);
  }
  return (
    <section className="card compact regeneration-card meal-regeneration-card">
      <p className="eyebrow">Refresh meals</p>
      <p className="regeneration-copy">Generate two different recommendations while keeping today's exercise unchanged.</p>
      {disabledReason && <small className="regeneration-note">{disabledReason}</small>}
      <div className="regeneration-actions">
        <button type="button" className="quiet small" disabled={regenerate.isPending || disabledReason !== null} onClick={() => regenerate.mutate()}>{regenerate.isPending ? "Regenerating..." : "Regenerate"}</button>
        <button type="button" className="text-button" aria-expanded={showPreference} aria-controls={`meal-preference-${today.date}`} disabled={regenerate.isPending || disabledReason !== null} onClick={togglePreference}>{showPreference ? "Hide preference" : "Add preference"}</button>
      </div>
      {showPreference && <form className="compact-regeneration-form" id={`meal-preference-${today.date}`} onSubmit={submit}>
        <label>Optional preference<textarea value={preference} maxLength={2000} onChange={(event) => setPreference(event.target.value)} placeholder="For example: egg-based or especially high-protein." /></label>
        <button className="primary small" disabled={regenerate.isPending}>{regenerate.isPending ? "Regenerating..." : "Regenerate with preference"}</button>
      </form>}
      {regenerate.error && <p className="error">{regenerate.error.message}</p>}
    </section>
  );
}

function actualWorkoutText(actual?: Record<string, unknown> | null): string {
  if (!actual) return "";
  const parts: string[] = [];
  if (typeof actual.distance_km === "number") parts.push(`${actual.distance_km.toFixed(2)} km`);
  if (typeof actual.duration_seconds === "number") parts.push(`${Math.round(actual.duration_seconds / 60)} min`);
  if (typeof actual.load_kg === "number") parts.push(`${actual.load_kg} kg`);
  if (Array.isArray(actual.reps_per_set)) parts.push(`${actual.reps_per_set.join(" / ")} reps`);
  if (typeof actual.average_power_watts === "number") parts.push(`${Math.round(actual.average_power_watts)} W avg`);
  if (typeof actual.average_heartrate_bpm === "number") parts.push(`${Math.round(actual.average_heartrate_bpm)} bpm avg`);
  return parts.join(" · ");
}

type EditableWorkout = ExtractedWorkout & { draftKey: string; repsText: string };
type EditableWorkoutExtraction = Omit<WorkoutLogExtraction, "workouts"> & { workouts: EditableWorkout[] };

function editableWorkout(workout: ExtractedWorkout): EditableWorkout {
  return {
    ...workout,
    draftKey: crypto.randomUUID(),
    repsText: workout.reps_per_set?.join(", ") ?? "",
  };
}

function submittedWorkout(workout: EditableWorkout): ExtractedWorkout {
  return {
    workout_name: workout.workout_name,
    exercise_type: workout.exercise_type,
    duration_seconds: workout.duration_seconds,
    distance_km: workout.distance_km,
    load_kg: workout.load_kg,
    external_load_kg: workout.external_load_kg,
    sets: workout.sets,
    reps_per_set: workout.reps_per_set,
    average_power_watts: workout.average_power_watts,
    average_heartrate_bpm: workout.average_heartrate_bpm,
    difficulty_1_to_10: workout.difficulty_1_to_10,
    pain_flag: workout.pain_flag,
    notes: workout.notes,
    matched_recommendation_id: workout.matched_recommendation_id,
    match_confidence: workout.match_confidence,
    assumptions: workout.assumptions,
  };
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function workoutDraftError(draft: EditableWorkoutExtraction | null): string | null {
  if (!draft) return null;
  const matchedIds = draft.workouts.flatMap((workout) => workout.matched_recommendation_id ? [workout.matched_recommendation_id] : []);
  if (matchedIds.length !== new Set(matchedIds).size) return "A recommendation can only be matched to one extracted exercise.";
  for (const workout of draft.workouts) {
    if (!workout.workout_name.trim()) return "Every exercise needs a name.";
    const evidence = [workout.duration_seconds, workout.distance_km, workout.load_kg, workout.external_load_kg, workout.sets, workout.reps_per_set];
    if (!evidence.some((value) => value !== null)) return `${workout.workout_name} needs at least one duration, distance, load, set, or repetition value.`;
    if (workout.duration_seconds !== null && (workout.duration_seconds <= 0 || workout.duration_seconds > 43200)) return `${workout.workout_name} needs a duration between 1 second and 12 hours.`;
    if (workout.distance_km !== null && (workout.distance_km <= 0 || workout.distance_km > 500)) return `${workout.workout_name} needs a distance between 0 and 500 km.`;
    if (workout.load_kg !== null && (workout.load_kg < 0 || workout.load_kg > 500)) return `${workout.workout_name} needs a load between 0 and 500 kg.`;
    if (workout.external_load_kg !== null && (workout.external_load_kg < 0 || workout.external_load_kg > 200)) return `${workout.workout_name} needs an external load between 0 and 200 kg.`;
    if (workout.sets !== null && (!Number.isInteger(workout.sets) || workout.sets < 1 || workout.sets > 100)) return `${workout.workout_name} needs a whole-number set count between 1 and 100.`;
    const repTokens = workout.repsText.split(",").map((value) => value.trim()).filter(Boolean);
    if (repTokens.some((value) => !Number.isInteger(Number(value)) || Number(value) < 1 || Number(value) > 1000)) return `${workout.workout_name} has an invalid repetition value.`;
    if (workout.reps_per_set && workout.reps_per_set.length > 100) return `${workout.workout_name} cannot contain more than 100 sets of repetitions.`;
    if (workout.average_power_watts !== null && (workout.average_power_watts < 0 || workout.average_power_watts > 3000)) return `${workout.workout_name} needs average power between 0 and 3000 W.`;
    if (workout.average_heartrate_bpm !== null && (workout.average_heartrate_bpm < 20 || workout.average_heartrate_bpm > 260)) return `${workout.workout_name} needs average heart rate between 20 and 260 bpm.`;
    if (workout.difficulty_1_to_10 !== null && (!Number.isInteger(workout.difficulty_1_to_10) || workout.difficulty_1_to_10 < 1 || workout.difficulty_1_to_10 > 10)) return `${workout.workout_name} needs a whole-number difficulty between 1 and 10.`;
  }
  return null;
}

function WorkoutDraftEditor({
  workout,
  recommendations,
  onChange,
  onDelete,
}: {
  workout: EditableWorkout;
  recommendations: Exercise[];
  onChange: (changes: Partial<EditableWorkout>) => void;
  onDelete: () => void;
}) {
  const strength = workout.exercise_type === "strength" || workout.exercise_type === "bodyweight";
  return (
    <article className="workout-editor">
      <div className="card-heading"><strong>Extracted exercise</strong><button type="button" className="text-button danger" onClick={onDelete}>Delete</button></div>
      <div className="workout-editor-grid">
        <label>Exercise name<input required maxLength={160} value={workout.workout_name} onChange={(event) => onChange({ workout_name: event.target.value })} /></label>
        <label>Type<select value={workout.exercise_type} onChange={(event) => onChange({ exercise_type: event.target.value as ExtractedWorkout["exercise_type"] })}><option value="strength">Strength</option><option value="bodyweight">Bodyweight</option><option value="run">Run</option><option value="bike">Bike</option><option value="recovery">Recovery</option></select></label>
        <label>Duration, minutes<input type="number" min="0.1" step="0.1" value={workout.duration_seconds ? workout.duration_seconds / 60 : ""} onChange={(event) => { const minutes = optionalNumber(event.target.value); onChange({ duration_seconds: minutes === null ? null : Math.round(minutes * 60) }); }} /></label>
        <label>Distance, km<input type="number" min="0.01" step="0.01" value={workout.distance_km ?? ""} onChange={(event) => onChange({ distance_km: optionalNumber(event.target.value) })} /></label>
        {strength && <><label>Load, kg<input type="number" min="0" step="0.5" value={workout.load_kg ?? ""} onChange={(event) => onChange({ load_kg: optionalNumber(event.target.value) })} /></label><label>External load, kg<input type="number" min="0" step="0.5" value={workout.external_load_kg ?? ""} onChange={(event) => onChange({ external_load_kg: optionalNumber(event.target.value) })} /></label><label>Sets<input type="number" min="1" step="1" value={workout.sets ?? ""} onChange={(event) => onChange({ sets: optionalNumber(event.target.value) })} /></label><label>Reps per set<input value={workout.repsText} placeholder="8, 8, 8" onChange={(event) => { const repsText = event.target.value; const reps = repsText.split(",").map((value) => Number(value.trim())).filter((value) => Number.isInteger(value) && value > 0); onChange({ repsText, reps_per_set: reps.length ? reps : null }); }} /></label></>}
        {workout.exercise_type === "bike" && <label>Average power, W<input type="number" min="0" step="1" value={workout.average_power_watts ?? ""} onChange={(event) => onChange({ average_power_watts: optionalNumber(event.target.value) })} /></label>}
        <label>Average heart rate<input type="number" min="20" max="260" step="1" value={workout.average_heartrate_bpm ?? ""} onChange={(event) => onChange({ average_heartrate_bpm: optionalNumber(event.target.value) })} /></label>
        <label>Difficulty, 1-10<input type="number" min="1" max="10" step="1" value={workout.difficulty_1_to_10 ?? ""} onChange={(event) => onChange({ difficulty_1_to_10: optionalNumber(event.target.value) })} /></label>
        <label>Matched recommendation<select value={workout.matched_recommendation_id ?? ""} onChange={(event) => onChange({ matched_recommendation_id: event.target.value || null, match_confidence: event.target.value ? 1 : 0 })}><option value="">Unplanned exercise</option>{recommendations.map((exercise) => <option key={exercise.recommendation_id} value={exercise.recommendation_id}>{exercise.exercise_name}</option>)}</select></label>
      </div>
      <label>Notes<textarea maxLength={2000} value={workout.notes ?? ""} onChange={(event) => onChange({ notes: event.target.value || null })} /></label>
      {workout.pain_flag && <p className="assumption-note">Pain or discomfort was detected in your description and will be included in the record.</p>}
    </article>
  );
}

function WorkoutLogCard({ today }: { today: Today }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(today.workout_log?.raw_text ?? "");
  const [draft, setDraft] = useState<EditableWorkoutExtraction | null>(null);
  const [analyzedText, setAnalyzedText] = useState<string | null>(null);
  const [stravaMessage, setStravaMessage] = useState("");
  const workoutLog = today.workout_log;
  const analyze = useMutation({
    mutationFn: () => api<{ raw_text: string; extraction: WorkoutLogExtraction }>(datedPath("/today/workout/log/analyze", today.date), {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
    onSuccess: (result) => {
      setDraft({ ...result.extraction, workouts: result.extraction.workouts.map(editableWorkout) });
      setAnalyzedText(result.raw_text);
    },
  });
  const submitReview = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error("Analyze the workout before submitting it.");
      const extraction: WorkoutLogExtraction = {
        ...draft,
        did_no_workout: draft.workouts.length === 0,
        workouts: draft.workouts.map(submittedWorkout),
      };
      return api<{ coach_feedback: string }>(datedPath("/today/workout/log", today.date), {
        method: "POST",
        body: JSON.stringify({ text, extraction }),
      });
    },
    onSuccess: async () => {
      setDraft(null);
      setAnalyzedText(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-feedback"] }),
      ]);
    },
  });
  const retrieveStrava = useMutation({
    mutationFn: () => api<StravaSyncResult>(datedPath("/integrations/strava/sync-day", today.date), { method: "POST" }),
    onSuccess: async (result) => {
      setStravaMessage(result.fetched ? `Retrieved ${result.fetched} ${result.fetched === 1 ? "activity" : "activities"} from Strava.` : "No Strava activities were found for this day.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["strava"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-feedback"] }),
      ]);
    },
  });
  function submitAnalysis(event: FormEvent) {
    event.preventDefault();
    if (text.trim()) analyze.mutate();
  }
  function changeWorkout(index: number, changes: Partial<EditableWorkout>) {
    setDraft((current) => current ? { ...current, workouts: current.workouts.map((workout, workoutIndex) => workoutIndex === index ? { ...workout, ...changes } : workout) } : current);
  }
  function addWorkout() {
    const workout = editableWorkout({
      workout_name: "New exercise",
      exercise_type: "recovery",
      duration_seconds: null,
      distance_km: null,
      load_kg: null,
      external_load_kg: null,
      sets: null,
      reps_per_set: null,
      average_power_watts: null,
      average_heartrate_bpm: null,
      difficulty_1_to_10: null,
      pain_flag: false,
      notes: null,
      matched_recommendation_id: null,
      match_confidence: 0,
      assumptions: [],
    });
    setDraft((current) => current ? { ...current, did_no_workout: false, workouts: [...current.workouts, workout] } : current);
  }
  const reviewError = workoutDraftError(draft);
  return (
    <section className="card workout-log-card" id="record-workout">
      <div className="card-heading"><div><p className="eyebrow">What I trained</p>{workoutLog && <StatusPill status="processed" />}</div><button type="button" className="quiet small" disabled={retrieveStrava.isPending} onClick={() => { setStravaMessage(""); retrieveStrava.mutate(); }}>{retrieveStrava.isPending ? "Retrieving..." : "Retrieve from Strava"}</button></div>
      <h2>Describe the workout in your own words</h2>
      <p>Describe what you did, including any pain or discomfort. Then review every extracted exercise and submit only when the record is accurate.</p>
      <form onSubmit={submitAnalysis}>
        <label>Workout details<textarea value={text} maxLength={5000} onChange={(event) => setText(event.target.value)} placeholder="Ran 6.2 km in 38 minutes, then did 3 sets of 8 pull-ups. Difficulty 6/10 and no pain." /></label>
        <div className="food-log-submit"><small>Analysis does not record anything. Existing Strava evidence is preserved.</small><button className="primary" disabled={analyze.isPending || !text.trim()}>{analyze.isPending ? "Analyzing..." : "Analyze"}</button></div>
      </form>
      {analyze.error && <p className="error">{analyze.error.message}</p>}
      {retrieveStrava.error && <p className="error">{retrieveStrava.error.message}</p>}
      {stravaMessage && <p className="success standalone">{stravaMessage}</p>}
      {draft && <div className="workout-review">
        <div><p className="eyebrow">Review before submitting</p><h3>Extracted exercises</h3><p>Correct fields, delete incorrect items, or add anything the analysis missed.</p></div>
        <label>Summary<input maxLength={1000} value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} /></label>
        {draft.workouts.map((workout, index) => <WorkoutDraftEditor key={workout.draftKey} workout={workout} recommendations={today.workout.exercises} onChange={(changes) => changeWorkout(index, changes)} onDelete={() => setDraft({ ...draft, workouts: draft.workouts.filter((_, workoutIndex) => workoutIndex !== index) })} />)}
        {draft.workouts.length === 0 && <p className="empty-review">No exercises will be recorded. Add an exercise if that is not correct.</p>}
        <div className="review-actions"><button type="button" className="quiet" onClick={addWorkout}>Add exercise</button><button type="button" className="primary" disabled={submitReview.isPending || analyzedText !== text || reviewError !== null} onClick={() => submitReview.mutate()}>{submitReview.isPending ? "Submitting..." : "Submit reviewed workout"}</button></div>
        {analyzedText !== text && <p className="assumption-note">The description changed after analysis. Analyze it again before submitting.</p>}
        {reviewError && <p className="assumption-note">{reviewError}</p>}
        {submitReview.error && <p className="error">{submitReview.error.message}</p>}
      </div>}
      {!draft && workoutLog && <div className="extraction-result">
        <p className="extraction-summary">{workoutLog.extraction.summary}</p>
        {workoutLog.extraction.did_no_workout && <p>No workout was recorded.</p>}
        {workoutLog.extraction.workouts.map((workout, index) => <article className="recorded-workout" key={`${workout.workout_name}-${index}`}>
          <div className="card-heading"><div><small>{workout.exercise_type}</small><h3>{workout.workout_name}</h3></div>{workout.matched_recommendation_id && <StatusPill status="completed" />}</div>
          <p>{actualWorkoutText(workout as unknown as Record<string, unknown>)}</p>
          <div className="meta">{workout.difficulty_1_to_10 && <span>Difficulty {workout.difficulty_1_to_10}/10</span>}{workout.matched_recommendation_id && <span>Matched recommendation · {Math.round(workout.match_confidence * 100)}%</span>}{workout.pain_flag && <span>Pain recorded</span>}</div>
          {workout.notes && <small>{workout.notes}</small>}
        </article>)}
        {workoutLog.extraction.assumptions.length > 0 && <p className="assumption-note"><strong>Assumptions:</strong> {workoutLog.extraction.assumptions.join(" ")}</p>}
      </div>}
    </section>
  );
}

function WorkoutRegenerationCard({ today }: { today: Today }) {
  const queryClient = useQueryClient();
  const [preference, setPreference] = useState("");
  const [showPreference, setShowPreference] = useState(false);
  const unresolved = today.workout.exercises.every((exercise) => (today.workout_status[exercise.recommendation_id]?.status ?? "planned") === "planned");
  const hasRecordedExercise = today.actual_workouts.some((entry) => entry.status === "completed" || entry.actual);
  const regenerate = useMutation({
    mutationFn: () => api("/today/workout/regenerate", {
      method: "POST",
      body: JSON.stringify({ preference: preference.trim() || null }),
    }),
    onSuccess: async () => {
      setPreference("");
      setShowPreference(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["strava"] }),
      ]);
    },
  });
  const disabledReason = today.workout_log
    ? "Today's workout diary is already the actual record."
    : hasRecordedExercise
      ? "Exercise has already been recorded for today."
      : !unresolved
        ? "The workout can only be regenerated before it is completed or skipped."
        : null;
  function submit(event: FormEvent) {
    event.preventDefault();
    regenerate.mutate();
  }
  function togglePreference() {
    if (showPreference) setPreference("");
    setShowPreference(!showPreference);
  }
  return (
    <section className="card compact regeneration-card workout-regeneration-card">
      <p className="eyebrow">Refresh exercise</p>
      <p className="regeneration-copy">Retrieve the latest Strava history and rebuild only today's recommendation.</p>
      {disabledReason && <small className="regeneration-note">{disabledReason}</small>}
      <div className="regeneration-actions">
        <button type="button" className="quiet small" disabled={regenerate.isPending || disabledReason !== null} onClick={() => regenerate.mutate()}>{regenerate.isPending ? "Regenerating..." : "Regenerate"}</button>
        <button type="button" className="text-button" aria-expanded={showPreference} aria-controls={`workout-preference-${today.date}`} disabled={regenerate.isPending || disabledReason !== null} onClick={togglePreference}>{showPreference ? "Hide preference" : "Add preference"}</button>
      </div>
      {showPreference && <form className="compact-regeneration-form" id={`workout-preference-${today.date}`} onSubmit={submit}>
        <label>Optional preference<textarea value={preference} maxLength={2000} onChange={(event) => setPreference(event.target.value)} placeholder="For example: upper body or an easy run." /></label>
        <button className="primary small" disabled={regenerate.isPending}>{regenerate.isPending ? "Regenerating..." : "Regenerate with preference"}</button>
      </form>}
      {regenerate.error && <p className="error">{regenerate.error.message}</p>}
    </section>
  );
}

function WorkoutCard({
  today,
  mode = "summary",
  onAskAlternative,
}: {
  today: Today;
  mode?: "summary" | "record";
  onAskAlternative?: () => void;
}) {
  const queryClient = useQueryClient();
  const [difficulties, setDifficulties] = useState<Record<string, number>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const workoutLogLocked = today.workout_log !== null;
  const complete = useMutation({
    mutationFn: () => {
      const results: Record<string, Record<string, unknown>> = {};
      for (const exercise of today.workout.exercises) {
        const first = values[`${exercise.recommendation_id}:first`] ?? "";
        const second = values[`${exercise.recommendation_id}:second`] ?? "";
        if (exercise.exercise_type === "strength" || exercise.exercise_type === "bodyweight") {
          results[exercise.recommendation_id] = {
            load_kg: Number(first || exercise.load_kg || exercise.external_load_kg || 0),
            reps_per_set: (second || exercise.reps_per_set?.join(",") || "").split(",").map(Number),
          };
        } else if (exercise.exercise_type === "run") {
          results[exercise.recommendation_id] = {
            distance_km: Number(first || exercise.distance_km),
            duration_seconds: Math.round(Number(second || Math.round((exercise.duration_seconds ?? 0) / 60)) * 60),
          };
        } else {
          results[exercise.recommendation_id] = {
            duration_seconds: Math.round(Number(first || Math.round((exercise.duration_seconds ?? 0) / 60)) * 60),
            average_power_watts: second ? Number(second) : null,
          };
        }
      }
      return api(datedPath("/today/workout/complete", today.date), {
        method: "POST",
        body: JSON.stringify({ results, difficulty_1_to_10: 5, pain_flag: false, notes: notes || null }),
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-feedback"] }),
      ]);
    },
  });
  const recommendationAction = useMutation({
    mutationFn: ({ recommendationId, kind, difficulty }: { recommendationId: string; kind: "confirm" | "skip"; difficulty: number }) =>
      api(datedPath(`/today/workout/${recommendationId}/${kind}`, today.date), {
        method: "POST",
        ...(kind === "confirm" ? { body: JSON.stringify({ difficulty_1_to_10: difficulty }) } : {}),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["today-details"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-feedback"] }),
      ]);
    },
  });
  if (today.workout.kind === "rest") {
    return <section className="card workout-card"><p className="eyebrow">Training</p><h2>Rest</h2><p>{today.workout.summary}</p></section>;
  }
  const isRecording = mode === "record";
  return (
    <section className={`card workout-card workout-card-${mode}`}>
      <div className="card-heading"><p className="eyebrow">{isRecording ? "Changed workout" : "The prescription"}</p><span className="difficulty">{today.workout.exercises.length} {today.workout.exercises.length === 1 ? "exercise" : "exercises"}</span></div>
      {isRecording && <><h2>Record changes to the plan</h2><p>Use these fields only when the completed workout differed from the recommendation.</p></>}
      {today.workout.exercises.map((exercise) => {
        const status = today.workout_status[exercise.recommendation_id]?.status ?? "planned";
        const recorded = today.workout_status[exercise.recommendation_id];
        const strength = exercise.exercise_type === "strength" || exercise.exercise_type === "bodyweight";
        const hasEvaluation = recorded && (recorded.difficulty_1_to_10 != null || recorded.pain_flag);
        const selectedDifficulty = difficulties[exercise.recommendation_id] ?? recorded?.difficulty_1_to_10 ?? 5;
        const difficultyProgress = `${((selectedDifficulty - 1) / 9) * 100}%`;
        const skipped = status === "skipped" || status === "skipped_assumed" || status === "skipped_by_workout_log";
        return (
          <div className="exercise" key={exercise.recommendation_id}>
            <div className="exercise-heading"><div><strong>{exercise.exercise_name}</strong> <StatusPill status={status} /></div><span className="difficulty">Planned effort {exercise.expected_difficulty}/10</span></div>
            <p className="prescription">{exerciseText(exercise)}</p><p>{exercise.instructions}</p>
            {isRecording && recorded?.actual && <p className="recorded-actual"><strong>{recorded.source === "strava" ? "Recorded by Strava" : "Recorded actual"}:</strong> {actualWorkoutText(recorded.actual)}</p>}
            {isRecording && hasEvaluation && <div className="meta recorded-evaluation">{recorded.difficulty_1_to_10 != null && <span>Self-evaluated difficulty {recorded.difficulty_1_to_10}/10</span>}{recorded.pain_flag && <span>Pain recorded</span>}</div>}
            {isRecording && recorded?.notes && <p className="recorded-notes"><strong>Notes:</strong> {recorded.notes}</p>}
            {isRecording && <div className="actual-grid">
              <label>{strength ? "Actual load kg" : exercise.exercise_type === "run" ? "Actual distance km" : "Actual minutes"}<input value={values[`${exercise.recommendation_id}:first`] ?? ""} onChange={(event) => setValues({ ...values, [`${exercise.recommendation_id}:first`]: event.target.value })} placeholder={strength ? String(exercise.load_kg ?? exercise.external_load_kg ?? 0) : String(exercise.distance_km ?? Math.round((exercise.duration_seconds ?? 0) / 60))} /></label>
              <label>{strength ? "Actual reps, comma separated" : exercise.exercise_type === "run" ? "Actual minutes" : "Average power, optional"}<input value={values[`${exercise.recommendation_id}:second`] ?? ""} onChange={(event) => setValues({ ...values, [`${exercise.recommendation_id}:second`]: event.target.value })} placeholder={strength ? exercise.reps_per_set?.join(",") : exercise.exercise_type === "run" ? String(Math.round((exercise.duration_seconds ?? 0) / 60)) : "watts"} /></label>
            </div>}
            {!isRecording && <div className="exercise-checkin">
              <label className="exercise-difficulty-control" htmlFor={`difficulty-${exercise.recommendation_id}`}>
                <span><b>How hard was it?</b><output htmlFor={`difficulty-${exercise.recommendation_id}`}>{selectedDifficulty}<small>/10</small></output></span>
                <input
                  id={`difficulty-${exercise.recommendation_id}`}
                  aria-label={`Difficulty for ${exercise.exercise_name}`}
                  type="range"
                  min="1"
                  max="10"
                  step="1"
                  value={selectedDifficulty}
                  style={{ "--difficulty-progress": difficultyProgress } as CSSProperties}
                  disabled={workoutLogLocked || recommendationAction.isPending || status === "completed"}
                  onChange={(event) => setDifficulties({ ...difficulties, [exercise.recommendation_id]: Number(event.target.value) })}
                />
                <span className="difficulty-scale" aria-hidden="true"><i>Easy</i><i>Hard</i></span>
              </label>
              <div className="exercise-action-buttons">
                <button type="button" className="primary small" disabled={workoutLogLocked || recommendationAction.isPending || status === "completed"} onClick={() => recommendationAction.mutate({ recommendationId: exercise.recommendation_id, kind: "confirm", difficulty: selectedDifficulty })}>Done</button>
                <button type="button" className="quiet small" disabled={workoutLogLocked || recommendationAction.isPending || skipped} onClick={() => recommendationAction.mutate({ recommendationId: exercise.recommendation_id, kind: "skip", difficulty: selectedDifficulty })}>Skip</button>
              </div>
            </div>}
          </div>
        );
      })}
      {isRecording && <><label>Notes, optional<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      <div className="actions">
        <button className="primary small" onClick={() => complete.mutate()} disabled={complete.isPending || workoutLogLocked}>Save changed workout</button>
      </div>
      {workoutLogLocked && <p className="locked-note">Structured actions are locked because this day's workout text is the actual record.</p>}
      {complete.error && <p className="error">{complete.error.message}</p>}</>}
      {!isRecording && workoutLogLocked && <p className="locked-note">Actions are locked because this day's workout text is the actual record.</p>}
      {!isRecording && recommendationAction.error && <p className="error">{recommendationAction.error.message}</p>}
      {!isRecording && onAskAlternative && <button className="ink-button" type="button" onClick={onAskAlternative}>Ask for an alternative <span aria-hidden="true">→</span></button>}
    </section>
  );
}

type PlanChatMessage = {
  message_id: string;
  message_date: string;
  question: string;
  answer: string;
  proposed_change: Record<string, unknown> | null;
  applied_at: string | null;
  created_at: string;
};

function ChatPanel({
  initialQuestion,
  canAsk,
  selectedDate,
}: {
  initialQuestion: string;
  canAsk: boolean;
  selectedDate: string;
}) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState(initialQuestion);
  const [previousOpen, setPreviousOpen] = useState(false);
  const messages = useQuery({
    queryKey: ["chat-messages", selectedDate],
    queryFn: () => api<PlanChatMessage[]>(datedPath("/today/questions", selectedDate)),
  });
  const previousMessages = useQuery({
    queryKey: ["chat-messages", "before", selectedDate],
    queryFn: () => api<PlanChatMessage[]>(`/today/questions?before=${encodeURIComponent(selectedDate)}`),
    enabled: previousOpen,
  });
  const ask = useMutation({
    mutationFn: () => api("/today/questions", { method: "POST", body: JSON.stringify({ question }) }),
    onSuccess: async () => {
      setQuestion("");
      await queryClient.invalidateQueries({ queryKey: ["chat-messages"] });
    },
  });
  const apply = useMutation({
    mutationFn: (messageId: string) => api(`/today/recommendations/${messageId}/apply-change`, { method: "POST" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-messages"] }),
      ]);
    },
  });
  function submit(event: FormEvent) { event.preventDefault(); if (question.trim()) ask.mutate(); }
  function renderMessage(message: PlanChatMessage) {
    const canApply = canAsk && message.message_date === selectedDate && !message.applied_at;
    return <article className="chat-exchange" key={message.message_id}>
      <div className="chat-exchange-meta"><strong>{new Date(`${message.message_date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</strong><time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</time></div>
      <div className="chat-message chat-question"><small>You</small><p>{message.question}</p></div>
      <div className="chat-message chat-response"><small>AI</small><p>{message.answer}</p></div>
      {message.proposed_change && <div className="chat-proposal"><small>Proposed plan change</small><pre>{JSON.stringify(message.proposed_change, null, 2)}</pre>{message.applied_at ? <span className="status status-completed">Applied</span> : canApply ? <button className="primary small" disabled={apply.isPending} onClick={() => apply.mutate(message.message_id)}>Apply this change</button> : <small>This change is from an earlier plan and is kept for reference.</small>}</div>}
    </article>;
  }
  return (
    <section className="card chat-card">
      {canAsk && <><p className="eyebrow">Ask about today's plan</p><form onSubmit={submit}><label htmlFor={`coach-question-${selectedDate}`}>Message your AI coach</label><div className="chat-composer"><textarea id={`coach-question-${selectedDate}`} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Why this pace? Can I use the KICKR instead?" /><button className="primary small" disabled={ask.isPending || !question.trim()}>{ask.isPending ? "Asking..." : "Ask AI"}</button></div></form></>}
      <div className="chat-feed-heading"><p className="eyebrow">Chats</p><small>Newest first</small></div>
      {messages.isLoading && <p>Loading saved chats...</p>}
      {messages.error && <p className="error">{messages.error.message}</p>}
      {messages.data?.length === 0 && <p>No saved conversations for this day.</p>}
      <div className="chat-feed">
        {messages.data?.map(renderMessage)}
      </div>
      <details className="previous-chats" onToggle={(event) => setPreviousOpen(event.currentTarget.open)}>
        <summary>Previous chats</summary>
        {previousOpen && previousMessages.isLoading && <p>Loading previous chats...</p>}
        {previousMessages.error && <p className="error">{previousMessages.error.message}</p>}
        {previousMessages.data?.length === 0 && <p>No earlier conversations.</p>}
        <div className="chat-feed">{previousMessages.data?.map(renderMessage)}</div>
      </details>
      {(ask.error || apply.error) && <p className="error">{ask.error?.message ?? apply.error?.message}</p>}
    </section>
  );
}

function sourceLabel(source: Today["source"]): string {
  return source === "openai" ? "AI planned" : "Reliable fallback";
}

function CoachFeedbackNote({ feedback, loading }: { feedback: string | null; loading: boolean }) {
  return <aside className="coach-feedback-top" aria-live="polite">
    <p className="eyebrow">Coach's feedback</p>
    <p>{feedback || (loading ? "Reviewing today's plan..." : "No additional coaching note for this day.")}</p>
    <span aria-hidden="true">01</span>
  </aside>;
}

function TodayEditionHeader({ today, section }: { today: Today; section: "food" | "exercise" }) {
  const date = new Date(`${today.date}T12:00:00`);
  const dateLong = date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const dateShort = date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const monthYear = date.toLocaleDateString(undefined, { month: "short", year: "numeric" }).split(" ");
  const isFood = section === "food";
  return <header className={`edition-header ${isFood ? "edition-header-food" : "edition-header-exercise"}`}>
    <div className="edition-meta"><span>Daily edition</span><span>Europe / Zurich</span><time className="date-long" dateTime={today.date}>{dateLong}</time><time className="date-short" dateTime={today.date}>{dateShort}</time></div>
    {isFood && <div className="edition-title food-edition-title">
      <div className="date-block"><strong>{String(date.getDate()).padStart(2, "0")}</strong><span>{monthYear[0]}<br />{monthYear[1]}</span></div>
      <div className="food-brief">
        <p className="eyebrow">Today's food</p>
        <h1>{today.nutrition.guidance}</h1>
        <div className="edition-brief-facts"><span>{today.nutrition.expected_main_meals} {today.nutrition.expected_main_meals === 1 ? "meal" : "meals"}</span><span>Approx. {today.nutrition.approximate_protein_g} g protein</span><span>{today.recovery_status.replaceAll("_", " ")} recovery</span></div>
      </div>
      <div className={`source-stamp source-${today.source}`}><span>Source</span><strong>{sourceLabel(today.source)}</strong></div>
    </div>}
  </header>;
}

function ExerciseLead({ today }: { today: Today }) {
  return <section className="lead-story">
    <div className="lead-copy">
      <p className="eyebrow"><span>I</span> The main work</p>
      <h1>{today.workout.title}</h1>
      <p className="dropcap">{today.rationale.summary || today.workout.summary}</p>
      {today.current_target_goal && <div className="target-note"><span>Current target</span><strong>{today.current_target_goal}</strong></div>}
    </div>
    <ExerciseFigure today={today} />
  </section>;
}

type RecordKind = "exercise" | "food";
const RECORD_SHEET_ANIMATION_MS = 300;

function RecordSheet({
  today,
  kind,
  onKindChange,
  onClose,
}: {
  today: Today;
  kind: RecordKind | null;
  onKindChange: (kind: RecordKind) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeTimer = useRef<number | null>(null);
  const [isClosing, setIsClosing] = useState(false);
  useEffect(() => {
    const recordDialog = dialog.current;
    if (kind) {
      if (!recordDialog?.open) recordDialog?.showModal();
      const frame = requestAnimationFrame(() => recordDialog?.scrollTo({ top: 0 }));
      return () => cancelAnimationFrame(frame);
    }
    if (recordDialog?.open) recordDialog.close();
  }, [kind]);
  useEffect(() => () => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
  }, []);
  const stravaActivities = today.actual_workouts.filter((entry) => entry.source === "strava");
  function finishClose() {
    if (dialog.current?.open) dialog.current.close();
    else onClose();
    setIsClosing(false);
  }
  function requestClose() {
    if (isClosing) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finishClose();
      return;
    }
    setIsClosing(true);
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null;
      finishClose();
    }, RECORD_SHEET_ANIMATION_MS);
  }
  function handleNativeClose() {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setIsClosing(false);
    onClose();
  }
  function closeFromBackdrop(event: MouseEvent<HTMLDialogElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const outsideSheet = event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom;
    if (outsideSheet) requestClose();
  }
  return <dialog className={`detail-sheet record-sheet${isClosing ? " is-closing" : ""}`} ref={dialog} aria-labelledby="record-sheet-title" onClick={closeFromBackdrop} onCancel={(event) => { event.preventDefault(); requestClose(); }} onClose={handleNativeClose}>
    <button type="button" className="sheet-close" onClick={requestClose}>Close ×</button>
    <p className="eyebrow">Record the day / {today.date}</p>
    <h2 id="record-sheet-title">What should the record say?</h2>
    <p className="record-sheet-intro">Choose a section and describe the day in your own words. The structured fields remain available for precise changes.</p>
    <div className="record-tabs" aria-label="Record type">
      <button type="button" aria-pressed={kind === "exercise"} className={kind === "exercise" ? "active" : ""} onClick={() => onKindChange("exercise")}>Exercise</button>
      <button type="button" aria-pressed={kind === "food"} className={kind === "food" ? "active" : ""} onClick={() => onKindChange("food")}>Food</button>
    </div>
    <div className="record-panel" hidden={kind !== "exercise"}>
      <WorkoutLogCard key={`workout-record-${today.date}`} today={today} />
      {stravaActivities.length > 0 && <section className="card"><p className="eyebrow">Strava activities</p>{stravaActivities.map((entry) => <div className="recorded-activity" key={entry.id}><div><strong>{entry.exercise_name}</strong><StatusPill status={entry.status} /></div><small>{actualWorkoutText(entry.actual)}</small></div>)}</section>}
      {today.workout.kind !== "rest" && <WorkoutCard today={today} mode="record" />}
    </div>
    <div className="record-panel" hidden={kind !== "food"}>
      <FoodLogCard key={`food-record-${today.date}`} today={today} />
    </div>
  </dialog>;
}

function FolioRule({ label, number }: { label: string; number: string }) {
  return <div className="folio-rule" aria-hidden="true"><span>{label}</span><i /><b>{number}</b></div>;
}

function SevenDayOutlook({ outlook, section }: { outlook: RecedingHorizonOutlook; section: "food" | "exercise" }) {
  const queryClient = useQueryClient();
  const [preference, setPreference] = useState("");
  const [showPreference, setShowPreference] = useState(false);
  const isFood = section === "food";
  const strategy = isFood ? outlook.nutrition_strategy : outlook.training_strategy;
  const preferenceId = `outlook-preference-${section}`;
  const regenerate = useMutation({
    mutationFn: () => api<RecedingHorizonOutlook>("/today/outlook/regenerate", {
      method: "POST",
      body: JSON.stringify({ preference: preference.trim() || null }),
    }),
    onSuccess: async () => {
      setPreference("");
      setShowPreference(false);
      await queryClient.invalidateQueries({ queryKey: ["today"] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    regenerate.mutate();
  }
  function togglePreference() {
    if (showPreference) setPreference("");
    setShowPreference(!showPreference);
  }
  return <details className={`seven-day-outlook outlook-${section}`}>
    <summary>
      <div><p className="eyebrow">Receding horizon / committed week</p><h2>{isFood ? "The next seven days of meals" : "The next seven days of exercise"}</h2></div>
      <span className="outlook-toggle"><b>View plan</b><i aria-hidden="true">+</i></span>
    </summary>
    <div className="outlook-introduction">
      <div className="outlook-copy"><p>{strategy}</p><small>{outlook.adjustment_summary}</small></div>
      <div className="outlook-regeneration">
        <small>Refreshes meals, fueling, and exercise together. Today's daily plan stays unchanged.</small>
        <div className="regeneration-actions">
          <button className="quiet small" type="button" disabled={regenerate.isPending} onClick={() => regenerate.mutate()}>{regenerate.isPending ? "Regenerating..." : "Regenerate weekly plan"}</button>
          <button className="text-button" type="button" aria-expanded={showPreference} aria-controls={preferenceId} disabled={regenerate.isPending} onClick={togglePreference}>{showPreference ? "Hide preference" : "Add preference"}</button>
        </div>
      </div>
    </div>
    {showPreference && <form className="outlook-preference-form" id={preferenceId} onSubmit={submit}>
      <label>Optional preference<textarea value={preference} maxLength={2000} onChange={(event) => setPreference(event.target.value)} placeholder={isFood ? "For example: more batch-friendly meals and simple pre-run fuel." : "For example: favor cycling this week and keep Saturday's strength session."} /></label>
      <button className="primary small" disabled={regenerate.isPending}>{regenerate.isPending ? "Regenerating..." : "Regenerate with preference"}</button>
    </form>}
    {regenerate.error && <p className="error outlook-regeneration-error" role="alert">{regenerate.error.message}</p>}
    <div className="outlook-days">
      {outlook.days.map((day, index) => {
        const formatted = new Date(`${day.plan_date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
        return <article className="outlook-day" key={`${section}-${day.plan_date}`}>
          <header><span>{String(index + 1).padStart(2, "0")}</span><div><time dateTime={day.plan_date}>{formatted}</time><small>{index === 0 ? "Adapts today" : index === 1 ? "Adaptation window" : "Committed"}</small></div></header>
          {isFood ? <>
            <h3>{day.nutrition.meal_template_names.join(" + ")}</h3>
            <p>{day.nutrition.focus}</p>
            {day.nutrition.fueling_recommendations.length > 0 && <ul>{day.nutrition.fueling_recommendations.map((item) => <li key={item}>{item}</li>)}</ul>}
            {day.nutrition.prep_note && <small className="outlook-prep">Prep: {day.nutrition.prep_note}</small>}
          </> : <>
            <div className="outlook-session-heading"><h3>{day.workout.title}</h3><span>{day.workout.expected_duration_minutes} min · {day.workout.intensity.replaceAll("_", " ")}</span></div>
            {day.workout.exercises.length > 0 ? <ul className="outlook-exercises">{day.workout.exercises.map((exercise) => <li key={exercise.exercise_name}><strong>{exercise.exercise_name}</strong><span>{exerciseText(exercise)}</span></li>)}</ul> : <p>{day.workout.summary}</p>}
          </>}
          <p className="outlook-rationale">{day.rationale}</p>
        </article>;
      })}
    </div>
    <footer><span>7 days committed</span><span>14 days considered by AI</span><span>Revision {outlook.revision}</span></footer>
  </details>;
}

export function TodayPage({ section }: { section: "food" | "exercise" }) {
  const [alternativeQuestion, setAlternativeQuestion] = useState("");
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedDate = searchParams.get("date");
  const todayPath = requestedDate ? datedPath("/today", requestedDate) : "/today";
  const today = useQuery({ queryKey: ["today", requestedDate ?? "current"], queryFn: () => api<Today>(todayPath) });
  const coachFeedback = useQuery({
    queryKey: ["coach-feedback", today.data?.date],
    queryFn: () => api<{ message: string | null }>(datedPath("/today/workout/coach-feedback", today.data!.date), { method: "POST" }),
    enabled: today.data !== undefined,
  });
  useEffect(() => {
    if (!today.data || !location.hash) return;
    const frame = requestAnimationFrame(() => document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [location.hash, today.data]);
  if (today.isLoading) return <div className="loading" role="status">Building the selected day's plan...</div>;
  if (today.error || !today.data) return <div className="error-panel" role="alert"><h1>The selected day's plan is unavailable</h1><p>{today.error?.message}</p></div>;
  const data = today.data;
  const isFood = section === "food";
  const currentDate = data.recording_dates[0] ?? data.date;
  const isHistorical = data.date !== currentDate;
  const tabSearch = isHistorical ? `?date=${encodeURIComponent(data.date)}` : "";
  const feedback = coachFeedback.data?.message ?? data.coach_feedback;
  const recordValue = searchParams.get("record");
  const recordKind: RecordKind | null = recordValue === "exercise" || recordValue === "food" ? recordValue : null;
  function setRecordKind(kind: RecordKind | null) {
    const next = new URLSearchParams(searchParams);
    if (kind) next.set("record", kind);
    else next.delete("record");
    setSearchParams(next, { replace: true });
  }
  return (
    <div className={`field-notes-edition today-${section}`}>
      <CoachFeedbackNote feedback={feedback} loading={coachFeedback.isLoading} />
      <TodayEditionHeader today={data} section={section} />
      <div className="edition-tools">
      <nav className="page-tabs" aria-label="Today's plan sections">
        <NavLink to={`/today/exercise${tabSearch}`}>Exercise</NavLink>
        <NavLink to={`/today/food${tabSearch}`}>Food</NavLink>
      </nav>
        <label className="date-selector"><span>Record date</span><select aria-label="Record date" value={data.date} onChange={(event) => setSearchParams(event.target.value === data.recording_dates[0] ? {} : { date: event.target.value })}>{data.recording_dates.map((value, index) => <option value={value} key={value}>{recordingDateLabel(value, index)}</option>)}</select></label>
      </div>
      {!isFood && <ExerciseLead today={data} />}
      <FolioRule label={isFood ? "Today's table" : "Session detail"} number="02" />
      <div className="today-grid">
        <div className="main-column">
          {isFood ? <>
            <MealCard meal={data.nutrition.meal_1} slot="Meal 1" index={1} today={data} />
            {data.nutrition.meal_2 && <MealCard meal={data.nutrition.meal_2} slot="Meal 2" index={2} today={data} />}
          </> : <>
            <WorkoutCard key={`structured-${data.date}`} today={data} onAskAlternative={isHistorical ? undefined : () => setAlternativeQuestion("Please propose a safe measurable alternative to today's workout.")} />
          </>}
        </div>
        <aside className="side-column">
          {isFood ? <>
            {!isHistorical && <MealRegenerationCard today={data} />}
            <section className="card compact"><p className="eyebrow">{data.food_log ? "Original fruit suggestions" : "Fruit"}</p>{data.nutrition.fruits.map((fruit) => <div className="list-item" key={fruit.recommendation_id}><strong>{fruit.name} · {fruit.quantity} <StatusPill status={data.nutrition_status[fruit.recommendation_id]?.status ?? "planned"} /></strong><NutritionSuggestionActions recommendationId={fruit.recommendation_id} today={data} /></div>)}</section>
            <section className="card compact"><p className="eyebrow">{data.food_log ? "Original optional suggestions" : "Optional"}</p>{data.nutrition.snacks.map((snack) => <div className="list-item" key={snack.recommendation_id}><strong>{snack.name} <StatusPill status={data.nutrition_status[snack.recommendation_id]?.status ?? "planned"} /></strong><small>{snack.description}</small><NutritionSuggestionActions recommendationId={snack.recommendation_id} today={data} /></div>)}</section>
            <section className="card emergency-plate-card"><p className="eyebrow">Always-available fallback</p><h3>{data.emergency_plate.name}</h3><p>{data.emergency_plate.description}</p><div className="meta"><span>{data.emergency_plate.estimated_protein_g} g protein</span><span>{data.emergency_plate.hands_on_minutes} active min</span></div><div className="emergency-ingredients">{data.emergency_plate.ingredients.map((ingredient) => <small key={ingredient.name}><strong>{ingredient.quantity}</strong> {ingredient.name}</small>)}</div><p className="emergency-preparation">{data.emergency_plate.preparation}</p></section>
          </> : <>{!isHistorical && <WorkoutRegenerationCard today={data} />}<section className="card compact"><p className="eyebrow">Current target</p><h3>{data.current_target_goal ?? "No active target configured"}</h3>{data.current_target_goal && <><p>{data.rationale.summary}</p><strong>How today progresses it</strong><p>{data.rationale.progression_logic}</p></>}</section></>}
          <section className="card action-card"><p className="eyebrow">Next action</p><h3>{data.next_action?.action ?? "Nothing to prepare"}</h3>{data.next_action && <p>{data.next_action.when} · {data.next_action.active_minutes} active min</p>}</section>
          {isFood && <section className="card compact"><p className="eyebrow">Shopping</p><p>{data.shopping.summary}</p></section>}
        </aside>
      </div>
      <ChatPanel key={`${data.date}-${alternativeQuestion}`} initialQuestion={alternativeQuestion} canAsk={!isHistorical} selectedDate={data.date} />
      {!isHistorical && data.outlook && <SevenDayOutlook outlook={data.outlook} section={section} />}
      <RecordSheet today={data} kind={recordKind} onKindChange={(kind) => setRecordKind(kind)} onClose={() => setRecordKind(null)} />
    </div>
  );
}
