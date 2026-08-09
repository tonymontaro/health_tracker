#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$project_dir"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e './backend[dev]'
npm install
docker compose up -d postgres

cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/health-autopilot seed

echo "Setup complete. Start the API with: .venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8001"
echo "Start the web app with: npm run dev --workspace frontend"
