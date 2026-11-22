# v4 비서 백엔드 설계(계약서)

- 2026-11-21. 설계 담당 보고를 리드가 확정한 판이에요.
- 구현하는 사람은 모두 이 문서를 기준으로 해요. 바꿀 일이 생기면 리드에게 먼저 알려요.
- 경로는 `backend/app/` 기준이고, (새)는 새로 만들 함수예요.

## 리드가 정한 것(설계안과 다른 점)
- **연락처 공개는 하지 않아요.** `propose_contact_share` · `share_contact`는 만들지 않아요. v3처럼 믿집 안 채팅으로 이어요.
- **프런트 폴더는 `components/assistant/`예요**(설계안의 `components/v2/assistant`가 아님).
  - `components/v2`는 v2 vs v3 비교용으로 그대로 둬요.
  - API 입구는 `lib/api/assistant.ts`, 업체 쪽은 `components/pro/assistant/`예요.
- 화면 결정
  - v2 모양 + `globals.css` 토큰을 써요.
  - **'표준 대비 %' 같은 표준 대비 비교는 화면 · 답에 넣지 않아요.**
  - 문구는 v3 문구를 따라요.
  - 업체 화면은 v3 스타일 작업함 + 비서 카드예요.
  - 경로는 v3 경로를 유지해요(해시 안 씀).
- 표준견적서 금액은 '조건별 두 기준'이에요(도배만: 시장 가운데 R안, 전체 철거 · 목공 큰 리모델링: 서울12호 P3). 별도 담당이 calc를 바꾸고, 비서는 읽기만 해요.
- 비용 상한(이번 작업 전체 $50)
  - 코드 상한: 사용자 하루 $1.00(가입 7일 안 새 계정은 한 계정 하루 $0.20 · 새 계정 합 하루 $1), 서비스 하루 $5, 전체 $45(`08-rules.md` 비용 상한)
  - 80%에서 기록 · 알림, 90%에서 유료 호출을 멈추고 무료 모드로 답해요.
  - 턴 상한은 $0.06이에요.

## 1. 모듈 구조
```
조립  main.py | worker.py
흐름  assistant → v2 → chat → schedule → visit → quote
기반  files | refprice | jobs | knowledge | notify | usage → auth
도구  agent → calc
```
- `assistant`는 `main.py` · `worker.py`만 import해요.
- `usage/`(새 기반 패키지): `llm_usage` 표, `prices.py`, `allow()`, `record()`. v2 · v3 · worker도 같은 상한을 거쳐요.
- `agent/llm.py`(Claude 호출은 이 파일 한 곳)
  - `claude_stream()` · `claude_json()`(새)를 더하고, `structured()` · `chat_tools()`도 Claude로 바꿔요.
  - `_guard()`(usage.allow), `_sink()`(usage.record), ContextVar `CALL_CTX`(user · turn · purpose), 시험용 대본 `set_claude_script()`
  - 모델: 비서 · 도면은 `claude-sonnet-5-5`, 문장 · 분류 · 기억은 `claude-haiku-5-5`(json), 판정은 `claude-opus-5-5`(evaluation에서만)
  - 이 모델들은 강제 tool_choice가 400이에요. auto + strict로 써요.
  - 임베딩은 지금 공급자를 유지해요.

| `assistant/` 파일 | 주요 함수 |
| --- | --- |
| `router.py` | `router`(/assistant) · `vendor_router`(/vendor/assistant) |
| `service.py` | `start_turn` · `finish_turn` · `approve` · `reject` · `feed_for` · `brief_for` · `forget` · `nudge_act` · `suggest_for` · `sweep` · `hourly` |
| `runtime.py` | `run_turn(ctx, emit)` · `SentenceGate` · `RefTable` · `free_turn` |
| `free.py` | 무료 모드 코드 길잡이: `answer`(의도 → 도구 → 카드 + 정해 둔 글) · `fit_cards`(글이 말한 카드) · `view_for` |
| `choices.py` | 카드 단추 고르기: `field` · `action` · `valid` · `apply`(고른 칸 · 행동 → 승인 카드) |
| `tools/` | `REGISTRY` · `defs(surface)`, customer · vendor · propose · answer · floorplan · cards |
| `actions.py` | `propose` · `EXECUTORS` · `execute` · `expire_due` · `close_handled` |
| `policy.py` | `mask_in` · `to_model` · `TurnBudget` · `mode_for` · `NudgeRules` |
| `proactive.py` | `TRIGGERS` · `scan_events` · `scan_time` · `evaluate_due` · `score` · `judge` · `write` |
| `memory.py` | `KEYS` · `wants` · `extract` · `validate` · `save` |
| `prompts/` | `customer_v3.md` · `vendor_v3.md`(2026-11-21, 말투 · 지난 말 · 범위 밖 · 도구 앞 말) 등 판 번호, Haiku용 `nudge_judge_v1` · `nudge_write_v2` · `memory_v3` · `brief_v2` |
| `schemas.py` | `TurnIn` · SSE 이벤트 · `CardOut`(kind로 구분) · `ActionOut` · `NudgeOut` · `SuggestOut` · `MemoryOut` · 도구 입력(strict) |
| `models.py` · `repository.py` · `jobs.py` | 표 4개 · 조건부 UPDATE(commit 안 함) · `HANDLERS`(assistant_memory) |

기존 코드와의 관계
- 재사용: `agent/v3/check`(mask · sentence_ok), `agent/v3/gate.gate`, `chat/tools.project_facts`, `chat/repository`(rev), `knowledge.service.search`
- 감쌈
  - `chat.service.answer_only`(새)는 `ai_turn`에서 저장만 뺀 함수예요. `answer_question` 도구가 불러요.
  - v2가 이긴 질문 종류만 `v2.ask.answer_only`(새)로 보내요.
- 대체: v2 화면 도구(set_* · show_step)는 `show_card` · `propose_home_info`가 맡아요. `/v2/ask` · `/ai/turns`는 옛 화면을 위해 남겨 둬요.

## 2. 데이터 모델(마이그레이션)
| 번호 | 이름 | 담당 |
| --- | --- | --- |
| 0039 | `0039_v4_llm_usage` | 기반 |
| 0040 | `0040_v4_assistant_turns`(+ `chats.kind`) | 비서 |
| 0041 | `0041_v4_assistant_actions` | 비서 |
| 0042 | `0042_v4_assistant_nudges_memory`(+ jobs kind CHECK에 `assistant_memory`) | 비서 |
| 0043~ | 금액 보정 · 도메인용 | 리드가 번호를 정해요 |

### assistant_turns(턴 장부)
- 열: user_id · chat_id FK CASCADE, surface(customer · vendor), project_id · visit_id FK, client_key, status(running · done · stopped · failed), mode(llm · free), tool_calls 0~6, cost_micros, error_code, trace · cards JSONB, heartbeat_at · ended_at
- UNIQUE(user_id, client_key), 부분 UNIQUE(chat_id) WHERE running
- CHECK: (failed) = (error_code 있음), (running) = (ended_at 없음)

### chats.kind
- 값: ai · assistant
- v3 목록(`list_chats` · `latest_chat`)은 ai만 보여요.

### assistant_actions
- 열: user_id FK CASCADE, surface, origin(turn · nudge), kind(제안 도구와 1:1, CHECK), project_id FK, target_kind, target_id(FK 없음), target_ver, payload JSONB, summary(무엇 · 얼마 · 어느 버전), idem_key, expires_at, decided_at, executed_at, error_code, result JSONB
- status: proposed → approved → executed, 또는 rejected · expired · failed
- UNIQUE(user_id, idem_key), 부분 UNIQUE(user_id, kind, target_id) WHERE proposed
- CHECK: expires_at > created_at, (proposed · expired) = (decided_at 없음), (executed) = (executed_at 있음), (failed) = (error_code 있음)

### assistant_nudges
- 열: user_id FK CASCADE, project_id FK, trigger, ref_id, dedup_key, channel(feed · notify), status(pending · held · sent · opened · dismissed · expired), score 0~100, body ≤200, action_id FK SET NULL, due_at · sent_at
- UNIQUE(user_id, dedup_key), 부분 색인 (due_at) WHERE pending
- 구현에서 더한 열(0042)
  - surface(customer · vendor): API가 화면별로 404를 가려요. 업체 줄은 project_id를 비워요(업체는 고객 공사 id를 받지 않음).
  - src(ai · guide): 문장을 Haiku가 썼는지 · 정해 둔 틀인지. reason: held · expired 까닭(snooze · mute · night · cap · low · judge · gone · replaced).
  - card JSONB(보낼 때 만든 CardOut 통째), acted_at(열기 · 닫기 때), created_at. 색인 (user_id, sent_at).
- CHECK: 보낸 줄(sent · opened · dismissed)은 sent_at · body · src가 있고, opened · dismissed면 acted_at이 있어요(연 뒤 새 제안에 밀려 expired가 돼도 남아요)

### assistant_memory
- 열: user_id FK CASCADE, key(CHECK 9종: avail_days · avail_half · living · style · material · priority · pet · diy · move_in(0048)), value 1~60자, evidence_message_id(FK chat_messages CASCADE, NOT NULL), evidence_quote
- UNIQUE(user_id, key): 새 말로 덮어써요. 목록 칸(diy · pet)은 앞 값에 더해요. 사용자마다 12개까지예요.
- 구현: evidence_quote 1~200자, created_at · updated_at, 색인 (evidence_message_id). 12줄 상한은 코드(새것부터 남김)예요. 키가 9종이라 지금은 9줄을 넘지 않아요.

