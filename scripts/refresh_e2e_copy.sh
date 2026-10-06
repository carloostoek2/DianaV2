#!/usr/bin/env bash
# Construye/actualiza la copia local de la base real que usan las pruebas e2e.
#
#   ./scripts/refresh_e2e_copy.sh
#
# Por qué existe: la suite completa (tests/e2e, con docker) crea y borra tablas
# (migraciones arriba/abajo) y hace DELETE sin filtro en algunas tablas. Correrla
# contra la base real la dañaría. Este script toma la conexión REAL desde el .env
# (solo lectura: un pg_dump), la deja como copia local y tests/e2e/conftest.py la
# restaura en el contenedor desechable de cada corrida. Resultado: las pruebas
# corren sobre datos reales y la base real nunca se toca.
#
# El volcado CONTIENE DATOS REALES DE LOS VIP: queda en runtime/ (ignorado por
# git) y no se versiona ni se comparte.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
OUT_DIR="$ROOT/runtime/e2e_copy"
OUT="$OUT_DIR/diana_copy.sql"

# --- conexión real, tomada del .env ----------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: no existe $ENV_FILE (ahí vive DATABASE_URL)." >&2
  exit 1
fi
DB_URL="$(grep -E '^[[:space:]]*DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//" | tr -d '[:space:]')"
if [[ -z "$DB_URL" ]]; then
  echo "ERROR: DATABASE_URL no está en $ENV_FILE." >&2
  exit 1
fi

# pg_dump no entiende el driver ni el ?ssl=require del .env: se traduce a un URL
# libpq limpio y el SSL se pide con PGSSLMODE (el servidor real lo exige).
DUMP_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql://}"
DUMP_URL="${DUMP_URL%%\?*}"

command -v pg_dump >/dev/null 2>&1 || {
  echo "ERROR: falta pg_dump (postgresql-client)." >&2
  exit 1
}

mkdir -p "$OUT_DIR"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/diana_copy.XXXXXX")"
TMP="$WORK/raw.sql"
trap 'rm -rf "$WORK"' EXIT

# --- volcado (solo lectura sobre la base real) ------------------------------
echo "==> Volcando la base real (solo lectura): esquema public + datos…"
if ! PGSSLMODE=require pg_dump "$DUMP_URL" \
      --schema=public --no-owner --no-privileges \
      >"$TMP" 2>"$WORK/err.log"; then
  echo "ERROR: falló el volcado de la base real:" >&2
  tail -5 "$WORK/err.log" >&2
  exit 1
fi

# --- adaptación al contenedor de pruebas ------------------------------------
# 1) SET transaction_timeout es de Postgres 17; el contenedor es pg16 y aborta.
# 2) CREATE SCHEMA public ya existe en el contenedor (se restaura sobre una base
#    recién creada, no sobre un servidor vacío).
# 3) Las extensiones que el esquema necesita se crean antes de las tablas (el
#    volcado de public no las incluye porque viven en otros esquemas / son del
#    servidor de origen).
# Se escribe primero al lado y se mueve al final: una copia a medias nunca queda
# en su lugar (las pruebas la tomarían como buena).
PARTIAL="$WORK/diana_copy.sql"
{
  echo "-- Copia local de la base real para las pruebas e2e (generada por"
  echo "-- scripts/refresh_e2e_copy.sh — NO versionar: contiene datos de VIP)."
  echo "CREATE EXTENSION IF NOT EXISTS vector;"
  echo "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
  grep -v -e '^SET transaction_timeout' -e '^CREATE SCHEMA public;' "$TMP"
} >"$PARTIAL"
mv "$PARTIAL" "$OUT"

# --- resumen ----------------------------------------------------------------
TABLAS="$(grep -c '^COPY public' "$OUT" || true)"
echo "==> Copia lista: $OUT"
echo "    tamaño:   $(du -h "$OUT" | cut -f1)"
echo "    tablas:   $TABLAS con datos"
echo "    generada: $(date -u '+%Y-%m-%d %H:%M UTC')"
echo
echo "Las pruebas e2e la usarán automáticamente en la próxima corrida:"
echo "    ./scripts/run_e2e.sh"
