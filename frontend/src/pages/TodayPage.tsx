import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import type { Exercise, ExtractedWorkout, Meal, StravaSyncResult, Today, WorkoutLogExtraction } from "../api/types";
import { StatusPill } from "../components/StatusPill";

function pace(seconds?: number | null): string {
  if (!seconds) return "";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}/km`;
}

function exerciseText(exercise: Exercise): string {
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

function MealCard({ meal, slot, today }: { meal: Meal; slot: string; today: Today }) {
  const queryClient = useQueryClient();
  const status = today.nutrition_status[meal.recommendation_id]?.status ?? "planned";
  const foodLogLocked = today.food_log !== null;
  const action = useMutation({
    mutationFn: (kind: "confirm" | "skip") =>
      api(`/today/nutrition/${meal.recommendation_id}/${kind}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["today"] }),
  });
  return (
    <section className="card meal-card">
      <div className="card-heading"><p className="eyebrow">{foodLogLocked ? `Original suggestion · ${slot}` : slot}</p><StatusPill status={status} /></div>
      <h2>{meal.template_name}</h2>
      <p>{meal.description}</p>
      <div className="meta"><span>{meal.estimated_protein_g} g protein</span><span>{meal.hands_on_minutes} active min</span><span>{meal.suggested_window}</span></div>
      <div className="actions">
        <button className="primary small" disabled={foodLogLocked || action.isPending || status === "confirmed"} onClick={() => action.mutate("confirm")}>Done</button>
        <button className="quiet small" disabled={foodLogLocked || action.isPending} onClick={() => action.mutate("skip")}>Skip</button>
      </div>
      {foodLogLocked && <p className="locked-note">Actions are locked because today's food text is the actual record.</p>}
      {action.error && <p className="error">{action.error.message}</p>}
    </section>
  );
}

