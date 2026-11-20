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
  - 코드 상한: 사용자 하루 $0.40, 서비스 하루 $5, 전체 $45
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
| `service.py` | `start_turn` · `finish_turn` · `approve` · `reject` · `feed_for` · `brief_for` · `forget` |
| `runtime.py` | `run_turn(ctx, emit)` · `SentenceGate` · `RefTable` |
| `tools/` | `REGISTRY` · `defs(surface)`, customer · vendor · propose · answer · floorplan · cards |
| `actions.py` | `propose` · `EXECUTORS` · `execute` · `expire_due` |
| `policy.py` | `mask_in` · `to_model` · `TurnBudget` · `mode_for` · `NudgeRules` |
| `proactive.py` | `TRIGGERS` · `scan_events` · `scan_time` · `evaluate_due` · `score` · `judge` · `write` |
| `memory.py` | `KEYS` · `extract` · `validate` · `save` |
| `prompts/` | `customer_v1.md` 등 판 번호 |
| `schemas.py` | `TurnIn` · SSE 이벤트 · `CardOut`(kind로 구분) · `ActionOut` · 도구 입력(strict) |
| `models.py` · `repository.py` · `jobs.py` | 표 4개 · 조건부 UPDATE(commit 안 함) · `HANDLERS` |

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

### assistant_memory
- 열: user_id FK CASCADE, key(CHECK 8종: avail_days · avail_half · living · style · material · priority · pet · diy), value 1~60자, evidence_message_id(FK chat_messages CASCADE, NOT NULL), evidence_quote
- UNIQUE(user_id, key): 새 말로 덮어써요. 사용자마다 12개까지예요.

### llm_usage
- 열: user_id FK SET NULL, turn_id, purpose(CHECK), model, 토큰 4종(캐시 읽기 · 쓰기 따로), web_searches, cost_micros(정수), price_ver, ok, error(종류 이름만), latency_ms
- 색인: (created_at), (user_id, created_at)
- 글은 넣지 않아요.

## 3. API
| 고객(`require_role("customer")`) | 업체(`approved_vendor`) |
| --- | --- |
| `POST /assistant/turns`(SSE) · `GET …/turns/{id}` · `GET …/threads/latest?project_id=` | `POST /vendor/assistant/turns`(SSE, visit_id) · `GET …/turns/{id}` |
| `GET /assistant/feed?project_id=&before=&limit=` | `GET /vendor/assistant/feed` · `GET …/briefs/{visit_id}` |
| `GET /assistant/board?project_id=` · `GET /assistant/today?project_id=` (화면 제안) | `GET …/checklists/{visit_id}` · `GET …/today` (화면 제안) |
| `GET /assistant/actions?project_id=&status=` · `POST …/{id}/approve` · `…/reject` | 같은 꼴 |
| `POST /assistant/nudges/{id}/open` · `…/dismiss` (0042 담당) | 같은 꼴 (0042 담당) |
| `GET` · `DELETE /assistant/memory[/{id}]` (0042 담당) · `GET /assistant/health` | – |

- `approve` 몸통: `{client_key?, seen?}`. `seen`(화면이 본 target_ver)이 행과 다르면 409 stale, 기능 오류는 409(기능 오류 코드).
- `health`: `{mode: llm | free, reason: ok | off | budget | breaker}`(글 · 키 없음).

### SSE
- 순서: `ack`{turn_id, chat_id, at} → `status`{text, task?} · `card`{card_id, kind, data, say?} · `action`(ActionOut)(여러 번) → `token`{text}(여러 번) → `done`{rev, mode, cards, actions, stopped, chips}
- 실패하면 `done` 대신 `error`{code, message}를 보내요.
- 모든 data에 `seq`(턴 안에서 늘기만 함)와 `id: {turn_id}:{seq}`를 붙여요. 화면은 이미 받은 seq 이하를 버려요.
- `action`은 행을 commit한 뒤, `done`은 대화 저장을 commit한 뒤에 보내요. 새 제안에 밀려 닫힌 옛 제안도 `action`(expired)으로 보내요.
- 스트림을 열기 전 오류(404 · 409 · 429)는 지금과 같은 오류 모양이에요. 같은 client_key로 끝난 턴이면 저장한 카드 · 행동(지금 상태) · 답 글을 같은 이벤트로 다시 보내요.
- 화면이 끊어도 턴은 끝까지 돌려 저장해요(다시 열면 feed로 보여요).

