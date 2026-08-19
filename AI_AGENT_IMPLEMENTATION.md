# AI Agent Implementation Instructions — Personal Health & Hybrid Training Autopilot

## 0. Mission

Build a production-quality **single-user personal health autopilot** in one GitHub repository.

The application must:

1. Generate a simple, actionable daily nutrition and exercise plan.
2. Maintain a complete editable history of planned vs. actual nutrition and training.
3. Adapt future recommendations using that history.
4. Minimize user effort and decision fatigue.
5. Use a Python/FastAPI backend as the source of truth and decision engine.
6. Use OpenAI models through the OpenAI API for high-quality planning, interpretation, explanations, and contextual Q&A.
7. Keep hard constraints and state transitions deterministic in Python rather than relying on the LLM.
8. Provide:
   - a hosted React web app,
   - a Chrome extension,
   - morning and evening emails.
9. Support both a **simple recommendation view** and a **detailed/advanced view** derived from the same canonical plan.
10. Stay intentionally lean. Do not overengineer the architecture or test suite.

The project should feel like an **autopilot**, not a traditional calorie tracker or fitness dashboard.

---

# 1. Agent Operating Instructions

Implement the application rather than merely scaffolding it.

Follow these priorities, in order:

1. Correct domain rules and history handling.
2. A clean, understandable data model.
3. Reliable planner context construction.
4. Strict validation of AI output.
5. Low-friction UX.
6. Scheduled emails and daily reconciliation.
7. Shopping and inventory support.
8. Advanced explanations and AI Q&A.
9. Minimal but meaningful tests.
10. Cosmetic refinements.

Do not introduce infrastructure unless the current requirements need it.

Specifically, do **not** add these in v1:

- Kubernetes
- Kafka
- RabbitMQ
- a microservice architecture
- GraphQL
- a vector database
- a separate analytics database
- elaborate event sourcing
- Redux unless React state actually becomes complex enough to justify it
- a full end-to-end testing framework unless a concrete problem requires it
- retailer checkout automation
- a mobile app

Prefer simple, explicit code over generalized frameworks.

When a small amount of duplication makes the system easier to understand than a premature abstraction, prefer the small duplication.

---

# 2. Known User Profile and Hard Constraints

Seed the initial profile with the following values, while making all user-editable from Settings.

## Location and schedule

- Location: Zurich, Switzerland
- Timezone: `Europe/Zurich`
- Thursday is an office day.
- Thursday commute is approximately 3 hours total.
- Thursday should default to:
  - rest, or at most very light exercise,
  - high nutrition flexibility because the user often eats with colleagues.
- Gym-specific recommendations may only occur on:
  - Saturday
  - Sunday

## Body and current capacity

- Weight: 90 kg
- Height: 180 cm
- Relatively muscular
- Current bench press capacity:
  - approximately 100 kg for 5–8 reps
- Current strict pull-up capacity:
  - more than 10 reps

Do not invent missing performance values such as deadlift 1RM, FTP, running threshold, or recent 10K time. Store unknowns as unknown.

## Training goal

Primary goal:

> Become a very strong hybrid athlete who can retain substantial strength while comfortably running approximately 8–12 km and developing strong general aerobic fitness.

Exercise preferences:

- Prefer compound exercises.
- Strong preference for:
  - bench press
  - deadlift
  - pull-ups
- Avoid squat-based programming by default because squats have caused waist/lower-back discomfort.
- If an exercise causes pain, do not automatically progress it.
- Maximum exercises prescribed per day: **3**.
- One-exercise training days are encouraged when they provide high value.

## Home equipment

- Wahoo KICKR BIKE SHIFT
- Decathlon RUN 500 treadmill
- Home gym bench
- Dumbbell pairs:
  - 16 kg x2
  - 20 kg x2
  - 30 kg x2
- Sportsroyals Power Tower:
  - pull-ups
  - dips
  - push-up-related work
- Gym subscription with normal commercial gym equipment

## Nutrition behavior

- Maximum main meals per day: **2**
- One main meal in a day is valid.
- Never force a breakfast/lunch/dinner model.
- Use neutral names:
  - Meal 1
  - Meal 2
- Fruit is separate from meal count.
- Snacks are separate from meal count.
- A protein smoothie can be treated as an optional snack/module rather than automatically as a formal main meal.
- Prioritize:
  - health
  - body composition support
  - athletic recovery
  - skin-supportive nutrient density
  - simplicity
  - consistency
  - very low active preparation time
- Meal prep:
  - never require more than one prep session in a day,
  - target roughly every 2 days or less often,
  - batch prep and freezing are preferred.

## Existing kitchen equipment

- High-quality blender
- Other quality kitchen gadgets, exact inventory unknown

Recommended high-value additions to surface in Settings/setup if not already owned:

- multicooker or rice cooker
- air fryer or good convection oven
- digital kitchen scale
- instant-read meat thermometer
- ~10 good freezer/microwave-safe meal containers
- large sheet pan
- good chef's knife

Do not require these to use the application.

---

# 3. Product Principles

## 3.1 One canonical plan, multiple presentations

There must be exactly **one canonical `DailyPlan`** for a date.

Do not independently ask the AI to generate a simple plan and a detailed plan.

The canonical object should contain:

- prescriptions,
- summaries,
- explanations,
- historical comparisons,
- assumptions,
- supporting metadata.

The email, Chrome extension, default React UI, and advanced React UI all render different levels of detail from that same object.

This avoids contradictory recommendations.

## 3.2 Simple by default, detail on demand

The normal daily workflow should take seconds.

Default surfaces should show only:

- short current-profile summary,
- Meal 1,
- Meal 2 if planned,
- fruit,
- optional snacks,
- workout prescription,
- next preparation action,
- shopping action if any.

The advanced React view may show:

- why each recommendation was chosen,
- historical comparisons,
- progression logic,
- nutrient information,
- assumptions,
- alternatives,
- detailed profile/capacity snapshot,
- AI Q&A.

Use progressive disclosure instead of an information-heavy default dashboard.

## 3.3 Deterministic rules beat prompt rules

The model can propose a plan.

Python must enforce hard rules.

Examples:

- `main_meal_count <= 2`
- `exercise_count <= 3`
- no gym workout Monday–Friday
- Thursday cannot contain hard training
- workout prescriptions require measurable targets
- unresolved nutrition is assumed consumed
- unresolved exercise is assumed skipped
- pain prevents automatic progression
- user edits override assumptions
- historical plans are never silently rewritten

Prompt instructions alone are not sufficient for these invariants.

## 3.4 Preserve plan vs. reality

Always retain:

- what was recommended,
- what the user actually did,
- what was assumed,
- later corrections.

Never overwrite the original prescription with actual performance.

---

# 4. Repository Structure

Use one GitHub repository.

Recommended structure:

