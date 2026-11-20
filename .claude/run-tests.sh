#!/usr/bin/env bash
# 사용: bash .claude/run-tests.sh <역할> [pytest 인자...]
# 역할마다 테스트 DB(mitjip_test_<역할>)와 Redis db 번호를 따로 써서 동시에 돌려도 부딪히지 않아요
set -euo pipefail
ROLE="${1:?역할 이름을 넣어 주세요(dev · agent · security · data · v4 · b1 · b2 ...)}"; shift
. "$(dirname "$0")/env.sh"
case "$ROLE" in
  b1a) N=1 ;; b1b) N=2 ;; b5|agent) N=3 ;; b6|data) N=4 ;; b7|security) N=5 ;; b8) N=6 ;; lead) N=8 ;; b2) N=9 ;; b3) N=10 ;; b4|design) N=11 ;; dev) N=14 ;; v4) N=15 ;; *) N=12 ;;
esac
export TEST_DB_NAME="mitjip_test_${ROLE}" TEST_REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/${N}"
cd "$(cd "$(dirname "$0")/.." && pwd)/backend"  # 이 작업 폴더의 backend
exec uv run pytest "$@"
