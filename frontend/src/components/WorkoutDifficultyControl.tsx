import type { CSSProperties } from "react";

export function WorkoutDifficultyControl({
  inputId,
  exerciseName,
  label,
  value,
  disabled = false,
  onChange,
}: {
  inputId: string;
  exerciseName: string;
  label: string;
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  const progress = `${((value - 1) / 9) * 100}%`;
  return <label className="exercise-difficulty-control" htmlFor={inputId}>
    <span><b>{label}</b><output htmlFor={inputId}>{value}<small>/10</small></output></span>
    <input
      id={inputId}
      aria-label={`Difficulty for ${exerciseName}`}
      type="range"
      min="1"
      max="10"
      step="1"
      value={value}
      style={{ "--difficulty-progress": progress } as CSSProperties}
      disabled={disabled}
      onChange={(event) => onChange(Number(event.target.value))}
    />
    <span className="difficulty-scale" aria-hidden="true"><i>Easy</i><i>Hard</i></span>
  </label>;
}