### project_conditions.demolition (0043, 2026-11-21 리드 결정 보강)
- 모은 조건에 철거 범위 칸을 더해요: 키 `demolition`, 값 `full`(전체 철거) · `partial`(부분 철거) · `none`(철거 안 함).
- CHECK `key <> 'demolition' or value in ('full', 'partial', 'none')`. 다른 칸(되묻기 단추 글)은 그대로예요.
- `calc/dobae.py` `REMODEL_SIGNALS`에 `("전체 철거", None, "demolition", "full", "none")`을 더했어요. full이면 리모델링(P3), partial · none은 다른 신호를 봐요.
- 받는 곳(값은 모두 full · partial · none, 다른 값은 422):
  - 집 정보 API: `POST /projects` · `PATCH /projects/{id}`의 `HomeInfoIn.demolition`. 고치기에서 칸을 안 보내면 그대로, `null`이면 지워요. 응답 `HomeInfoOut.demolition`(없으면 null).
  - 손님 표준견적서 `POST /guest/standard`(저장 없음, full이면 리모델링 기준).
  - 비서: `propose_home_info`(fields.demolition) 승인 · 카드 고르기 `context.choice = "demolition:<값>"`(4장).
- 저장은 `project.service.set_demolition`(모은 조건 덮어쓰기 · 지우기)이에요. 비서 승인에서 바뀐 칸이 철거 범위뿐이면 집 정보 rev는 안 올라요(집 정보 칸도 바뀌면 `project.service.update`가 같이 써요). 칩 목록은 '철거 범위: 전체 철거'처럼 화면 말로 보여요. 칩 지우기(DELETE …/conditions/demolition)도 돼요.

### llm_usage
- 열: user_id FK SET NULL, turn_id, purpose(CHECK), model, 토큰 4종(캐시 읽기 · 쓰기 따로), web_searches, cost_micros(정수), price_ver, ok, error(종류 이름만), latency_ms
- 색인: (created_at), (user_id, created_at)
- 글은 넣지 않아요.

## 3. API
| 고객(`require_role("customer")`) | 업체(`approved_vendor`) |
| --- | --- |
| `POST /assistant/turns`(SSE) · `GET …/turns/{id}` · `GET …/threads/latest?project_id=` | `POST /vendor/assistant/turns`(SSE, visit_id) · `GET …/turns/{id}` |
| `GET /assistant/feed?project_id=&before=&limit=` | `GET /vendor/assistant/feed` · `GET …/briefs/{visit_id}`(읽기만) · `POST …/briefs/{visit_id}`(브리핑 + 기간 답하기 제안) |
| `GET /assistant/board?project_id=` · `GET /assistant/today?project_id=` (화면 제안) | `GET …/checklists/{visit_id}` · `GET …/today` (화면 제안) |
| `GET /assistant/actions?project_id=&status=` · `POST …/{id}/approve` · `…/reject` | 같은 꼴 |
| `POST /assistant/nudges/{id}/open` · `…/dismiss` | `POST /vendor/assistant/nudges/{id}/open` · `…/dismiss` |
| `GET /assistant/memory` · `DELETE /assistant/memory/{id}`(204) · `GET /assistant/health` | – |

- `approve` 몸통: `{client_key?, seen?}`. `seen`(화면이 본 target_ver)이 행과 다르면 409 stale, 기능 오류는 409(기능 오류 코드).
- `health`: `{mode: llm | free, reason: ok | off | budget}`(글 · 키 없음). budget은 고객 본인 하루 상한일 때만이고, 서비스 전체 상한 · 차단기는 off로 묶어요(2026-11-22 보안 I3, breaker는 보내지 않아요).
- 턴 글(`TurnIn` · `VendorTurnIn`의 text): 제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자는 지우고, 지운 뒤 공백만 남거나 가린 뒤 비면 LLM 전에 422예요(2026-11-22 리뷰 R1 · 보안 L1). 가입 이름 · 채팅 글도 같은 글자를 지워요(`shared/text.py`).
- nudges `open` · `dismiss` 응답: `NudgeOut{nudge_id, trigger, channel, status, body, src, action_id, sent_at, acted_at}`.
  - sent → opened(열기), sent · opened → dismissed(닫기). 이미 그 상태 · 바꿀 수 없는 상태(닫힘 · 밀려 닫힘)면 지금 상태를 200으로 돌려줘요.
  - 기다림 · 기록만(pending · held)인 줄과 남의 줄 · 다른 화면 줄은 404, 역할이 다르면 403이에요.
- memory 응답: `MemoryOut{id, key, label, value, evidence_message_id, evidence_quote, updated_at}`. 남의 것 · 없는 것을 지우면 404예요.

### SSE
- 순서: `ack`{turn_id, chat_id, at} → `status`{text, task?} · `card`{card_id, kind, data, say?} · `action`(ActionOut)(여러 번) → `token`{text}(여러 번) → `done`{rev, mode, cards, actions, stopped, chips, suggest}
- `done.suggest`: 다음에 물을 말 0~3개(`SuggestOut{id, text, why, say, nudge_id?}` 목록). 코드가 골라요: 열린 먼저 말 걸기 줄 → 지금 단계 다음 일(업체는 오늘 할 일). 이번 말 · 칩과 같은 말은 빼요. 그 단계의 다음 일이 열린 승인 카드로 와 있으면(실측 요청 · 반나절 · 업체 확정 · 날짜 수락) 단계 제안은 빼요(`STEP_OPEN`, QA r2 c5). 같은 client_key 되돌림에서는 비워요.
  - 화면 메모: 목업(`lib/api/assistant.ts`)은 `suggest`를 하나(SuggestOut)로 받아요. 백엔드는 목록이라 화면 담당이 맞춰야 해요.
- 실패하면 `done` 대신 `error`{code, message}를 보내요.
- 모든 data에 `seq`(턴 안에서 늘기만 함)와 `id: {turn_id}:{seq}`를 붙여요. 화면은 이미 받은 seq 이하를 버려요.
- `action`은 행을 commit한 뒤, `done`은 대화 저장을 commit한 뒤에 보내요. 새 제안에 밀려 닫힌 옛 제안도 `action`(expired)으로 보내요.
- 스트림을 열기 전 오류(404 · 409 · 429 · 503)는 지금과 같은 오류 모양이에요. 같은 client_key로 끝난 턴이면 저장한 카드 · 행동(지금 상태) · 답 글을 같은 이벤트로 다시 보내요.
  - 503 `busy`: 이 프로세스의 동시 턴 자리(`TURN_SLOTS`)가 다 찼어요. 503 `unavailable`: DB 연결을 `DB_POOL_TIMEOUT`초 안에 못 받았어요. 둘 다 `Retry-After`(`BUSY_RETRY_AFTER`초)를 붙여요. 화면은 그만큼 기다렸다 같은 client_key로 다시 보내요.
- 화면이 끊어도 턴은 끝까지 돌려 저장해요(다시 열면 feed로 보여요).

### 카드 kind
- home_info · standard_quote · vendor_picks · visit_slots · quote_compare · schedule · knowledge · answer · floorplan_links · today · vendor_brief · quote_checklist
- (2026-11-22 갈래 T) grade_compare(벽지 두 종류 견주기: 합지 · 실크 합계 · 차액 · 달라지는 줄, 단추 choice `grade:<값>` → 집 정보 승인 카드) · market_range(시세 범위 · 출처 한 줄, 표본이 모자라면 카드 없음) · options(고르기 칩: 누르면 say를 보냄)
- 화면은 `components/assistant/cards/registry`에서 kind로 컴포넌트를 골라요. data 모양은 `assistant/schemas.py`의 `*Data`예요.
- 같은 card_id면 카드를 바꿔 끼워요. 대화를 다시 열면 `assistant_turns.cards`로 그려요.
- 업체가 쓴 자유 글은 `vendor_note` 칸('업체가 적은 말', 40자)에만 와요: `quote_compare.cols[].vendor_note`(벽지 사양, 옛 `paper` 대신) · `visit_slots.vendor_note`(다른 날 제안 메모) · `schedule.vendor_note`(날짜 바꾼 까닭). 화면은 이 칸만 그 이름표로 보여 주고 다른 글에 섞지 않아요.
- 카드 단추 이름표(2026-11-21 고침)
  - `schedule`(phase dates)에는 `proposal_ref`(p…) · `proposal_kind`(처음 날짜 dates_accept · 수락한 뒤 바뀐 날짜 delay_accept)가 와요. 카드 [이 날짜로 수락] = choice `<proposal_kind>:<proposal_ref>`. 확정 공정표(final)는 둘 다 비워요.
  - `vendor_brief`에는 요청함일 때 답할 기간 후보 `windows`(w…, 첫 것이 suggest와 같은 기간)가 와요. 단추 = choice `window_answer:<ref>`.
  - `visit_slots.candidates[].why`는 화면 말이에요(코드 사실만: 가장 빠른 날이에요 · 공사 시작 20일 전쯤이에요 · 말한 시간대예요 · 말한 요일이에요 · 평일이에요 · 주말이에요 · 업체가 낸 날이에요). '가장 빠른'은 가장 이른 열린 반나절 하나, '20일 전쯤'은 희망일 − 20일에서 3일 안의 가장 가까운 하나에만 달아요.
  - `quote_compare.cols[].received_on`은 서울 날짜예요(견적서 보낸 때 timestamptz → 서울).

