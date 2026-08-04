#!/usr/bin/env bash
# Run the full DianaV2 e2e suite: tier1 (app), tier2 (DB), tier3 (lifecycle).
#
# Usage:
#   ./scripts/run_e2e.sh                          # full suite
#   ./scripts/run_e2e.sh tests/e2e/tier1 -k ...   # subset / extra pytest args
#
# Handles the environment details so you don't have to remember them:
#   - uses the project venv (.venv/bin/python) when present
#   - installs `testcontainers` (tier2/3 dep) into the venv if missing
#   - runs pytest under `sg docker` when the Docker socket needs the docker group
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- resolve python (prefer the project venv) -------------------------------
if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="${PYTHON:-python3}"
  echo "==> aviso: no hay .venv; usando ${PY} (instala deps con 'pip install -e .[dev]')"
fi
echo "==> python: $("$PY" --version)"

# --- testcontainers (required by tier2/3) -----------------------------------
if ! "$PY" -c "import testcontainers" &>/dev/null; then
  echo "==> testcontainers no está instalado; instalándolo en el venv…"
  "$PY" -m pip install testcontainers
fi

# --- build target (defaults to the whole e2e suite) --------------------------
TARGET=("$@")
if [[ ${#TARGET[@]} -eq 0 ]]; then
  TARGET=(tests/e2e/)
fi

# --- run under sg docker when the socket needs the docker group ---------------
if docker info &>/dev/null 2>&1; then
  echo "==> docker accesible directo; ejecutando: pytest ${TARGET[*]} -q"
  exec "$PY" -m pytest "${TARGET[@]}" -q
else
  echo "==> docker requiere grupo 'docker'; ejecutando vía 'sg docker': pytest ${TARGET[*]} -q"
  exec sg docker -c "$PY -m pytest ${TARGET[*]} -q"
fi
