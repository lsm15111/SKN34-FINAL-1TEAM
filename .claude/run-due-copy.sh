#!/usr/bin/env bash
# 사용: bash .claude/run-due-copy.sh <이름> <시각 ISO, 예: 2026-11-21T10:00+09:00>
# 복사본 DB(mitjip_v3_<이름>)에서만 기한 일을 그 시각으로 당겨 돌려요(공유 시연 DB에는 쓰지 않아요)
set -euo pipefail
NAME="${1:?이름}"; NOW="${2:?시각}"
. "$(dirname "$0")/env.sh"
export APP_ENV=local
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-mitjip}:${POSTGRES_PASSWORD}@127.0.0.1:${DB_HOST_PORT:-5433}/mitjip_v3_${NAME}"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/6" REALTIME_PREFIX="mj:local:${NAME}"
cd "$(cd "$(dirname "$0")/.." && pwd)/backend"
exec uv run python -m app.run_due --now "$NOW"
