#!/usr/bin/env bash
# 미리보기 API. 사용: bash .claude/run-api.sh [v4]
# - 기본(v3): DB mitjip_v3 · Redis db 13 · 포트 8031 (화면은 run-web.sh, 3031)
# - v4: DB mitjip_v4 · Redis db 7 · 포트 8040 (화면은 run-web.sh v4, 3040)
# 환경변수 V3_DB_NAME · V3_REDIS_DB · V3_API_PORT · V3_WEB_PORT로도 바꿔요(따로 준 값이 먼저예요)
set -euo pipefail
if [ "${1:-}" = v4 ]; then
  : "${V3_DB_NAME:=mitjip_v4}" "${V3_REDIS_DB:=7}" "${V3_API_PORT:=8040}" "${V3_WEB_PORT:=3040}"
fi
. "$(dirname "$0")/env.sh"
WEB="${V3_WEB_PORT:-3031}"
export APP_ENV=local DEMO_AUTO=false JEV_ENABLED=false
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-mitjip}:${POSTGRES_PASSWORD}@127.0.0.1:${DB_HOST_PORT:-5433}/${V3_DB_NAME:-mitjip_v3}"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/${V3_REDIS_DB:-13}"
export ALLOWED_ORIGINS="http://localhost:${WEB},http://127.0.0.1:${WEB},http://vendor.localhost:${WEB},http://admin.localhost:${WEB},http://localhost:3030,http://127.0.0.1:3030,http://vendor.localhost:3030,http://admin.localhost:3030,http://localhost:3102,http://vendor.localhost:3102,http://localhost:3103,http://vendor.localhost:3103,http://admin.localhost:3103,http://localhost:3104,http://localhost:3105,http://localhost:3106,http://vendor.localhost:3106,http://localhost:3108,http://vendor.localhost:3108,http://admin.localhost:3108,http://localhost:3109"
export FILES_DIR="C:/Workspace/SKN34/.v3-files"
cd "$(cd "$(dirname "$0")/.." && pwd)/backend"
uv run alembic upgrade head
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${V3_API_PORT:-8031}" --reload