```text
health-autopilot/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py
│   │   │   ├── today.py
│   │   │   ├── history.py
│   │   │   ├── nutrition.py
│   │   │   ├── workouts.py
│   │   │   ├── shopping.py
│   │   │   ├── chat.py
│   │   │   └── settings.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   └── logging.py
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   └── models/
│   │   ├── schemas/
│   │   │   ├── daily_plan.py
│   │   │   ├── profile.py
│   │   │   ├── nutrition.py
│   │   │   ├── workout.py
│   │   │   ├── shopping.py
│   │   │   └── chat.py
│   │   ├── services/
│   │   │   ├── planner/
│   │   │   ├── nutrition/
│   │   │   ├── training/
│   │   │   ├── inventory/
│   │   │   ├── openai/
│   │   │   └── email/
│   │   ├── jobs/
│   │   │   ├── morning_plan.py
│   │   │   ├── evening_checkin.py
│   │   │   ├── finalize_day.py
│   │   │   ├── shopping_plan.py
│   │   │   └── scheduler.py
│   │   └── main.py
│   ├── migrations/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── today/
│   │   │   ├── history/
│   │   │   ├── shopping/
│   │   │   ├── ai-chat/
│   │   │   └── settings/
│   │   └── pages/
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── extension/
│   ├── src/
│   │   ├── popup/
│   │   ├── api/
│   │   └── auth/
│   ├── manifest.json
│   └── package.json
├── scripts/
│   ├── seed_foods.py
│   ├── seed_exercises.py
│   └── dev_setup.sh
├── docs/
│   └── architecture.md
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

Keep backend, frontend, and extension clearly separated.

Do not create separate repositories.

---

# 5. Technology Choices

## Backend

Use:

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- official OpenAI Python SDK
- pytest for the small backend test suite

Use UTC internally for timestamps, but all daily scheduling and date boundaries must use `Europe/Zurich`.

## Frontend

Use:

- React
- TypeScript
- Vite
- React Router
- lightweight API/data-fetching approach

TanStack Query is acceptable if useful, but do not add a large client-state stack unnecessarily.

## Chrome extension

Use:

- Manifest V3
- TypeScript
- small React popup if convenient
- direct calls to the FastAPI backend

The extension is primarily a read/quick-action interface, not a second full application.

## Email

Implement an `EmailService` abstraction.

Support SMTP configuration in v1 so the application is not tied to one commercial provider.

Environment examples:

```text
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_TLS=
```

Keep it easy to replace with another provider later.

---

# 6. Configuration

Use environment variables and a Pydantic settings object.

At minimum:

```text
DATABASE_URL=
APP_BASE_URL=
API_BASE_URL=

APP_TIMEZONE=Europe/Zurich

OPENAI_API_KEY=
OPENAI_PLANNER_MODEL=
OPENAI_QA_MODEL=
OPENAI_REASONING_EFFORT=

SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_TLS=

SESSION_SECRET=
EXTENSION_API_TOKEN=

COOP_ONLINE_MINIMUM_CHF=100
MIGROS_ONLINE_MINIMUM_CHF=100
```

Do not commit secrets.

Do not hardcode an OpenAI model ID throughout the codebase. Model choice must be configurable.

---

# 7. Core Database Model

Use conventional normalized relational tables.

The exact column layout may evolve, but preserve these concepts.

## 7.1 `user_profile`

Fields should include:

```text
id
timezone
location
weight_kg
height_cm
age                    nullable until supplied
sex                    nullable until supplied
body_composition_goal  nullable/configurable
primary_training_goal
max_main_meals_per_day
preferred_main_meals_per_day
max_exercises_per_day
gym_days
office_days
excluded_exercises
nutrition_preferences
allergies
medical_constraints
created_at
updated_at
```

Seed:

```text
timezone = Europe/Zurich
location = Zurich
weight_kg = 90
height_cm = 180
max_main_meals_per_day = 2
preferred_main_meals_per_day = 2
max_exercises_per_day = 4
gym_days = [Saturday, Sunday]
office_days = [Thursday]
excluded_exercises includes squat-based programming by default
```

Keep unknown personal information unknown.

## 7.2 `equipment`

Represent available exercise/kitchen equipment.

Exercise examples:

- treadmill
- KICKR bike
- bench
- DB 16 pair
- DB 20 pair
- DB 30 pair
- pull-up/dip tower
- commercial gym access

## 7.3 `food_item`

Suggested fields:

```text
id
name
category
protein_g_per_100
carbs_g_per_100
fat_g_per_100
fiber_g_per_100
calories_per_100
typical_unit
shelf_life_days
freezer_friendly
retailer_notes
active
```

Approximate nutrition data is acceptable for planning. Do not imply laboratory precision.

## 7.4 `meal_template`

Important fields:

```text
id
name
description
ingredients
servings
hands_on_minutes
total_minutes
batch_size
fridge_life_days
freezer_friendly
reheat_method
estimated_protein_g
estimated_fiber_g
produce_portions
effort_score
preference_score
tags
active
```

## 7.5 `exercise`

Fields:

```text
id
name
category
equipment_required
gym_only
compound
measurement_type
pain_exclusion_tags
active
```

Categories may include:

- strength
- run
- bike
- bodyweight
- recovery

## 7.6 `daily_plan`

Store the canonical plan.

Suggested fields:

```text
id
plan_date
profile_snapshot_id
planner_run_id
status
short_summary
canonical_plan_json
created_at
updated_at
```

Use relational child tables if helpful, but keeping the validated immutable recommendation payload in JSONB is useful for auditing.

## 7.7 `nutrition_entry`

Suggested fields:

```text
id
entry_date
meal_slot
planned_recommendation_id
food_or_meal_reference
description
quantity
source
status
created_at
updated_at
```

Enums:

```text
source:
- recommended
- manual
- history_correction