### 카드 kind
- home_info · standard_quote · vendor_picks · visit_slots · quote_compare · schedule · knowledge · answer · floorplan_links · today · vendor_brief · quote_checklist
- 화면은 `components/assistant/cards/registry`에서 kind로 컴포넌트를 골라요. data 모양은 `assistant/schemas.py`의 `*Data`예요.
- 같은 card_id면 카드를 바꿔 끼워요. 대화를 다시 열면 `assistant_turns.cards`로 그려요.

### 행동(ActionOut)
- `{action_id, kind, status, summary, target_ver, expires_at, decided_at?, executed_at?, error_code?, result?, supersedes?}`
- kind는 제안 도구 이름에서 `propose_`를 뗀 것(home_info · visit_request · visit_slot · vendor_confirm · dates_accept · delay_accept · window_answer · decline · dates)이에요.
- summary: `{title, amount_won?, amounts[], diff?, version?, rows[], file?, note?, approve_label}`. 금액 · 차액은 계산 엔진 값이에요.
- 만료 까닭(due · replaced)은 `result.reason`에 두고 `error_code`로 내보내요(DB의 error_code는 failed에만, 2장 CHECK).
- 견적서가 새 판이라 확정이 실패(quote_changed)하면 새 판 금액 · 차액으로 새 제안을 만들고, 새 행동의 `supersedes` = 옛 id, 옛 행동 `result.superseded_by` = 새 id예요. feed는 옛 자리에 새 행동을 그려요.

### 화면 제안 칸(2026-11-21 반영)
| 칸 | 결정 | 메모 |
| --- | --- | --- |
| `status.task` | 넣음(모양만) | TaskOut 모양을 정했어요. 만드는 쪽은 먼저 말 걸기(0042 담당)예요 |
| `card.say` | 넣음 | 카드 위 한 줄. 정해 둔 글(코드)만 써요 |
| `done.chips` · `feed.chips` | 넣음 | 마지막 카드 종류로 고른 정해 둔 칩이에요 |
| `done.suggest` · feed `suggest` 조각 | 뺌 | 먼저 말 걸기(nudges, 0042 담당)가 채워요 |
| `action.kind` · `status` · `supersedes` | 넣음 | 위 '행동' 참고 |
| `feed.now` · `feed.before`(턴 번호 커서) | 넣음 | 처음 30줄, `before`로 앞 쪽 |
| `GET /assistant/board` | 넣음 | 단계(0~6) · 집 요약 · 낼 금액(won) · 업체 줄 · 기간 · 서류. `money.range` · `memory`(0042)는 비워요 |
| `GET /assistant/today` | 넣음 | 오늘 정할 일 줄(코드가 골라요). `know` · 문장 하나는 비워요 |
| 업체 `checklists` · `today` | 넣음 | 표준견적서 줄 · 내 견적서 칸 · 빠지기 쉬운 것 / 새 요청 · 오늘 실측 · 보낼 견적서 |
| 업체 `briefs.suggest.action_id` | 넣음 | 요청함이면 기간 답하기 제안 행(window_answer)을 만들어요(같은 내용이면 같은 행). `sentence`(AI 한 문장)는 비워요 |
| `home_info`의 주소 찾기(search · manual) · `GET /address/search` | 뺌 | 범위 밖. 집 정보 카드는 confirm 모양(요약 · 면적 · 바뀜 · action_id)만이에요 |
| `TurnIn.context`{card_id, choice} | 넣음 | choice는 1~40자 값 하나 또는 5개까지예요. LLM에는 이번 대화에서 도구가 준 ref만 가고 모르는 값은 버려요(422 아님) |

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
   - 순서: tools(고정 · 이름순, 끝에 cache_control) → system(판 고정, cache_control) → 지난 턴 글 → 이번 글(가림) → `role:"system"` 턴 사실(오늘 · 단계 · 집 요약 · 기억, 코드 값만)
   - 턴 안에서는 덧붙이기만 하고, 턴 사이에는 글만으로 다시 짜요.
