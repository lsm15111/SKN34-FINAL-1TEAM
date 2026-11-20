# 코드 지도: v2 화면 · v3 에이전트(2026-11-21)

- 기준: upstream/dev(f3ecd63)와 feat-v3-agent-design(b1985d8, wt-v3-agent)
- 방법: 읽기 전용 조사 하위 에이전트 보고를 정리했어요. 경로는 저장소 루트 기준이에요. [feat]는 feat-v3-agent-design에만 있는 것이에요.

## 1. 화면
- **v2 UI**는 `/v2` 한 경로예요(`frontend/app/v2/page.tsx`).
  - `components/v2/V2App.tsx`가 `#`(첫 화면)과 `#chat`(상담)으로 나뉜 대화형 한 화면 앱이에요.
  - 단계 화면은 표(F)의 함수가 대화에 카드로 붙여요.
  - 백엔드는 `/v2/*`(`backend/app/v2/router.py`)만 불러요. 고객 로그인이 필요하고, v3 화면에서 이리로 오는 링크는 없어요.
  - 두 브랜치의 v2 코드는 같아요(diff 0).
- **v2 UI는 v2 에이전트에 묶여 있어요.** `components/v2/ai/llm.ts`가 `/v2/ask` 도구 루프를 돌리고 화면 도구(set_style · set_home_info · set_scope · set_budget · pick_material · show_step)를 실행해요.
- v2가 다루는 범위는 목적 고르기 → 질문 → 예산 · 표준견적서 · 공정표예요. 업체 요청은 로컬 브랜치 `feat-v2-vendor-request`에만 있어요(메모리 기준).
- **기본 경로는 모두 v3(9판) 화면이에요.** `/`, `/start`, `/projects/[id]/{standard,plan,vendors,visits,quotes,schedule,review,docs}`, `/vendor/**`
  - 단계: `components/ui/Steps.tsx`
  - 경로표: `docs/v3/routes.md`
- v3 AI 칸(`AiPanel` · `AiSlot` · `GuestAsk` · `AskLauncher`)은 모두 `lib/api/chat.ts` → `POST /ai/turns`를 불러요.

## 2. 에이전트
| | v2 | v3 |
| --- | --- | --- |
| 진입 | `POST /v2/ask`, `/v2/ask/{turn_id}` | `POST /ai/turns`(SSE) · `/ai/threads` · `/ai/faq` |
| 흐름 | `agent/gate.py`(학습 모델, 신뢰도 0.7 미만이면 Jev) → LLM↔도구 루프(턴당 최대 6회) → `v2/guard.py` | `agent/v3/gate.py` → 담당 → `check.py` |
| 지시문 | `v2/prompts/chat_v4.md`(현재), quote_explanation_v2, schedule_v1, trade_dobae_v1 · trade_mokgong_v1 | `agent/v3/prompts/*_v1.md`. [feat]: composer_v3~v7(현재 v7) · planner_v1 · general_v1 |
| LLM 없이 | 고정 문구 하나만(사실상 LLM 필요) | 무료 모드: 카드 · 검색 · 계산 엔진 답 |

- LLM 호출은 `agent/llm.py` 한 곳이에요(v2는 `chat_tools()`, v3는 `structured()`).
- 공급자는 OpenAI(langchain_openai)예요(`config.py`).
  - 모델: 기본 gpt-6.1-terra(effort low), 작은 모델 gpt-6-luna, 임베딩 text-embedding-3-small
  - Jev: OpenRouter를 거치고 v2 관문에서만 써요.
- upstream과 feat의 차이
  - upstream의 에이전트 변경은 #166뿐이에요. #170(feat-v3-llm-answer)은 설계 문서 `docs/v3/adr/agent-08-llm-compose.md`만 바꿨고, 그 설계는 feat에 이미 구현돼 있어요.
  - feat에만 있는 것: composer · planner · general · brief · context · explain · calc_lines · screen · screen_tools, 무료 모드 의미 검색, 하루 LLM 100회 상한, SSE part, 마이그레이션 0036~0038
  - 둘이 같이 고친 파일이 13개예요.

## 3. 평가 자산
- `evaluation/answer/`: set30(30문항), run.py(v2 ask, 유료), judge.md, score.py
- `evaluation/trade/`: 담당별 9문항, route.py(390문항, 무료)
- `evaluation/rag/`: questions 90 · 300 · 시공 60, gold 225, metrics.py
- `evaluation/v3/`: beginner_eval 227, sets/multi.jsonl 45, judge_pack · judge_score · rubric.md
- [feat] `evaluation/v3/`
  - core_questions 32와 같은 질문의 ChatGPT 답(gpt_core_answers)
  - core_run(무료), composer_eval(LLM · 비용 기록), coverage_check(72), general_eval(37), brief_eval(A/B 짝 판정)
- 두 에이전트를 비교하려면 core 32로 v2(run.py에 q를 text로 넣어 맞춤)와 v3(composer_eval)를 돌리고, 집 조건(v2 32평 · v3 69.4㎡)을 맞춘 뒤, 순서를 섞은 짝 판정 + rubric.md로 채점해요.

## 4. 업체 쪽
- 실측 요청: `visit/router.py` · `service.py` · `flow.py`(요청할 때 `visit_requested` 알림). 업체용 `GET /vendor/visits/{id}`는 이름 · 연락처 없이 내려줘요.
- 일정 · 작업함: `schedule/router.py`(`/vendor/visits?tab=`, `/vendor/visits/summary`, `/vendor/jobs/{deal_id}`), `schedule/inbox.py`. 기한은 `visit/jobs.py` · `schedule/jobs.py`가 다뤄요.
- 알림: `notify/catalog.py`(업체용 약 20종), `notify/service.py`
- 화면: `components/pro/inbox/Inbox.tsx`, `app/vendor/requests/[visitId]/page.tsx` + `components/pro/visit/facts.tsx`(한 줄 요약이 이미 있어요)
- 요청 요약 자리: `schedule/inbox.py` 줄 데이터로 요약 → `visit/schemas.py`의 `InboxSummaryOut` · `VendorVisitDetailOut`에 칸 추가 → Inbox 머리 · facts에 보이기. 지금 `/ai/turns`는 고객만 써요.

## 5. 계산 엔진(calc)
- 표준견적서: `quote/service.py` `calc_trades()`(목공 → 도배) · `standard_v3()` → `calc/dobae.py` `standard_v3()`
  - 저장은 `ensure_standard()`, 화면은 `standard_for()`, 로그인 전은 `POST /guest/standard`
- 업체 견적서는 합계 · 일수 · 포함 여부만 있고 항목 줄은 없어요(`quote/models.py` `VendorQuote`).
- 비교 함수
  - `calc/quote_diff.py` `percent_vs`
  - `calc/visit_view.py` `quote_vs_estimate` · `quote_gap`
  - `calc/estimate.py` `estimate_v3`
  - 묶어서 쓰는 곳: `visit/service.py` `compare`(`GET /projects/{id}/quotes`). v2는 `calc/v2_check.py` `check`

## 6. 기준 브랜치
- 추천: feat-v3-agent-design에 upstream/dev를 병합한 뒤 새 브랜치를 따요.
- 이유: 더 나은 답 후보(composer v7 · planner · 의미 검색)와 비교 세트가 feat에만 있고, v2 UI는 두 쪽이 같아요.
- 실제로는 2026-11-21에 `feat-v4-secretary`(wt-v4)를 feat-v3-agent-design b1985d8에서 따서 병합 중이에요.
