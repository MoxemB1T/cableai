#!/bin/sh
set -eu

mkdir -p /app/persist

if [ ! -f "${CABLE_AI_DB_PATH:-/app/persist/catalog.db}" ]; then
  cp /app/catalog.db "${CABLE_AI_DB_PATH:-/app/persist/catalog.db}"
  echo "[INIT] Seeded persistent catalog database."
fi

exec python app.py