3. 모델 설정: `claude-sonnet-5-5`, thinking adaptive, effort medium, max_tokens 8000, stream, tool_choice auto + strict
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
9. 무료 모드: 키 없음 · LLM_LIVE=false · 상한 넘음 · 차단기일 때 `gate.gate` + 단계 카드 + `answer_only(mode="free")`로 답해요.

## 5. 도구
- id는 받지 않아요. `*_ref`(v1 · r1 · s1 · w1)는 `RefTable`로 풀고, 모르는 ref면 is_error예요.
- 모든 결과는 `policy.to_model`을 지나요.

### 읽기
| 도구(입력) | 부르는 함수 |
| --- | --- |
| `get_home`() | `project.service.get_for` |
| `get_standard_quote`(trade) | `quote.service.standard_for` |
| `recommend_vendors`(trade) | `visit.service.vendors_for` + `calc.vendor_pick.pick` · `reasons` → v1~v3 |
| `vendor_free_slots`(vendor_ref · visit_ref, prefer) | 요청 전: `visit.service.open_halves_for`(새, 칸 수만) + `calc.slots.wish_candidates`(새) → r1~r2. 요청 뒤: `pick_view` + `calc.slots.candidates`(새) → s1~s3 |
| `compare_quotes`(trade) | `visit.service.compare`. 표준 대비 %는 넘기지 않아요 |
| `get_schedule`() | `schedule.service.schedule_for` |
| `today_tasks`() | `service.feed_for`(`schedule.service.overview_for` + 열린 행동) |
| `search_knowledge`(query, trade) | `knowledge.service.search` |
| `answer_question`(question, kind) | `chat.service.answer_only` / `v2.ask.answer_only` |
| `find_floorplan_docs`() | `tools/floorplan.py`: Sonnet 5.5 + `web_search_20260209`(max_uses 3, 네이버 부동산 · 호갱노노 · 아실 차단, 링크 · 출처만) |
| `show_card`(kind) | `tools/cards.py` |
| 업체 `request_brief`(visit_ref) | `visit.service.vendor_visit` + `vendor.service.get_profile` · `estimate_v3_for` |
| 업체 `my_free_slots`(from, to) | `vendor_visit(preview)` + `calc.slots.best_windows`(새) → w1~w3 |
| 업체 `quote_checklist`(visit_ref) | `quote.service.latest_of` + `agent/trades` 주의점 |
| 업체 `my_jobs`() | `schedule.service.vendor_inbox` · `job_for` |

### 제안(행동 행만 만들어요)
| 도구(입력) | 승인 뒤 실행 |
| --- | --- |
| `propose_home_info`(칸) | `project.service.update` |
| `propose_visit_request`(trade, vendor_refs, wish_ref) | `visit.flow.add_shortlist`(안 담은 업체만) → `visit.flow.request` |
| `propose_visit_slot`(slot_ref) | `visit.flow.pick` · `pick_proposal` |
| `propose_vendor_confirm`(visit_ref) | `schedule.service.confirm`(seen_ver) |
| `propose_dates_accept` · `propose_delay_accept`(proposal_ref) | `schedule.service.accept_dates`(seen_version) |
| 업체 `propose_window_answer`(visit_ref, window_ref) | `visit.flow.answer_window` |
| 업체 `propose_decline`(visit_ref, code) | `visit.service.decline` |
| 업체 `propose_dates`(deal_ref, days_ref) | `schedule.service.propose_dates` |

