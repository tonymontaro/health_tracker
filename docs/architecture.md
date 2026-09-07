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
       +<-- active dated training-plan guide
       |
       v
RecedingHorizonContext + previous horizon revision
       |
       v
OpenAI 14-day structured proposal
       |
       v
Pydantic and domain validation
       |
       +-- invalid --> one repair request
       |                    |
       |                    +-- invalid --> deterministic fallback
       v
Immutable TwoWeekPlan revision for this anchor date
       |
       +-- days 0-1: adaptive zone
       +-- days 0-6: committed user-facing strategy
       +-- days 7-13: provisional AI planning horizon
       |
       v
Task-specific Daily PlannerContext with today's strategy and three-day lookahead
       |
       v
OpenAI structured daily proposal
       |
       v
Pydantic and domain validation
       |
       +-- invalid --> repair or deterministic fallback
       v
Canonical DailyPlan
```

The model never reads the database directly.
The context builder selects recent, decision-relevant history.
Pydantic validates shape and Python validates domain rules.
The deterministic fallback uses the same plan schema and validators.

Planning uses a receding horizon.
The AI considers fourteen consecutive days so that training load, recovery, meal variety, preparation, and fueling are not chosen in isolation.
The first seven days contain strategic workout intent and fueling guidance and are exposed in the exercise outlook.
The Meals page exposes all saved calendar meal weeks, independently of this adaptive training horizon.
The second week remains provisional strategic context.
The daily planner creates the final measurable workout prescription.
The independent calendar meal planner supplies stable recipes and groceries for complete weeks.

One or more immutable, numbered `two_week_plan` revisions can be stored for a Zurich-local anchor date.
Automatic planning creates revision one, while explicit regeneration creates a new revision and retains the preceding version for audit.
Each revision points to the preceding revision and preserves overlapping committed dates unless new evidence or an explicit regeneration preference creates a clear reason to change them.
Manual regeneration preserves day zero because today's canonical daily plan is already fixed, then refreshes tomorrow onward.
Today and tomorrow are the adaptation zone.
Completed or skipped training, recorded difficulty, pain or soreness notes, nutrition adherence, and known schedule constraints can change the near-term prescription.
Unrecorded sleep, appetite, soreness, fatigue, or schedule changes are never invented.

The rolling horizon is generated or refreshed before the daily plan.
The daily planner receives only the matching strategic day, the next three strategic days, and compact strategy summaries rather than the complete horizon.
The daily plan treats the horizon and imported CSV as guidance, decides the final recommendation from all current evidence, and still passes the existing safety and catalog validators.

Planner context is task-specific.
Horizon planning receives compact catalog metadata and no recipes, shopping state, or prior full daily plan.
Daily planning receives eligible current-day catalogs, a compact summary of yesterday, and only the nearby horizon.
Workout regeneration excludes nutrition catalogs, while nutrition regeneration excludes workout history and the exercise catalog.

## Coach messaging

Coach Forge generates workout feedback and the coaching note in morning and evening emails with one shared character prompt.
The critical coaching signal and next useful action remain primary, while dry humor is optional and pain or safety messages stay serious.
The interactive plan Q&A uses the same character and independently decides whether a brief story would materially strengthen motivation, encouragement, or the coaching lesson.
The athlete does not need to request a story, and most Q&A remains direct feedback without one.

Generated coaching notes include internal structured metadata indicating whether a humorous or motivational story was used and a short topic key.
Successful email deliveries retain this metadata in their notification record, while workout feedback retains it in the existing context snapshot.
No separate story table or schema migration is required.

Each generated coaching note receives at most ten compact recent-message excerpts and twelve recent story topics from the preceding thirty days.
After a story is delivered, stories are disabled for the following four calendar days, while ordinary feedback and occasional non-story humor remain available.
Application validation rejects a story during the cooldown, in a pain-related message, or when its normalized topic exactly repeats a recent topic, then uses the deterministic serious fallback.

## Imported training-plan guide

Settings accepts one CSV with `Date` and `Workout` columns as the active externally supplied training guide.
The application stores the original CSV, its SHA-256 source revision, and normalized dated rows in `training_plan_guide`.
Uploading another CSV updates that single profile-owned row, so code changes are not required when the external plan changes.

The guide is future intent and never enters workout history as completed activity.
Horizon context contains the current fourteen-day guide window and the next benchmark or race beyond it.
Daily context contains today's raw `Workout` value, the next three guide days, and the next later benchmark or race.
The AI treats those rows as high-priority advisory training intent after pain, medical, equipment, schedule, exercise-catalog, and other hard constraints, and it remains responsible for deciding the final daily plan.
It uses the guide workload to shape recovery, meal selection, and fueling, and it must explain material deviations.

Two-week horizon context records the guide source revision.
When the active CSV changes, the next current-day planning request creates a new immutable horizon revision.
An already-created canonical daily plan remains unchanged, while tomorrow onward can use the replacement guide.

## Meal selection policy

Calendar meal planning uses the curated template catalog, profile limits, preferences and allergies, recent recommendation history, training evidence, and the active training guide.
It asks OpenAI for fourteen consecutive days beginning on a Monday using `OPENAI_PLANNER_MODEL`, Structured Outputs, and `store=false`.
The planner may repair one invalid result before using a validated deterministic fallback, whose source is visible in the Meals page.
Python checks date coverage, catalog membership, allergies, meal count, consecutive-day variety, and cooking effort before storing a week.
Monday through Saturday meals must take at most 20 hands-on minutes, 30 total minutes, and an effort score of two.
Sunday permits one special meal, with any second meal kept easy.
All recipe quantities and preparation steps describe one serving, without implicit batch multiplication.

Meal and exercise regeneration accept optional free-text preferences.
For exercise regeneration, a supplied preference remains the athlete's highest-priority workout instruction after hard safety, schedule, equipment, and catalog constraints.
Meal regeneration honors preferences within allergy safety, Sunday-only involved cooking, and catalog constraints.
Approved changes to today's meals are audited in `plan_modification` and reflected in the calendar and shopping list without rewriting either original plan.

## Calendar meals and shopping

`weekly_meal_plan` stores one stable Monday-Sunday recipe document per week, its provider source, validation results, and generation context.
Missing weeks are generated in pairs of complete weeks.
A unique Monday date and conflict-safe insertion prevent concurrent requests from replacing a saved week.
The user-facing window includes the current week through the Sunday covering today plus thirteen days, so a midweek view includes three calendar weeks.
Daily planning and the existing shopping job fill this window automatically.
The authenticated, CSRF-protected `POST /api/v1/meals/plan` also fills missing weeks and returns the calendar with shopping lists.

Daily planning uses the saved nutrition document verbatim, including recipe quantities, fruit, and optional snacks, while training continues to adapt separately.
Already-created daily plans remain canonical; calendar serialization overlays their current recommendations and flags differences from the saved week.
The weekly shopping list is derived from exactly the meals and extras displayed in that calendar response.
Identical ingredients and compatible units are summed using decimal arithmetic.
Cooked grain and pulse weights remain explicitly cooked weights and the copyable list recommends ready-cooked or cooked/drained products rather than implying those are dry weights.
Legacy recipe quantities that cannot be parsed remain visible as manual-check notes instead of disappearing from the list.
There is no fixed basket, speculative pricing, retailer threshold padding, purchase status, or stock subtraction.
Lists include delivery-by-Monday guidance and frozen options for ingredients needed later in the week.

Inventory models, endpoints, ingestion, provider configuration, UI, and recording side effects have been removed.
The migration renames old stock and purchase tables to `retired_inventory_item` and `retired_shopping_plan` for offline rollback only.
These archives are excluded from future migration autogeneration and have no runtime application access.

## Canonical plan and history

There is at least one immutable `two_week_plan` revision per planned Zurich-local anchor date.
The latest revision is active, while earlier revisions remain available for audit.
Only its first seven days are committed and user-facing, while all fourteen days remain available to subsequent planning runs.
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
                            +-- recalculate nutrition history
```

There is at most one `daily_food_log` row per date.
It preserves the user's original text and the validated extraction for audit and re-analysis.
AI-derived `nutrition_entry` rows store explicit meal components, estimated average quantities, approximate nutrients, assumptions, and an optional recommendation match.
The external call completes before any mutation, so provider or validation failures leave recommendations and actual records untouched.
A later submission locks the plan row, deletes only entries still owned by the earlier extraction, and applies the replacement atomically.
History corrections detach corrected actual entries from diary ownership so re-analysis preserves them.
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
Password changes require the current password and an authenticated browser session, retain only that session, and use the existing recommended password hasher.
Logout deletes the current server-side session, clears the cookie, and clears browser-held CSRF and cached application data.
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