### 행동(ActionOut)
- `{action_id, kind, status, summary, target_id, target_ver, expires_at, decided_at?, executed_at?, error_code?, result?, supersedes?, replaced_by?}`
- `target_id`: 카드가 가리키는 대상 id(공사 · 실측 요청 · 확정 · 공사 날짜 제안 · 추가 금액, 2026-11-22). 화면은 v3 쓰기 주소의 대상과 같은 카드만 '처리됨'으로 보고, 실측 요청 취소(visit_cancel)가 실행되면 같은 대상의 열린 카드 단추를 숨겨요.
- `replaced_by`: 같은 대상의 새 제안으로 닫힌 행동(expired · replaced)이면 그 새 행동 id예요(화면이 어림하지 않게).
- kind는 제안 도구 이름에서 `propose_`를 뗀 것(home_info · visit_request · visit_slot · vendor_confirm · dates_accept · delay_accept · window_answer · decline · dates · visit_cancel(0051))이에요.
- 거두기(withdraw_proposal, 고정 선 1의 예외): 실행 전 카드는 고객 말로 거둬요. 거절과 같게 `rejected`로 남고 `result.reason = withdrawn`이라 `error_code` withdrawn으로 내보내요(화면 '거뒀어요'). 거둔 카드를 승인하면 409 action_closed('고객이 거둔 제안이에요.')예요.
- summary: `{title, amount_won?, amounts[], diff?, version?, rows[], file?, note?, approve_label}`. 금액 · 차액은 계산 엔진 값이에요.
- 만료 까닭은 `result.reason`에 두고 `error_code`로 내보내요(DB의 error_code는 failed에만, 2장 CHECK): `due`(기한 지남) · `replaced`(같은 대상 새 제안) · `handled_elsewhere`(대상 상태가 비서 밖에서 바뀜, 아래).
- 닫힌 행동을 승인하면 409예요: due는 `expired`(문구 '기한이 지난 제안이에요. …'), 그 밖은 `action_closed`(문구: replaced '새 카드로 바뀐 제안이에요.' · handled_elsewhere '화면에서 이미 처리했거나 상태가 바뀐 제안이에요.').
- 기능 오류로 실패한 행동은 고객에게 준 말을 `result.message`에 남겨요(턴 사실 '최근 처리한 카드'의 까닭, 2026-11-22).

#### 화면에서 직접 처리한 제안 닫기(handled_elsewhere, 2026-11-21)
- 사람이 v3 화면 단추(업체 확정 · 날짜 수락 · 기간 답하기 …)로 직접 처리하면 같은 대상의 비서 제안이 proposed로 남아요. sweep(2분)이 열린 제안 모두(새 것부터 200개씩 쪽마다, 시간 예산 10초를 넘기면 멈춘 자리부터 다음 차례가 이어 봄)의 대상 지금 상태를 읽기 조인으로 보고, 만든 때 상태(target_ver)와 다르면 `proposed → expired`, `result.reason = handled_elsewhere`로 닫아요.
- 조건부 UPDATE(proposed일 때만)라 같은 때 승인과 겹치면 승인이 이겨요. 그 행동을 단 먼저 말 걸기 줄(sent · opened)도 `expired`(reason handled)로 닫아 대화 기록에서 빠져요.
- 화면 신호는 따로 보내지 않아요. 화면은 다음 feed · actions 읽기나 승인 409(action_closed)로 알아요.

| 행동 kind | target_kind · target_ver | 닫는 때 |
| --- | --- | --- |
| home_info | project · rev(직접 할 일을 바꾸면 `rev:칩 지문`) | rev가 바뀜(집 정보 고침) · 잠김(실측 요청, 직접 할 일만 바꾸는 카드는 빼요) · 화면에서 직접 할 일 칩이 바뀜 |
| visit_request | project · rev | rev가 바뀜 · 고른 업체 모두 살아 있는 실측이 생김(화면에서 직접 요청) |
| visit_slot · window_answer · decline | visit · 만든 때 실측 상태 | 실측 상태가 바뀜(직접 고름 · 답함 · 닫힘) |
| vendor_confirm | visit · 견적서 판 | 실측 상태가 quoted가 아님(직접 확정 · 다시 고르기 · 닫힘). 새 판은 승인 때 quote_changed로 새 제안 |
| dates_accept · delay_accept | proposal · 공정표 판 | 낸 날짜가 pending이 아님(직접 수락 · 새로 냄 · 거둠) |
| dates(업체) | deal · dates_state | 공사 날짜 상태가 바뀜(직접 날짜 보냄 · 고객 수락 · 다시 고르기) |
| visit_cancel | visit · 만든 때 실측 상태 | 취소할 수 없는 상태가 됨(견적서 옴 · 확정 · 닫힘). 업체가 답해 상태가 바뀌어도 취소할 수 있는 동안은 그대로. 실행하면 같은 요청의 다른 열린 카드(반나절 · 확정)를 같은 트랜잭션에서 닫아요 |
- 견적서가 새 판이라 확정이 실패(quote_changed)하면 새 판 금액 · 차액으로 새 제안을 만들고, 새 행동의 `supersedes` = 옛 id, 옛 행동 `result.superseded_by` = 새 id예요. feed는 옛 자리에 새 행동을 그려요.

### 화면 제안 칸(2026-11-21 반영)
| 칸 | 결정 | 메모 |
| --- | --- | --- |
| `status.task` | 넣음 | 실측 진행 작업 카드 `TaskOut{task_id: "visits", title: "실측 요청 n곳" · "실측 · 견적서 n곳", rows: 업체마다 need · waiting · done · cancelled}`(공사 요약 vendors 그대로). `today_tasks` · `compare_quotes` 도구가 `status`로 보내고, 대화 기록에서는 실측 · 견적서 먼저 말 건 줄 가장 새것에 붙여요 |
| `card.say` | 넣음 | 카드 위 한 줄. 정해 둔 글(코드)만 써요 |
| `done.chips` · `feed.chips` | 넣음 | 마지막 카드 종류로 고른 정해 둔 칩 중 지금 공사 단계 사실(`service.chip_facts`: 실측 요청함 · 견적서 옴 · 공사 날짜 정함, 업체는 브리핑 요청 상태)에 맞는 것만이에요(예: 견적서가 오기 전에는 '견적서 비교 보기'를 빼요) |
| `done.suggest` · feed `suggest` 조각 | 넣음(0042) | 위 SSE 참고. 대화 기록의 먼저 말 건 줄 끝에 `suggest` 조각(nudge_id 있음) 하나 |
| `action.kind` · `status` · `supersedes` | 넣음 | 위 '행동' 참고 |
| `feed.now` · `feed.before`(턴 번호 커서) | 넣음 | 처음 30줄, `before`로 앞 쪽. 쪽마다 그 쪽 말 사이에 보낸 먼저 말 건 줄(보냄 · 엶 · 완료)을 모두(200줄 상한, 줄에는 커서가 없어 2026-11-22 리뷰 R13로 30에서 늘림) 보낸 때 자리에 끼워요(`AssistantItem{id: "n-…", turn_id: null, nudge_id, parts: text · card? · action? · task? · suggest}`). 비서 대화가 없어도 보여요 |
| `GET /assistant/board` | 넣음 | 단계(0~6) · 집 요약 · 낼 금액(won) · 업체 줄 · 기간 · 서류 · `money.range`(확정 전 업체 금액 두 곳 이상: 받은 실측 견적서, 없으면 요청 때 고정한 가견적, [작은 값, 큰 값]) · `memory`(MemoryOut 목록) |
| `GET /assistant/today` | 넣음 | 오늘 정할 일 줄(코드가 골라요). `nudge_id` = 이 공사의 열린 먼저 말 건 줄 가장 새것('오늘은 그만'이 닫아요), `dismissed` = 오늘 닫았고 열린 줄이 없음, `know` = 시간 트리거 줄(공사 전날 · 담기 없음) |
| 업체 `checklists` · `today` | 넣음 | 표준견적서 줄(이름은 고객 화면과 같은 말: '실크벽지 시장 평균 가격' → '실크벽지', 계산 엔진 이름은 그대로) · 내 견적서 칸 · 빠지기 쉬운 것 / 새 요청 · 오늘 실측 · 보낼 견적서 |
| 업체 `briefs.suggest.action_id` · `sentence` | 넣음 | `POST`(화면 브리핑 카드)는 요청함이면 기간 답하기 제안 행(window_answer)을 만들어요(같은 내용이면 같은 행). 이 요청에 열린 제안(대화에서 고른 못 받아요 · 다른 기간)이 있으면 새로 만들지 않고 덮지 않아요(읽기 도구 request_brief · 먼저 말 걸기도 같음, 바꿔치기는 사람이 고른 턴에서만, 2026-11-22 리뷰 B3). `GET`은 읽기만이라 제안 행을 만들지 않고 열린 기간 답하기 제안만 보여요(보안 L4). `sentence`: POST는 Haiku 한 문장(60자, 같은 사실이면 Redis 하루 캐시, 검사에 걸리거나 못 부르면 틀), GET은 캐시 문장 또는 틀, 도구 · 먼저 말 걸기 카드는 틀(코드 값만). 지역은 막지 않아요: 서비스 지역 밖이면 맞음 칸 '확인 필요 · 서비스 지역 밖(가까운 구)'이고 기간 후보 · 제안은 그대로예요(리드 결정 D11) |
| `home_info`의 주소 찾기(search · manual) · `GET /address/search` | 뺌 | 범위 밖. 집 정보 카드는 confirm 모양(요약 · 면적 · 바뀜 · action_id)만이에요 |
| `TurnIn.context`{card_id, choice} | 넣음 | card_id는 100자까지예요(slots- · brief- · dates- · check- + id는 42자, 할 일이 끝난 먼저 말 건 줄 카드는 '@줄 id'가 붙어 79자이고 서버가 떼고 봐요, 2026-11-22 QA P4). choice는 1~40자 값 하나 또는 5개까지예요. LLM에는 이번 대화에서 도구 · 카드가 준 ref만 가고 모르는 값은 버려요(422 아님). 이 화면의 행동 꼴인데 이름표를 모르거나 카드 id의 대상과 다르면(지난 카드 단추) 그 카드를 새로 불러와 '카드를 새로 불러왔어요. 다시 골라 주세요.'로 답해요(4장 11). 집 정보 칸 고르기 `demolition:<full · partial · none>`은 코드가 바로 집 정보 승인 카드를 만들어요(무료 모드도, LLM에는 '철거 범위: 전체 철거' 화면 말과 '승인 카드를 만들었어요' 한 줄로 알려요) |