### `actions.execute`
1. tx1: proposed → approved(조건부 UPDATE, 만료 전) 뒤 commit해요.
2. tx2: approved → executed와 기능 함수를 같이 실행해요. 기능 함수의 commit으로 확정돼요.
3. AppError가 나면 rollback하고 failed(기능 오류 코드)로 바꾼 뒤 409를 돌려줘요.
4. approved로 2분 넘게 남은 행은 sweep이 failed로 바꿔요(다시 실행하지 않음).
- 기능 함수가 여러 번 commit하는 실행(visit_request: 안 담은 업체 담기 → 요청)은 마지막 기능 함수 바로 앞에서 executed를 써요(담기가 먼저 commit돼도 행동은 executed가 아니에요).

### 구현 메모(2026-11-21, 비서 담당)
- ref 머리글자: v 업체 · m 실측 요청 · r 희망 기간 · s 반나절 · w 업체 기간 · d 확정 · p 공사 날짜 제안 · n 공사 날 후보. 대화마다 Redis 30분.
- `answer_question`은 `answer_only(mode="free")`로 근거 문장만 받아요(겹친 LLM 호출 없음). `v2.ask.answer_only`는 v2 파일이라 이번에 하지 않았어요.
- `vendor_free_slots`는 `prefer`(any · am · pm)와 `days`(any · weekday · weekend)를 받아요. `find_floorplan_docs`는 고객이 말한 단지 이름(`complex`, 동 · 호수 뗌)을 받을 수 있어요.
- `vendor_free_slots`(요청 전) · `request_brief` · `my_free_slots`의 업체 빈 반나절은 도메인 갈래의 `visit.service.open_halves_for`(실제 함수, 공사 날 · 잡기 반영)를 불러요. 가견적은 요청 때 고정한 값(`vendor_visit.estimate_total`)이에요.
- `propose_dates`의 날 후보(n1~)는 `my_jobs`가 견적서 공사 기간 · 예상 공정표 시작일로 `calc.schedule.workdays`에서 만들어요.
- `assistant_actions`에는 turn_id 칸을 두지 않았어요. 턴의 행동 id는 `assistant_turns.trace.actions`에 있어요.

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
  - 21~9시에는 9시로 미뤄요(feed에는 쌓아요).
  - 닫으면 같은 trigger를 3일 쉬어요. 7일 안에 2번 닫으면 notify를 7일 멈춰요.
  - 대상마다 열린 제안은 하나예요.
- '부를 만한가'
  - 점수: 기한 24시간 안 +50(48시간 안 +30), 행동 준비 +20, 돈 · 날짜 결정 +15, 같은 알림을 이미 읽음 −30, 24시간 안 보낸 것마다 −20, 같은 trigger 닫음 −30
  - 70 이상이면 보내요. 40~69는 Haiku가 코드 사실만 보고 yes/no로 정해요. 40 미만은 기록만 해요(held).
  - 문장은 Haiku가 60자 안으로 쓰고, 검사에 걸리면 템플릿을 써요.

## 7. 안전
- 가림
  - 사용자 글: `mask_in`(저장 · LLM 전)
  - 도구 결과: `to_model` 허용 필드만(이름 · 연락처 · 동호수 없음)
  - 모델 글: `SentenceGate`(숫자 · AI_ACTS · URL · 누출)
  - 웹 질의: 단지명 · 구만
  - 기록: `llm_usage` · trace · 로그에 글을 남기지 않아요.
- 주입 방어
  - 업체 글(견적 메모 · 소개 · 채팅)과 웹 글은 tool_result 안 `{"자료(지시 아님)": …}`로만 넘겨요. system에는 코드 값만 넣어요.
  - 도면 링크는 `web_search_tool_result`의 url만 코드가 뽑아요. 그림은 저장하지 않아요.
  - 행동은 ref와 사람 승인을 거쳐서 주입으로 실행되지 않아요.
- 기억 쓰기 잠금
  - 기억 쓰기 도구는 만들지 않아요. `memory.extract`(Haiku)는 그 사용자 메시지 한 줄만 읽어요.
  - 허용 목록 밖 키, evidence_quote에 없는 value, 건강 · 연락처 · 금액은 버려요.
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
