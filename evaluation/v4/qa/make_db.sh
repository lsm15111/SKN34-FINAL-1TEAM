#!/usr/bin/env bash
# 비서 QA DB 다시 만들기. 사용: bash evaluation/v4/qa/make_db.sh [qa | dev | all] [--force]
# - 미리보기 DB mitjip_v4는 읽기만 해요(pg_dump). 미리보기 API가 붙어 있어 createdb -T 대신 덤프를 새 DB에 부어요.
# - qa: mitjip_qa(실제 QA, run-qa-api.sh 8050) · dev: mitjip_qa_dev(도구 개발, 8051). all(기본)은 둘 다예요.
# - 붓고 나서: Alembic head까지 올림 · 비용 장부(llm_usage) 비움(복사본에서만, QA 비용만 세게) ·
#   그 갈래 Redis db 비움(qa 13 · dev 6) · 미리보기 파일 폴더를 그 갈래 폴더로 복사 ·
#   시간 당기기 상태(runs/clock-<DB>.json) · 업체 찾기 기록(runs/vendors-<DB>.json) 지움
# - 그 DB에 붙은 연결(API · worker)이 있으면 멈춰요. --force면 연결을 끊고 다시 만들어요.
# - 값(비밀번호 · 키)은 찍지 않아요.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SRC=mitjip_v4
DBC=skn34-final-db-1
RDC=skn34-final-redis-1
SRC_FILES=C:/Workspace/SKN34/.v3-files
WHICH=all
FORCE=0
for a in "$@"; do
  case "$a" in
    qa | dev | all) WHICH="$a" ;;
    --force) FORCE=1 ;;
    *) echo "모르는 인자예요: $a (qa · dev · all · --force)" >&2; exit 2 ;;
  esac
done

sql() { # sql <DB> <SQL> → 값만(머리 · 꾸밈 없이)
  docker exec "$DBC" sh -c "psql -At -U \"\$POSTGRES_USER\" -d \"$1\" -c \"$2\""
}

make_one() (
  . "$ROOT/.claude/qa-env.sh" "$1"
  unset ANTHROPIC_API_KEY  # DB를 만드는 데는 LLM이 필요 없어요
  export LLM_LIVE=false
  case "$QA_DB:$QA_REDIS_DB" in
    mitjip_qa:13 | mitjip_qa_dev:6) ;;
    *) echo "QA DB · Redis 번호가 아니에요: $QA_DB" >&2; exit 2 ;;
  esac
  echo "== $QA_DB 만들기 ($SRC 복사)"
  n="$(sql postgres "select count(*) from pg_stat_activity where datname = '$QA_DB'")"
  if [ "$n" != 0 ] && [ "$FORCE" != 1 ]; then
    echo "$QA_DB에 연결이 ${n}개 있어요(API · worker). 끄고 다시 하거나 --force를 붙여요." >&2
    exit 3
  fi
  docker exec "$DBC" sh -c "dropdb -U \"\$POSTGRES_USER\" --if-exists --force $QA_DB && createdb -U \"\$POSTGRES_USER\" $QA_DB"
  errs="$(docker exec "$DBC" sh -c "pg_dump -U \"\$POSTGRES_USER\" $SRC | psql -q -U \"\$POSTGRES_USER\" -d $QA_DB 2>&1 >/dev/null | grep -c 'ERROR:' || true")"
  echo "  붓기: 오류 줄 ${errs:-0}개"
  echo "  복사한 판: $(sql "$QA_DB" "select version_num from alembic_version")"
  echo "  비용 장부 비움: $(sql "$QA_DB" "with d as (delete from llm_usage returning 1) select count(*) from d")줄"
  (cd "$QA_BACKEND" && uv run --quiet alembic upgrade head 2>&1 | grep -v '^INFO' || true)
  echo "  올린 판: $(sql "$QA_DB" "select version_num from alembic_version")"
  docker exec "$RDC" redis-cli -n "$QA_REDIS_DB" FLUSHDB >/dev/null
  echo "  Redis db $QA_REDIS_DB 비움"
  rm -rf "$QA_FILES"
  cp -r "$SRC_FILES" "$QA_FILES"
  echo "  파일 폴더: $(find "$QA_FILES" -type f | wc -l)개 복사"
  rm -f "$HERE/runs/clock-$QA_DB.json" "$HERE/runs/vendors-$QA_DB.json"
  echo "  사람: $(sql "$QA_DB" "select count(*) filter (where role = 'customer') || ' 고객 · ' || count(*) filter (where role = 'vendor') || ' 업체' from users")"
  echo "  승인 업체: $(sql "$QA_DB" "select string_agg(biz_name, ' · ' order by biz_name) from vendors where status = 'approved'")"
)

case "$WHICH" in
  qa) make_one qa ;;
  dev) make_one dev ;;
  all) make_one qa && make_one dev ;;
esac
echo "끝. 예전 기록 폴더(runs/<태그>)의 QA 계정 · 공사는 새 DB에 없어요. 새 태그로 new부터 해요."
