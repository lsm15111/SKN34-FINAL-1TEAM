#!/usr/bin/env bash
# 비서 QA API. 사용: bash .claude/run-qa-api.sh [qa | dev]
# - qa(기본): DB mitjip_qa · Redis db 13 · 포트 8050 · LLM 모드(메인 .env의 Anthropic 키, 값은 찍지 않아요)
#   비용 상한은 운영 기본값 그대로(사용자 하루 $0.40 · 서비스 하루 $5 · 전체 $45 · 턴 $0.06)
# - dev: DB mitjip_qa_dev · Redis db 6 · 포트 8051 · 무료 모드(유료 호출 0회). QA 도구를 고치고 확인할 때
# DB는 evaluation/v4/qa/make_db.sh로 먼저 만들어요. worker는 run-qa-worker.sh(같은 갈래)를 함께 띄워요.
# 코드는 이 스크립트가 있는 체크아웃의 backend예요(미리보기처럼 --reload는 쓰지 않아요).
set -euo pipefail
. "$(dirname "$0")/qa-env.sh" "${1:-qa}"
cd "$QA_BACKEND"
uv run alembic upgrade head
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$QA_API_PORT"
