#!/usr/bin/env bash
# v3 미리보기 화면(feat-v3-agent-design 작업 폴더): 포트 3031, API는 run-api.sh(8031)
set -euo pipefail
export API_INTERNAL_URL="http://127.0.0.1:${V3_API_PORT:-8031}"
cd "$(cd "$(dirname "$0")/.." && pwd)/frontend"
exec pnpm exec next dev --port "${V3_WEB_PORT:-3031}"