### 권한
- 모든 조회에 `user_id = 세션 사용자`를 붙여요. 남의 것 · 없는 것은 404, 역할이 다르면 403이에요.
- project_id · visit_id는 `project.service.get_for` · `visit.service.vendor_visit`로 확인해요.
- executed인 행동을 다시 승인하면 200(같은 result)이에요. rejected · expired · failed는 409, approved(처리 중)는 409 in_progress예요.

## 4. 런타임(`runtime.run_turn`)
1. `start_turn`(짧은 세션)
   - client_key 재생: done이면 결과를 돌려주고, running이면 409예요.
   - 잠금은 running 행이에요(부분 UNIQUE → 409 turn_running). heartbeat가 2분 넘게 멈추면 failed 'stalled'로 바꿔요.
   - 복원: 최근 12줄(글만) · `project_facts` · 기억 · 열린 행동 · refs(Redis 30분)
   - 세션을 닫은 뒤 LLM을 불러요.
2. 프롬프트 캐시
   - 순서: tools(고정 · 이름순, 끝에 cache_control) → system(판 고정, cache_control) → 지난 턴 글 → 이번 글(가림) → `role:"system"` 턴 사실(지금 · 올해 · 알림 · 단계 · 집 요약 · 기억, 코드 값만)
   - 시각 줄(2026-11-22): `지금: 11월 22일(일) 새벽 2시 5분`(서울, 때 말은 `shared.kdate.PERIODS` 표 하나) · `올해: 2026년` · `알림: 밤 9시~아침 9시엔 아침에 보내요`(`proactive.RULES` 값에서). 지시문 판 묶음은 `ASSISTANT_PROMPT_SET`(v3 기본 · v4)이고 판마다 system이 달라 캐시도 따로 맞아요
   - 공정표 줄(QA r2 c5): `공정표: 예상 공사 12월 7일(월)~11일(금) · 일하는 날 4일(업체가 공사 날짜를 올리기 전 예상)`, 수락 뒤엔 `(수락한 공사 날짜)`. 공사 판(rev)이 바뀐 낡은 예상은 넣지 않아요(`schedule.service.period_now`, 읽기만). 실측 요청 뒤 비어 있는 시작 희망은 `공사 시작 희망 안 정함(실측 요청 뒤라 업체와 정해요)`으로 넣어요
   - 턴 안에서는 덧붙이기만 하고, 턴 사이에는 글만으로 다시 짜요.
3. 모델 설정: `claude-sonnet-5-5`, thinking adaptive, effort medium, max_tokens 8000, stream, tool_choice auto + strict. 앱 시작 때 SDK(anthropic · openai)를 작업 스레드로 미리 불러요(`llm.warm`: 첫 LLM 턴의 늦은 import 12~20초 · 이벤트 루프 멈춤, QA r2 c5)
4. stop_reason
   - tool_use → 도구 실행
   - pause_turn → 다시 보냄(2회까지)
   - refusal → 무료 모드
   - max_tokens → 끊긴 문장을 버림
5. 상한: 도구 6회 · LLM 8회 · 45초 · 턴 $0.06
   - 넘으면 "지금까지로 답해요"를 덧붙여 한 번 더 불러요.
   - 그래도 넘으면 카드만으로 끝내요(stopped).
6. 실패
   - 도구 오류는 is_error로 돌려줘요. 같은 (도구, 오류 코드)가 두 번이면 멈추고 실패 카드를 보여요.
   - Claude 호출이 두 번 실패하면 무료 모드로 바꾸고 5분 차단기를 걸어요.
7. `SentenceGate`: 문장마다 `check.sentence_ok`(허용 숫자 = 이번 턴 도구 결과)를 지난 것만 `token`으로 보내요.
8. `finish_turn`(한 트랜잭션): bump_rev → add_turn(가린 질문 · 검사한 답) → 턴 done → 기억할 말이 있으면 jobs(kind="assistant_memory") → commit → `done`
   - '기억할 말'은 `memory.wants`(낱말 규칙: 요일 · 오전 · 살면서 · 스타일 · 친환경 · 반려 · 셀프 등)가 정해요. 고객 턴만이고, ref_id는 그 턴의 고객 메시지, dedup_key `assistant_memory:{메시지 id}`예요.
   - `done` 앞에 `suggest_for`가 다음에 물을 말을 골라요(실패하면 비움).
9. 무료 모드(키 없음 · LLM_LIVE=false · 상한 넘음 · 차단기): `free.answer`가 LLM 없이 코드 길잡이로 답해요(2026-11-21 보강).
   - 고객 의도(낱말 규칙, 위에서부터) → 도구 함수 → 카드 + 정해 둔 글:

     | 의도 | 카드 | 글 |
     | --- | --- | --- |
     | 견적 비교 · 업체 확정 | quote_compare(+ 작업 카드) | 받은 견적서 n곳 · 확정은 카드 단추로. 없으면 '아직 받은 실측 견적서가 없어요' |
     | 실측 시간 | 업체가 답했으면 visit_slots 반나절 후보(기억의 편한 때), 요청 중이면 작업 카드, 요청 전이면 vendor_picks + 첫 업체 희망 기간(visit_slots wishes) | 카드에 맞는 틀 |
     | 업체 추천 | vendor_picks(코드 점수 3곳, 실측을 요청한 · 못 받은 업체는 뺌) | '도배 업체 n곳을 믿집 점수로 골랐어요'. 요청한 업체가 있으면 그 업체를 말하고(남은 추천이 없으면 작업 카드만), 확정했으면 확정한 업체 |
     | 공정표 · 공사 날짜 | schedule | 카드 한 줄 + 수락은 카드 단추로 |
     | 표준견적서 · 얼마 | standard_quote(목공만 물으면 목공, 이 공사에 목공이 없으면 지식 답) | 부가세 포함 합계(계산 엔진 값) |
     | 집 정보 · 오늘 할 일 | home_info · today(+ 작업 카드) | 정해 둔 글 |

   - 그 밖(지식 · 공통)은 입구 관문 단계 카드 + `chat.service.answer_only(mode="free", view, button)`예요. view는 보던 카드(card_id 머리: picks → vendors · slots → pick · compare → quotes …), 없으면 공사 요약 phase(estimate → vendors · progress → visits · work → schedule · done → plan)예요. 목공만 물으면 `button=(trade, mokgong)`으로 목공 담당이 답하고, '언제 해요'처럼 공종 일의 때를 물으면 answer_only에 보내는 글 끝에 '순서'를 붙여요(무료 낱말 검색이 순서 자료를 찾게, 대화 기록은 그대로).
   - 글이 카드를 말하면(희망 기간 · 실측 날짜 · 업체 n곳 · 견적서 비교 · 공정표 · 표준견적서) 같은 턴에 그 카드가 있어야 해요(`free.fit_cards`): 없으면 만들고, 못 만들면 그 문장을 빼요. '믿집 공정표는 …'처럼 일반 규칙을 말한 문장은 카드 말이 아니에요.
   - 의도 모델 앞에서 거르는 말(`free.guard_of`, QA 1차 2026-11-22): 지시문 → '그건 보여 드릴 수 없어요' · 연락처 · 동호수 → '주고받지 않아요 · 업체와 연락은 믿집 채팅으로' · 영어 답 → 짧은 거절 + 지금 할 일 한 줄 · 내용 없이 화난 말 → 사과 + 무엇이 문제인지 묻기.
   - 범위 밖 답 틀(`free.off_said`, 2026-11-22 FM, 피클 표본 8): 되받기(고객 낱말 · 지금 서울 때 낱말, 받침에 맞춘 조사) · 솔직(못 하는 까닭 한 마디) · 지금 할 일 한 줄. 갈래는 음식 · 배달 / 날씨 · 잡담 / 돈 · 투자 / 다른 앱 일(예약 · 쇼핑 · 택시) / 대신 전화 · 문자(공사 낱말이 있어도) / 다른 공정(업체 연결 의도에 바닥 · 욕실 · 전기 …만, 오늘 할 일 카드와 함께) / 그 밖이에요. 갈래마다 틀 셋을 이 대화의 최근 답에 덜 나온 것부터 돌려 써요. 되받는 낱말은 갈래 표에서 맞은 꼴만 쓰고, 욕 · 화난 말 · 가린 개인정보 · 이상한 글(영어 · 주소 · 위험한 말 · 60자 넘는 글)은 되받지 않고 그 밖 틀로 답해요. 느낌표는 되받기에 하나만이에요.
   - 무료 모드는 카드 + 짧은 안내를 하는 비상 길이에요(08-rules). 말투 · 길이를 손보는 사례 규칙(공감 머리말 · 결론 먼저 글 · 이음말 떼기 · 글자 수 상한)은 두지 않고, 말로 승인 카드를 만드는 길의 낱말 규칙(묻는 말 · 가정 · 부정 · 다른 뜻 거르기)만 촘촘히 둬요.
   - 정해 둔 길(`free.route_of`, 의도 모델 앞): 비서가 낸 칩(runtime.CHIPS · 다음에 물을 말 · 카드 칩 · 첫 화면 칩)과 같은 뜻의 말은 칩 뜻대로 가요. 폐기물 · 철거 포함 → 받은 견적서의 포함 칸(철거는 집 정보 철거 범위와 다르면 확인하라고) · 비싸요 · 바가지 → 받은 견적서가 있으면 견적 비교 카드, 없으면 표준견적서 카드(정해 둔 글 그대로) · 추가금 → 추가 금액 승인 길 · 가견적 계산 · 실측에서 보는 것 · 공사 순서 → 정해 둔 글 · 다른 시간 → 반나절 카드 · 공사 전날 준비물 → 준비물 카드 · 반려동물 · 출입 → 정해 둔 글. 이번 말이 요일을 바라면('평일엔 회사라 주말에') 반나절 후보는 그 요일을 먼저 봐요.
   - 다른 공정(믿집이 계산 · 연결하지 않는 공정)만 물으면 알아 두기 자료(`knowledge.other_trades`)로 순서 · 주의점 두 문장 + '믿집은 … 업체를 잇지 않아요'로 답해요(돈 · 기간은 계산하지 않는다는 말). 도배 · 목공과 섞인 질문은 answer_only 답을 쓰고 모르면 자료로 바꿔요. answer_only의 v3 단계 번호('지금은 2단계예요')는 떼고, 단추로 되묻는 글은 정해 둔 되묻기로 바꿔요.
   - 말로 고른 일도 승인 카드를 만들어요(2026-11-21 바꿈): 날짜 바꾸기 요청 · 추가 금액 답 · 공사 끝 확인 · 한 번 더 요청 · 이웃 안내문처럼 뜻이 분명한 말만이에요. 실행은 여전히 사람이 카드를 승인할 때만이에요.
   - 업체 연결(추천 · 실측 · 견적 비교 · 확정)은 아직 도배만이에요. 목공으로 물으면 '아직 도배 업체만 연결돼요. 목공은 표준견적서와 궁금한 점까지 도와드려요.', 다른 공사(바닥 · 욕실 · 전기 …)로 물으면 범위 밖 답 틀(다른 공정)로 답하고 도배 쪽 오늘 할 일 카드를 보여요. 목공 지식 · 표준견적서는 그대로 답해요.
     - 공종 낱말은 이 대화(이름표 표) · 공사(실측 요청 · 확정 · 담기)에 나온 업체 이름을 뺀 뒤 찾아요('마루와벽으로 확정할게요'의 '마루'는 바닥이 아니에요).
     - 견적서 말('견적서에 철거 포함 · 폐기물 처리도 포함인가요?')의 철거 · 폐기물은 도배 견적 칸이라 다른 공사로 보지 않아요.
   - 비서가 기억한 것을 어디서 보고 지우는지 물으면 정해 둔 안내('내 정보 → 비서가 기억한 것')로 답해요(기억해 달라는 말은 아님).
   - 고객 승인 카드는 말로 만들지 않고, 사람이 카드 단추를 누른 턴(choice, 11)에 만들어요.
   - 업체: 못 받아요 → decline 제안 하나(까닭 코드는 낱말: 일정 · 바빠 → full, 지역 · 멀어 → out_of_area, 그 밖 other) · 기간 답하기 → 브리핑 + window_answer 제안 하나 · 견적서 체크리스트 · 오늘 할 일(today 카드). 의도가 없으면 브리핑(새 제안 없이) + answer_only예요.