status:
- planned
- assumed_consumed
- confirmed
- skipped
```

`meal_slot` examples:

- meal_1
- meal_2
- fruit
- snack

## 7.8 `workout_entry`

Store prescription and actual result separately.

Fields:

```text
id
entry_date
planned_recommendation_id
exercise_id
prescription_json
actual_json
difficulty_1_to_10
status
source
pain_flag
notes
created_at
updated_at
```

Statuses:

```text
planned
completed
skipped
skipped_assumed
partial
```

Never mark a workout complete unless the user explicitly records evidence of completion.

## 7.9 `profile_snapshot`

Capture what the system believed at recommendation time.

Fields/concepts:

```text
id
snapshot_date
weight_kg
training_status
strength_capacity_json
endurance_capacity_json
recent_training_summary_json
recent_nutrition_summary_json
recovery_status
adherence_summary
important_constraints_json
current_priorities_json
short_summary
detailed_summary
source_quality_json
created_at
```

The `source_quality_json` should distinguish:

- recorded
- calculated
- estimated
- goal

## 7.10 `planning_run`

Store enough data to audit planner decisions:

```text
id
plan_date
model
planner_version
context_snapshot_json
model_output_json
validation_result_json
created_at
```

Do not store hidden chain-of-thought.

Store only application-facing rationale and decision data.

## 7.11 `shopping_plan`

Fields:

```text
id
week_start
retailer
mode
estimated_total_chf
items_json
status
created_at
updated_at
```

Modes:

```text
online
in_store
mixed
```

## 7.12 `inventory_item`

Keep inventory approximate.

Suggested fields:

```text
id
food_item_id
quantity_estimate
unit
confidence
expires_on
location
updated_at
```

Confidence can be:

```text
high
medium
low
```

Avoid requiring exact gram-by-gram stock management.

## 7.13 `notification_event`

Use for idempotency and audit:

```text
id
event_type
event_date
sent_at
status
metadata_json
```

Unique constraints should prevent duplicate morning/evening emails for the same date.

---

# 8. Daily Lifecycle

All user-facing day boundaries use Zurich local time.

## 8.1 Morning

Target sequence:

```text
~05:50
Build ProfileSnapshot
Build PlannerContext
Generate candidate DailyPlan
Run deterministic validation
Persist plan
```

Then:

```text
06:00
Send morning email
```

The React app and Chrome extension read the same persisted plan.

If plan generation fails:

1. retry once if appropriate,
2. use a deterministic fallback plan,
3. still send a useful morning email.

Do not make morning functionality depend entirely on OpenAI availability.

## 8.2 During the day

The user may:

- confirm a meal,
- replace a meal,
- skip a meal,
- record fruit/snacks,
- complete a workout,
- record actual performance,
- rate difficulty 1–10,
- flag pain,
- replace a workout,
- ask the AI questions,
- edit inventory,
- alter the plan through explicit approved actions.

## 8.3 Evening

At approximately:

```text
21:00 Europe/Zurich
```

send a short check-in email.

It should contain:

- what was planned,
- a link directly to today's React page,
- an explicit request to record deviations and workout results.

Do not make the user answer the email directly in v1; the email links to the app.

## 8.4 End-of-day reconciliation

At approximately:

```text
00:05 Europe/Zurich
```

finalize the previous local date.

This rule is extremely important.

### Nutrition default

For each unresolved **planned main meal**:

```python
status = "assumed_consumed"
```

The system assumes the planned meal was eaten.

Do not automatically assume optional snacks or optional fruit were consumed unless that specific recommendation is marked as expected rather than optional.

### Exercise default

For every unresolved prescribed exercise/workout:

```python
status = "skipped_assumed"
```

The system assumes exercise was completely skipped.

Do not infer completed exercise from the fact that it was recommended.

### Partial logging

Apply reconciliation per item.

Example:

```text
Meal 1 = user confirmed
Meal 2 = untouched
Workout = untouched
```

becomes:

```text
Meal 1 = confirmed
Meal 2 = assumed_consumed
Workout = skipped_assumed
```

---

# 9. History Corrections and Recalculation

History must always remain editable.

If a user later changes an assumed record:

```text
Monday workout:
skipped_assumed
```

to:

```text
8.0 km
47:41
5:58/km
difficulty 6/10
completed
source = history_correction
```

then recalculate affected derived summaries.

At minimum refresh:

- recent training volume
- comparable-exercise history
- training adherence
- running progression
- strength progression
- average session difficulty
- capacity estimates
- recent nutrition adherence
- nutrition summaries
- inventory estimates when relevant

Do **not** rewrite the historical `DailyPlan`.

The historical plan must continue to show what was recommended at that time.

Future plans use the corrected history.

---

# 10. Nutrition Planning Rules

## 10.1 Meal count

Hard rule:

```text
1 <= planned_main_meals <= 2
```

It is valid to plan one meal.

Never create:

- breakfast
- lunch
- dinner

as three formal meals.

Use:

- Meal 1
- Meal 2

Meal 2 may be absent.

Fruit and snacks do not count as main meals.

## 10.2 Meal timing

Use suggested windows, not rigid mandatory times.

Example defaults:

```text
Meal 1: late morning to early afternoon
Meal 2: evening
```

Learn actual timing from history later.

Do not punish adherence merely because a meal occurs outside its suggested window.

## 10.3 Protein

Seed an approximate protein planning range around:

```text
145–170 g/day
```

but make final target logic configurable and dependent on the profile.

Because 1-meal days can make this difficult, allow:

- Skyr/quark
- cottage cheese
- protein smoothie
- similar high-protein snacks

to close gaps without pretending they are additional formal meals.

Do not turn nutrition into obsessive precision.

## 10.4 Calories

Do not hardcode a permanent calorie target yet.

Important missing fields include:

- age
- sex
- desired body-composition direction
- recent weight trend
- actual running/training volume

Collect these in onboarding/settings.

Use trends over time rather than treating an initial calorie estimate as ground truth.

## 10.5 Meal scoring

Score candidate meals based on:

- protein density
- vegetables / produce
- fiber
- useful carbohydrate for training
- healthy fats
- micronutrient diversity
- estimated active prep time
- batch friendliness
- current inventory
- ingredient expiry
- user preference history
- recent food repetition
- upcoming training
- Thursday flexibility
- shopping requirements

Effort should be a major factor.

A nutritionally excellent meal that repeatedly takes 45 minutes of active work is usually worse for this product than a slightly less optimized meal taking 5–10 minutes.

## 10.6 Initial curated meal library

Seed a small, high-quality meal library rather than generating arbitrary recipes.

Start with approximately 15–20 templates.

Include variants around these:

### Berry protein smoothie

Typical components:

- Skyr or quark
- frozen berries
- oats
- ground flax or chia
- small amount of spinach
- milk/water
- optional whey/protein powder

Target:

- ~3 minutes active preparation
- high protein
- fiber
- freezer/pantry friendly

Treat as an optional snack/module unless explicitly designated as a main meal.

### Skyr fruit bowl

- Skyr
- kiwi or berries
- oats
- walnuts

No cooking.

### Chicken power bowl

- chicken
- brown rice or quinoa
- broccoli
- peppers
- yogurt-based sauce
- rapeseed or olive oil

Batch friendly.

### Salmon plate

- salmon
- potatoes
- broccoli or spinach
- tomato

Simple high-protein fish meal.

### Egg + cottage cheese plate

- eggs
- cottage cheese
- wholegrain bread
- tomatoes
- spinach

Fast fallback.

### Lentil/chickpea bowl

- lentils or chickpeas
- quinoa or rice
- vegetables
- yogurt or tahini-lemon style sauce

Batch-friendly plant-protein option.

### Sardine tomato toast

- sardines
- wholegrain bread
- tomato
- lemon

Fast pantry option.

### Emergency meal

- Skyr/quark
- fruit
- nuts
- wholegrain bread

Purpose: avoid takeaway or low-quality food because nothing is prepared.

### Thursday office rule

Do not attempt precise control over the colleague meal.

Simple guidance may be:

- prioritize a clear protein source,
- add vegetables/salad,
- include carbohydrates according to hunger/training,
- avoid turning the meal into a tracking exercise.

Allow quick logging categories such as:

```text
restaurant meal — protein + vegetables + carbs
restaurant meal — protein-heavy
restaurant meal — unknown/mixed
```

## 10.7 Fruit library

Prioritize easy, low-friction fruit.

Seed:

- kiwi
- berries
- oranges/clementines
- apples
- bananas

Also allow seasonal variation.

Frozen berries should be considered a permanent freezer staple.

Fruit should be displayed independently so the user can take it whenever convenient.

## 10.8 Snacks

Seed optional high-value snacks:

- Skyr/quark
- Greek-style yogurt where appropriate
- cottage cheese
- walnuts or mixed nuts
- protein smoothie
- fruit
- wholegrain bread with a simple protein topping

Keep the catalog deliberately small.

---

# 11. Meal Prep Logic

Primary goal:

> Maximum benefit per minute of active preparation.

Default strategy:

- roughly two major prep sessions per week,
- e.g. Sunday and Wednesday,
- use refrigeration plus freezing,
- allow adaptive changes if the week requires it.

A `prep_task` should represent the action the user actually needs to perform.

Bad:

```text
Prepare lunch tomorrow.
```

Good:

```text
Move chicken container #3 from freezer to fridge.
```

Good:

```text
Batch cook 4 chicken bowls — ~20 min active time.
```

The planner must understand that a previously batch-prepared meal requires no new cooking.

---

# 12. Shopping and Inventory

## 12.1 Retailers

Support:

- Coop
- Migros

For v1, do not automate checkout.

Generate retailer-specific shopping lists.

Both online and in-store modes must be supported.

## 12.2 Online minimum basket

Treat approximately CHF 100 as a configurable minimum for online ordering.

Environment/config values:

```text
COOP_ONLINE_MINIMUM_CHF
MIGROS_ONLINE_MINIMUM_CHF
```

Do not buy unnecessary food solely to hit a shipping threshold.

If the planned basket is too small:

- roll durable items forward when sensible, or
- recommend an in-store purchase instead.

## 12.3 Weekly pattern

Suggested starting behavior:

- one larger online order per week when economical,
- small in-person fresh-produce top-ups approximately Tuesday and Friday.

These days are defaults, not hard rules.

The user has a large Coop about an 8-minute bike ride away, so tiny fresh shopping trips are acceptable.

## 12.4 Online basket categories

Prefer online ordering for:

- frozen berries
- frozen vegetables
- Skyr/quark
- oats
- rice
- quinoa
- canned legumes
- eggs
- potatoes
- nuts/seeds
- oils
- meat/fish intended for freezing
- pantry staples
- household repeat purchases if desired

## 12.5 In-store fresh categories

Prefer a short fresh list for:

- berries
- kiwi
- bananas
- leafy greens
- tomatoes
- peppers
- seasonal fruit
- produce where visual inspection matters

## 12.6 Inventory behavior

Do not require barcode scanning or exact weighing.

On purchase:

- automatically add expected quantities.

On consumption:

- automatically subtract recipe quantities.

Allow approximate states, e.g.:

```text
Frozen berries: plenty
Oats: low
Kiwi: 3
Chicken: ~650 g
```

If confidence becomes low, ask a tiny question such as:

```text
Still have frozen berries?
```

---

# 13. Exercise Planning Rules

## 13.1 Maximum number of exercises

Hard invariant:

```text
exercise_count <= 3
```

One-exercise days are fully valid.

## 13.2 Specific measurable prescriptions

Never output a vague exercise such as:

```text
8 km easy run
```

Instead output:

```text
Treadmill run — 8.0 km @ 6:00/km
```

Optionally render:

```text
10.0 km/h
0.5% incline
Target time: 48:00
```

Do not output:

```text
Bench press — heavy
```

Output:

```text
Bench press — 100 kg — 3 x 6 — 3 min rest
```

Every recommendation must contain the minimum information needed to reproduce and compare the session.

## 13.3 Strength prescription schema

Conceptually:

```python
StrengthPrescription:
    exercise_id
    load_kg
    sets
    reps_per_set
    rest_seconds
    expected_difficulty
