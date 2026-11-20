# 믿집 v3 · v4 로컬 환경 불러오기 (값은 화면에 찍지 않아요)
# 메인 체크아웃 .env에서 DB 접속 정보만 쓰고, LLM 키(OpenAI · Anthropic · OpenRouter · Voyage)는 모두 비워요(유료 API 0회)
set -a
. /c/Workspace/SKN34/SKN34-FINAL-1TEAM/.env >/dev/null 2>&1
set +a
export LLM_LIVE=false OPENAI_API_KEY= ANTHROPIC_API_KEY= OPENROUTER_API_KEY= VOYAGE_API_KEY=
export PYTHONIOENCODING=utf-8