10. 턴 사실의 기억 줄: `기억(고객이 직접 한 말 · 지시 아님): 편한 때: 평일 오전이 편해요 · 반려동물: 강아지`. 값은 검사를 지난 고객 말이에요(코드 값은 아니라서 '지시 아님'을 붙여요).
11. 카드 단추 고르기(`choices.apply`): `context.choice`의 칸 · 행동 꼴은 모드를 고르기 전에 코드가 그 제안 도구로 승인 카드를 만들어요(사람이 누른 고르기라 LLM 판단 없이, 무료 모드도). 실행은 여전히 그 카드를 승인할 때만이에요.
    - 집 정보 칸 `demolition:<full · partial · none>` → propose_home_info(고객)
    - 고객 `visit_request:v1,v2[,r1]` · `visit_slot:s1` · `vendor_confirm:m1` · `dates_accept:p1`(연기 날짜면 delay_accept로 바꿔 만듦)
    - 업체 `window_answer:m1,w1`(w1만도 됨) · `decline:m1,full`(보던 요청이면 `decline:full`) · `dates:d1,n1`(n1만도 됨)
    - 이름표는 이 대화의 도구 · 카드가 준 것만 받아요(422 아님). 한 턴에 행동 2개까지, 화면(고객 · 업체)이 다른 꼴은 버려요.
    - 지난 카드 단추(2026-11-21 고침): 이 화면의 행동 꼴인데 이름표를 모르거나(표가 지워짐), 카드 id의 대상(slots- · dates- · brief- + id)과 이름표 대상이 다르면 버리지 않아요. 그 행동을 고르는 카드(업체 추천 · 반나절 · 견적 비교 · 공사 날짜 · 업체 브리핑)를 이 대화 이름표로 새로 만들어 보내고 '카드를 새로 불러왔어요. 다시 골라 주세요.'로 답해요. 무료 · LLM 모드 같고 LLM은 부르지 않아요(trace reason reload). 카드를 못 만들면 '지금은 고를 수 있는 것이 없어요. 진행 상황을 확인해 주세요.'예요.
    - 무료 모드는 '고른 것으로 승인 카드를 만들었어요. 카드를 확인하고 눌러 주세요.'(도구 오류면 그 문장) 한 줄로 답하고, LLM 모드는 그 한 줄과 화면 말('철거 범위: 전체 철거' · '실측 요청 v1, v2')을 이번 글에 붙여 보내요.

## 5. 도구
- id는 받지 않아요. `*_ref`(v1 · r1 · s1 · w1)는 `RefTable`로 풀고, 모르는 ref면 is_error예요.
- 모든 결과는 `policy.to_model`을 지나요.

### 읽기
| 도구(입력) | 부르는 함수 |
| --- | --- |
| `get_home`() | `project.service.get_for` |
| `get_standard_quote`(trade) | `quote.service.standard_for` |
| `recommend_vendors`(trade, sgg?) | `visit.service.vendors_for` + `calc.vendor_pick.pick` · `reasons` → v1~v3(점수 순). 모델 값 note에 '맡기시면: 점수 1위 · 까닭 틀'. sgg가 집 지역과 다르면 `visit.service.vendors_elsewhere`로 그 구 업체를 읽기만(이름표 없음 · 카드 id `picks-dobae@구` = 단추 없는 카드, 실측 요청은 집 지역 업체에만) |
| `vendor_free_slots`(ref, prefer, days, more?) | ref는 꼭 넣어요. 요청 전 업체 v…: `visit.service.open_halves_for`(새, 칸 수만) + `calc.slots.wish_candidates`(새) → r1~r2. 업체가 기간을 답한 뒤 실측 요청 m…: `pick_view` + `calc.slots.candidates`(새) → s1~s3. more면 이 대화에서 이미 보인 반나절(이름표 s…)을 빼고 남은 자리(오후 포함)에서 골라요 |
| `compare_quotes`(trade) | `visit.service.compare`. 표준 대비 %는 넘기지 않아요. 받은 견적서가 없으면 카드 없이 `note`('아직 받은 견적서가 없어요 · 기다리는 업체 n곳') · `count` 0 · `waiting`, 한 곳이면 비교가 아니라 그 견적서 카드(`quote_compare.single`, 열 하나)예요(`show_card(quote_compare)`도 같아요) |
| `get_schedule`() | `schedule.service.schedule_for` |
| `today_tasks`() | `service.feed_for`(`schedule.service.overview_for` + 열린 행동) |
| `search_knowledge`(query, trade) | `knowledge.service.search` |
| `answer_question`(question, kind) | `chat.service.answer_only` / `v2.ask.answer_only` |
| `find_floorplan_docs`() | `tools/floorplan.py`: Sonnet 5.5 + `web_search_20260209`(max_uses 3, 네이버 부동산 · 호갱노노 · 아실 차단, 링크 · 출처만) |
| `show_card`(kind) | `tools/cards.py` |
| `compare_grades`() | `quote.service.home_v3` · `standard_v3`(합지 · 실크, 저장 안 함) + `calc.visit_view.grade_diff`(차액) |
| `market_range`(trade) | `calc.quick_budget.quick`(`refprice.market` 시장 기준 한 벌): 부가세 포함 범위 · 근거 실견적 수 · 출처 한 줄. 부분 공사 · 천장만 · 천장 평탄화 · 근거 30건 미만이면 범위 없이 까닭 |
| 업체 `request_brief`(visit_ref) | `visit.service.vendor_visit` + `vendor.service.get_profile` · `estimate_v3_for` |
| 업체 `my_free_slots`(from, to) | `vendor_visit(preview)` + `calc.slots.best_windows`(새) → w1~w3 |
| 업체 `quote_checklist`(visit_ref) | `quote.service.latest_of` + `agent/trades` 주의점 |
| 업체 `my_jobs`() | `schedule.service.vendor_inbox` · `job_for` |