```

For bodyweight work:

```python
BodyweightPrescription:
    exercise_id
    external_load_kg
    sets
    reps_per_set
    rest_seconds
    expected_difficulty
```

where `external_load_kg = 0` can represent pure bodyweight.

## 13.4 Running schema

Use numeric canonical values:

```python
RunPrescription:
    distance_km
    pace_seconds_per_km
    expected_duration_seconds
    treadmill_speed_kmh
    incline_percent
    expected_difficulty
```

Store:

```text
pace_seconds_per_km = 360
```

rather than storing only `"6:00/km"`.

Render human-friendly formats on clients.

## 13.5 Cycling schema

When sufficient data exists:

```python
BikePrescription:
    duration_seconds
    target_power_min_watts
    target_power_max_watts
    cadence_min_rpm
    cadence_max_rpm
    expected_difficulty
```

For interval sessions use explicit segments.

Do not invent an FTP.

If FTP or equivalent power history is unavailable:

- use prior completed power sessions if present,
- otherwise create a conservative calibration/baseline session,
- mark estimates clearly.

## 13.6 Interval prescription

Use structured segments.

Example:

```text
Warm-up:
10 min @ 6:30/km

6 rounds:
800 m @ 4:45/km
400 m @ 6:30/km recovery

Cool-down:
5 min easy
```

The detailed UI can show all segments.

The simple view can summarize them compactly.

## 13.7 Initial weekly structure

Use this only as a starting template, then adapt from history.

```text
Monday
Home strength:
- DB bench
- pull-ups
- DB Romanian deadlift
max 3 exercises

Tuesday
Easy/moderate running session
usually 1 exercise

Wednesday
KICKR session
optionally 1–2 simple upper-body exercises
max 3 total

Thursday
Rest by default
optional very light movement only

Friday
Easy aerobic work
bike or treadmill
usually 1 exercise

Saturday
Gym allowed
high-value compound strength
max 3 exercises

Sunday
Gym allowed, but often useful as long aerobic day depending on recovery
max 3 exercises
```

Do not blindly prescribe this every week.

## 13.8 Strength priorities

High-value gym candidates:

- bench press
- deadlift
- weighted pull-up
- dips
- row variations
- overhead press where useful

Avoid squat recommendations by default.

Do not substitute another painful spinal-loading movement without considering the same pain constraint.

## 13.9 Running progression

Goal:

- comfortably run approximately 8–12 km
- retain high strength

Do not blindly start at 10 km just because the goal is 8–12 km.

Use actual recent running history.

If recent running history is weak or absent:

- be conservative,
- use a measurable baseline session,
- progressively build volume.

Do not increase distance and pace aggressively at the same time.

## 13.10 Adaptation using difficulty

Each completed workout asks:

```text
How difficult was this?
1 ... 10
```

Use deterministic progression guidance.

### Strength

Approximate rules:

```text
completed + difficulty <= 6 + no pain:
    small progression is eligible

