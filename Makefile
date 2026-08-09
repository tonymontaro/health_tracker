.PHONY: setup db-up db-down migrate seed api web extension scheduler scheduler-check scheduler-start scheduler-stop test lint typecheck build verify

SCHEDULER_PID_FILE := .runtime/scheduler.pid
SCHEDULER_LOG_FILE := .runtime/scheduler.log

setup:
	./scripts/dev_setup.sh

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

migrate:
	cd backend && ../.venv/bin/alembic upgrade head

seed:
	.venv/bin/health-autopilot seed

api:
	.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8001

web:
	npm run dev --workspace frontend

extension:
	npm run dev --workspace extension

scheduler:
	.venv/bin/health-autopilot scheduler

scheduler-check:
	@if [ ! -f "$(SCHEDULER_PID_FILE)" ]; then \
		echo "Scheduler is stopped (no PID file)."; \
		exit 1; \
	fi; \
	pid="$$(sed -n '1p' "$(SCHEDULER_PID_FILE)")"; \
	if ! kill -0 "$$pid" 2>/dev/null; then \
		echo "Scheduler is stopped (stale PID $$pid)."; \
		exit 1; \
	fi; \
	command="$$(ps -p "$$pid" -o command=)"; \
	case "$$command" in \
		*health-autopilot*scheduler*|*app.jobs.scheduler*) \
			ps -p "$$pid" -o pid=,etime=,command= ;; \
		*) \
			echo "PID $$pid does not belong to the scheduler; refusing to report it as running."; \
			exit 1 ;; \
	esac

scheduler-start:
	@mkdir -p .runtime; \
	if [ -f "$(SCHEDULER_PID_FILE)" ]; then \
		pid="$$(sed -n '1p' "$(SCHEDULER_PID_FILE)")"; \
		if kill -0 "$$pid" 2>/dev/null; then \
			command="$$(ps -p "$$pid" -o command=)"; \
			case "$$command" in \
				*health-autopilot*scheduler*|*app.jobs.scheduler*) \
					echo "Scheduler is already running with PID $$pid."; \
					exit 0 ;; \
			esac; \
		fi; \
		echo "Replacing stale scheduler PID file."; \
		rm -f "$(SCHEDULER_PID_FILE)"; \
	fi; \
	nohup .venv/bin/health-autopilot scheduler > "$(SCHEDULER_LOG_FILE)" 2>&1 & \
	pid=$$!; \
	echo "$$pid" > "$(SCHEDULER_PID_FILE)"; \
	sleep 1; \
	if ! kill -0 "$$pid" 2>/dev/null; then \
		echo "Scheduler failed to start; check $(SCHEDULER_LOG_FILE)."; \
		exit 1; \
	fi; \
	ps -p "$$pid" -o pid=,etime=,command=

scheduler-stop:
	@if [ ! -f "$(SCHEDULER_PID_FILE)" ]; then \
		echo "Scheduler is already stopped (no PID file)."; \
		exit 0; \
	fi; \
	pid="$$(sed -n '1p' "$(SCHEDULER_PID_FILE)")"; \
	if ! kill -0 "$$pid" 2>/dev/null; then \
		rm -f "$(SCHEDULER_PID_FILE)"; \
		echo "Removed stale scheduler PID file ($$pid)."; \
		exit 0; \
	fi; \
	command="$$(ps -p "$$pid" -o command=)"; \
	case "$$command" in \
		*health-autopilot*scheduler*|*app.jobs.scheduler*) ;; \
		*) \
			echo "PID $$pid does not belong to the scheduler; refusing to stop it."; \
			exit 1 ;; \
	esac; \
	kill -TERM "$$pid"; \
	count=0; \
	while kill -0 "$$pid" 2>/dev/null && [ "$$count" -lt 50 ]; do \
		sleep 0.1; \
		count=$$((count + 1)); \
	done; \
	if kill -0 "$$pid" 2>/dev/null; then \
		echo "Scheduler PID $$pid did not stop within 5 seconds; PID file retained."; \
		exit 1; \
	fi; \
	rm -f "$(SCHEDULER_PID_FILE)"; \
	echo "Scheduler stopped."

test:
	cd backend && ../.venv/bin/pytest

lint:
	cd backend && ../.venv/bin/ruff check app tests ../scripts
	cd backend && ../.venv/bin/ruff format --check app tests ../scripts
	npm run lint

typecheck:
	cd backend && ../.venv/bin/mypy app
	npm run typecheck

build:
	npm run build

verify: lint typecheck test build