function FoodLogCard({ today }: { today: Today }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(today.food_log?.raw_text ?? "");
  const foodLog = today.food_log;
  const save = useMutation({
    mutationFn: () => api("/today/nutrition/food-log", {
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
    <section className="card food-log-card">
      <div className="card-heading"><p className="eyebrow">What I ate today</p>{foodLog && <StatusPill status="processed" />}</div>
      <h2>Record the day in your own words</h2>
      <p>Submitting this text treats it as the actual record, discards today's food suggestions, and uses AI to estimate average portions and nutrients.</p>
      <form onSubmit={submit}>
        <label>Food and drinks<textarea value={text} maxLength={5000} onChange={(event) => setText(event.target.value)} placeholder="Chicken curry with rice, two kiwis, and a bowl of skyr." /></label>
        <div className="food-log-submit"><small>Only this text, today's food suggestions, and the food catalog are sent for analysis. Your workout is unaffected.</small><button className="primary" disabled={save.isPending || !text.trim()}>{save.isPending ? "Analyzing..." : foodLog ? "Re-analyze and replace record" : "Analyze and record"}</button></div>
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
  const meals = [today.nutrition.meal_1, today.nutrition.meal_2].filter((meal): meal is Meal => meal !== null);
  const unresolved = meals.every((meal) => (today.nutrition_status[meal.recommendation_id]?.status ?? "planned") === "planned");
  const regenerate = useMutation({
    mutationFn: () => api("/today/nutrition/regenerate", { method: "POST" }),
    onSuccess: async () => {
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
  return (
    <section className="card meal-regeneration-card">
      <div><p className="eyebrow">Scheduled meals</p><strong>Want fresh recommendations?</strong><small>Generate different catalog meals while keeping today's workout unchanged.</small>{disabledReason && <small>{disabledReason}</small>}</div>
      <button className="quiet" disabled={regenerate.isPending || disabledReason !== null} onClick={() => regenerate.mutate()}>{regenerate.isPending ? "Regenerating..." : "Regenerate meals"}</button>
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
      <label className="checkbox"><input type="checkbox" checked={workout.pain_flag} onChange={(event) => onChange({ pain_flag: event.target.checked })} /> Pain occurred</label>
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
    mutationFn: () => api<{ raw_text: string; extraction: WorkoutLogExtraction }>("/today/workout/log/analyze", {
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
      return api("/today/workout/log", {
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
      ]);
    },
  });
  const retrieveStrava = useMutation({
    mutationFn: () => api<StravaSyncResult>("/integrations/strava/sync-today", { method: "POST" }),
    onSuccess: async (result) => {
      setStravaMessage(result.fetched ? `Retrieved ${result.fetched} ${result.fetched === 1 ? "activity" : "activities"} from Strava.` : "No Strava activities were found for today.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["today"] }),
        queryClient.invalidateQueries({ queryKey: ["history"] }),
        queryClient.invalidateQueries({ queryKey: ["strava"] }),
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
    <section className="card workout-log-card">
      <div className="card-heading"><div><p className="eyebrow">What I trained today</p>{workoutLog && <StatusPill status="processed" />}</div><button type="button" className="quiet small" disabled={retrieveStrava.isPending} onClick={() => { setStravaMessage(""); retrieveStrava.mutate(); }}>{retrieveStrava.isPending ? "Retrieving..." : "Retrieve from Strava"}</button></div>
      <h2>Describe the workout in your own words</h2>
      <p>Analyze your description, review every extracted exercise, make any corrections, and submit only when the record is accurate.</p>
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
  const unresolved = today.workout.exercises.every((exercise) => (today.workout_status[exercise.recommendation_id]?.status ?? "planned") === "planned");
  const hasRecordedExercise = today.actual_workouts.some((entry) => entry.status === "completed" || entry.actual);
  const regenerate = useMutation({
    mutationFn: () => api("/today/workout/regenerate", { method: "POST" }),
    onSuccess: async () => {
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
  return (
    <section className="card workout-regeneration-card">
      <div><p className="eyebrow">Refresh today's recommendation</p><strong>Use the latest activity history</strong><small>When Strava is connected, yesterday is retrieved first. The planner then rebuilds only today's exercise recommendation from the refreshed 28-day history.</small>{disabledReason && <small>{disabledReason}</small>}</div>
      <button type="button" className="quiet" disabled={regenerate.isPending || disabledReason !== null} onClick={() => regenerate.mutate()}>{regenerate.isPending ? "Regenerating..." : "Regenerate exercise"}</button>
      {regenerate.error && <p className="error">{regenerate.error.message}</p>}
    </section>
  );
}

function WorkoutCard({ today, onAskAlternative }: { today: Today; onAskAlternative: () => void }) {
  const queryClient = useQueryClient();
  const [difficulty, setDifficulty] = useState(5);
  const [pain, setPain] = useState(false);
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
            duration_seconds: Math.round(Number(second) * 60),
          };
        } else {
          results[exercise.recommendation_id] = {
            duration_seconds: Math.round(Number(first) * 60),
            average_power_watts: second ? Number(second) : null,
          };
        }
      }
      return api("/today/workout/complete", {
        method: "POST",
        body: JSON.stringify({ results, difficulty_1_to_10: difficulty, pain_flag: pain, notes: notes || null }),
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["today"] }),
  });
  const skip = useMutation({
    mutationFn: () => api("/today/workout/skip", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["today"] }),
  });
  if (today.workout.kind === "rest") {
    return <section className="card workout-card"><p className="eyebrow">Training</p><h2>Rest</h2><p>{today.workout.summary}</p></section>;
  }
  return (
    <section className="card workout-card">
      <div className="card-heading"><p className="eyebrow">Training</p><span className="difficulty">Expected {today.workout.exercises[0]?.expected_difficulty}/10</span></div>
      <h2>{today.workout.title}</h2>
      {today.workout.exercises.map((exercise) => {
        const status = today.workout_status[exercise.recommendation_id]?.status ?? "planned";
        const recorded = today.workout_status[exercise.recommendation_id];
        const strength = exercise.exercise_type === "strength" || exercise.exercise_type === "bodyweight";
        return (
          <div className="exercise" key={exercise.recommendation_id}>
            <div><strong>{exercise.exercise_name}</strong> <StatusPill status={status} /></div>
            <p className="prescription">{exerciseText(exercise)}</p><p>{exercise.instructions}</p>
            {recorded?.actual && <p className="recorded-actual"><strong>{recorded.source === "strava" ? "Recorded by Strava" : "Recorded actual"}:</strong> {actualWorkoutText(recorded.actual)}</p>}
            <div className="actual-grid">
              <label>{strength ? "Actual load kg" : exercise.exercise_type === "run" ? "Actual distance km" : "Actual minutes"}<input value={values[`${exercise.recommendation_id}:first`] ?? ""} onChange={(event) => setValues({ ...values, [`${exercise.recommendation_id}:first`]: event.target.value })} placeholder={strength ? String(exercise.load_kg ?? exercise.external_load_kg ?? 0) : String(exercise.distance_km ?? Math.round((exercise.duration_seconds ?? 0) / 60))} /></label>
              <label>{strength ? "Actual reps, comma separated" : exercise.exercise_type === "run" ? "Actual minutes" : "Average power, optional"}<input value={values[`${exercise.recommendation_id}:second`] ?? ""} onChange={(event) => setValues({ ...values, [`${exercise.recommendation_id}:second`]: event.target.value })} placeholder={strength ? exercise.reps_per_set?.join(",") : exercise.exercise_type === "run" ? String(Math.round((exercise.duration_seconds ?? 0) / 60)) : "watts"} /></label>
            </div>
          </div>
        );
      })}
      <div className="completion-row">
        <label>Difficulty <strong>{difficulty}/10</strong><input type="range" min="1" max="10" value={difficulty} onChange={(event) => setDifficulty(Number(event.target.value))} /></label>
        <label className="checkbox"><input type="checkbox" checked={pain} onChange={(event) => setPain(event.target.checked)} /> Pain occurred</label>
      </div>
      <label>Notes, optional<textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      <div className="actions">
        <button className="primary small" onClick={() => complete.mutate()} disabled={complete.isPending || workoutLogLocked}>Save completion</button>
        <button className="quiet small" onClick={() => skip.mutate()} disabled={skip.isPending || workoutLogLocked}>Skip workout</button>
        <button className="quiet small" onClick={onAskAlternative}>Ask for an alternative</button>
      </div>
      {workoutLogLocked && <p className="locked-note">Structured actions are locked because today's workout text is the actual record.</p>}
      {(complete.error || skip.error) && <p className="error">{complete.error?.message ?? skip.error?.message}</p>}
    </section>
  );
}

function ChatPanel({ initialQuestion }: { initialQuestion: string }) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState(initialQuestion);
  const ask = useMutation({
    mutationFn: () => api<{ message_id: string; answer: string; proposed_change: Record<string, unknown> | null }>("/today/questions", { method: "POST", body: JSON.stringify({ question }) }),
  });
  const apply = useMutation({
    mutationFn: (messageId: string) => api(`/today/recommendations/${messageId}/apply-change`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["today"] }),
  });
  function submit(event: FormEvent) { event.preventDefault(); if (question.trim()) ask.mutate(); }
  return (
    <section className="card chat-card">
      <p className="eyebrow">Ask about today's plan</p>
      <form onSubmit={submit}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Why this pace? Can I use the KICKR instead?" /><button className="primary small" disabled={ask.isPending}>Ask AI</button></form>
      {ask.data && <div className="ai-answer"><p>{ask.data.answer}</p>{ask.data.proposed_change && <><pre>{JSON.stringify(ask.data.proposed_change, null, 2)}</pre><button className="primary small" onClick={() => apply.mutate(ask.data.message_id)}>Apply this change</button></>}</div>}
      {(ask.error || apply.error) && <p className="error">{ask.error?.message ?? apply.error?.message}</p>}
    </section>
  );
}

export function TodayPage({ section }: { section: "food" | "exercise" }) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [alternativeQuestion, setAlternativeQuestion] = useState("");
  const today = useQuery({ queryKey: ["today"], queryFn: () => api<Today>("/today") });
  const details = useQuery({ queryKey: ["today-details"], queryFn: () => api<{ plan: Record<string, unknown>; original_plan: Record<string, unknown> }>("/today/details"), enabled: detailsOpen });
  if (today.isLoading) return <div className="loading">Building today's plan...</div>;
  if (today.error || !today.data) return <div className="error-panel"><h1>Today's plan is unavailable</h1><p>{today.error?.message}</p></div>;
  const data = today.data;
  const isFood = section === "food";
  return (
    <>
      <header className="page-header"><div><p className="eyebrow">{new Date(`${data.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p><h1>{isFood ? "Food & nutrition" : "Exercise"}</h1></div><span className={`source source-${data.source}`}>{data.source === "openai" ? "AI planned" : "Reliable fallback"}</span></header>
      <nav className="page-tabs" aria-label="Today's plan sections">
        <NavLink to="/today/food">Food & nutrition</NavLink>
        <NavLink to="/today/exercise">Exercise</NavLink>
      </nav>
      <div className="today-grid">
        <div className="main-column">
          {isFood ? <>
            <FoodLogCard key={`food-${data.date}`} today={data} />
            <MealRegenerationCard today={data} />
            <MealCard meal={data.nutrition.meal_1} slot="Meal 1" today={data} />
            {data.nutrition.meal_2 && <MealCard meal={data.nutrition.meal_2} slot="Meal 2" today={data} />}
          </> : <>
            <WorkoutRegenerationCard today={data} />
            <WorkoutCard today={data} onAskAlternative={() => setAlternativeQuestion("Please propose a safe measurable alternative to today's workout.")} />
            <WorkoutLogCard key={`workout-${data.date}`} today={data} />
            {data.actual_workouts.filter((entry) => entry.source === "strava").length > 0 && <section className="card"><p className="eyebrow">Other Strava activities today</p>{data.actual_workouts.filter((entry) => entry.source === "strava").map((entry) => <div className="recorded-activity" key={entry.id}><div><strong>{entry.exercise_name}</strong><StatusPill status={entry.status} /></div><small>{actualWorkoutText(entry.actual)}</small></div>)}</section>}
          </>}
        </div>
        <aside className="side-column">
          <section className="card compact"><p className="eyebrow">Current status</p><h3>{data.current_status}</h3><p>Recovery: {data.recovery_status.replaceAll("_", " ")}</p></section>
          {isFood ? <>
            <section className="card compact"><p className="eyebrow">{data.food_log ? "Original fruit suggestions" : "Fruit"}</p><div className="chips">{data.nutrition.fruits.map((fruit) => <span key={fruit.recommendation_id}>{fruit.name} · {fruit.quantity} <StatusPill status={data.nutrition_status[fruit.recommendation_id]?.status ?? "planned"} /></span>)}</div></section>
            <section className="card compact"><p className="eyebrow">{data.food_log ? "Original optional suggestions" : "Optional"}</p>{data.nutrition.snacks.map((snack) => <div className="list-item" key={snack.recommendation_id}><strong>{snack.name} <StatusPill status={data.nutrition_status[snack.recommendation_id]?.status ?? "planned"} /></strong><small>{snack.description}</small></div>)}</section>
            <section className="card emergency-plate-card"><p className="eyebrow">Always-available fallback</p><h3>{data.emergency_plate.name}</h3><p>{data.emergency_plate.description}</p><div className="meta"><span>{data.emergency_plate.estimated_protein_g} g protein</span><span>{data.emergency_plate.hands_on_minutes} active min</span></div><div className="emergency-ingredients">{data.emergency_plate.ingredients.map((ingredient) => <small key={ingredient.name}><strong>{ingredient.quantity}</strong> {ingredient.name}</small>)}</div><p className="emergency-preparation">{data.emergency_plate.preparation}</p></section>
          </> : <section className="card compact"><p className="eyebrow">Today's training</p><h3>{data.workout.title}</h3><p>{data.workout.summary}</p><div className="meta"><span>{data.workout.intensity.replaceAll("_", " ")}</span><span>{data.workout.expected_duration_minutes} min</span></div></section>}
          <section className="card action-card"><p className="eyebrow">Next action</p><h3>{data.next_action?.action ?? "Nothing to prepare"}</h3>{data.next_action && <p>{data.next_action.when} · {data.next_action.active_minutes} active min</p>}</section>
          {isFood && <section className="card compact"><p className="eyebrow">Shopping</p><p>{data.shopping.summary}</p></section>}
        </aside>
      </div>
      <ChatPanel key={alternativeQuestion} initialQuestion={alternativeQuestion} />
      <section className="details-section"><button className="text-button" onClick={() => setDetailsOpen(!detailsOpen)}>{detailsOpen ? "Hide advanced details" : "Why these recommendations? View advanced details"}</button>{detailsOpen && details.data && <div className="card details-card"><pre>{JSON.stringify(details.data.plan, null, 2)}</pre></div>}</section>
    </>
  );
}