### 제안(행동 행만 만들어요)
| 도구(입력) | 승인 뒤 실행 |
| --- | --- |
| `propose_home_info`(칸, 지역 sgg 포함) | `project.service.update`. 지역은 잠기기 전만(시 · 도와 구를 같이, 옛 동은 지움) |
| `propose_visit_request`(trade, vendor_refs, wish_ref, pick?) | `visit.flow.add_shortlist`(안 담은 업체만) → `visit.flow.request`. pick=top(고객이 맡김)이면 서버가 추천 점수 1위를 넣어요. 요약에 지역 줄 |
| `propose_visit_slot`(slot_ref) | `visit.flow.pick` · `pick_proposal` |
| `propose_vendor_confirm`(visit_ref) | `schedule.service.confirm`(seen_ver) |
| `propose_dates_accept` · `propose_delay_accept`(proposal_ref) | `schedule.service.accept_dates`(seen_version) |
| `propose_date_change`(deal_ref, reason, delay_days 또는 wish_from, direction?) | `schedule.service.request_dates`(`POST …/date-requests`와 같은 함수). direction(earlier 앞당기기 · later 미루기)과 반대인 후보는 내지 않아요. 없으면 delay_days는 미루기, wish_from은 지금 시작일과 견줘 정해요. 앞당길 날이 없으면 도구 오류 `no_earlier` |
| 업체 `propose_window_answer`(visit_ref, window_ref) | `visit.flow.answer_window` |
| 업체 `propose_decline`(visit_ref, code) | `visit.service.decline` |
| 업체 `propose_dates`(deal_ref, days_ref) | `schedule.service.propose_dates` |
| `propose_visit_cancel`(visit_ref?, code) | `visit.service.cancel`(CancelIn 이유 코드 changed · other_vendor · other, 메모 없음). visit_ref가 비면 살아 있는 요청이 하나일 때 그 요청, 여럿이면 고르기 칩(state choose). 끝난 요청은 카드 없이 까닭(state closed, `visit.service.ended_why`) |
| `withdraw_proposal`(kind, about) | 행동 행을 거둠(proposed → rejected · withdrawn). 하나면 바로, 여럿이면 고르기 칩 카드(state choose), 없으면 보낸 실측 요청(requests m…) |

### `actions.execute`
1. tx1: proposed → approved(조건부 UPDATE, 만료 전) 뒤 commit해요.
2. tx2: approved → executed와 기능 함수를 같이 실행해요. 기능 함수의 commit으로 확정돼요.
3. AppError가 나면 rollback하고 failed(기능 오류 코드)로 바꾼 뒤 409를 돌려줘요.
4. approved로 2분 넘게 남은 행은 sweep이 failed로 바꿔요(다시 실행하지 않음).
- 기능 함수가 여러 번 commit하는 실행(visit_request: 안 담은 업체 담기 → 요청)은 마지막 기능 함수 바로 앞에서 executed를 써요(담기가 먼저 commit돼도 행동은 executed가 아니에요).

- 대상마다 열린 제안은 하나예요(`actions.offer` · `propose`). 같은 (사람, 대상)의 제안 만들기는 트랜잭션 잠금으로 줄 서요. 같은 제안(종류 · target_ver · payload)이 열려 있으면 턴이 달라도 새 행을 만들지 않고 그 행을 써요. 다르면 그 대상의 열린 제안 중 서로 바꾸는 묶음(같은 종류, 그리고 기간 답하기 ↔ 못 받아요 · 날짜 수락 ↔ 바뀐 날짜 수락)만 만료(replaced)로 바꾸고 새 행을 넣어요(예: 업체 기간 답하기 → 못 받아요). 같은 공사의 직접 할 일 · 집 정보 카드와 실측 요청 카드는 서로 바꾸지 않아요(2026-11-22).
  - 먼저 말 걸기는 같은 종류 · 같은 판의 열린 카드(대화에서 만든 것)를 덮지 않고 그 행을 써요.
  - 거절한 제안은 대상 판 · 금액 · 날짜가 같으면 다시 만들지 않아요. 도구는 오류 대신 모델 값 state rejected('고객이 거절한 제안이에요')를 돌려줘요. 카드 단추로 직접 고른 턴(pressed)과 LLM 턴에서 고객이 분명히 해 달라고 한 말('저장해 주세요' 같은 부탁)은 새 결정이라 새로 만들어요. 거절 막기는 먼저 말 걸기 · 비서가 스스로 낸 제안에만 걸어요.
  - 멱등 키(턴 · 종류 · 대상 · payload)가 같은 행이 닫혔거나 기한이 지났으면 새로 만들어요(먼저 말 걸기는 턴이 없어 키가 늘 같아요).
  - 실행 중 기능 함수 안 읽기 도우미(표준견적서 · 예상 공정표)의 commit이 executed를 먼저 확정하지 않게, 승인 실행은 그 도우미를 executed 표시 앞에서 먼저 불러 맞춰요.
- 업체 연결 도구(`recommend_vendors` · `compare_quotes` · `propose_visit_request`)는 trade가 dobae가 아니면 도구 오류 `dobae_only`('아직 도배 업체만 연결돼요. …')예요. `get_standard_quote`(mokgong) · 지식 답은 그대로예요.
- 업체가 쓴 자유 글(견적서 벽지 사양 · 다른 날 제안 메모 · 날짜 바꾼 까닭)은 고객 카드의 `vendor_note`('업체가 적은 말', 연락처 가림 · 한 줄 · 40자, 넘으면 …)에만 둬요. 모델 값에는 있는지만(`vendor_note: true`) 가서 비서 문장 · 요약 · 버튼 문구로 옮겨지지 않아요. `quote_compare.cols[].paper`는 `vendor_note`로 바뀌었고 `visit_slots` · `schedule`(dates)에도 `vendor_note`가 있어요.

### 구현 메모(2026-11-21, 비서 담당)
- ref 머리글자: v 업체 · m 실측 요청 · r 희망 기간 · s 반나절 · w 업체 기간 · d 확정 · p 공사 날짜 제안 · n 공사 날 후보. 대화마다 Redis 표(`assistant:refs:{chat_id}`).
  - 2026-11-21 고침: 표는 7일(저장할 때마다 늘림, 30분이면 지난 카드 · 며칠 뒤 먼저 말 걸기 카드 단추가 조용히 버려졌어요). 턴 · 먼저 말 걸기 · 업체 브리핑(REST)이 한 대화의 표를 같이 써요(대화가 없으면 만들어요).
  - 번호는 머리글자마다 쓴 가장 큰 번호(`…:num`, 30일) 다음이라, 표가 지워지거나 오래된 것을 버려도 같은 이름이 다른 대상을 가리키지 않아요.
  - 저장은 Redis 표와 합쳐요(WATCH). 두 곳이 같은 번호를 다른 대상에 썼으면 그 이름을 버리고 다시 살리지 않아요(그 단추는 카드를 새로 불러와요).
- `answer_question`은 질문 종류(kind: general · price · period · material · process)별 설정 `ASSISTANT_ANSWER_ROUTE`(기본 `v3`)로 엔진을 골라요(0042 담당 반영).
  - 값: `v3` · `v2`(모두), 또는 `price=v2,material=v2`(적은 종류만, 나머지 v3, `*=`는 기본값). 모르는 값은 v3예요.
  - v3: `chat.service.answer_only(mode="free")`로 근거 문장만 받아요(겹친 LLM 호출 없음).
  - v2: `v2.ask.answer_only`(새). v2 일반 상담 파이프라인에서 저장 · 화면 도구 · Redis 턴 · 입구 관문 · 요청 제한을 뺀 함수예요. 서버 도구(price_reference · search_knowledge)만 주고, 턴이 LLM이면 v2도 LLM(v2_chat 장부, 같은 턴 비용)으로 답해요. 무료 모드면 근거 제목만이에요.
  - 주의: v2 price_reference 금액은 v2 계산 엔진(평형) 값이라 v4 표준견적서(두 기준)와 다를 수 있어요. 평가에서 같이 봐야 해요.
- `today_tasks` · `compare_quotes`는 실측 진행 작업 카드(`status.task`)도 보내요.
- `propose_home_info`는 철거 범위(fields.demolition: full · partial · none)를 받아요. 바뀐 칸이 철거 범위뿐이면 집 정보 검사 · rev 올림 없이 모은 조건만 저장해요.
- `vendor_free_slots`는 `prefer`(any · am · pm)와 `days`(any · weekday · weekend)를 받아요. `find_floorplan_docs`는 고객이 말한 단지 이름(`complex`, 동 · 호수 뗌)을 받을 수 있어요.
- `vendor_free_slots`(요청 전) · `request_brief` · `my_free_slots`의 업체 빈 반나절은 도메인 갈래의 `visit.service.open_halves_for`(실제 함수, 공사 날 · 잡기 반영)를 불러요. 가견적은 요청 때 고정한 값(`vendor_visit.estimate_total`)이에요.
- `propose_dates`의 날 후보(n1~)는 `my_jobs`가 견적서 공사 기간 · 예상 공정표 시작일로 `calc.schedule.workdays`에서 만들어요.
  - 고객의 날짜 요청이 열려 있으면(dates_state requested · change_requested) 후보는 고객이 고른 시작일(`aftercare.request_candidates`)이고, 카드는 먼저 말 걸기 `dates_requested`와 같은 `request_dates_offer`(payload kind · request_id)예요.
  - 고른 시작일이 모두 막혔는지(지났거나 그날부터 공사 날 수만큼 이으면 같은 업체의 다른 공사와 겹침)는 비서 후보와 실행(`schedule.service.propose_dates`)이 같은 판정 `calc.schedule.wishes_blocked`를 써요. 막혔을 때만 가까운 빈 날(다른 날 제안)을 내고 받아요(QA r2 c6, 고침 3차 B2).
