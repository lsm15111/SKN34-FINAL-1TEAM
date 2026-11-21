#!/usr/bin/env bash
# 미리보기 worker(arq). 사용: bash .claude/run-worker.sh [v4]
# - run-api.sh와 같은 DB · Redis를 써요(v4: mitjip_v4 · Redis db 7). 먼저 말 걸기 sweep(2분) · hourly · jobs(기억 뽑기)를 돌려요
set -euo pipefail
if [ "${1:-}" = v4 ]; then
  : "${V3_DB_NAME:=mitjip_v4}" "${V3_REDIS_DB:=7}"
fi
. "$(dirname "$0")/env.sh"
# live(두 번째 인자): 메인 .env의 Anthropic 키만 살리고 LLM_LIVE=true(사용자 결정 2026-11-21, 상한 $50). OpenAI · 다른 키는 그대로 비워요
if [ "${2:-}" = live ]; then
  ANTHROPIC_API_KEY="$(sed -n 's/^ANTHROPIC_API_KEY=//p' /c/Workspace/SKN34/SKN34-FINAL-1TEAM/.env | tail -1 | tr -d '\r"'"'"'')"
  # 흐름 시험: 사용자 하루 상한($0.40)에 걸려 흐름 중간에 무료 모드로 떨어지지 않게 올려요(쓴 돈은 장부로 따로 봐요)
  export ANTHROPIC_API_KEY LLM_LIVE=true LLM_CAP_USER_DAY_USD="${LLM_CAP_USER_DAY_USD:-2}"
fi
export APP_ENV=local DEMO_AUTO=false JEV_ENABLED=false
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-mitjip}:${POSTGRES_PASSWORD}@127.0.0.1:${DB_HOST_PORT:-5433}/${V3_DB_NAME:-mitjip_v3}"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/${V3_REDIS_DB:-13}"
export FILES_DIR="C:/Workspace/SKN34/.v3-files"
cd "$(cd "$(dirname "$0")/.." && pwd)/backend"
exec uv run arq app.worker.WorkerSettings
