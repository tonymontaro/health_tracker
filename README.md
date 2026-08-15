# Health Autopilot

Health Autopilot is a single-user personal health and hybrid training planner.
It produces one low-friction daily plan with one or two main meals, separate fruit and optional snacks, a measurable workout, and the next useful preparation or shopping action.

The application preserves what was recommended, what actually happened, what was assumed at reconciliation, and every later correction.
Future recommendations use corrected history without rewriting old plans.

Meal recommendations avoid consecutive-day template repeats when alternatives exist, favor easy nutrient-dense food by default, and include a more ambitious curated meal at least weekly.
Inventory can improve convenience and reduce waste, but missing ingredients do not prevent a meal from being recommended.
The Today page also accepts optional high-priority preferences when regenerating meals or exercise.

## Architecture

```text
React web app -----------+
Chrome extension --------+---> FastAPI ---> PostgreSQL
Scheduled job commands --+       |   |
                                 |   +---> Resend Email API
                                 |   +---> OpenAI Responses API
                                 +-------> Strava API
```

PostgreSQL is the source of truth.
Python calculates state and enforces all hard constraints.
OpenAI chooses and explains high-quality options within those constraints.
The web app, extension, and emails all render the same persisted canonical plan.

See [docs/architecture.md](docs/architecture.md) for the detailed flow.

## Repository layout

```text
backend/      FastAPI, SQLAlchemy, Alembic, planner, jobs, and tests
frontend/     React and TypeScript web application
extension/    Manifest V3 React popup
scripts/      Local setup helpers
docs/         Architecture documentation
```

## Prerequisites

- Python 3.12 or newer
- Node.js 22 or newer
- Docker with Docker Compose

## Local setup

Copy `.env.example` values into your private `.env` as needed.
The application also accepts the legacy `OPEN_AI_API_KEY` spelling for compatibility.

Run:

```bash
./scripts/dev_setup.sh
```

The setup creates a project-local virtual environment, installs approved project dependencies, starts PostgreSQL, applies migrations, and seeds the initial profile and catalogs.

The default development login is:

```text
owner@localhost
change-me-now
```

Change `BOOTSTRAP_EMAIL` and `BOOTSTRAP_PASSWORD` before the first production seed.
Never use the development password in production.

## Environment variables

The full list is in `.env.example`.
Important groups are:

- PostgreSQL: `DATABASE_URL`
- Public URLs: `APP_BASE_URL`, `API_BASE_URL`
- Time: `APP_TIMEZONE`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_PLANNER_MODEL`, `OPENAI_QA_MODEL`, `OPENAI_FOOD_LOG_MODEL`, `OPENAI_INVENTORY_MODEL`, `OPENAI_WORKOUT_LOG_MODEL`, `OPENAI_REASONING_EFFORT`
- Strava: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_WEBHOOK_VERIFY_TOKEN`, `STRAVA_WEBHOOK_SUBSCRIPTION_ID`, `STRAVA_INITIAL_SYNC_DAYS`, `STRAVA_SYNC_LOOKBACK_DAYS`, `STRAVA_SYNC_INTERVAL_MINUTES`
- Email: `RESEND_API_KEY`, `RESEND_FROM`, `RESEND_TO`
- Security: `SESSION_SECRET`, `BOOTSTRAP_EMAIL`, `BOOTSTRAP_PASSWORD`, `EXTENSION_API_TOKEN`
- Shopping: `COOP_ONLINE_MINIMUM_CHF`, `MIGROS_ONLINE_MINIMUM_CHF`

Do not commit `.env` or any API token.

## Database commands

Start local services:

```bash
docker compose up -d postgres
```

Apply migrations:

```bash
cd backend
../.venv/bin/alembic upgrade head
```

Seed the user profile, equipment, exercise catalog, foods, and 25 curated meal templates:

```bash
.venv/bin/health-autopilot seed
```

Seed operations are idempotent.

## Import Garmin activity history

Garmin Connect activity CSV exports can be imported into canonical workout history:

```bash
.venv/bin/health-autopilot import-garmin --file "/path/to/Activities.csv"
```

Imports are idempotent. Each row retains Garmin CSV provenance and the available distance, time,
pace, elevation, heart-rate, cadence, power, calories, and training-effect fields. Imported workouts
feed the same derived metrics and AI context as other completed workouts.

The active target can be edited in Settings or set from the command line:

