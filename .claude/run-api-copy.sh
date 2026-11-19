#!/usr/bin/env bash
# 사용: bash .claude/run-api-copy.sh <이름> <포트>
# 시연 DB(mitjip_v3)를 mitjip_v3_<이름>으로 통째 복사하고, 그 DB로 API를 띄워요.
# 기한 당기기(run_due)처럼 데이터를 크게 바꾸는 점검은 공유 시연 DB 대신 이 복사본에서 해요.
set -euo pipefail
NAME="${1:?이름(예: b2b · e2e · cust)}"; PORT="${2:?포트(예: 8038)}"
. "$(dirname "$0")/env.sh"
DB="mitjip_v3_${NAME}"
docker exec skn34-final-db-1 dropdb -U "$POSTGRES_USER" --if-exists --force "$DB"
docker exec skn34-final-db-1 createdb -U "$POSTGRES_USER" "$DB"
docker exec skn34-final-db-1 sh -c "pg_dump -U \"\$POSTGRES_USER\" mitjip_v3 | psql -q -U \"\$POSTGRES_USER\" $DB" >/dev/null
export APP_ENV=local DEMO_AUTO=false JEV_ENABLED=false
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-mitjip}:${POSTGRES_PASSWORD}@127.0.0.1:${DB_HOST_PORT:-5433}/${DB}"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/6" REALTIME_PREFIX="mj:local:${NAME}"
export ALLOWED_ORIGINS="http://localhost:3030,http://127.0.0.1:3030,http://vendor.localhost:3030,http://admin.localhost:3030,http://localhost:3102,http://vendor.localhost:3102,http://localhost:3103,http://vendor.localhost:3103,http://admin.localhost:3103,http://localhost:3104,http://localhost:3105,http://localhost:3106,http://vendor.localhost:3106,http://localhost:3108,http://vendor.localhost:3108,http://admin.localhost:3108,http://localhost:3109"
export FILES_DIR="C:/Workspace/SKN34/.v3-files"
cd "$(cd "$(dirname "$0")/.." && pwd)/backend"
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