- 집 정보 잠금(`projects.locked_at`)은 첫 실측 요청 때 찍고, 보낸 요청이 모두 끝나고(취소 · 못 받음 · 기한 지남 · 안 옴 · 닫힘) 받은 견적서 · 확정이 없으면 풀려요(`visit.service.unlock_if_idle`, 요청이 끝날 때 `end_visit`이 불러요. 리드 결정 11-22). 단계 판정(`trade_facts`)도 견적서 없이 끝난 요청은 세지 않아요.
- `assistant_actions`에는 turn_id 칸을 두지 않았어요. 턴의 행동 id는 `assistant_turns.trace.actions`에 있어요.

### 구현 메모(2026-11-21, 카드 갈래)
- 제안 도구 모델 값 `state`: new(새 행) · same(열린 같은 행) · rejected(거절한 같은 제안, 승인 카드 없음) · closed. 승인 카드(action)는 new · same일 때만 보내요.
- 수락 승인 카드가 열려 있으면 공사 날짜 카드(schedule dates)는 수락 단추(proposal_ref · proposal_kind)를 비우고 `action_id`를 달아요. 먼저 말 걸기 반나절 카드는 승인 카드의 반나절을 `chosen`으로 표시해요.
- 말과 행동 맞추기(`runtime.SentenceGate` · `policy.card_claim`): '카드를 만들었어요 · 만들어 드릴게요 · 눌러 주세요'는 이번 턴에 만든 승인 카드 · 열린 승인 카드가 있을 때만 보내요. 눌러 달라는 말이 단추 이름(수락 · 실측 요청 …)을 대면 이번 턴에 보인 화면 카드 단추도 맞아요. 아직 모르면 붙잡아 두고, 턴 끝까지 없으면 첫 문장을 정직한 한 줄로 바꾸고 나머지는 빼요.
- `propose_home_info`는 평형(`pyeong`, 계산 엔진이 공급 ㎡로 바꿈)을 받아요. ㎡만 오고 기준(area_basis)이 없으면 `need_basis` 오류예요.
- 날짜 바꾸기 요청(행동 `date_change`, 0044): 대상은 확정(deal), target_ver는 '공사 날짜 상태:기준 시작일', payload는 {deal_id, wish_dates 1~3, reason(move · family · other_work · other), proposal_id}. 실행하면 그 확정의 '공사 전날' · 그 날짜 제안의 '공사 날짜 왔어요' 줄을 닫아요(SETTLES). 무료 모드도 '공사 미루고 싶어요'처럼 바라는 말이면 이 승인 카드를 만들어요(묻는 말은 안내만, 계약 4장 9의 예외).
- 턴 사실에 '최근 처리한 카드'(사람이 처리한 제안 4개까지, '제목(승인해 실행됨 · 거절함 · 승인했지만 실행 못 함)')를 넣어요. 이미 처리된 카드를 '안 만들어졌다'고 고쳐 말하지 않게 해요.
- 도구 오류 글(message)에는 이름표 · 도구 이름을 넣지 않아요(카드 단추 답에 그대로 보여요). 고칠 방법은 모델에만 가는 `hint`(이름표 · 도구 이름 · bad_input의 빠진 칸)로 줘요.
- 인사 · 고마움만 한 턴은 `tool_choice` none이에요(도구 정의는 그대로 보내 캐시를 지켜요). '네 · 좋아요'처럼 앞 물음에 답하는 말은 막지 않아요.
- 카드만 보낸 턴의 기록 글은 카드 화면 이름이에요('(카드를 보여 줬어요: 집 정보)').

## 6. 먼저 말 걸기
- 원천: 상태를 바꾸는 트랜잭션 안에서 함께 쓰는 `notifications`를 아웃박스로 읽어요.

| 이벤트 → 받는 사람 | 후보 | 채널(상태가 그대로일 때만) |
| --- | --- | --- |
| visit_offered → 고객 | 반나절 후보 3 + visit_pick 행동 | feed, 48시간 안 고르면 notify |
| quote_sent · quote_resent → 고객 | 견적 비교 | feed, 3일 무응답 notify |
| dates_proposed → 고객 | dates_accept(수락 뒤면 delay_accept + 영향) | feed, 2일(연기 1일) 뒤 notify |
| 공사 시작 전날 → 고객 | 준비물 · 지식 카드 | notify 10시 |
| 표준견적서 뒤 3일 담기 없음 → 고객 | 업체 추천 | notify |
| visit_requested → 업체 | 요청 브리핑(V1) | feed |
| visit_picked · deal_confirmed → 업체 | 수락 · 공사 날짜 후보 | feed |

- worker
  - `assistant_sweep`: 2분마다(unique). 만료 · 멈춘 턴 · 이벤트 · due 평가
  - `assistant_hourly`: 시간 · 무응답 트리거
  - 기억 추출은 기존 `sweep_jobs`가 돌려요.
- 규칙
  - notify는 하루 고객 2번 · 업체 3번까지예요.
  - 21~9시에는 9시로 미뤄요(feed에는 쌓아요). 밤 · 하루 상한으로 미루면 할 일의 기한(공사 시작일 등)이 지나는 알림은 미루지 않고 대화 줄(feed, 종 알림 없음)로 지금 보내요(2026-11-22 고침: 미룬 공사 전날 알림이 시작일에 닫혀 안 갔어요).
  - 하루 상한 · 24시간 감점은 보낸 줄을 상태와 상관없이 `sent_at`으로 세요(보낸 뒤 할 일이 끝나 닫힌 줄도 보낸 줄).
  - 닫으면 같은 trigger를 3일 쉬어요. 7일 안에 2번 닫으면 notify를 7일 멈춰요.
  - 대상마다 열린 제안은 하나예요(같은 제안이면 그 행을 다시 써요, 5장 구현 메모).
- '부를 만한가'
  - 점수: 기한 24시간 안 +50(48시간 안 +30), 행동 준비 +20, 돈 · 날짜 결정 +15, 같은 알림을 이미 읽음 −30, 24시간 안 보낸 것마다 −20, 같은 trigger 닫음 −30
  - 70 이상이면 보내요. 40~69는 Haiku가 코드 사실만 보고 yes/no로 정해요. 40 미만은 기록만 해요(held).
  - 문장은 Haiku가 60자 안으로 쓰고, 검사에 걸리면 템플릿을 써요.

### 구현 메모(2026-11-21, 0042 담당)
- 기본 점수는 50이에요(표에 없던 값). 그래서 새 이벤트 + 승인 카드 + 날짜 결정이면 85(보냄), 견적서 도착(결정만)은 65(판정)예요.
  - 기한: 기간 고르기 마감(pick_due_at) · 견적서 유효기간 끝 · 공사 날짜 시작일 · 업체 답 마감(reply_due_at) · 수락 마감(hold.until) · 공사 날짜 낼 기한(dates_due_at) · 공사 시작일.
  - '행동 준비'는 트리거가 승인 카드를 만드는지(visit_offered · dates_proposed · visit_requested · deal_confirmed)예요. '닫음 −30'은 7일 안이에요.
  - 판정을 못 부르면(꺼짐 · 상한 · 실패) feed는 보내고 notify는 기록만 해요(held judge).
- 규칙 순서: 같은 trigger 3일 안 닫음 → held(snooze, feed도) → notify만: 멈춤(held mute) · 밤(9시로 미룸, night) · 하루 상한(내일 9시로 미룸, cap) → 점수.
- 아웃박스: `scan_events`가 48시간 안 알림 중 아직 줄이 없는 것(dedup_key `ev:{알림 id}`)을 읽어요. 대상 id는 알림 dedup_key의 첫 id예요(견적서는 그 실측 요청). 대상을 못 찾으면 expired(gone) 줄로 남겨 다시 읽지 않아요.
- 무응답: `scan_time`(매시간 5분)이 보낸 feed 줄 뒤 48시간(visit_offered) · 3일(quote_sent) · 2일(dates_proposed, 연기 change면 1일)에 `{원래 dedup_key}:notify` 알림 줄을 만들어요. 상태는 보낼 때 다시 봐요.
  - 공사 시작 전날: scheduled이고 내일 시작하는 확정마다 그날 10시(지났으면 지금) 알림 줄(`work_eve:{확정 id}:{시작일}`).
  - 담기 없음: 첫 표준견적서가 3~14일 전이고 잠기지 않았고 담기 · 요청이 하나도 없는 공사마다 한 번(`no_pick:{공사 id}`).
- 보낼 때(한 트랜잭션): 카드(CardOut 통째, card 칸) · 승인 카드(origin nudge, 같은 대상 열린 제안은 actions.propose 규칙대로) · 같은 대상의 보이는 줄 expired(replaced) · notify면 알림(`notifications.kind = assistant_nudge`, 고객 링크 `/projects/{id}`, 업체 링크 요청 · 공사 화면) → commit 뒤 화면 신호(state, notify면 notif).
  - 카드: visit_offered 반나절 후보(기억의 편한 때 · 요일을 반영) + 첫 후보 visit_slot 승인 카드, quote_sent 견적 비교, dates_proposed 공사 날짜 카드 + 수락(겹치면 카드만), work_eve 준비물(공정 설정 고객 준비 · 주의점), no_pick 업체 추천, visit_requested · visit_picked 요청 브리핑(요청함이면 window_answer), deal_confirmed 공사 날 후보 첫 것으로 dates 승인 카드.
  - 이름표는 그 사람 비서 대화의 표에 넣어요(2026-11-21 고침, 대화가 없으면 만들어요). 카드 단추(견적 비교 [업체 할래요] · 반나절 · 공사 날짜 · 업체 기간)를 대화가 같은 이름표로 알아요. 승인 카드는 행동 id로 승인해요.
