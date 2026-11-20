# 에이전트 작업 협약

**현행 v3 `dev` `344f6dc`**의 AI 경로와 **기존 v2 C안(#110)**을 구분한다. 아래 1~8절의 `chat_v4`·Jev·`/v2/ask`·`living_said`·평가 데이터 2:1 규칙은 계속 남아 있는 **v2 구현·설계 기록**이다. 현행 v3 호출은 [v3 구조](v3/architecture.md)와 코드, 기존 v2 호출은 [v2 구조](v2/structure.md)·[v2 ERD](v2/erd.md)를 따른다. 후속 설계를 구현 완료로 해석하지 않는다.

## 현행 v3 AI 상담 (`/ai/turns`)

| 단계 | 구현과 책임 | 근거 |
| --- | --- | --- |
| 질문·인증 | 로그인 고객이 `POST /ai/turns`로 질문. 세션 소유 대화·공사만 사용하고, 새 대화는 첫 성공 턴에 저장. 같은 대화 `rev` 충돌은 409, `client_key` 재전송은 짧은 캐시로 같은 답 사용 | [chat/router.py](../backend/app/chat/router.py) · [chat/service.py](../backend/app/chat/service.py) |
| 입구 관문 | 버튼·대기 역할, 정책, 12공종 낱말, 학습 분류기, 규칙, 화면 문맥으로 역할·범위를 정함. **v3는 Jev 호출 없음**. 단일 담당은 바로 답하고 복합 요청은 코드 오케스트레이터가 조각을 합침 | [agent/v3/gate.py](../backend/app/agent/v3/gate.py) · [orchestrator.py](../backend/app/agent/v3/orchestrator.py) |
| 기본 답 | `LLM_LIVE=false`가 기본. 무료 카드·키워드 BM25 검색(활성 지식이 있을 때)·정해진 안내·계산 결과를 사용하며, 모르는 것은 모른다고 답함. 도배·목공 계산과 다른 공종의 지식 안내를 구분 | [agent/v3/answer.py](../backend/app/agent/v3/answer.py) · [knowledge/search3.py](../backend/app/knowledge/search3.py) |
| 선택 LLM | `LLM_LIVE=true`와 `OPENAI_API_KEY`가 모두 있을 때에만 가이드·공종·복합 답의 일부 카드·조각 문장을 재작성. 높은 점수 카드·정해진 글·계산 묶음은 건너뛰고, 실패·출력 검사 탈락 시 무료 답을 유지 | [chat/service.py](../backend/app/chat/service.py) · [agent/v3/turn.py](../backend/app/agent/v3/turn.py) |
| 저장·SSE | **정상 답은** 서버가 계산·검사하고 대화를 **commit한 뒤**, `token`(완성된 문장) → `card`(화면 카드) → `done`(전체 답) SSE를 보낸다. **실시간 모델 토큰 생성 스트리밍은 아니다.** 고객·업체 `/threads` 채팅과도 별도 | [chat/router.py](../backend/app/chat/router.py) · [thread/router.py](../backend/app/thread/router.py) |

계획 문서 [v3 AI 설계](v3/agents.md)의 모든 기능을 구현으로 간주하지 않는다. 실제 [worker](../backend/app/worker.py)는 `ping`·선택적 시연 자동 응답과 실측·견적·공사 기한 `sweep_jobs`를 등록했고, 예약형 AI 답변·지식 수집 LLM 업무는 아직 등록하지 않았다. [`mcp_server.py`](../backend/app/mcp_server.py)는 빈 파일로, 일정 MCP 호출도 미구현이다. [검증 기록](testing.md#v3-병합-기준-검증-기록)은 선택 테스트·별도 AI QA DB 범위를 따른다.

## 1. 역할

- 오케스트레이터: 고객과 말하는 LLM 하나. 현재는 의도 라벨에 따라 역할 힌트·공정별 지시문·서버/화면 도구를 사용한다. 공종 에이전트 하위 호출로 결과를 합치는 흐름은 후속 구현 목표다. 되묻기는 오케스트레이터만 한다.
- 공종 에이전트(`trade`): 고객에게 말하지 않는 하위 호출. 공정별 설정 + 지식 검색으로 필요한 조건 · 주의점 · 근거 번호를 돌려준다. 후속 구현 목표(지금은 뼈대만).
- 범위 밖: LLM 없이 고정 안내.
- 의도 라벨 `trade`(옛 이름 `consult`)는 공정 상담 역할이다. 학습 데이터 · eval · 모델 라벨도 `trade`다(#75).

| 의도 라벨 | 역할 | 하는 일 | 지시문 |
| --- | --- | --- | --- |
| `orchestrator` | 가이드 | 처음 궁금증 · 시작 순서 · 기본 정보 · 제출 서류, 복합 요청 | 현재 `v2/prompts/chat_v4.md`; 역할별 `guide_v*.md` 분리는 후속 |
| `trade` | 공정 상담 | 우리 집 조건 묻기 · 공정 간 조정. 공종 에이전트 하위 호출은 후속 | 현재 `chat_v4.md` + `trade_dobae_v1.md` · `trade_mokgong_v1.md` |
| `quote_explanation` | 견적 설명 | 계산 엔진 금액 풀이만 | `v2/prompts/quote_explanation_v*.md` |
| `schedule` | 공정표 | 말을 제약으로 바꾸기 · 결과 설명. 일정 MCP는 후속 | 현재 `v2/prompts/schedule_v1.md` |

- 지금은 가이드 · 공정 상담이 `chat_v4.md` 하나를 같이 쓰고, 관문 라벨에 맞는 역할 힌트를 붙인다. 공정 상담은 질문 낱말로 공정 하나가 분명하면 그 공정 지시문(`trade_dobae_v1` · `trade_mokgong_v1`)과 공정 설정을 더한다(공정은 코드가 고른다). 나누는 것은 eval을 붙인 `prompt` PR로 한다.
- 현재 역할별 사용 가능 도구는 `v2/ask_tools.py`의 `BY_KIND`가 정한다. `trade_agent.py`의 `trade()`는 `AgentAnswer(failed=True)`를 반환하고 오케스트레이터에서 호출되지 않는다.
- **이미지 없는 일반 상담(`kind=chat`)에 한해** `?` · `ㅠㅠ` 등 낱말 없는 질문은 관문·LLM 호출 전에 고정 안내로 끝나며 저장하지 않는다. 이 조건에서 낱말이 있을 때만 의도 분류를 실행한다. 이미지 있는 채팅·견적·공정표 설명 요청은 무문자 검사와 의도 분류를 모두 건너뛴다(PR #140).
- `set_home_info`에서 `living`의 의미(거주·비거주·미정)는 모델이 판단한다. 서버는 모델이 옮긴 `living_said` 문구가 실제 고객 발화에 있는지(짧은 네/아니요 답은 직전 AI 질문까지) 확인한다. `living_said`는 모델 쪽 대화 기록에 보존하지만 화면에 보낼 도구 인자에서는 제거한다. 이는 인용 문구 존재 확인이지 **거주 의미를 서버가 검증했다는 뜻은 아니다**.

## 2. 파일 나누기

| 묶음 | 현재 존재하는 코드·지시문·평가 | 후속/미생성(현재 완료로 보지 않음) |
| --- | --- | --- |
| 한 턴 · 관문 | `backend/app/v2/ask.py` · `ask_chat.py` · `guard.py`, `backend/app/agent/gate.py` · `route.py` · `intent.py`, `evaluation/intent/` | — |
| 가이드 · 오케스트레이터 | 현재 공용 상담 프롬프트 `backend/app/v2/prompts/chat_v4.md` | 역할 분리 `guide_v*.md`는 **미생성**. `evaluation/guide/` · `evaluation/orchestrator/`는 폴더의 `.gitkeep`만 있어 평가 세트 **미생성** |
| 공종 | `backend/app/agent/trade_agent.py`(실패를 반환하는 뼈대) · `trades/dobae.py` · `trades/mokgong.py`; `backend/app/v2/prompts/trade_dobae_v1.md` · `trade_mokgong_v1.md`; `evaluation/trade/` | 단일 공종 에이전트의 **실제 하위 호출**은 후속(도배·목공 별도 에이전트를 만드는 계획 아님) |
| 견적 설명 (담당 미정) | `backend/app/v2/prompts/quote_explanation_v2.md`(현재 `/v2/ask` 설명 역할) | `evaluation/quote_explanation/`는 `.gitkeep`만 있어 **역할 전용 평가 세트 미생성** |
| 공정표 | `backend/app/v2/prompts/schedule_v1.md`(현재 설명 역할) | `backend/app/mcp_server.py`는 빈 파일(일정 MCP 미구현). `evaluation/schedule/`는 `.gitkeep`만 있어 **역할 전용 평가 세트 미생성** |
| 지식 검색 · 추천 질문 | `backend/app/knowledge/`; `evaluation/rag/` · `evaluation/answer/`(실제 평가 자료·실행 파일 있음) | — |
| 대화 저장 | `backend/app/chat/`(`chats` · `chat_messages` 저장) | — |
| 공용 | `backend/app/agent/schemas.py` · `llm.py` · `trades/base.py`, `backend/app/v2/ask_tools.py` · `schemas.py`, `backend/app/config.py` | 공용 파일 수정은 아래 팀 조정 규칙을 유지 |

**v2 기록 기준: 2026-11-19 `dev` `6d41f94` (PR #140·#148 병합).** `/v2/ask`는 **`chat_v4` · `quote_explanation_v2` · `schedule_v1`** 및 공종 힌트 `trade_dobae_v1` · `trade_mokgong_v1`을 사용한다(`backend/app/v2/ask.py`의 `PROMPT_VERSION` · `TRADE_PROMPTS`). 이전 **2026-11-18 `dev` `1a3e656`** 당시의 상담 프롬프트는 `chat_v3`였다. `evaluation/intent/` · `rag/` · `answer/` · `trade/` · `ask_back/`에는 실제 평가 자료 또는 실행 파일이 있지만, 폴더 존재만으로 `guide/orchestrator/quote_explanation/schedule` 역할 전용 평가가 완성됐다고 보지 않는다.

- 자기 묶음 파일만 고친다.
- `trades/base.py`(공정 설정 모양)는 공종 · 견적 설명 · 공정표가 같이 읽으므로 공용이다. 공정별 값은 공종이 맡는다.
- 공용 파일은 여럿이 같이 쓰므로 충돌을 줄이려고 이렇게 고친다:
  1. 고칠 게 생기면 팀 채팅에 먼저 말한다.
  2. 새 줄 더하기만이면 기능 PR에 같이 둔다. PR 본문에 고친 공용 파일을 적는다.
  3. 기존 줄을 바꾸거나 지우면 그 변경만 담은 PR을 따로 올려 먼저 병합한다.
  4. 나머지는 dev로 rebase해서 받는다.

## 3. 공종 에이전트 모양 (후속 구현 목표)

- 받는 값: 오케스트레이터가 나눈 고객 문장, 코드가 고른 공정 설정(도배 · 목공, 모르면 둘 다), 지식 검색 결과(조각 번호 포함). 사용자 · 대화 id는 받지 않는다.
- 돌려주는 값(Pydantic): 공정, 필요한 조건(빠진 칸), 주의점, 근거 번호. 금액 · 수량 · 날짜는 넣지 않는다.
- 설정 + 검색으로 채울 수 있으면 LLM을 부르지 않는다. 필요할 때만 작은 모델을 쓴다.
- LLM 실패(`llm.LLMError`)는 잡아서 그 공정 몫만 실패로 돌려준다. 규칙으로 만든 가짜 설명으로 채우지 않는다.
- 다른 에이전트 · 오케스트레이터를 부르지 않는다.

## 4. LLM 호출과 출력 모델

- 오케스트레이터는 `llm.chat_tools(system, messages, tools)`로 부른다. 지시문 · 도구 · 반복 횟수는 서버(`v2/ask.py`)가 정한다.
- 공종 에이전트를 구현할 때는 `llm.structured(role, schema, messages)`로 부른다(후속 설계).
- LLM에서 받는 모양(예: `TradeNote`)은 자기 파일 안에 둔다. 여럿이 같이 쓸 때만 `agent/schemas.py`로 옮긴다.
- 답 글은 출력 검사(`v2/guard.py`)를 거친다. 금액 · 기간 숫자는 계산 엔진 결과에 있어야만 남는다.

## 5. 오케스트레이터가 공종 에이전트를 부를 때 (후속 구현 목표)

- 서버 도구로 부른다. 두 공정이면 동시에 부른다.
- 턴당 공종 에이전트 호출은 3회까지, 역할별 도구 호출은 4회까지다.
- 돌아온 주의점은 바꾸지 않고 근거 번호를 붙여 보여 준다.
- 일부 공정만 실패하면 그 몫만 "설명을 만들지 못했어요"로 넣는다. 모두 실패했을 때만 답 전체를 실패로 한다.

## 6. 데이터와 도구

- 도구는 `v2/ask_tools.py`가 정한다. 서버 도구는 계산 엔진 둘(`price_reference` · `set_schedule_constraints`)과 지식 검색(`search_knowledge`)이고 서버가 바로 실행한다. 화면 도구(고객 상태 제안 · 단계 카드)는 브라우저가 실행해 결과만 돌려준다. 고객 상태 도구는 제안만 하고, 고객이 [담기]를 눌러야 저장한다.
- 자료 검색은 서버가 한다. 턴을 시작할 때 첫 근거를 찾아 넣고, 도구 검색은 `knowledge.service` → 활성 버전(`knowledge.repository`) → PostgreSQL이다. 공정이 분명하면 그 공정 + 공통 자료를 먼저 본다. 공종 에이전트 도구는 후속 구현 목표다.
- 숫자 근거는 서버가 만든 값(계산 엔진 결과 · 서버가 찾은 근거 원문)만 쓰는 것이 목표다. 지식 자료의 기간 숫자는 공사 기간 근거에 넣지 않는다. 화면 도구 결과도 아직 숫자 검사의 허용 글에 들어가며, 이를 빼는 것은 남았다(#124).
- 견적 · 공정표 정보는 화면이 보낸 입력으로 서버가 다시 계산한다. 기능 service는 import하지 않는다.
- 일정 MCP는 공정표 역할만 부르도록 설계한다. 현재 `backend/app/mcp_server.py`는 비어 있고 실제 도구 연결이 없다.
- 업체가 쓴 글은 지시문에 넣지 않고 데이터로만 넘긴다.

## 7. 테스트와 eval

- 현재 상담 코드의 주요 테스트는 `backend/tests/test_v2_ask.py`·`test_v2_ask_chat.py`다. 테스트에 따라 `FakeLLM`으로 `llm.chat_tools`를 바꾸거나 `llm.set_stub`·`set_jev_stub` 등 가짜 응답을 사용하며 유료 모델 호출 없이 동작을 확인한다. 후속 `test_agent_<묶음>.py`·역할별 eval 세트는 실제 파일이 만들어진 범위에서만 통과라고 기록한다.
- eval 세트는 dev와 held-out을 **2:1**로 나눈다는 팀 원칙을 유지한다. 실제 자료는 `evaluation/intent`·`rag`·`answer`·`trade`·`ask_back`에 있으며, 각 세트의 분할·개수·검증 여부는 실제 파일 기준으로 확인한다.
- 프롬프트를 바꾸는 PR은 커밋 type `prompt`로 하고 eval 결과를 붙인다.

## 8. 한 턴 (`/v2/ask`)

`v2/ask_chat.py`가 대화 표를 잇고, `v2/ask.py`가 한 턴을 돌린다.

| 순서 | 하는 일 | DB 세션 |
| --- | --- | --- |
| 1. 열기 | `ask_chat.start`. 일반 상담(`kind=chat`)이고 `chat_id`가 있을 때만 내 대화를 연다(`get_for`). 남의 대화 · 없는 대화는 404. `rev` · `waiting` · 지난 대화(`recent`)를 들고 간다. 새 대화는 여기서 만들지 않는다 | 짧은 세션, 닫고 나온다 |
| 2. 관문 | `ask.start`: **`kind=chat` · 이미지 없음**인 경우, 무문자 질문("?" · "ㅠㅠ")은 고정 안내로 끝내고 저장하지 않는다. **같은 조건에서 낱말이 있는 경우에만** `gate.classify(message, waiting)`를 실행한다(학습 모델 → waiting 유지 → 저신뢰 시 Jev → 범위 밖 재검사). 분류 뒤 [agent/route.py의 `keep_in_scope`](../backend/app/agent/route.py)는 결과가 `None`이거나 `out_of_scope`가 아니면 그대로 두고, `out_of_scope`이면서 도배·목공 `symptom_words`가 있을 때만 `trade` / `source=rule` / `confidence=0`으로 바꾼다. 일상어 `실크`·`낙서`·`테두리`만으로는 바꾸지 않고 범위 밖이면 고정 안내(미저장). 기다리던 역할(출처 `rule`)은 신뢰도와 무관하게 역할 힌트를 붙인다. 이미지 있는 채팅·견적·공정표 설명은 무문자 검사와 의도 분류를 모두 건너뛴다([이슈 #147](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/147)·[PR #148](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/pull/148)) | 없음 |
| 3. 실행 | 지시문(`chat_v4` 등) + 지난 대화 + 이번 질문으로 LLM ↔ 도구. 서버 도구는 바로 실행한다. 화면 도구를 부르면 턴을 Redis에 두고 `done=false` · `turn` · `tool_calls`로 응답한다 | 쥐지 않는다 |
| 3-1. 재개 | 브라우저가 `/v2/ask/{turn}`로 결과를 보낸다 → `ask_chat.resume` → `ask.take` → `ask.resume`으로 3을 이어 간다 | 쥐지 않는다 |
| 4. 검사 | 출력 검사(`v2/guard.py`): 숫자 · 근거 · 금지 표현 · 가림. 남은 글이 없으면 실패 | 없음 |
| 5. 되물음 판정 | `ask_chat.asked_back`: 답이 `[되물음]`으로 끝나고 출력 검사가 뺀 문장이 없으면 되물음. 표시는 어디 있든 뗀다. 떼고 남은 글이 없으면 실패 | 없음 |
| 6. 저장 | 끝났고 실패하지 않은 일반 상담만(범위 밖 고정 안내는 제외). 새 대화면 이때 만든다. `rev`가 그대로일 때만 1 올리고 고객 문장 · 답 · 관문 결과 · `waiting`을 쓴다(`save_turn`). 다르면 아무것도 쓰지 않고 409 | 새 세션, commit |
| 7. 응답 | `V2AskOut`. commit 뒤에만 보낸다 | 없음 |

- 실패한 답은 저장하지 않는다. 빈 대화가 남지 않고 `rev`가 그대로라 다음 질문이 이어진다.
- 상담의 `price_reference`는 평형과 도면 모두 없으면 계산하지 않고 평형 입력을 안내한다. 별도 원시 `/v2/quote` 계산 API의 32평 기본값은 유지되므로 상담 도구의 규칙과 다르다.
- **범위 밖 고정 안내도 저장하지 않는다**(반영된 #128·PR #129). 새 `chats` 행을 만들지 않고 기존 대화의 `rev`·`waiting`도 변경하지 않는다(`v2/ask_chat.py`의 `out.gate == "out"`). 범위 밖 관문 결과가 저장되지 않으므로 오분류 점검은 #118의 별도 eval 대상이다.
- 견적서 · 공정표 화면 버튼의 설명(`kind=quote_explanation` · `schedule`)은 대화 표에 쌓지 않는다. `chat_id`는 늘 비어 있다

**넣는 값**

| 값 | 어디서 | 비고 |
| --- | --- | --- |
| `user_id` | 로그인 세션 | 요청 본문 · LLM 출력으로 받지 않는다 |
| `chat_id` | 요청 본문(없으면 첫 저장 때 새 대화) | 남의 대화면 404 |
| `kind` | 요청 본문 | `chat` · `quote_explanation` · `schedule`. 역할 지시문 · 도구를 정한다 |
| `message` | 요청 본문 | 1~1,000자. 본문 한도는 `BodyLimit` |
| 지난 대화 | `recent()`의 최근 메시지 6개 | 이번 문장은 빼고 오래된 것부터. 지난 답의 숫자는 다시 말해도 된다(기간은 계산 엔진만) |
| `waiting` | 대화 행에 저장해 둔 지난 턴 값 | 없으면 `None` |
| 견적 · 공정표 입력 | 요청 본문 | 서버가 계산 엔진으로 다시 계산한다 |

**저장**

- 고객 문장과 답을 메시지 행 두 개로 쌓는다(같은 `turn`). 답은 화면에 보낸 글(표시를 뗀 글) 그대로 저장한다
- 관문 결과(라벨 · 신뢰도 · 출처)는 고객 문장 행에만 남긴다. 의도 eval 재료
- 대화 행에 `waiting`을 덮어쓰고 `rev`를 1 올린다. 되물었을 때만 `waiting`에 그 턴의 관문 라벨(없으면 `orchestrator`)이 들어간다

**응답 모양 (`V2AskOut`)**

| 칸 | 뜻 |
| --- | --- |
| `chat_id` | 다음 질문에 같이 보낼 대화 id. 저장하지 않은 턴은 요청에 온 값 그대로(없으면 비움) |
| `done` · `turn` · `tool_calls` | `done=false`면 화면 도구를 실행하고 `/v2/ask/{turn}`로 결과를 보낸다 |
| `text` | 출력 검사를 마친 답. `done`일 때만 |
| `failed` | LLM 실패 · 남은 글 없음. `text`는 역할별 고정 문구(`ask.FAILED`) |
| `gate` | `out`이면 범위 밖이거나 글자 없는 질문이라 LLM을 부르지 않았다. 둘은 `intent`로 가른다(글자 없는 질문은 비어 있음) |
| `intent` | 관문 결과(라벨 · 신뢰도 · 출처) |
| `dropped` | 출력 검사로 뺀 문장의 이유 |
| `cons` | 공정표 상담이 바꾼 조건 |

- `sources`는 답에 남은 [K번호] 근거, `suggest`는 이어 물을 질문 0~3개(일반 상담만, 서버가 질문 은행에서 답할 수 있는 것만 고른다), `trade`는 코드가 고른 공정(없으면 비움)
- 지금은 `/v2/ask`의 JSON 답을 한 번에 보낸다. `chat/router.py`는 빈 파일이고 FastAPI `main.py`에 등록되지 않아 SSE 채팅은 미구현이다.

**rev와 Redis 턴**

| | rev | Redis 턴 |
| --- | --- | --- |
| 자리 | PostgreSQL 대화 행(정수, 1부터) | Redis `v2ask:{turn}`, 10분 |
| 담는 것 | 대화 버전 하나 | 한 질문의 메시지 · 기다리는 도구 id · 열 때 본 rev · 저장할 질문 |
| 막는 것 | 같은 대화의 다른 질문끼리 늦은 저장(409) | 같은 턴 재개가 두 번 와서 LLM · 도구를 두 번 도는 것(늦은 쪽 404) |
| 지워지면 | 없음(원본 데이터) | 재개가 404. 고객은 다시 물으면 된다 |

**동시 요청: 번호표(`rev`)**

- 열 때 본 값을 Redis 턴에 들고 있다가, 저장할 때 `rev`가 그대로일 때만 조건부 UPDATE로 1 올린다. 1행이 아니면 409이고 메시지도 쓰지 않는다
- 만료 시각으로 잠그지 않는다. 한 질문이 요청 여러 번(화면 도구 재개)에 걸치고 화면이 중간에 버릴 수 있어서, 기한 잠금은 버린 질문이 대화를 막는다
- 같은 대화에 두 질문이 동시에 오면 둘 다 실행되고 먼저 저장한 쪽만 남는다. 늦은 쪽 LLM 호출은 버려지므로 사용자별 요청 제한(시간당 60회, 로컬 제외)으로 비용을 막는다
- 예외가 나도 풀 잠금이 없다. 저장하지 않고 오류를 보낸다

**같은 턴 재개: `ask.take`**

- 결과 id가 기다리는 도구 id와 다르거나 같은 id가 두 번 오면, 턴을 건드리지 않고 422. 화면은 맞는 결과로 다시 보낼 수 있다
- 내 턴이 아니거나 없으면 404
- 읽은 값이 그대로일 때만 지운다(비교와 삭제를 Redis 안에서 한 번에). 그사이 다음 도구 턴이 같은 키에 저장됐으면 늦은 요청은 지우지 못하고 404

## 9. 아직 정할 것 · 후속

- 견적 설명 담당
- 사용자별 일일 토큰 제한을 어디서 셀지(`v2/ask.py` 또는 `llm.py`)
- 공종 에이전트가 넘기는 브리프 모양과 저장 자리(#85)
- 공종 에이전트 하위 호출
- 화면 도구 결과를 숫자 근거에서 빼기(#124)
- 범위 밖 고정 안내 미저장은 반영됨(#128·PR #129). 이후 로직을 바꾸면 실패·되물음·`rev`에 대한 회귀 검사가 필요하다.
- 의도를 못 정하면(Jev 실패) 선택지로 되묻기(#123)
- `waiting` 만료(지금은 다음 턴에 덮어쓸 때까지 남는다)
- 가이드 · 공정 상담 지시문을 `chat_v4.md`에서 나누는 시점
