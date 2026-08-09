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
      normalized Strava activity          OpenAI Structured Output
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
