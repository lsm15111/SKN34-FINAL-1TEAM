#!/usr/bin/env bash
# 비서 QA worker(arq). 사용: bash .claude/run-qa-worker.sh [qa | dev] [once <명령> ...]
# - run-qa-api.sh와 같은 DB · Redis · LLM 모드예요. 기한 일(1분) · 기억 뽑기 · 비서 정리(2분) · 시간 트리거(매시간)를 돌려요.
# - once: worker를 띄우지 않고 같은 설정으로 QA 도구의 프로세스 안 일(시간 당기기 · 업체 세션 · 비용 장부)을
#   한 번 돌려요(evaluation/v4/qa/qa.py가 불러요).
set -euo pipefail
PROFILE=qa
case "${1:-}" in qa | dev) PROFILE="$1"; shift ;; esac
. "$(dirname "$0")/qa-env.sh" "$PROFILE"
cd "$QA_BACKEND"
if [ "${1:-}" = once ]; then
  shift
  exec uv run python "$QA_ROOT/evaluation/v4/qa/inproc.py" "$@"
fi
exec uv run arq app.worker.WorkerSettings
