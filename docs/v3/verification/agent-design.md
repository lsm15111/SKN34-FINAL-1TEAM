# 에이전트 설계 브랜치 검증 기록 (`feat-v3-agent-design`)

실제로 돌린 것만 적어요. 유료 API 호출은 0회예요(`LLM_LIVE=false`, 키 비움).

## 브랜치 만들기

| 날짜 | 무엇 | 명령 · 방법 | 결과 |
| --- | --- | --- | --- |
| 2026-11-19 | 새 작업 폴더 · 브랜치 | `git worktree add -b feat-v3-agent-design ../wt-v3-agent 1a3e656` → `wt-v3`의 바뀐 파일(`git diff --binary HEAD`) · 새 파일(`git ls-files --others --exclude-standard`)을 옮김 | 바뀜 225 · 새 파일 878개, 두 폴더 트리 해시 같음(`ff4e9a7…`). 기준점 커밋 `c72f0a0`(1,103파일). `feat-v3` · `wt-v3`는 그대로(커밋 안 함) |
| 2026-11-19 | 실행 환경 | `uv sync --frozen`(캐시), `pnpm install --frozen-lockfile --prefer-offline`, 평가 캐시 `evaluation/v3/.cache` 복사(git 밖, 9.2MB) | 에이전트 테스트 4파일 91 passed |
| 2026-11-19 | 실행 스크립트를 이 폴더 기준으로 | `.claude/run-*.sh`의 `cd /c/.../wt-v3/...`를 스크립트 위치 기준으로 바꿈. 미리보기는 API 8031 · 화면 3031 · Redis db 13(`V3_API_PORT` · `V3_WEB_PORT` · `V3_REDIS_DB`로 바꿈) | `wt-v3`(8030 · 3030)와 같이 띄워짐 |

## 짧은 답(brief) 시제품

| 날짜 | 무엇 | 명령 · 방법 | 결과 |
| --- | --- | --- | --- |
| 2026-11-19 | 단위 · 턴 테스트 | `uv run --no-sync pytest tests/test_v3_agent_brief.py tests/test_v3_agent_gate.py tests/test_v3_agent_turn.py tests/test_v3_agent_knowledge.py tests/test_v3_agent_cards.py tests/test_agent_gate.py tests/test_v3_agent_judge_score.py` | **138 passed** |
| 2026-11-19 | API · 계약 테스트(실제 DB) | `bash .claude/run-tests.sh agentdesign tests/test_v3_ai_api.py tests/test_v3_contract.py` | **24 passed**(`done` 몸통에 `brief`가 있고, 고른 문장이 sections 안에 있음) |
| 2026-11-19 | OpenAPI | `app.openapi()`에 `AiAnswer` · `AiBrief`가 없음(SSE 몸통은 설명 글뿐) | `schema.d.ts` 바꿀 것 없음 |
| 2026-11-19 | 린트 · 타입 | `ruff check` · `ruff format --check`(바꾼 파일), `pnpm typecheck` · `pnpm lint` | 통과 · 오류 0 · 0 |
| 2026-11-19 | 화면 직접 확인(localhost 시연 고객) | 앱 안 브라우저, 미리보기 `v3a-api`(8031) · `v3a-web`(3031). 표준견적서 옆 'AI에게 묻기'에 질문 두 개 | 웹 1280: 접힘 = 핵심 1문장 + 못 찾은 공종 한 줄 + 출처 + '자세히 보기 · 3문장 더'(44px, `aria-expanded=false`) → 누르면 전체 3문장 + 주의 + '짧게 보기'(`true`). 폰 360: 가로 넘침 0, 단추 44px, 콘솔 오류 0 |
| 2026-11-19 | 짧은 답 코드 지표 | `uv run --no-sync python ../evaluation/v3/brief_eval.py`(초보 227 + 은행 493 → 근거 답 197개 비교) | 보이는 글자 중앙값 초보 217 → 109 · 은행 238 → 109, 200자 넘는 답 61 → 0 · 73 → 1. 표는 `docs/v3/agent-next.md` 6.4 |
| 2026-11-19 | 짧은 답 뜻 판정 | 고르기와 앞에서 자르기가 다른 102쌍(초보 56 · 은행 46)을 A/B 순서를 섞어 두 묶음으로 → 하위 에이전트 판정자 둘이 51쌍씩(정답표는 열지 않음) → 정답표로 풀어 집계 | 더 나음 39 : 30(같음 33, 부호 검정 p ≈ 0.34), 첫 문장이 바로 닿음 69 : 51(정확 검정 p ≈ 0.003), 핵심 놓침 9 : 19, '전체 답이 어긋남' 23쌍. 판정은 의문사 규칙 전 판 |
| 2026-11-19 | 조사 문서 | `docs/v3/research/agent-web.md`에 OpenAI 값(C15~C21)과 양쪽 대화 비용 표를 더함, Voyage 재순위 값 정정 | 공식 페이지 직접 확인 · 유료 호출 0 |
