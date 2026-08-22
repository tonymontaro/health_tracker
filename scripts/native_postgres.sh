#!/usr/bin/env bash
set -euo pipefail

readonly formula="postgresql@17"
readonly postgres_bin="/opt/homebrew/opt/${formula}/bin"
readonly postgres_config="/opt/homebrew/var/${formula}/postgresql.conf"
readonly postgres_port="55432"

require_homebrew() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required to manage native PostgreSQL 17." >&2
    exit 1
  fi
}

install_postgres() {
  require_homebrew
  if ! brew list --versions "$formula" >/dev/null 2>&1; then
    brew install "$formula"
  fi
}

configure_port() {
  if grep -Eq "^[#]?[[:space:]]*port[[:space:]]*=" "$postgres_config"; then
    sed -i '' -E "s/^[#]?[[:space:]]*port[[:space:]]*=.*/port = ${postgres_port}/" "$postgres_config"
  else
    printf '\nport = %s\n' "$postgres_port" >> "$postgres_config"
  fi
}

start_postgres() {
  install_postgres
  configure_port
  brew services start "$formula" >/dev/null
  for _ in {1..30}; do
    if "$postgres_bin/pg_isready" -h 127.0.0.1 -p "$postgres_port" >/dev/null 2>&1; then
      echo "PostgreSQL 17 is ready on port ${postgres_port}."
      return
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready on port ${postgres_port}." >&2
  exit 1
}

database_exists() {
  "$postgres_bin/psql" -h 127.0.0.1 -p "$postgres_port" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '$1'" | grep -q 1
}

role_exists() {
  "$postgres_bin/psql" -h 127.0.0.1 -p "$postgres_port" -d postgres -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname = '$1'" | grep -q 1
}

setup_databases() {
  start_postgres
  if ! role_exists health; then
    "$postgres_bin/createuser" -h 127.0.0.1 -p "$postgres_port" health
  fi
  "$postgres_bin/psql" -h 127.0.0.1 -p "$postgres_port" -d postgres \
    -c "ALTER ROLE health WITH LOGIN PASSWORD 'health';" >/dev/null
  if ! database_exists health; then
    "$postgres_bin/createdb" -h 127.0.0.1 -p "$postgres_port" -O health health
  fi
  if ! database_exists health_test; then
    "$postgres_bin/createdb" -h 127.0.0.1 -p "$postgres_port" -O health health_test
  fi
  echo "Native PostgreSQL databases are configured."
}

case "${1:-start}" in
  start)
    start_postgres
    ;;
  stop)
    require_homebrew
    brew services stop "$formula"
    ;;
  setup)
    setup_databases
    ;;
  *)
    echo "Usage: $0 {start|stop|setup}" >&2
    exit 2
    ;;
esac
