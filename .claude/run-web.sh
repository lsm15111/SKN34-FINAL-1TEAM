#!/usr/bin/env bash
# 미리보기 화면. 사용: bash .claude/run-web.sh [v4]
# - 기본(v3): 포트 3031, API는 run-api.sh(8031)
# - v4: 포트 3040, API는 run-api.sh v4(8040)
# 환경변수 V3_WEB_PORT · V3_API_PORT로도 바꿔요(따로 준 값이 먼저예요)
set -euo pipefail
if [ "${1:-}" = v4 ]; then
  : "${V3_API_PORT:=8040}" "${V3_WEB_PORT:=3040}"
fi
export API_INTERNAL_URL="http://127.0.0.1:${V3_API_PORT:-8031}"
cd "$(cd "$(dirname "$0")/.." && pwd)/frontend"
exec pnpm exec next dev --port "${V3_WEB_PORT:-3031}"