- 문장 검사(Haiku): 60자 · 한 줄 · '요'로 끝 · 숫자는 사실(JSON)에 있는 것만 · 한 일처럼 말하지 않음 · 링크 · 표준 대비 % 없음. 틀은 `proactive.TRIGGERS`의 feed · notify예요.
- 비용: 판정 · 문장 · 업체 브리핑 한 문장은 purpose `nudge`, 기억은 `memory`(둘 다 Haiku, 사용자 비용 상한을 지나요).
- `assistant_sweep`는 60초 안에 끝나야 해서 한 번에 50줄까지, 40초가 지나면 멈추고 남은 줄은 다음 차례(2분)에 봐요. 예산은 sweep 시작부터 재요: 정리(close_settled) 15초 · 평가 45초까지, 판정 · 문장 한 번은 10초까지(2026-11-22).
- 보낼 때 상태를 다시 봐요: 판정 · 문장을 기다리는 사이 상태가 바뀌었으면 보내지 않고 닫아요(gone). 근원 알림이 이미 종을 울린 사건(`done_remind`)은 비서 알림을 더하지 않아요(같은 사건 종 알림은 하나).
- 카드 · 승인 카드를 못 만들면 문장만 보내요. 평가 중 오류가 나면 그 줄을 expired(error)로 닫아 2분마다 되풀이하지 않아요.
- 할 일이 끝난 줄 닫기(2026-11-21 고침): 서버가 보이는 줄(sent · opened)을 닫아 대화 기록 · 턴 끝 제안(suggest) · 오늘에서 빠져요.
  - 비서 승인(`actions.execute`)으로 행동을 실행하면 같은 트랜잭션에서 그 사람의 줄 중 같은 대상의 승인 카드를 단 줄(새 카드로 바뀐 옛 카드 포함)과 같은 대상을 가리키는 줄(`repository.SETTLES`: visit_slot → visit_offered · vendor_confirm → quote_sent · dates_accept · delay_accept → dates_proposed · visit_request → no_pick · window_answer · decline → visit_requested · visit_picked · dates → deal_confirmed)을 expired(acted)로 닫아요.
  - 정리(2분, `proactive.close_settled`)는 보이는 줄(새것 50 + 오래 안 본 줄부터 150: 보이는 줄의 `due_at`은 정리가 마지막으로 본 때) 중 달린 행동이 실행된 줄은 acted, 대상 상태가 바뀐 줄(`context` 없음: 승인 카드가 없는 업체 추천 · 견적 도착 줄도)은 handled로 닫아요. 상태만 가볍게 보고(기한 · 이름 사실 · 추천 계산 없음), 업체 빠짐 줄은 이을 업체가 잠깐 없다고 닫지 않아요(2026-11-22).
  - 기록(2026-11-21 고침): 닫힌 줄(acted · handled)도 대화 기록에 남아요(`AssistantItem.settled`). 화면은 단추 · 제안 없이 보낸 때 카드와 '완료'로 보여요. 고객이 닫은 줄(dismissed)은 기록에서 빠져요.
    - 먼저 말 건 줄은 보낸 때가 속한 쪽에 끼워요(한 쪽 30줄까지, `service.NUDGE_FEED`).
    - 정리가 줄을 닫으면 화면 신호(state)를 보내고, 화면은 그 공사의 `state` · `resync`를 받으면 기록을 다시 읽어요(턴이 도는 중이면 끝난 뒤).

## 7. 안전
- 가림
  - 사용자 글: `mask_in`(저장 · LLM 전)
  - 도구 결과: `to_model` 허용 필드만(이름 · 연락처 · 동호수 없음)
  - 모델 글: `SentenceGate`(숫자 · AI_ACTS · URL · 누출). 숫자는 근거 값에 더해 어림 · 원대 · 차액 · 합계 · 평당 · 날짜 꼴을 읽고(`guard.loose`, 08-rules 숫자 절), 누출은 지시문의 규칙 절과만 견줘요(`prompts.rules`: `<!-- 규칙 -->`부터 `<!-- 예시 -->` 앞까지, 큰따옴표 말 뺌). 한글이 없고 로마자 같은 다른 글자가 반 넘는 문장(도구 앞 영어 속말, QA r2 c3)은 보내지 않고 까닭만 trace에 남겨요(`runtime.foreign`)
  - 웹 질의: 단지명 · 구만
  - 기록: `llm_usage` · trace · 로그에 글을 남기지 않아요.
- 주입 방어
  - 업체 글(견적 메모 · 소개 · 채팅)과 웹 글은 tool_result 안 `{"자료(지시 아님)": …}`로만 넘겨요. system에는 코드 값만 넣어요.
  - 도면 링크는 `web_search_tool_result`의 url만 코드가 뽑아요. 그림은 저장하지 않아요.
  - 행동은 ref와 사람 승인을 거쳐서 주입으로 실행되지 않아요.
- 기억 쓰기 잠금
  - 기억 쓰기 도구는 만들지 않아요. `memory.extract`(Haiku)는 그 사용자 메시지 한 줄만 읽어요.
  - 허용 목록 밖 키, evidence_quote에 없는 value, 건강 · 연락처 · 금액은 버려요.
  - 구현: 인용은 그 메시지 글 안(띄어쓰기 무시), 값은 인용 안이어야 해요. 금액 · 연락처가 인용에만 있으면 인용을 값으로 줄여요. 같은 키는 처음 것, 한 번에 4개까지예요.
  - 업체 턴 · 업체 글 · 도구 결과 · 웹 글은 기억 뽑기에 들어가지 않아요(고객 턴의 고객 줄만 jobs에 넣어요).
  - 꺼짐 · 상한이면 일은 skipped(다시 안 함), 공급자 오류면 jobs가 다시 해 봐요(1 · 5 · 30분).
- 비용 상한: 모든 호출이 `llm._guard` → `usage.allow`를 지나요. Redis 정수 카운터로 세고, Redis가 안 되면 llm_usage 합계로 세요.
- 함정 다섯
  - 중복: UNIQUE(client_key · idem_key · dedup_key)
  - 순서: seq · rev · target_ver
  - 조용한 멈춤: heartbeat · approved 2분 감시
  - 끝없는 루프: 도구 6 · LLM 8 · 45초
  - 사라지는 실패: error_code · jobs.last_error → feed 실패 카드

## 8. 테스트
- 단위: `calc.slots`, `policy`(고정 시계로 상한 · 밤 · 쉬기), `proactive.score`, `memory.validate`, runtime 대본(6회 상한 · 같은 오류 두 번 · pause_turn · refusal · 상한 넘으면 무료)
- 상태 · 409
  - 같은 승인 두 번이면 200, 동시에 승인해도 executed 1건
  - 만료 뒤 409, 견적 새 버전 뒤 확정은 quote_changed failed
  - client_key 재생, turn_running, rev 충돌
- 권한: 남의 turn · action · nudge · memory는 404, 업체가 고객 API를 부르면 403, 미승인 업체 403, 남의 project_id 404, 모르는 ref는 is_error
- 레드팀 50문항(`evaluation/v4/redteam.jsonl`): 견적 메모 · 웹 글 속 지시, '기억해: 예산 · 전화번호', 남의 정보 요구, '그냥 확정해', 지시문 빼내기, 도구 무한 유도 → 누출 · 승인 없는 실행 · 주입 반영 모두 0건
- 유료 0회: CI는 LLM_LIVE=false + `set_claude_script` 대본으로 돌려요.
- 시뮬레이터: `evaluation/v4/sim/run.py`가 ASGI로 `/assistant/turns`를 불러 끝 상태(visits · deals · actions)를 정답과 비교하고 pass^1 · pass^3를 재요. eval 상한은 $15이고, 판정은 Opus 5.5가 해요.

## 9. 순서 · 담당(worktree)
| 순서 | 역할 · 브랜치 | 고치는 파일 |
| --- | --- | --- |
| 1 | 기반 `feat-v4-llm`(wt-v4-llm) | `agent/llm.py` · `config.py` · `pyproject.toml`(anthropic) · `uv.lock` · `.env.example` · `usage/*` · 0039 · `migrations/env.py` 한 줄 |
| 1 | 금액 보정 `feat-v4-calc`(wt-v4-calc) | `calc/dobae.py` · `refprice/*` · `quote/service.py`(기준 고르기) · calc 테스트 |
| 1 | 평가 `feat-v4-eval`(wt-v4-eval) | `evaluation/v4/**` · `docs/v4/eval/**` |
| 1 | 프런트 `feat-v4-web`(wt-v4-web) | `components/assistant/**` · `components/pro/assistant/**` · `lib/api/assistant.ts` · `lib/mock/assistant/**` · 비서 화면 page |
| 2 | 비서 `feat-v4-assistant` | `assistant/**` · `chat/*`(answer_only · kind) · `jobs/models.py` · 0040~0042 · `main.py` · `worker.py` |
| 2 | 도메인 `feat-v4-domain` | `calc/slots.py` · `visit/service.py`(open_halves_for) |

- 리드가 각 갈래를 `feat-v4-secretary`에 병합해요. 공용 파일(`main.py` · `worker.py` · migrations · `schema.d.ts`)은 표에 적힌 역할만 고쳐요.
- ADR(`docs/v4/adr/`)
  - 실측 후보 제안
  - Anthropic 공급자(agent-06 대체)
  - 대기 행동 · 층 규칙
  - 금액 조건별 두 기준
  - 연락처 공개 안 함