```bash
.venv/bin/health-autopilot set-goal --text "Race, distance, elevation, date, and target time"
```

## Run the backend

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8001
```

The API is available at `http://localhost:8001`.
Development API documentation is available at `http://localhost:8001/api/docs`.

## Run the web application

```bash
npm run dev --workspace frontend
```

Open `http://localhost:5173`.

When using the local Cloudflare Tunnel, the web application is available at
`https://health.anthonyngene.com` and its public API endpoint is
`https://api-health.anthonyngene.com`.

## Build and install the Chrome extension

Build:

```bash
npm run build --workspace extension
```

Open `chrome://extensions`, enable Developer mode, choose Load unpacked, and select `extension/dist`.

Generate a revocable extension token from the web application's Settings page.
Open the popup, enter the API URL, web app URL, and token, then save.

## Email delivery

Morning and evening messages are sent with the Resend Email API.
Set `RESEND_API_KEY`, `RESEND_FROM`, and `RESEND_TO` before invoking an email job.
The sender must use a domain verified in Resend.
Each scheduled message uses both database idempotency and a stable Resend idempotency key.

## Jobs and scheduler

Generate a plan manually:

```bash
.venv/bin/health-autopilot plan --date 2026-08-09
```

Force deterministic fallback planning:

```bash
.venv/bin/health-autopilot plan --date 2026-08-09 --no-ai
```

Run individual idempotent jobs:

```bash
.venv/bin/health-autopilot job morning-plan --date 2026-08-09
.venv/bin/health-autopilot job morning-email --date 2026-08-09
.venv/bin/health-autopilot job evening-email --date 2026-08-09
.venv/bin/health-autopilot job finalize --date 2026-08-09
.venv/bin/health-autopilot job shopping --date 2026-08-04
```

### Run the scheduler in the foreground

Run the lightweight scheduler directly when you want its logs in the current terminal:

```bash
.venv/bin/health-autopilot scheduler
```

Stop a foreground scheduler by pressing `Ctrl+C` in that terminal.

### Check whether the scheduler is running

Search the process table:

```bash
pgrep -fl "health-autopilot.*scheduler|app.jobs.scheduler"
```

Process information means the scheduler is running.
No output means it is stopped.
The scheduler normally logs one completed-job check every minute.

### Run the scheduler in the background

Start the scheduler with `nohup` and save its process ID:

```bash
make scheduler-start
```

The `.runtime` directory is ignored by Git.
Follow the background logs with:

```bash
tail -f .runtime/scheduler.log
```

Check the exact background process saved in the PID file with:

```bash
make scheduler-check
```

`nohup` keeps the scheduler alive after the terminal closes, but it does not restart it after a computer reboot.
Use `launchd` on macOS or the hosting provider's process supervisor when automatic restart is required.

### Stop a background scheduler

Verify the saved process belongs to the scheduler and stop it gracefully:

```bash
make scheduler-stop
```

The stop target removes the PID file after the process exits and safely cleans up a stale PID file.

If the scheduler was started without a PID file, use `pgrep` to obtain its PID, verify the displayed command, and then run `kill -TERM <PID>`.
Do not run multiple scheduler instances for the same database.

A hosting provider may invoke the same individual job commands through cron instead.
Correctness does not depend on a single in-memory timer.

## Verification

Create the test database once when using the local Compose PostgreSQL service:

```bash
docker compose exec postgres createdb -U health health_test
```

Run all quality gates:

```bash
make verify
```

This runs Ruff, mypy, ESLint, TypeScript checks, the focused backend test suite, and production frontend and extension builds.

## Production assumptions

Production requires HTTPS, managed or protected PostgreSQL, protected backups, a strong random `SESSION_SECRET`, non-default credentials, restrictive CORS origins, Resend configuration, and scheduled job invocation.
The frontend can be hosted as static assets.
The backend and scheduler can use the supplied backend image or an equivalent Python runtime.
The database must not be exposed publicly.

## OpenAI configuration

Planning uses the Responses API with Pydantic Structured Outputs.
The prompt is versioned, all structured output is validated, domain rules are validated again in Python, one repair attempt is allowed, and deterministic fallback is always available.
Daily food text uses a separate configurable model and a strict meal, component, portion, nutrient, and recommendation-match schema.
The default models are configurable and are never embedded throughout the codebase.
Application history remains in PostgreSQL and API calls use `store=false`.

