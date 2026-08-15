import type { Exercise, Today } from "../../api/types";

type FigureKind = Exercise["exercise_type"] | "rest" | "mixed";

function figureKind(today: Today): FigureKind {
  if (today.workout.kind === "rest" || today.workout.exercises.length === 0) return "rest";
  const kinds = new Set(today.workout.exercises.map((exercise) => exercise.exercise_type));
  return kinds.size > 1 ? "mixed" : today.workout.exercises[0]!.exercise_type;
}

function pace(seconds?: number | null): string | null {
  if (!seconds) return null;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} /km`;
}

function facts(exercise?: Exercise): Array<{ label: string; value: string }> {
  if (!exercise) return [];
  const values: Array<{ label: string; value: string } | null> = [
    exercise.distance_km != null ? { label: "Distance", value: `${exercise.distance_km.toFixed(1)} km` } : null,
    pace(exercise.pace_seconds_per_km) ? { label: "Pace", value: pace(exercise.pace_seconds_per_km)! } : null,
    exercise.duration_seconds != null ? { label: "Duration", value: `${Math.round(exercise.duration_seconds / 60)} min` } : null,
    exercise.load_kg != null ? { label: "Load", value: `${exercise.load_kg} kg` } : null,
    exercise.external_load_kg != null ? { label: "External load", value: `${exercise.external_load_kg} kg` } : null,
    exercise.sets != null ? { label: "Sets", value: String(exercise.sets) } : null,
    exercise.reps_per_set?.length ? { label: "Repetitions", value: exercise.reps_per_set.join(" / ") } : null,
    exercise.target_power_min_watts != null ? {
      label: "Power",
      value: exercise.target_power_max_watts != null
        ? `${exercise.target_power_min_watts}-${exercise.target_power_max_watts} W`
        : `${exercise.target_power_min_watts} W`,
    } : null,
    exercise.cadence_min_rpm != null ? {
      label: "Cadence",
      value: exercise.cadence_max_rpm != null
        ? `${exercise.cadence_min_rpm}-${exercise.cadence_max_rpm} rpm`
        : `${exercise.cadence_min_rpm} rpm`,
    } : null,
  ];
  return values.filter((value): value is { label: string; value: string } => value !== null).slice(0, 3);
}

function Graphic({ kind }: { kind: FigureKind }) {
  if (kind === "run") return <svg viewBox="0 0 530 600" aria-hidden="true"><path className="figure-faint" d="M43 481C124 503 142 414 213 438c79 27 83-79 157-67 46 8 78-30 112-78" /><path className="figure-faint" d="M15 534C104 560 149 475 231 491c89 18 92-84 175-65 52 12 94-39 123-87" /><path className="figure-route" d="M77 503C114 470 86 418 144 401c48-15 38-90 99-94 78-5 45-118 128-121 45-2 76 30 108 0" /><circle className="figure-endpoint" cx="77" cy="503" r="7" /><circle className="figure-endpoint" cx="479" cy="186" r="7" /></svg>;
  if (kind === "bike") return <svg viewBox="0 0 560 560" aria-hidden="true"><circle className="figure-route" cx="158" cy="358" r="112" /><circle className="figure-route" cx="418" cy="358" r="112" /><path className="figure-route" d="M158 358l105-8 69-126 86 134M263 350l-57-126h87m-30 126 155 8M325 224h70" /><circle className="figure-endpoint" cx="263" cy="350" r="8" /><path className="figure-faint" d="M65 169h88M65 142h135M65 115h176" /></svg>;
  if (kind === "strength") return <svg viewBox="0 0 560 560" aria-hidden="true"><path className="figure-faint" d="M36 130v300M524 130v300M74 170h412M74 390h412" /><path className="figure-route" d="M104 280h352M151 218v124M181 238v84M409 218v124M379 238v84" /><rect className="figure-route" x="77" y="251" width="28" height="58" /><rect className="figure-route" x="456" y="251" width="28" height="58" /><circle className="figure-endpoint" cx="280" cy="280" r="7" /><path className="figure-faint" d="M202 430h156" /></svg>;
  if (kind === "bodyweight") return <svg viewBox="0 0 560 560" aria-hidden="true"><circle className="figure-route" cx="280" cy="122" r="42" /><path className="figure-route" d="M280 164v139m0-85-92 74m92-74 92 74m-92 11-84 134m84-134 84 134" /><circle className="figure-endpoint" cx="280" cy="303" r="7" /><path className="figure-faint" d="M104 462h352M123 489h314" /></svg>;
  if (kind === "recovery") return <svg viewBox="0 0 560 560" aria-hidden="true"><path className="figure-route" d="M80 352c92-185 309-185 400 0" /><path className="figure-faint" d="M116 379c72-130 257-130 328 0M154 411c55-79 198-79 252 0M280 82v82M122 150l58 58m258-58-58 58" /><circle className="figure-endpoint" cx="280" cy="230" r="10" /></svg>;
  if (kind === "mixed") return <svg viewBox="0 0 560 560" aria-hidden="true"><circle className="figure-faint" cx="280" cy="280" r="190" /><circle className="figure-faint" cx="280" cy="280" r="130" /><path className="figure-route" d="M90 342c78 17 111-72 179-48 87 31 102-97 201-91M121 195h114m-57-57v114M331 383h108m-54-54v108" /><circle className="figure-endpoint" cx="90" cy="342" r="7" /><circle className="figure-endpoint" cx="470" cy="203" r="7" /></svg>;
  return <svg viewBox="0 0 560 560" aria-hidden="true"><circle className="figure-faint" cx="280" cy="280" r="184" /><circle className="figure-faint" cx="280" cy="280" r="126" /><circle className="figure-route" cx="280" cy="280" r="58" /><path className="figure-route" d="M280 40v82m0 316v82M40 280h82m316 0h82" /><circle className="figure-endpoint" cx="280" cy="280" r="7" /></svg>;
}

export function ExerciseFigure({ today }: { today: Today }) {
  const kind = figureKind(today);
  const first = today.workout.exercises[0];
  const displayFacts = facts(first);
  const primaryFact = displayFacts[0] ?? {
    label: "Session",
    value: today.workout.kind === "rest" ? "Rest" : today.workout.title,
  };
  const label = kind === "rest"
    ? "A quiet schematic for today's rest day"
    : `A schematic representing today's ${kind} session`;
  return <figure className={`exercise-figure exercise-figure-${kind}`}>
    <div className="exercise-graphic" role="img" aria-label={label}>
      <Graphic kind={kind} />
      <div className="figure-primary">
        <strong>{primaryFact.value}</strong>
        <span>{primaryFact.label}</span>
      </div>
      <div className="figure-facts">
        {displayFacts.slice(1).map((fact) => <span key={fact.label}><small>{fact.label}</small><strong>{fact.value}</strong></span>)}
      </div>
    </div>
    <figcaption><span>Fig. 01</span> {label}. The drawing is illustrative and contains no route data.</figcaption>
  </figure>;
}
