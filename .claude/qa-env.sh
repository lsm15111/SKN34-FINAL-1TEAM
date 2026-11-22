# 믿집 v4 비서 QA 환경 불러오기. run-qa-api.sh · run-qa-worker.sh · evaluation/v4/qa/make_db.sh가 같이 써요.
# 사용: . .claude/qa-env.sh <qa | dev>   (값 · 키는 화면에 찍지 않아요)
# - qa : DB mitjip_qa     · Redis db 13 · API 8050 · 화면 Origin 3050 · LLM 모드(메인 .env의 Anthropic 키만 살림)
# - dev: DB mitjip_qa_dev · Redis db 6  · API 8051 · 화면 Origin 3051 · 무료 모드(LLM_LIVE=false, 키 비움)
# 비용 상한은 운영 기본값(app/config.py) 그대로예요. 부르는 셸에 LLM_CAP_* 가 있어도 지워요.
# 새 계정 몫(가입 7일 안 고객)은 qa에서 기본으로 꺼요(QA 페르소나는 모두 새 계정). 보안 M4를 다시 볼 땐
# QA_NEW_USER_DAYS(예: 7) · QA_CAP_NEW_USER_DAY_USD · QA_CAP_NEW_POOL_DAY_USD를 넘기면 그 값으로 켜요(API · worker 같이).
QA_PROFILE="${1:-qa}"
case "$QA_PROFILE" in
  qa) QA_DB=mitjip_qa QA_REDIS_DB=13 QA_API_PORT=8050 QA_WEB_PORT=3050 QA_FILES=C:/Workspace/SKN34/.v4-qa-files ;;
  dev) QA_DB=mitjip_qa_dev QA_REDIS_DB=6 QA_API_PORT=8051 QA_WEB_PORT=3051 QA_FILES=C:/Workspace/SKN34/.v4-qa-dev-files ;;
  *) echo "모르는 갈래예요: $QA_PROFILE (qa · dev)" >&2; return 2 2>/dev/null || exit 2 ;;
esac
QA_CLAUDE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$QA_CLAUDE/env.sh"  # 메인 .env(DB 접속값) + LLM 키 비움 + LLM_LIVE=false
unset LLM_CAP_USER_DAY_USD LLM_CAP_SERVICE_DAY_USD LLM_CAP_TOTAL_USD LLM_CAP_TURN_USD LLM_CAP_NEW_USER_DAY_USD LLM_CAP_NEW_POOL_DAY_USD LLM_NEW_USER_DAYS
if [ "$QA_PROFILE" = qa ]; then
  # run-api.sh live 갈래와 같은 방법: Anthropic 키만 살려요(OpenAI · 다른 키는 비운 그대로). 상한은 올리지 않아요
  ANTHROPIC_API_KEY="$(sed -n 's/^ANTHROPIC_API_KEY=//p' /c/Workspace/SKN34/SKN34-FINAL-1TEAM/.env | tail -1 | tr -d '\r"'"'"'')"
  export ANTHROPIC_API_KEY LLM_LIVE=true ASSISTANT_PROMPT_SET="${QA_PROMPT_SET:-v4}"  # 지시문 판(QA 3차부터 v4, QA_PROMPT_SET=v3으로 되돌림)
  # 새 계정 몫: QA_*를 하나라도 넘기면 켜요(안 넘긴 값은 운영 기본값), 아니면 꺼요
  if [ -n "${QA_NEW_USER_DAYS:-}${QA_CAP_NEW_USER_DAY_USD:-}${QA_CAP_NEW_POOL_DAY_USD:-}" ]; then
    if [ -n "${QA_NEW_USER_DAYS:-}" ]; then export LLM_NEW_USER_DAYS="$QA_NEW_USER_DAYS"; fi
    if [ -n "${QA_CAP_NEW_USER_DAY_USD:-}" ]; then export LLM_CAP_NEW_USER_DAY_USD="$QA_CAP_NEW_USER_DAY_USD"; fi
    if [ -n "${QA_CAP_NEW_POOL_DAY_USD:-}" ]; then export LLM_CAP_NEW_POOL_DAY_USD="$QA_CAP_NEW_POOL_DAY_USD"; fi
  else
    export LLM_NEW_USER_DAYS=0
  fi
fi
export APP_ENV=local DEMO_AUTO=false JEV_ENABLED=false
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER:-mitjip}:${POSTGRES_PASSWORD}@127.0.0.1:${DB_HOST_PORT:-5433}/${QA_DB}"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT:-6379}/${QA_REDIS_DB}"
export ALLOWED_ORIGINS="http://localhost:${QA_WEB_PORT},http://127.0.0.1:${QA_WEB_PORT},http://vendor.localhost:${QA_WEB_PORT},http://admin.localhost:${QA_WEB_PORT}"
export FILES_DIR="$QA_FILES"
QA_ROOT="$(dirname "$QA_CLAUDE")"
QA_BACKEND="$QA_ROOT/backend"
export QA_PROFILE QA_DB QA_REDIS_DB QA_API_PORT QA_WEB_PORT QA_FILES QA_ROOT QA_BACKEND