difficulty 7–8:
    maintain or progress conservatively

difficulty 9:
    usually maintain load or reduce volume slightly

difficulty 10 / substantial failure:
    reduce next comparable workload

pain:
    no automatic progression
    consider substitution/disable
```

### Endurance

Approximate rules:

```text
completed + difficulty <= 5 + normal recovery:
    small duration/distance progression eligible

difficulty 6–7:
    approximately maintain

difficulty >= 8:
    reduce next comparable workload or increase recovery
```

Do not let this become a rigid algorithm that ignores context, but enforce safe progression bounds in Python.

## 13.11 Actual performance logging

For strength allow per-set actuals:

```text
Set 1: 100 x 6
Set 2: 100 x 6
Set 3: 100 x 5
Difficulty: 8
```

For running:

```text
distance_km
duration
average_pace
difficulty
optional notes
```

For cycling:

```text
duration
average_power if known
interval completion
difficulty
optional notes
```

The next recommendation should use comparable historical sessions.

---

# 14. Profile Snapshot

Every daily recommendation must start from a `ProfileSnapshot`.

The snapshot is persisted so old plans can be interpreted in the context in which they were generated.

## Simple summary

The email, Chrome extension, and default React view show a very short summary.

Example:

```text
Strength stable. Endurance volume is rebuilding.
Recent training difficulty is moderate and recovery appears normal.
Today emphasizes aerobic volume without increasing intensity.
```

Keep this short.

## Detailed summary

The advanced React view may show:

```text
Bodyweight: 90 kg — recorded

Bench capacity: ~100 kg x 5–8 — recorded/recent

Pull-ups: >10 strict reps — recorded

Running status:
rebuilding toward consistent 8–12 km sessions — goal + calculated status

Last 7 days:
4 completed sessions
median difficulty 6/10

Nutrition:
estimated protein average ...
fruit adherence ...
meal-plan adherence ...

Current emphasis:
increase aerobic consistency while preserving strength

Constraints:
Thursday office/rest
gym Sat/Sun
max 3 exercises
avoid squat programming
```

Only display values supported by data.

---

# 15. Data Confidence

Explicitly distinguish:

```text
RECORDED
directly entered by the user

CALCULATED
deterministically derived from recorded data

ESTIMATED
inferred by the planner/model

GOAL
desired future state
```

Do not present model estimates as measurements.

The detailed React UI should visually expose this distinction.

---

# 16. Planner Architecture

Use this conceptual dependency flow:

```text
PostgreSQL state
      ↓
deterministic context builder
      ↓
PlannerContext
      ↓
OpenAI model
      ↓
candidate DailyPlan
      ↓
Pydantic schema validation
      ↓
domain rule validation
      ↓
repair/retry if necessary
      ↓
deterministic fallback if still invalid
      ↓
persist canonical DailyPlan
```

The LLM is not the database.

The LLM is not the rules engine.

The LLM is a high-quality contextual planner operating inside explicit constraints.

---

# 17. PlannerContext

Do not send the entire lifetime history every morning.

Build a compact context.

Suggested structure:

```python
PlannerContext:
    current_date
    day_of_week
    timezone

    profile
    hard_constraints

    current_profile_snapshot

    yesterday_detail

    nutrition_summary_14d
    training_summary_28d

    comparable_strength_sessions
    comparable_run_sessions
    comparable_bike_sessions

    current_inventory
    expiring_inventory

    active_meal_templates
    active_exercise_catalog

    upcoming_schedule_constraints

    recent_adherence
    recent_difficulty

    shopping_state
    prep_state
```

Keep raw history queries server-side.

Send only the most decision-relevant history to OpenAI.

---

# 18. OpenAI Integration

Use the official OpenAI SDK on the backend only.

Never expose `OPENAI_API_KEY` to React or the Chrome extension.

Use the **Responses API**.

Use **Structured Outputs / strict JSON schema** for canonical planning responses.

Prefer typed/Pydantic parsing supported by the current official SDK where practical.

The official OpenAI documentation currently recommends JSON-schema Structured Outputs over older JSON-only mode for supported models.

Model IDs must remain configurable:

```text
OPENAI_PLANNER_MODEL
OPENAI_QA_MODEL
```

Do not couple application behavior to one particular model version.

For privacy-sensitive calls, prefer not to persist provider-side state unless a feature truly needs it; use current official API controls such as `store=false` where appropriate and supported.

Keep application conversation/history state in PostgreSQL rather than depending on provider-side conversation persistence.

Official documentation to consult during implementation:

- OpenAI developer quickstart:
  `https://platform.openai.com/docs/quickstart`
- Responses API:
  `https://platform.openai.com/docs/api-reference/responses`
- Structured Outputs:
  `https://platform.openai.com/docs/guides/structured-outputs`
- OpenAI data controls:
  `https://platform.openai.com/docs/models/default-usage-policies-by-endpoint`

If current SDK syntax differs from examples in this file, use the current official documentation.

---

# 19. Planner Output Schema

Design a strict Pydantic schema approximately like:

```python
class DailyPlan(BaseModel):
    plan_date: date
    profile_snapshot: ProfileSnapshotSummary

    nutrition: NutritionPlan
    workout: WorkoutPlan
    shopping: ShoppingPlanSummary
    prep_actions: list[PrepAction]

    short_summary: str
    rationale: RecommendationRationale
    assumptions: list[str]
```

## Nutrition

```python
class NutritionPlan(BaseModel):
    meal_1: MealRecommendation
    meal_2: MealRecommendation | None
    fruits: list[FruitRecommendation]
    snacks: list[SnackRecommendation]
    expected_main_meals: int
```

Validator:

```text
expected_main_meals in {1, 2}
```

## Workout

Use a discriminated union, e.g.:

```text
strength
bodyweight
run
bike
interval_run
interval_bike
rest
```

Hard validator:

```text
len(exercises) <= 3
```

## Rationale

Return concise application-facing reasoning, not hidden chain-of-thought.

Suggested fields:

```python
class RecommendationRationale(BaseModel):
    summary: str
    objectives: list[str]
    history_factors: list[str]
    nutrition_factors: list[str]
    recovery_factors: list[str]
    scheduling_factors: list[str]
    progression_logic: str | None
    alternatives_considered: list[AlternativeSummary]
```

This is what powers the detailed UI.

---

# 20. Core Planner Prompt Requirements

Version the planner prompt, e.g.:

