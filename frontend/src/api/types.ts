export type EntryStatus = {
  id: string;
  recommendation_id: string | null;
  status: string;
  source: string;
  description?: string;
  exercise_name?: string;
  prescription?: Record<string, unknown>;
  actual?: Record<string, unknown> | null;
  difficulty_1_to_10?: number | null;
  pain_flag?: boolean;
  quantity?: Record<string, unknown>;
  food_log_id?: string | null;
  workout_log_id?: string | null;
};

export type FoodComponent = {
  name: string;
  quantity_value: number;
  unit: "g" | "ml" | "item";
  quantity_label: string;
  catalog_food_name: string | null;
  quantity_is_assumed: boolean;
};

export type ExtractedMeal = {
  meal_name: string;
  meal_slot: "meal_1" | "meal_2" | "snack" | "fruit";
  description: string;
  portion_count: number;
  quantity_label: string;
  components: FoodComponent[];
  estimated_calories_kcal: number;
  estimated_protein_g: number;
  estimated_fiber_g: number;
  matched_recommendation_id: string | null;
  match_confidence: number;
  assumptions: string[];
};

export type DailyFoodLog = {
  id: string;
  date: string;
  raw_text: string;
  extraction: {
    ate_nothing: boolean;
    meals: ExtractedMeal[];
    summary: string;
    assumptions: string[];
  };
  model: string;
  status: string;
  updated_at: string;
};

export type ExtractedWorkout = {
  workout_name: string;
  exercise_type: "strength" | "bodyweight" | "run" | "bike" | "recovery";
  duration_seconds: number | null;
  distance_km: number | null;
  load_kg: number | null;
  external_load_kg: number | null;
  sets: number | null;
  reps_per_set: number[] | null;
  average_power_watts: number | null;
  average_heartrate_bpm: number | null;
  difficulty_1_to_10: number | null;
  pain_flag: boolean;
  notes: string | null;
  matched_recommendation_id: string | null;
  match_confidence: number;
  assumptions: string[];
};

export type DailyWorkoutLog = {
  id: string;
  date: string;
  raw_text: string;
  extraction: {
    did_no_workout: boolean;
    workouts: ExtractedWorkout[];
    summary: string;
    assumptions: string[];
  };
  model: string;
  status: string;
  updated_at: string;
};

export type StravaIntegration = {
  configured: boolean;
  connected: boolean;
  status: string;
  athlete: { id: number; name: string; profile: string | null } | null;
  scopes: string[];
  last_synced_at: string | null;
  last_error: string | null;
  activity_count: number;
};

export type Meal = {
  recommendation_id: string;
  template_name: string;
  description: string;
  suggested_window: string;
  expected: boolean;
  estimated_protein_g: number;
  estimated_fiber_g: number;
  hands_on_minutes: number;
  ingredients: string[];
  preparation: string;
};

export type Exercise = {
  recommendation_id: string;
  exercise_name: string;
  exercise_type: "strength" | "bodyweight" | "run" | "bike" | "recovery";
  load_kg?: number | null;
  external_load_kg?: number | null;
  sets?: number | null;
  reps_per_set?: number[] | null;
  rest_seconds?: number | null;
  distance_km?: number | null;
  pace_seconds_per_km?: number | null;
  duration_seconds?: number | null;
  treadmill_speed_kmh?: number | null;
  incline_percent?: number | null;
  target_power_min_watts?: number | null;
  target_power_max_watts?: number | null;
  cadence_min_rpm?: number | null;
  cadence_max_rpm?: number | null;
  expected_difficulty: number;
  instructions: string;
};

export type Today = {
  date: string;
  source: "openai" | "fallback";
  current_status: string;
  recovery_status: string;
  nutrition: {
    meal_1: Meal;
    meal_2: Meal | null;
    fruits: Array<{ recommendation_id: string; name: string; quantity: string; expected: boolean }>;
    snacks: Array<{ recommendation_id: string; name: string; description: string; expected: boolean; estimated_protein_g: number }>;
    expected_main_meals: number;
    approximate_protein_g: number;
    guidance: string;
  };
  workout: {
    kind: string;
    intensity: string;
    title: string;
    exercises: Exercise[];
    expected_duration_minutes: number;
    summary: string;
  };
  next_action: { action: string; active_minutes: number; when: string } | null;
  shopping: { action_needed: boolean; summary: string };
  nutrition_status: Record<string, EntryStatus>;
  workout_status: Record<string, EntryStatus>;
  food_log: DailyFoodLog | null;
  actual_nutrition: EntryStatus[];
  workout_log: DailyWorkoutLog | null;
  actual_workouts: EntryStatus[];
  emergency_plate: {
    name: string;
    description: string;
    estimated_protein_g: number;
    estimated_fiber_g: number;
    hands_on_minutes: number;
    ingredients: Array<{ name: string; quantity: string }>;
    preparation: string;
  };
};

export type Profile = {
  timezone: string;
  location: string;
  weight_kg: number | null;
  height_cm: number | null;
  age: number | null;
  sex: string | null;
  body_composition_goal: string | null;
  primary_training_goal: string;
  max_main_meals_per_day: number;
  preferred_main_meals_per_day: number;
  max_exercises_per_day: number;
  gym_days: string[];
  office_days: string[];
  excluded_exercises: string[];
  nutrition_preferences: Record<string, unknown>;
  allergies: string[];
  medical_constraints: string[];
  strength_capacity_json: Record<string, unknown>;
  endurance_capacity_json: Record<string, unknown>;
  kitchen_equipment_json: Array<{ name: string; owned: boolean | null }>;
};

export type Equipment = {
  id: string;
  name: string;
  category: string;
  details_json: Record<string, unknown>;
  available: boolean;
};
