#!/usr/bin/env bash
# v3 미리보기 API(feat-v3-agent-design 작업 폴더): DB mitjip_v3 · Redis db 13 · 포트 8031 (화면은 run-web.sh, 3031)
# wt-v3(8030 · 3030)와 같이 띄울 수 있게 포트 · Redis 번호를 다르게 뒀어요. V3_API_PORT · V3_REDIS_DB로 바꿔요
set -euo pipefail
. "$(dirname "$0")/env.sh"
export APP_ENV=local DEMO_AUTO=false JEV_ENABLED=false
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-mitjip}:${POSTGRES_PASSWORD}@127.0.0.1:${DB_HOST_PORT:-5433}/mitjip_v3"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/${V3_REDIS_DB:-13}"
export ALLOWED_ORIGINS="http://localhost:3031,http://127.0.0.1:3031,http://vendor.localhost:3031,http://admin.localhost:3031,http://localhost:3030,http://127.0.0.1:3030,http://vendor.localhost:3030,http://admin.localhost:3030,http://localhost:3102,http://vendor.localhost:3102,http://localhost:3103,http://vendor.localhost:3103,http://admin.localhost:3103,http://localhost:3104,http://localhost:3105,http://localhost:3106,http://vendor.localhost:3106,http://localhost:3108,http://vendor.localhost:3108,http://admin.localhost:3108,http://localhost:3109"
export FILES_DIR="C:/Workspace/SKN34/.v3-files"
cd "$(cd "$(dirname "$0")/.." && pwd)/backend"
uv run alembic upgrade head
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${V3_API_PORT:-8031}" --reload