```text
planner-v1
```

Persist the version in every `planning_run`.

The planner system/developer prompt should make these constraints explicit:

```text
You are planning one day for a single user.

Return only a schema-valid DailyPlan.

The user eats at most two main meals per day.
Never prescribe breakfast/lunch/dinner as three meals.

Recommend one or two main meals.
Fruit and optional snacks are separate and do not count toward the meal limit.

A one-meal day is valid and is not non-adherence.

Prioritize nutrient density, protein, produce, fiber,
training support, low active cooking time, batch preparation,
inventory use, and consistency.

Never recommend more than four exercises in one day.

Gym-specific exercise is allowed only Saturday or Sunday.

Thursday is an office day and should be rest or at most very light training.

Every non-rest exercise prescription must contain measurable workload targets.
Do not say only "easy run", "heavy bench", "moderate bike", etc.

Use recent performance and difficulty feedback.
Do not invent unsupported capacity measurements.
Distinguish recorded/calculated facts from estimates.

Do not automatically progress an exercise associated with pain.

Prefer changing one major training variable at a time.

Use the supplied meal and exercise catalogs whenever practical
rather than inventing arbitrary new recipes/exercises.

Provide concise user-facing rationale.
Do not output private chain-of-thought.
```

Do not rely on this prompt as the only enforcement mechanism.

---

# 21. Deterministic Plan Validation

After Pydantic validation, run domain validators.

Examples:

```python
assert 1 <= plan.nutrition.expected_main_meals <= 2
assert len(plan.workout.exercises) <= 3

if weekday not in {"Saturday", "Sunday"}:
    assert not contains_gym_only_exercise(plan)

if weekday == "Thursday":
    assert workout_is_rest_or_light(plan)

for exercise in plan.workout.exercises:
    assert has_measurable_workload(exercise)

assert not contains_excluded_painful_exercise(plan)
```

Also validate:

- inventory feasibility,
- prep feasibility,
- impossible units,
- negative values,
- clearly nonsensical loads/paces,
- duplicate exercises unless intentionally represented as interval segments.

If AI output violates rules:

1. produce a concise validation error,
2. retry once with the invalid fields and required corrections,
3. validate again,
4. fall back deterministically if still invalid.

Do not enter infinite retry loops.

---

# 22. Deterministic Fallback Planner

Implement a small fallback planner so the app remains useful during OpenAI/API outages.

The fallback can:

- choose from existing meal templates using inventory + effort + recent repetition,
- select a conservative workout from the weekly template and recent history,
- enforce all hard rules,
- produce minimal rationale such as `"Fallback plan generated from recent history."`

It does not need to be sophisticated.

Reliability matters more than fallback intelligence.

---

# 23. AI Q&A in the React App

Advanced React should contain:

```text
Ask about today's plan
```

The backend endpoint receives the question and builds context from:

- user profile,
- today's ProfileSnapshot,
- today's canonical DailyPlan,
- relevant recent nutrition/training history,
- inventory,
- hard constraints.

Example questions:

- Why salmon today instead of chicken?
- Why am I running at this pace?
- Can I replace today's run with the KICKR?
- Why is bench still 100 kg?
- I feel unusually tired; what should I change?
- I ate pizza with colleagues; does tomorrow need to change?

The answer may propose a modification but must **not automatically modify the plan**.

Example UX:

```text
AI proposal:
Replace 8 km run with 50 min bike at 185–200 W.

[Apply this change]
```

Only an explicit apply action changes the plan.

Persist the original recommendation and the user-approved replacement.

---

# 24. API Design

Use `/api/v1`.

Suggested endpoints:

## Today

```text
GET /api/v1/today
GET /api/v1/today/details
```

`/today` returns the simplified representation.

`/today/details` returns the complete advanced representation.

## Nutrition

```text
POST /api/v1/today/nutrition/{recommendation_id}/confirm
POST /api/v1/today/nutrition/{recommendation_id}/skip
POST /api/v1/today/nutrition/{recommendation_id}/replace
POST /api/v1/today/nutrition/manual
```

## Workout

```text
POST /api/v1/today/workout/complete
POST /api/v1/today/workout/skip
POST /api/v1/today/workout/replace
```

Completion payload supports actual per-set/session values and difficulty 1–10.

## History

```text
GET /api/v1/history
GET /api/v1/history/{date}
PATCH /api/v1/history/{date}/nutrition/{entry_id}
PATCH /api/v1/history/{date}/workout/{entry_id}
```

Every edit invokes relevant recalculation.

## Shopping

```text
GET /api/v1/shopping/current
POST /api/v1/shopping/{id}/mark-purchased
PATCH /api/v1/inventory/{id}
```

## AI Q&A

```text
POST /api/v1/today/questions
POST /api/v1/today/recommendations/{recommendation_id}/apply-change
```

## Profile/settings

```text
GET /api/v1/profile
PATCH /api/v1/profile

GET /api/v1/settings
PATCH /api/v1/settings
```

The exact endpoint shape may be adjusted for clarity, but preserve these capabilities.

---

# 25. React UX

The application must be pleasant enough that the user actually opens it.

Avoid a dense fitness-dashboard aesthetic.

## 25.1 Default Today view

Above the fold:

```text
TODAY

CURRENT STATUS
Strength stable · Endurance rebuilding
Recovery normal
[View profile]

MEAL 1
Chicken power bowl
Ready in fridge
[Done] [Change]

MEAL 2
Salmon + potatoes + broccoli
[Done] [Skip] [Change]

FRUIT
Kiwi · blueberries · apple

OPTIONAL
Skyr + walnuts
Protein smoothie

TRAINING
Treadmill — 8.0 km @ 6:00/km
10.0 km/h · 48 min
Expected difficulty 5/10
[Complete] [Change]

NEXT ACTION
Move tomorrow's chicken from freezer to fridge

[Why these recommendations?]
[Ask AI about today's plan]
```

Do not force the user through multiple screens to log basic actions.

## 25.2 Advanced detail

Expandable sections should expose:

- profile snapshot
- recommendation rationale
- recent comparable history
- progression changes
- estimated nutrition
- meal ingredients
- preparation details
- workout meaning/instructions
- assumptions
- alternatives considered
- AI Q&A

Example workout detail:

```text
Why 8 km @ 6:00/km?

Previous comparable session:
7.5 km @ 6:03/km
difficulty 5/10

Change:
+0.5 km
roughly unchanged pace

Goal:
increase aerobic volume without increasing intensity at the same time
```

## 25.3 Completion UX

Strength:

```text
Recommended:
100 kg x 6 x 3

Actual:
Set 1 [100] x [6]
Set 2 [100] x [6]
Set 3 [100] x [5]

Difficulty:
1 2 3 4 5 6 7 8 9 10

Pain?
[No] [Yes]

[Save]
```

Running:

```text
Recommended:
8.0 km @ 6:00/km

Actual:
Distance
Time / average pace
Difficulty 1–10

[Save]
```

## 25.4 History

Use a simple calendar/timeline.

Tap a date.

Show:

- original recommendation,
- actual/assumed nutrition,
- prescribed workout,
- actual/skipped workout,
- profile snapshot at that time.

Allow edits.

## 25.5 Shopping

Show:

- online order option
- in-store option
- retailer
- estimated basket total
- whether online minimum is met
- fresh top-up list

Do not build complicated price comparison in v1.

---

# 26. Chrome Extension

Keep the extension deliberately small.

Popup should show:

```text
Current status
Meal 1
Meal 2 if any
Fruit
Workout
Next action
Shopping warning
```

Provide quick links/actions where easy.

Primary detailed action:

```text
Open full app
```

The extension should consume:

```text
GET /api/v1/today
```

It should not recreate planner logic.

Optional retailer assistance:

When browsing Coop or Migros, a later/simple content-script feature may show the current shopping list in a side panel.

Do not attempt undocumented automated checkout in v1.

---

# 27. Email Design

## 27.1 Morning email — approximately 06:00

Subject example:

```text
Today — meals, training and next action
```

Keep the body short.

Example:

```text
Current status
Strength stable. Endurance is rebuilding.
Recovery looks normal.

Meal 1
Chicken power bowl — ready in fridge

Meal 2
Salmon + potatoes + broccoli

Fruit
Kiwi · blueberries · apple

Optional
Protein smoothie

Training
Treadmill — 8.0 km @ 6:00/km
10.0 km/h · target 48 min
Expected difficulty: 5/10

Next action
Move tomorrow's chicken from freezer to fridge.

Shopping
Nothing needed today.

[Open today's plan]
```

Do not put extensive sensitive detail in the email.

## 27.2 Evening email — approximately 21:00

Subject:

```text
Quick check-in for today
```

Example:

```text
Planned today:
2 meals
8 km treadmill run

If anything differed, record it now.
Please also enter the workout result and difficulty.

[Complete today's check-in]
```

The link should deep-link to today's React page.

---

# 28. Authentication and Security

This is a personal app containing health-adjacent and performance data.

Keep security reasonable without turning authentication into the main project.

Requirements:

- OpenAI key is server-side only.
- Database is not publicly exposed.
- Use HTTPS in production.
- Hash passwords using a modern password hash.
- React session should use secure authentication.
- Prefer HttpOnly secure cookies for the web application.
- The Chrome extension may use a revocable personal API token.
- CORS must be restrictive.
- Backups should be protected.
- Do not log secrets.
- Avoid logging entire planner contexts by default in production logs.
- Planning-run database records may contain sensitive context; treat them accordingly.

For OpenAI requests, keep provider-side persistence disabled when practical and maintain application state locally.

---

# 29. Scheduling

Prefer an architecture that works with either:

1. hosting-provider cron/scheduled jobs, or
2. a small scheduler process.

Jobs must be idempotent.

Implement callable job functions separately from the scheduler:

```text
generate_morning_plan(date)
send_morning_email(date)
send_evening_checkin(date)
finalize_day(date)
generate_weekly_shopping_plan(week)
```

Use database uniqueness/idempotency so duplicate cron invocation does not send duplicate emails or double-finalize records.

Do not make correctness depend on one long-lived in-memory timer.

---

# 30. Minimal Testing Policy

Keep tests intentionally small.

Do **not** build a huge suite.

Do not add Cypress/Playwright, massive mocks, snapshot tests, or extensive frontend unit tests for v1 unless a concrete bug justifies them.

Frontend quality gates can initially be:

- TypeScript typecheck
- ESLint
- successful production build
- manual smoke testing

Backend should have approximately **10–20 focused tests** protecting invariants.

At minimum test:

1. planner cannot produce >2 main meals
2. fruit/snacks do not count toward meal limit
3. planner cannot produce >3 exercises
4. gym-only exercises cannot appear Monday–Friday
5. Thursday cannot receive hard training
6. non-rest workouts contain measurable workload
7. unresolved planned meals become `assumed_consumed`
8. unresolved workouts become `skipped_assumed`
9. explicit logs are not overwritten by reconciliation
10. history correction recalculates derived summaries
11. invalid AI output is rejected
12. failed AI planning reaches deterministic fallback
13. pain prevents automatic progression
14. old historical DailyPlans remain unchanged after correction
15. notification jobs are idempotent

That is enough initially.

Do not chase artificial code-coverage targets.

---

# 31. Seed Exercise Catalog

Seed a small catalog, not hundreds of exercises.

Suggested initial set:

## Strength

- barbell bench press
- dumbbell bench press
- deadlift
- Romanian deadlift
- pull-up
- weighted pull-up
- dip
- weighted dip
- one-arm dumbbell row
- barbell row
- overhead press

## Endurance

- treadmill run
- outdoor run
- KICKR steady ride
- KICKR interval ride

## Recovery

- walking / easy movement
- optional mobility

Mark squat variants excluded by default for this user.

---

# 32. Seed Meal Catalog

Start with roughly 15–20 templates built from a limited ingredient library.

Variants should reuse ingredients so the shopping list stays simple.

Prefer repeated building blocks:

## Proteins

- chicken
- salmon
- sardines
- eggs
- Skyr/quark
- cottage cheese
- lentils
- chickpeas
- optional whey/protein powder

## Carbohydrates

- oats
- potatoes
- brown rice
- quinoa
- wholegrain bread

## Vegetables

- broccoli
- spinach
- peppers
- tomatoes
- mixed frozen vegetables
- leafy greens

## Fruit

- berries
- kiwi
- apples
- bananas
- oranges/clementines

## Fats / extras

- walnuts
- mixed nuts
- flax/chia
- rapeseed oil
- olive oil
- yogurt-based sauces
- lemon
- simple herbs/spices

Avoid building a huge recipe database.

The goal is consistency and low mental load.

---

# 33. Derived Metrics

Implement only metrics that directly improve decisions.

Useful initial metrics:

## Training

- completed workouts last 7/14/28 days
- adherence rate
- median/average difficulty
- last comparable workout
- rolling run distance
- rolling run duration
- strength volume for primary lifts
- best recent set for primary lifts
- trend in prescribed vs. actual workload
- consecutive hard days
- days since comparable exercise

## Nutrition

- planned vs. confirmed/assumed meals
- rough protein average
- fruit/produce consistency
- meal repetition
- average meal effort
- frequency of manual replacements
- one-meal vs. two-meal pattern

Do not create dozens of vanity metrics.

---

# 34. Recommendation Logic: Deterministic + AI

The planner should use a hybrid system.

## Python should determine

- date/day constraints
- Thursday rule
- gym eligibility
- maximum meals
- maximum exercises
- excluded/painful movements
- current inventory
- expiry pressure
- comparable workout history
- derived progression bounds
- data confidence
- whether historical entries were assumed or confirmed
- shopping minimum logic
- plan validity

