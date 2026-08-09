# Health Autopilot

Health Autopilot is a single-user personal health and hybrid training planner.
It produces one low-friction daily plan with one or two main meals, separate fruit and optional snacks, a measurable workout, and the next useful preparation or shopping action.

The application preserves what was recommended, what actually happened, what was assumed at reconciliation, and every later correction.
Future recommendations use corrected history without rewriting old plans.

## Architecture

```text
React web app -----------+
Chrome extension --------+---> FastAPI ---> PostgreSQL
Scheduled job commands --+       |   |
                                 |   +---> Resend Email API
                                 +-------> OpenAI Responses API
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
- OpenAI: `OPENAI_API_KEY`, `OPENAI_PLANNER_MODEL`, `OPENAI_QA_MODEL`, `OPENAI_FOOD_LOG_MODEL`, `OPENAI_REASONING_EFFORT`
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

Seed the user profile, equipment, exercise catalog, foods, and 17 curated meal templates:

```bash
.venv/bin/health-autopilot seed
```

Seed operations are idempotent.

## Run the backend

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

The API is available at `http://localhost:8000`.
Development API documentation is available at `http://localhost:8000/api/docs`.

## Run the web application

```bash
npm run dev --workspace frontend
```

Open `http://localhost:5173`.

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

Create a local runtime directory, start the scheduler with `nohup`, and save its process ID:

```bash
mkdir -p .runtime
nohup .venv/bin/health-autopilot scheduler > .runtime/scheduler.log 2>&1 &
echo $! > .runtime/scheduler.pid
```

The `.runtime` directory is ignored by Git.
Follow the background logs with:

```bash
tail -f .runtime/scheduler.log
```

Check the exact background process saved in the PID file with:

```bash
ps -p "$(cat .runtime/scheduler.pid)" -o pid=,etime=,command=
```

`nohup` keeps the scheduler alive after the terminal closes, but it does not restart it after a computer reboot.
Use `launchd` on macOS or the hosting provider's process supervisor when automatic restart is required.

### Stop a background scheduler

First inspect the saved process, then send it a graceful termination signal:

```bash
ps -p "$(cat .runtime/scheduler.pid)" -o pid=,etime=,command=
kill -TERM "$(cat .runtime/scheduler.pid)"
```

After confirming that `pgrep` returns no scheduler process, remove the stale PID file:

```bash
rm .runtime/scheduler.pid
```

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
