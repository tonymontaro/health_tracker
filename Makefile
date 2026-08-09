.PHONY: setup db-up db-down migrate seed api web extension scheduler test lint typecheck build verify

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
	.venv/bin/uvicorn app.main:app --app-dir backend --reload

web:
	npm run dev --workspace frontend

extension:
	npm run dev --workspace extension

scheduler:
	.venv/bin/health-autopilot scheduler

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