## OpenAI model should help determine

- which valid meal combination is best today
- which valid training emphasis fits recent context
- how to balance recovery and progression
- concise explanations
- meaningful alternatives
- contextual responses to user questions
- nuanced adaptation where deterministic rules do not decide uniquely

This division is important.

---

# 35. Plan Modification Workflow

A user-requested alternative should not silently overwrite the plan.

Workflow:

```text
1. User asks question or clicks Change.
2. AI or deterministic engine proposes alternative.
3. Show proposed replacement.
4. User clicks Apply.
5. Persist modification event.
6. Update active canonical plan representation.
7. Preserve original recommendation for history/audit.
```

Record:

```text
original recommendation
replacement recommendation
reason
source
changed_at
```

---

# 36. Failure Modes

Handle these explicitly.

## OpenAI unavailable

Use fallback planner.

## Email fails

Persist failure and allow retry.

Do not regenerate the plan merely because email delivery failed.

## Scheduler invokes same job twice

Idempotency prevents duplicate state/email.

## Invalid LLM output

Validate, repair once, then fallback.

## Missing workout history

Create a conservative measurable plan or calibration session.

Do not invent precise athletic capacity.

## Missing food inventory

Use shelf-stable/frozen fallback meals or prompt for a minimal inventory check.

## User skips several workouts

Reduce or hold progression.

Do not keep increasing prescribed difficulty as if sessions were completed.

## User fails to check in

Nutrition:
assume planned main meals consumed.

Workout:
assume skipped.

This rule must never be reversed accidentally.

---

# 37. Implementation Sequence

Implement in this order.

## Phase 1 — Foundation

- repository
- FastAPI
- PostgreSQL
- SQLAlchemy/Alembic
- profile/settings
- seed data
- core schemas
- authentication
- basic history CRUD

At the end of Phase 1, the application should be able to store a profile, meals, exercise prescriptions, and historical entries.

## Phase 2 — Deterministic domain engine

Implement:

- derived metrics
- ProfileSnapshot
- PlannerContext
- nutrition constraints
- training constraints
- end-of-day reconciliation
- history correction/recalculation
- fallback planner

Do this before relying on the AI.

## Phase 3 — OpenAI planner

- official SDK
- Responses API
- strict structured output
- prompt versioning
- planner run persistence
- validation
- one repair attempt
- fallback

## Phase 4 — Scheduler + email

Implement:

- morning plan generation
- 06:00 morning email
- 21:00 check-in
- 00:05 finalization
- weekly shopping plan
- idempotency

## Phase 5 — React

Implement only:

- Today
- History
- Shopping
- Settings
- advanced details
- AI Q&A

Make Today excellent before adding secondary polish.

## Phase 6 — Chrome extension

- authentication/token
- today's simple recommendation
- quick links/actions
- open full app

## Phase 7 — refinement

- shopping usability
- inventory confidence
- recommendation replacement flows
- prompt refinement
- visual polish
- manual smoke testing

---

# 38. Acceptance Criteria

The v1 is complete when all of the following work.

## Daily plan

- A plan is generated each Zurich day.
- It contains 1 or 2 main meals.
- It may contain separate fruit and snacks.
- It contains at most 3 exercises.
- Thursday defaults to rest/light.
- Gym exercise only appears on Saturday/Sunday.
- Every active workout is quantitatively prescribed.

## Presentation

- Morning email shows a short profile summary and simple action plan.
- Chrome extension shows the same simplified plan.
- React defaults to the same simple plan.
- React can expand to detailed rationale/history.
- React includes contextual AI Q&A.

## Logging

- User can confirm/replace/skip meals.
- User can record actual exercise.
- User can enter difficulty 1–10.
- User can flag pain.
- User can edit historical entries.

## Default assumptions

If no check-in occurs by end of day:

- planned main meals become `assumed_consumed`
- workout becomes `skipped_assumed`

A later edit overrides those assumptions.

## Adaptation

- Future plans use corrected history.
- Missed workouts do not count as completed progression.
- Completed easy sessions can progress conservatively.
- painful movements do not auto-progress.

## Shopping

- Weekly list can be generated for Coop or Migros.
- Online and in-store options are visible.
- CHF ~100 online minimum is configurable.
- The app does not force wasteful purchases just to hit the threshold.
- Fresh top-ups can be recommended separately.

## Reliability

- AI output is schema validated.
- Domain constraints are validated in Python.
- There is a deterministic fallback planner.
- scheduler jobs are idempotent.
- email failure does not destroy the plan.

---

# 39. Explicit Non-Goals for v1

Do not spend time implementing:

- mobile app
- Apple Health / Garmin / Strava integration
- automated Coop/Migros checkout
- product scraping at scale
- photo calorie recognition
- barcode inventory
- exact micronutrient accounting
- wearable recovery scores
- social features
- public multi-user SaaS
- vector-search memory
- complex agent toolchains
- voice assistant
- exhaustive recipe generation
- elaborate test infrastructure

Design APIs cleanly enough that these could be added later.

---

# 40. Code Quality Expectations

The code should be:

- typed
- readable
- conventional
- easy for another engineer or AI agent to continue
- documented where domain rules are non-obvious

Prefer:

- small services with clear responsibilities
- explicit enums
- Pydantic schemas at API/LLM boundaries
- transactions around important history edits
- migrations for schema changes
- idempotent jobs
- structured logging
- a small number of well-named domain functions

Avoid:

- giant `utils.py` files
- circular service dependencies
- business logic inside React
- business logic inside SQLAlchemy models
- embedding prompts inline across random endpoints
- silent exception swallowing
- storing all application state in arbitrary JSON without a reason

---

# 41. README Requirements

The root README should explain:

1. what the product does
2. architecture
3. repository layout
4. local development
5. environment variables
6. database migration commands
7. seed commands
8. backend start command
9. frontend start command
10. extension build/install instructions
11. scheduler/job start instructions
12. production deployment assumptions
13. OpenAI configuration
14. email configuration
15. key domain rules

Provide a short architecture diagram.

---

# 42. Final Agent Instruction

Build the smallest system that fully satisfies these rules.

The defining UX is:

> The user opens an email, React page, or Chrome popup and immediately knows:
>
> - how their current state looks,
> - what to eat,
> - what fruit/snacks are available,
> - exactly what workout to perform,
> - what small preparation/shopping action is required.
>
> If they want more information, the React app can explain the decision in depth using the same context that produced it.

The defining backend behavior is:

> The database is the source of truth, Python enforces the rules, OpenAI supplies high-quality contextual planning, and the user's actual history continuously improves future recommendations.

Do not sacrifice this simplicity by adding features that do not directly improve adherence, recommendation quality, or low-effort operation.
