#!/bin/sh
# Migrate (serialized by a Postgres advisory lock inside migrations/env.py), then serve.
# ONE worker on purpose: open workbooks live in this process's memory (see apps/api/README.md).
set -eu
cd /app
python -m alembic upgrade head
exec python -m uvicorn --factory gridora_api.main:run \
  --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --no-server-header --no-access-log