## Daily food recording

The Today page accepts a short free-text description of the food and drinks consumed that day.
After successful AI extraction, every nutrition recommendation for that date is marked as matched or discarded and separate actual meal entries are stored with estimated average portions.
Submitting revised text replaces only the prior AI-derived entries for that day and safely reverses their inventory deltas before applying the new ones.
The original daily plan remains immutable.
If OpenAI is unavailable or the structured result fails validation, the transaction does not start and no recommendation is discarded.

## Strava activity import

Create an API application in Strava and set its authorization callback domain to the hostname from `API_BASE_URL`.
Configure `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`, restart the backend, then connect the athlete from the Settings page.
Do not configure the access and refresh tokens displayed in Strava's application settings.
Those tokens represent an existing athlete grant and may not include activity access; the application obtains and securely stores the correct short-lived token pair through OAuth consent.
The OAuth callback is `/api/v1/integrations/strava/callback`.
The integration requests read-only access to all athlete activities, including activities whose visibility is Only You.

The first sync imports the configured recent history window, which defaults to 90 days because recommendation context uses the latest 28 days.
Later syncs re-read a 35-day lookback window so delayed uploads and edited activities are updated idempotently.
Set `STRAVA_SYNC_MAX_ACTIVITIES_PER_RUN=2` while validating a new connection to cap each sync to the two newest activities, then raise or remove that override after testing.
The scheduler checks for due syncs before morning planning and no more often than the configured interval.
The Settings page also provides a manual sync control.
The Exercise page provides a date-bounded Retrieve from Strava action for today's activities without changing the periodic background-sync schedule.
Its Regenerate exercise action retrieves the previous local day from Strava when connected, rebuilds a fresh history snapshot, and regenerates only today's unresolved workout while preserving nutrition.

Runs, rides, and recovery activities are matched by activity type and workload to an unresolved recommendation for the same application-local date.
A Strava strength session can complete the day's unresolved strength recommendations, but it does not invent exercise-level loads or repetitions that Strava did not provide.
An activity that does not match the plan becomes a separate completed workout and is still included in future recommendation context.
Imported values preserve distance, duration, elevation, heart rate, power, device, and activity provenance when Strava supplies them.
Raw Strava location data is never included in AI planning context.

OAuth access and refresh tokens are encrypted in PostgreSQL with a key derived from `SESSION_SECRET`.
Changing `SESSION_SECRET` requires reconnecting Strava.
Disconnecting revokes the refresh token and removes Strava-derived activity records while restoring the prior state of matched recommendations.

### Optional Strava webhooks

Scheduled sync is sufficient for automatic imports.
For near-real-time create, update, delete, and deauthorization handling, configure `STRAVA_WEBHOOK_VERIFY_TOKEN` and register this callback URL with Strava:

```text
https://your-api.example/api/v1/integrations/strava/webhook
```

After Strava creates the subscription, set its ID as `STRAVA_WEBHOOK_SUBSCRIPTION_ID` and restart the backend.
Webhook requests are acknowledged immediately and processed after the response.
Scheduled sync remains the retry path if webhook processing fails.

## Daily workout recording

The Today page offers structured workout completion and an alternate free-text workout diary.
The free-text workflow first sends only the diary text and today's workout suggestions to OpenAI Structured Outputs without changing stored workout data.
The resulting draft can be corrected, deleted, or extended with manual exercises before a separately validated submission records it.
Validated results contain typed activities, measurements, difficulty, pain, notes, assumptions, and optional recommendation matches.
Matched recommendations become completed, unmatched recommendations become skipped by the diary, and unplanned exercise becomes a separate completed workout.
Re-analysis atomically replaces only entries still controlled by that diary and preserves later Strava imports or History corrections.
If OpenAI is unavailable or validation fails, no workout state changes.

## Key domain rules

- One canonical plan exists per Zurich-local date.
- One or two main meals are allowed.
- Fruit and optional snacks do not count as main meals.
- At most three exercises are allowed.
- Gym-only exercises are allowed only on Saturday and Sunday.
- Thursday is rest or very light recovery movement.
- Every active workout has numeric, reproducible targets.
- Pain prevents automatic progression.
- Unresolved expected meals become `assumed_consumed`.
- Unresolved workouts become `skipped_assumed`.
- Explicit records are never overwritten by reconciliation.
- Historical corrections recalculate derived summaries without rewriting original plans.
