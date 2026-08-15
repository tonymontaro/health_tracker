# Architecture

Health Autopilot is a single-user modular monolith.
PostgreSQL is the source of truth, FastAPI owns business behavior, and OpenAI operates only inside validated planning and Q&A boundaries.

```text
React web app -----------+
Chrome extension --------+---> FastAPI ---> PostgreSQL
Scheduled job commands --+       |   |
                                 |   +---> Resend Email API
                                 |   +---> OpenAI Responses API
                                 +-------> Strava API
```

## Planning flow

```text
PostgreSQL history
       |
       v
Derived metrics and ProfileSnapshot
       |
       v
Deterministic PlannerContext
       |
       v
OpenAI structured proposal
       |
       v
Pydantic and domain validation
       |
       +-- invalid --> one repair request
       |                    |
       |                    +-- invalid --> deterministic fallback
       v
Canonical DailyPlan
```

The model never reads the database directly.
The context builder selects recent, decision-relevant history.
Pydantic validates shape and Python validates domain rules.
The deterministic fallback uses the same plan schema and validators.

## Meal selection policy

Daily meal selection uses the active curated template catalog, profile preferences and allergies, recent recommendation and consumption history, training demand, schedule, shopping state, and inventory.
Inventory is a convenience and waste-reduction signal rather than an eligibility boundary.
The planner assumes that missing ingredients can be purchased.

When enough eligible alternatives exist, a main meal template recommended yesterday cannot be recommended again today.
The planner also minimizes repetition across the previous 14 days.
Easy, nutrient-dense meals remain the normal default, using preparation time, protein, fiber, and produce portions as quality signals.
At least one template tagged `special` is required in each rolling seven-day period outside the fixed office-day exception, providing a more creative, higher-effort meal while keeping the other meal easy on two-meal days.
The domain validator enforces consecutive-day variety, distinct meals within a day, allergy safety, catalog validity, and the weekly special-meal rule.
The deterministic fallback applies the same policy when AI planning is unavailable.

Meal and exercise regeneration accept optional free-text preferences.
The preference is stored in the planning-run context and treated as high priority after safety, allergy, pain, equipment, schedule, and other hard constraints.
Meal regeneration still uses only validated meal templates, and exercise regeneration still uses only available catalog exercises.

## Inventory and shopping

The Inventory page combines editable fridge, freezer, pantry, and counter records with the existing weekly shopping recommendations.
Catalog ingredients retain their food-catalog relationship, while standalone inventory records can represent arbitrary ingredients and prepared meals without polluting the nutrition catalog.
Before a draft shopping plan is marked purchased, its quantities can be changed and unneeded items can be removed.
Marking the plan purchased adds its final reviewed quantities to inventory in the same database transaction and is idempotent.

Free-text inventory additions use OpenAI Structured Outputs to distinguish ingredients from prepared meals, estimate missing quantities, identify storage locations, and match catalog foods only when appropriate.
The provider call and validation finish before database mutation, and the validated additions are committed atomically.
Provider-side response storage is disabled.

## Canonical plan and history

There is one `daily_plan` row per Zurich-local date.
`original_plan_json` is immutable after creation.
`current_plan_json` contains user-approved replacements.
Each replacement also creates a `plan_modification` audit row.

Nutrition and workout entries retain prescriptions separately from actual results.
End-of-day reconciliation changes only unresolved entries.
History corrections update the actual entries and recalculate derived summaries without rewriting the original plan.

## Free-text food recording

```text
Food diary text + today's nutrition suggestions + food catalog
                            |
                            v
                  OpenAI Structured Output
                            |
                            v
              Pydantic and domain validation
                            |
                invalid ----+---- valid
                   |                  |
          no state change            v
                            one database transaction
                            |
                            +-- mark suggestions matched or discarded
                            +-- replace AI-derived actual meal entries
                            +-- apply reversible inventory deltas
                            +-- recalculate nutrition history
```

There is at most one `daily_food_log` row per date.
It preserves the user's original text and the validated extraction for audit and re-analysis.
AI-derived `nutrition_entry` rows store explicit meal components, estimated average quantities, approximate nutrients, assumptions, and an optional recommendation match.
The external call completes before any mutation, so provider or validation failures leave recommendations and inventory untouched.
A later submission locks the plan row, reverses only the inventory amounts actually deducted by the earlier extraction, deletes those derived entries, and applies the replacement atomically.
Food logging does not alter the canonical plan or workout entries.

## Workout ingestion

```text
Strava OAuth and scheduled sync          Free-text workout diary
                 |                                  |
                 v                                  v
 normalized Strava / Garmin activity      OpenAI Structured Output
                 |                                  |
                 +---------------+------------------+
                                 |
                                 v
                 deterministic recommendation match
                                 |
                    +------------+-------------+
                    |                          |
             planned exercise            unplanned exercise
             actual is updated         completed entry created
                    |                          |
                    +------------+-------------+
                                 |
                                 v
                      derived training summary
                                 |
                                 v
                    future planner and chat context
```

`strava_activity` is an idempotent normalized provider record keyed by connection and Strava activity ID.
`strava_activity_match` links one activity to one or more materialized workout entries and retains the previous entry state for safe deletion or disconnect handling.
Strava payloads are reduced to decision-relevant actual workout fields before they enter planner context.
Exact strength volume is never inferred from a generic Strava strength session.

Garmin Connect CSV imports are idempotently fingerprinted in `imported_activity` and materialized as
completed `workout_entry` records with `garmin_csv` provenance. The import preserves decision-relevant
watch measurements without requiring a live provider connection.

The profile's optional `current_target_goal` is flexible free text. Planner and coaching contexts pair
it with calculated 180-day running evidence, while preserving the broader hybrid-training goal and hard
constraints. Race-time and readiness comparisons remain explicitly labelled estimates.

`daily_workout_log` preserves the user's source text, validated extraction, and the prior state of entries it controls.
The external AI call and validation finish before the transaction begins.
Re-analysis restores only entries still owned by the prior diary, deletes only its generated workouts, and applies the replacement atomically.
Strava matches and explicit History corrections detach an entry from diary ownership so later re-analysis cannot overwrite stronger evidence.

## Security

The React app authenticates with an opaque database-backed session in an HttpOnly cookie.
State-changing browser requests also require a per-session CSRF token.
The extension uses revocable random bearer tokens whose hashes are stored in PostgreSQL.
The OpenAI key exists only in backend configuration.
Strava client credentials exist only in backend configuration.
Strava access and refresh tokens are encrypted before persistence with a key derived from the session secret.
Provider-side response storage is disabled for planning, food extraction, and Q&A calls.
Provider-side response storage is also disabled for workout extraction.
Food extraction sends only the diary text, today's nutrition suggestions, and the food catalog rather than the full health profile.

## Jobs

Every job is a callable function and can be invoked by a hosting provider cron or by the included scheduler process.
The scheduler performs a rate-limited Strava sync before morning plan generation, allowing imported actuals to affect the next recommendation.
Notification uniqueness and plan-date uniqueness make repeated invocations safe.
Email delivery failure does not regenerate or remove the daily plan.
