# Health Autopilot agent guidance

This file applies to the entire repository. Read `README.md` and, for changes that affect data flow or domain behavior, `docs/architecture.md` before editing.

## What this repository is

Health Autopilot is a single-user personal health, meal, and hybrid-training planner.

- `backend/`: FastAPI, SQLAlchemy, Alembic, planner and ingestion services, scheduled jobs, and pytest tests.
- `frontend/`: React 19, TypeScript, TanStack Query, React Router, and Vite.
- `extension/`: Chrome Manifest V3 React extension.
- `docs/`: architecture and behavior documentation.
- `scripts/`: local setup helpers.

PostgreSQL is the source of truth. FastAPI owns state changes and hard constraints. OpenAI returns structured proposals/extractions which must pass Pydantic and domain validation before persistence. The frontend, extension, email jobs, and scheduler consume the same canonical data.

## Important runtime facts

- Python 3.12+, Node.js 22+, and Docker Compose are expected.
- The project-local Python environment is `.venv`; use its executables rather than a global Python installation.
- PostgreSQL normally listens on local port `55432` through Compose.
- The backend listens on `http://localhost:8001`; port 8000 belongs to another application on the owner's host.
- The Vite frontend listens on `http://localhost:5173` and proxies `/api` and `/health` to port 8001.
- Application dates are based on `Europe/Zurich`, not UTC or the agent's inferred locale.
- `.env` is private and may contain live OpenAI, Resend, Strava, session, and database secrets. Never print, quote, commit, or overwrite it. Use `.env.example` to understand the supported keys.

Useful commands from the repository root:

```bash
make db-up
make migrate
make seed
make api
make web
make scheduler-check
make scheduler-start
make scheduler-stop
make verify
```

For a focused frontend change, run:

```bash
npm run lint --workspace frontend
npm run typecheck --workspace frontend
npm run build --workspace frontend
```

For a focused backend change, run the relevant tests from `backend/`, then the backend lint/type checks when appropriate:

```bash
cd backend
../.venv/bin/pytest tests/<relevant_test_file>.py
../.venv/bin/ruff check app tests ../scripts
../.venv/bin/mypy app
```

The backend test suite expects a `health_test` database. See `README.md` for its one-time creation command. Use `make verify` before handoff when the change is broad or high-risk.

## Cloudflare Tunnel: detect the machine before assuming hosting

The repository can be checked out on another developer's computer. Committed domain names, README text, frontend `allowedHosts`, or values in `.env` do **not** prove that the current computer hosts the application.

There are two states to distinguish:

1. **Owner host configured:** the Cloudflare binary and a valid local tunnel config exist, and that config contains the Health Autopilot ingress routes.
2. **Application currently served:** the configured tunnel is running, both local origins are running, and health checks succeed.

At the beginning of work that involves hosting, deployment, public URLs, CORS, callbacks, email links, or tunnel configuration, perform read-only checks such as:

```bash
command -v cloudflared

# Find the config used by the running command first. Common defaults:
test -f "$HOME/.cloudflared/config.yml" && echo "$HOME/.cloudflared/config.yml"
test -f /opt/homebrew/etc/cloudflared/config.yml && echo /opt/homebrew/etc/cloudflared/config.yml
test -f /etc/cloudflared/config.yml && echo /etc/cloudflared/config.yml

cloudflared tunnel ingress validate
pgrep -fl cloudflared
lsof -nP -iTCP:5173 -sTCP:LISTEN
lsof -nP -iTCP:8001 -sTCP:LISTEN
curl -fsS --max-time 3 http://127.0.0.1:8001/health
curl -fsS --max-time 3 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173
```

Process-table and loopback access can be blocked by an agent sandbox. A sandbox failure is not evidence that the host or service is absent; report the limitation or use an approved read-only check.

The known owner-host signature is:

```yaml
tunnel: home-tunnel
ingress:
  - hostname: health.anthonyngene.com
    service: http://localhost:5173
  - hostname: api-health.anthonyngene.com
    service: http://localhost:8001
```

On that host the default config is normally `$HOME/.cloudflared/config.yml`, and the tunnel command is `cloudflared tunnel run home-tunnel`. The same shared config also contains routes for other personal applications, currently including `solve.anthonyngene.com` on port 3000 and `api.anthonyngene.com` on port 8000. Preserve all unrelated routes and the final `http_status:404` catch-all.

Do not assume `cloudflared` is managed by Homebrew, `launchd`, or another supervisor. Inspect the actual process and service manager before suggesting a restart. On a manually launched instance, stop only the verified cloudflared PID and restart the exact tunnel command; do this only when the user asks. Never install cloudflared, start/stop the tunnel, change DNS routes, or edit a config outside this repository merely because an app code change was requested.

After an explicitly requested tunnel-config edit:

- preserve its credentials reference without displaying it;
- run `cloudflared tunnel ingress validate`;
- verify the two local origins independently;
- restart via the process manager actually in use;
- verify the public endpoints if network access is available.

If the current machine does not match the configured-host checks, treat it as a normal local development checkout. Use `http://localhost:5173` and `http://localhost:8001`, and do not claim that a public deployment or tunnel was updated.

## Public URL and configuration relationships

When the owner-host tunnel is active:

- Frontend: `https://health.anthonyngene.com`
- API: `https://api-health.anthonyngene.com`
- Local frontend origin: `http://localhost:5173`
- Local API origin: `http://localhost:8001`

`APP_BASE_URL` controls links placed in scheduler emails. `API_BASE_URL` controls public API/callback URLs. `CORS_ALLOWED_ORIGINS` must allow the actual frontend origins. The frontend normally calls relative `/api` paths, with Vite proxying locally and the deployed routing/configuration supplying the correct backend behavior. Check all of these relationships when changing ports or hostnames.

## Data and domain invariants

- There is one canonical plan per Zurich-local date.
- `original_plan_json` is immutable; approved changes go into `current_plan_json` and audit records.
- Recommendations and actual results are separate. Historical corrections must not rewrite the original recommendation.
- Explicit food/workout records must not be overwritten by end-of-day reconciliation.
- Free-text food and workout ingestion must finish provider calls and validation before mutating stored state.
- Re-analysis replaces only entries owned by the prior diary; preserve Strava imports and later History corrections.
- Pain blocks automatic progression.
- Thursday is rest or very-light recovery; rest is a valid workout-plan option and contains no exercises.
- Active workouts require measurable targets. At most four exercises and one or two main meals are allowed.
- The optional Settings training-plan CSV is the active external planning guide. A replacement upload supersedes the prior guide without rewriting existing daily-plan history.
- Raw Strava location data must never enter AI context.
- OpenAI calls use `store=false`; keep provider models configurable through settings rather than scattering model names.

When modifying workout or nutrition recording, check both the Today and History API/render paths. Persisted actual measurements, difficulty, pain, notes, source/provenance, and diary ownership should remain visible and consistent in both places.

## Editing and handoff expectations

- Inspect `git status` before editing. The worktree may contain user changes; preserve unrelated work and do not reset or discard it.
- Prefer focused changes and targeted tests. Add or update regression tests for backend behavior and validation rules.
- Use an Alembic migration for schema changes; do not edit an applied migration to alter an existing database.
- Keep API writes behind the existing authentication and CSRF dependencies.
- Do not expose secrets in logs, test output, screenshots, diffs, or final responses.
- Update `README.md`, `.env.example`, and this file when operational facts or developer workflows change.
