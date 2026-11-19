# v3 에이전트 질문 세트 커버리지 점검 (2026-11-19)

- 대상: `feat-v3-agent-design` 747e31d, `backend/app/agent/v3/` · `backend/app/chat/`
- 모드: 무료 모드만(`LLM_LIVE=false`, `OPENAI_API_KEY=` 비움). 점검 스크립트가 `llm.structured` · `jev_choice` · `embed_query`를 부르면 오류가 나게 막았고, 오류는 0건이에요. 유료 호출 0회.
- 지식: 저장소 CSV + v3 지식 요지로 만든 색인(`tests/v3_kb.repo_kb`, 조각 2,478 · 카드 416, 카드 판 `cards@3f0664a52009`). 운영은 같은 CSV를 DB에 넣고 `knowledge.service.index`로 읽어요. DB 적재본과 다를 수 있어요.
- 코드는 고치지 않았어요. 새로 만든 것: `evaluation/v3/coverage_check.py`, `evaluation/v3/coverage_questions.jsonl`(72문항). 결과는 `evaluation/v3/.cache/`(git 밖)에 저장돼요.

## 1. 기존 테스트

| 명령 | 결과 |
| --- | --- |
| `cd backend && . ../.claude/env.sh && TEST_DB_NAME=mitjip_test_agentaudit TEST_REDIS_URL=redis://127.0.0.1:6379/14 uv run pytest tests -k "v3 and (agent or gate or ai or chat or brief)" -q` | **169 passed, 1131 deselected (178.82s)** |
| `uv run ruff check app/agent/v3 app/chat tests ../evaluation/v3` | All checks passed |
| `uv run ruff format --check app/agent/v3 app/chat` | 27 files already formatted |
| `uv run ruff check` · `uv run ruff format --check` (backend 전체) | All checks passed · 394 files already formatted |
| `uv run ruff check ../evaluation/v3/coverage_check.py` (새 파일) | All checks passed (포맷 맞춤) |

- DB · Redis는 `docker start skn34-final-db-1 skn34-final-redis-1`로만 켰어요.
- `-k`의 `ai`가 다른 이름에도 걸려서, 에이전트 밖 시험도 일부 들어갔어요. 파일별 개수는 아래와 같아요.

| 파일 | 개수 | 파일 | 개수 |
| --- | --- | --- | --- |
| test_v3_agent_gate | 49 | test_v3_thread_rules | 12 |
| test_v3_agent_turn | 25 | test_v3_ai_api | 12 |
| test_v3_agent_brief | 19 | test_v3_agent_knowledge | 9 |
| test_v3_agent_cards | 8 | test_v3_visit_screens | 5 |
| test_v3_agent_judge_score · report_api · visit_request | 각 4 | test_v3_ai_tools · jobs_service | 각 3 |
| 나머지 11개 파일 | 각 1~2 | 합계 | 169 |

## 2. 질문 세트 커버리지

명령: `cd backend && . ../.claude/env.sh && uv run python ../evaluation/v3/coverage_check.py` (1,511문항, 34.7초)

질문마다 `gate.gate`와 `turn.run_turn`(mode=free)을 모두 돌렸어요. 프로젝트가 있는 세트(intent · 새 질문 일부)는 시험용 `ProjectFacts`(표준견적서 · 공정표 · 실측 초안 · 가견적 1곳)를 넣었어요.

### 2.1 세트별 요약

| 세트 | n | 정답 라벨 | 맞음 | 정확도 | 되묻기 | 범위 밖 | 칸 되묻기(ask) | 예외 | 출력 검사 걸림 | 실패 답 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| intent(dev 133 + held-out 67) | 200 | v3 라벨(e1_gate.v3_gold) | 176 | 88.0% (dev 118/133 · held-out 58/67) | 7 | 15 | 3 | 0 | 0 | 0 |
| 질문 은행 data/v3/questions | 493 | 담당(kb3 규칙) | 442 | 89.7% (dev 302/330 · held-out 140/163) | 12 | 16 | 1 | 0 | 0 | 0 |
| 초보 질문 beginner_web(= judge_packs/beginner_all) | 227 | 담당(kb3 규칙) | 208 | 91.6% | 2 | 8 | 10 | 0 | 0 | 0 |
| rag/questions | 90 | 공종 칸으로 정한 참고 정답 | 83 | 92.2% | 2 | 0 | 3 | 0 | 0 | 0 |
| rag/questions_300 | 300 (engine 19 뺌 → 281) | 참고 정답 | 219 | 77.9% | 11 | 4 | 6 | 0 | 0 | 0 |
| rag/questions_sigong | 60 | 참고 정답 | 50 | 83.3% | 7 | 1 | 1 | 0 | 0 | 0 |
| answer/set30 | 30 | 참고 정답 | 23 | 76.7% | 0 | 0 | 0 | 0 | 0 | 0 |
| trade/dobae + mokgong | 18 | trade | 17 | 94.4% | 0 | 0 | 2 | 0 | 0 | 0 |
| ask_back dev + held-out | 21 | 되물어야 하나(v2 기준) | 13 일치 | 61.9% | 1 | 0 | 2 | 0 | 0 | 0 |
| 새 질문 coverage_questions | 72 | 허용 담당 목록(직접 정함) | 65 | 90.3% | 10 | 5 | 3 | 0 | 0 | 0 |
| **합계** | **1,511** | | **1,283 / 1,471** | **87.2%** | **52 (3.4%)** | **49 (3.2%)** | **31** | **0** | **0** | **0** |

- 참고 정답(rag · answer30): 공종 칸이 도배 · 목공이면 trade, 공통이면 guide로 봤어요. 공통 질문에도 공종 낱말이 들어 있는 경우가 많아서 정답이 거친 편이에요.
- 질문 은행 · 초보 · rag는 프로젝트 없이 돌렸어요. 그래서 견적 · 일정 질문은 규칙대로 가이드로 가요(gate.py:146-147).
- 공종 질문이 multi로 가도 정답 공종이 들어 있으면 맞음으로 셌어요(e1_gate와 같은 규칙). 이렇게 센 것이 63건이에요.

### 2.2 담당 분포 (전체 1,511)

| 담당 | 건수 | 비율 |
| --- | --- | --- |
| trade | 944 | 62.5% |
| guide | 305 | 20.2% |
| multi | 95 | 6.3% |
| ask_back | 52 | 3.4% |
| out_of_scope | 49 | 3.2% |
| quote_explanation | 37 | 2.4% |
| schedule | 29 | 1.9% |

- 관문 결과와 턴의 최종 담당은 1,511건 모두 같았어요(turn이 기다림 · 버튼 없이 관문 결과를 그대로 씀).
- 관문이 고른 길: 분류기(model) 826 · 규칙(rule) 685.
- 공종이 정답인 884건 중 첫 공종이 맞은 것: **748 (84.6%)**.

### 2.3 답 출처와 출력 검사

| 답 모양 | 건수 | 비율 | 출처(sources) 붙음 |
| --- | --- | --- | --- |
| 모름만("확인하지 못했어요" + 확인할 곳) | 704 | 46.6% | 0 |
| 카드 | 382 | 25.3% | 382 |
| 정해 둔 글 + 모름 | 176 | 11.6% | 4 |
| 정해 둔 글만 | 123 | 8.1% | 2 |
| 정해 둔 글 + 계산 상자 | 65 | 4.3% | 0 |
| 조각 문장(extract) | 61 | 4.0% | 61 |

- **모름으로 끝나는 답(모름만 + 정해 둔 글 + 모름)은 880/1,511 (58.2%)**이에요. 모름만인 704건의 담당은 trade 538 · guide 124 · multi 42예요.
- 출처가 붙은 답은 449/1,511 (29.7%)이고, 카드 · 조각 답에만 붙어요.
- 출력 검사(`check.py`)에서 빠진 문장이 있는 턴은 **0건**이에요(trace.dropped가 모두 비어 있음). 실패 답(`failed`)도 0건이에요. 무료 모드는 카드 · 정해 둔 글 · 조각 원문만 내보내서 검사에 걸릴 글이 거의 없어요. 검사가 실제로 의미를 갖는 것은 LLM 모드예요(이번에는 돌리지 않음).

### 2.4 카드 열쇠와 질문 세트가 겹침

| 세트 | 카드 열쇠(keys)와 글자 그대로 같은 질문 | 카드 답 비율 |
| --- | --- | --- |
| 초보 질문 dev (152) | 87 | 81/152 (53.3%) |
| 초보 질문 held-out (75) | 0 | 9/75 (12.0%) |
| 질문 은행 (493) | 0 | 91/493 (18.5%) |
| rag300 (300) | 1 | 83/300 (27.7%) |

- 초보 dev 질문 87개가 카드 열쇠에 그대로 들어가 있어요. 열쇠와 같은 질문은 74/87이 카드로 답했지만, 다른 질문은 16/140만 카드로 답했어요. 카드가 dev 문장에 맞춰져 있어서 dev 점수는 실제보다 높게 나와요.
- 카드 416장은 모두 `verified.status = author_checked`예요. `ok`(다른 사람 확인)는 0장이에요.

### 2.5 되묻기 · 범위 밖을 기대한 질문

| 세트 | 기대 | n | 결과 |
| --- | --- | --- | --- |
| 질문 은행 | ask_back(조건을 되물어야 함) | 42 | 칸 되묻기 0 · 관문 되묻기 1 · 정책 표시(my_house · price · period · defect)로 정해 둔 글 32 |
| 초보 질문 | ask_back | 36 | 칸 되묻기 3 · 관문 되묻기 0 · 정책 표시 12 |
| 질문 은행 | out_of_scope | 28 | 범위 밖 14 · 추천 · 법률 거절 표시로 처리 7 · 처리 안 됨 7 |
| 초보 질문 | out_of_scope | 11 | 범위 밖 8 · 거절 표시 2 · 처리 안 됨 1 |

- 조건을 되물어야 하는 질문에서 카드 칸 되묻기(ask)는 거의 나오지 않아요(78건 중 3건). 카드에 `ask`가 붙은 카드가 걸려야만 되묻기 때문이에요(answer.py:228-234).

### 2.6 틀린 예시 (원문 그대로)

| # | 세트 · id | 질문 | 정답 | 실제(공종) | 원인 |
| --- | --- | --- | --- | --- | --- |
| 1 | coverage cov-045 | 싱크대 교체 기간은 며칠이에요? | trade(주방) | trade [paint, kitchen] → "도장 공사 기간은…" | '며칠이'의 '칠이'가 도장 낱말로 걸림 |
| 2 | rag300 | 우리 집 도배는 며칠이면 끝나요? | trade(도배) | trade [dobae, paint] | 같은 '칠이' 오인식(8건) |
| 3 | bank qv3-bath-005 | 욕실 덧방 공사는 타일, 도기 설치, 실리콘 순서로 진행되나요? | trade(욕실) | trade [tile, bath] | 첫 공종이 타일. 욕실 질문이 타일 담당으로 감 |
| 4 | 질문 은행(목공) | 안방 화장실 문이 잘 안 닫히는데 문틀이 틀어진 건가요? | trade(목공) | trade [bath, mokgong] | '화장실'(장소)이 공종 낱말로 먼저 걸림 |
| 5 | 질문 은행(목공) | 화장실 문폭이 좁아졌는데 넓힐 수 있나요? | trade(목공) | trade [bath] | '문'만으로는 목공이 안 걸림 |
| 6 | rag300 xd036 | 업체마다 도배 견적이 크게 차이 나는 건 왜예요? | trade(도배) | guide | 분류기 quote_explanation → 프로젝트 없어 guide. 공종 바꾸기(gate.py:144)보다 뒤에 바뀌어 공종을 잃음 |
| 7 | bank qv3-dobae-002 | 도배 견적 두 곳이 30만 원 넘게 차이 나는데 뭘 보고 비교해야 해요? | trade(도배) | guide | 6과 같음 |
| 8 | bank qv3-dobae-034 | 한 면만 새로 할지 방 전체를 다시 할지 정하는 기준이 있나요? | trade(도배) | ask_back | 공종 낱말 없음 · 분류기 0.461 |
| 9 | rag300 xd076 | 공사하는 날 집에 있어야 하나요, 비워도 되나요? | trade(도배) | ask_back | 공종 낱말 없음 · 분류기 0.67 |
| 10 | bank qv3-electric-018 | 거실이랑 방 조명 공사를 하면 금액이 얼마나 나올지 계산해 주세요. | out_of_scope | trade [electric] | 계산 요청 규칙(CALC_REQUEST)이 '얼마나 나올지 계산해'를 못 잡음 |
| 11 | bank qv3-bath-028 | 샤워수전 살 건데 요즘 제일 잘 팔리는 모델명 하나만 알려 주세요. | out_of_scope | trade, 정책 표시 없음 | brand_reco가 '모델명 하나만 알려'를 못 잡음 |
| 12 | 질문 은행 | 줄눈 업체 중에 후기 좋은 곳 이름 좀 알려 주세요. | out_of_scope | trade, 정책 표시 없음 | vendor_reco가 '후기 좋은 곳 이름'을 못 잡음 |
| 13 | intent dev-24 | 견적 설명이랑 일정 조정 둘 다 부탁드려요 | multi | guide | 분류기 0.971 orchestrator. '견적 설명'이 QUOTE_MINE에 안 걸려 신호가 하나(일정)뿐 |
| 14 | intent heldout-57 | 현금영수증 되요? | out_of_scope(v2 라벨) | guide | v3는 공통 지식으로 답하게 바꿈(gate.py:196). 라벨이 v2 기준 |
| 15 | beginner qv3b-common-013 | 도배랑 장판만 바꾸는데도 관리사무소에 미리 신고해야 해요? | guide | multi [dobae, floor] | 공종 둘 + 이음말이면 공통 질문도 multi |
| 16 | coverage cov-015 | 실측은 언제 와요? (프로젝트 있음) | schedule | guide → 모름 | '실측은'이 SCHEDULE_MINE(`실측\s*와`)에 안 걸리고 분류기 guide 0.775 |
| 17 | coverage cov-047 | 도베 비용 얼마에여 | trade(도배) | guide | 오타 '도베'를 공종 낱말이 못 잡음 |
| 18 | coverage cov-052 | wallpaper 교체 비용 how much? | trade(도배) | guide | 영어 낱말 없음 |
| 19 | coverage cov-056 | Can you explain my quote? (프로젝트 있음) | quote_explanation | ask_back | 영어 문장 분류 못 함(0.56) |
| 20 | coverage cov-013 | 목공이랑 도배 다 하면 기간 얼마나 걸려요? | multi · 기간 | multi, 정책 [price, period] → 첫 문장이 금액 안내 | price 정규식 '얼마'가 '얼마나 걸려'에도 걸림(4건) |

## 3. 빈틈 찾기 (새 질문 72개)

`evaluation/v3/coverage_questions.jsonl`. 칸: `cat` · `text` · `ok`(허용 담당) · `has_project` · `trade`(정답 첫 공종).

| 유형 | n | 맞음 | 실제 담당 | 답 모양에서 본 문제 |
| --- | --- | --- | --- | --- |
| 처음 고객 | 5 | 5 | guide 5 | '믿집은 어떻게 쓰는 거예요?'가 서비스 카드 대신 조각 문장. '표준견적서가 뭐예요?' 카드 첫 문장이 "아니에요."(다른 열쇠 질문의 카드) |
| 비용 | 6 | 6 | trade 3 · quote 2 · out 1 | '32평 도배 몇백 정도면 돼요?'는 price 표시가 안 붙어 모름('몇백' 없음) |
| 기간 | 4 | 3 | trade · multi · schedule · guide | '실측은 언제 와요?' → guide 모름 |
| 자재 비교 | 5 | 5 | trade 5 | 'MDF 몰딩이랑 원목 몰딩 차이' 모름 |
| 하자 | 4 | 4 | trade 3 · guide 1 | '하자 보수 기간은 보통 얼마예요?'에 price가 붙어 "일반 시세 숫자는 말하지 않아요" |
| 계약 | 4 | 4 | guide 4 | '계약금은 얼마나 주는 게 보통이에요?'도 같은 금액 거절 글 |
| 이웃 · 관리사무소 | 4 | 4 | guide 4 | '아랫집이 항의하면' 모름 |
| 셀프 | 3 | 3 | trade 3 | 도배 · 몰딩 셀프는 위험 공종이 아니라 정해 둔 글이 없고 카드도 없어 모름 |
| 사진 보여 달라 | 3 | 3 | trade 2 · guide 1 | 사진을 못 보여 준다는 안내가 없음. 그냥 "확인하지 못했어요" |
| 근처 업체 | 3 | 3 | trade 2 · guide 1 | 추천 거절 글 + 모름. 근처 업체 화면(업체 보기)으로 가는 버튼은 도배 · 목공만 |
| 다른 공정(욕실 · 바닥) | 5 | 5 | trade 4 · out 1 | 싱크대 질문이 도장으로 감(며칠이). '장판이랑 마루' 모름 |
| 오타 · 줄임말 | 5 | 4 | guide 2 · trade 3 | '도베' 못 잡음. '걸래받이 ㄱㄴ?' 모름 |
| 영어 섞임 | 5 | **1** | ask_back 3 · guide 1 · trade 1 | wallpaper · molding · schedule · quote 낱말 없음. 영어 문장은 되묻기 |
| 아주 긴 글(508자 · 53자) | 2 | 2 | trade 1 · multi 1 | 508자 4공종 글이 multi가 아니라 trade 하나로 가고 모름. 검색은 앞 80자만 씀(search3.py:44) |
| 빈 글 · 기호 | 4 | 4 | ask_back 3 · guide 1 | '?'는 guide 모름 |
| 이모지 | 4 | 4 | ask_back 2 · trade 2 | 이모지만이면 되묻기(괜찮음) |
| 범위 밖 · 잡담 | 4 | 3 | out 3 · ask_back 1 | '너 누구야?'가 되묻기(intent 세트는 같은 꼴을 guide로 봄) |
| 개인정보 · 지시 주입 | 2 | 2 | trade 1 · ask_back 1 | 전화번호는 가려짐. 주입 글은 되묻기로 끝남(지시문 노출 없음) |

### 3.1 잘못 가는 유형 (많이 · 크게 틀리는 순)

| 순위 | 유형 | 근거 숫자 | 위치 |
| --- | --- | --- | --- |
| 1 | 장소 낱말 · 겹치는 낱말로 첫 공종이 틀림('화장실 문' → 욕실, '욕실 타일' → 타일, '며칠이' → 도장) | 첫 공종 틀림 136/884. 목공→욕실 9 · 도배→설비 8 · 목공→도장 7 · 욕실→타일 6. '칠이' 오인식 8건 | trades.py:166(도장 낱말) · 299-322(WORK_OVER · trades_in) |
| 2 | 답이 모름으로 끝남 | 880/1,511 (58.2%), 모름만 704. 카드 답은 열쇠와 같은 dev 문장에 몰림(2.4) | answer.py:209-211 |
| 3 | 프로젝트 없는 견적 질문이 공종을 잃고 guide로 감 | rag300 trade→guide 32 · 질문 은행 15 | gate.py:143-147(공종 바꾸기가 프로젝트 없음 바꾸기보다 앞) |
| 4 | 영어 · 오타 | 새 질문 영어 1/5, 오타 '도베' 놓침 | trades.py 낱말 목록, 분류기 |
| 5 | 공종 낱말 없는 공종 질문 → 되묻기 | 질문 은행 trade→ask_back 11 · rag300 7 | gate.py:214 |
| 6 | price 표시 오탐('얼마나 걸려' · '계약금 얼마나' · '보수 기간 얼마') | 4건 + 새 질문 2건 | policy.py:16-19 |
| 7 | 10공종 계산 요청 · 모델명 · 업체 이름 요청을 못 잡음 | 질문 은행 범위 밖 28 중 7 처리 안 됨 | policy.py:24-31 · 68-73 |
| 8 | 공종 둘 + 이음말이면 공통 질문도 multi | 초보 guide→multi 7 | gate.py:179 · 183-186 |
| 9 | 조건을 되물어야 하는 질문에 칸 되묻기 거의 없음 | 78건 중 3건 | answer.py:228-234 |

## 4. RAG와 도구: 근거를 어디서 가져오나

**결론: RAG(지식 조각 검색)만 쓰지 않아요.** 다섯 가지 출처를 순서대로 써요. 검색은 BM25 키워드만이고, 의미 검색(pgvector)은 v3 턴에서 쓰지 않아요.

### 4.1 출처별

| 출처 | 무엇 | 어디서 쓰나 (파일:줄) |
| --- | --- | --- |
| 정해 둔 글(templates) | 범위 밖 · 금액 · 기간 · 추천 거절 · 하자 판정 안 함 · 셀프 위험 · 모름 · 다음 할 일 | templates.py:39-44 · 72-80 · 119-137, guide.py:21-48, trade_agent.py:29-70, turn.py:48-62 |
| 계산 엔진 결과(프로젝트 데이터) | 표준견적서 합계 · 줄 · 공급가 · 부가세, 공정표 기간 · 블록, 실측 초안 · 추천일, 가견적 합계 · 표준 대비 % | chat/tools.py:40-72(project.get_for · quote.standard_for · schedule.plan_for · overview_for · visit.vendors_for · draft_for · pick_view), answer.py:249-277(calc_box · line_box), quote_explain.py:54-143, schedule_agent.py:20-121 |
| 검증된 답 카드(정적 파일 416장) | 열쇠 질문 TF-IDF 맞추기 → 받아들이면 카드 문장 그대로. 문장마다 조각 번호 인용 | knowledge/cards.py:26(CARD_DIR=app/agent/cards) · 214(find), answer.py:142-179 |
| 지식 조각 검색(RAG, BM25) | 카드가 없을 때 위 조각에서 문장 뽑기. 미리 만든 해요체 요약(summaries.jsonl 624줄)이 있으면 요약 | answer.py:137-139(search3.search, k=8) · 180-208(extract.pick), knowledge/search3.py:28-95, knowledge/extract.py:5 |
| 제품 규칙 · 공정 순서 규칙 | 서비스 카드가 인용하는 화면 글 · 설계 결정(doc:), 공정표 순서(rule:, calc.v2_plan.PLAN_ORDER) | knowledge/cards.py:37-46(DOC_REFS), trades.py:240-288(ORDER_RULES · ORDER_CITES · rules), orchestrator.py:112-131 |

- 색인: 운영은 활성 지식 버전의 조각을 DB에서 읽어 BM25 색인을 만들어요(chat/service.py:179 → knowledge/service.py:23-38). 의미 검색이 있는 `knowledge.service.search`(service.py:42)는 v3 턴에서 부르지 않아요(agent/v3 · chat 안에 호출 없음).
- 이번 색인의 조각 출처 종류: kcs 640 · law 313 · maker_guide 261 · maker 240 · official 187 · gov_notice 134 · guide 121 · pumsem 105 · gov_guide 85 · experience 84 · consumer_agency 76 · book 59.
- 숫자 · 기간은 카드 글 · 조각 원문 · 계산 결과에 있는 숫자만 남겨요(check.py:62-123, answer.py:83-90). 담당 순서: 정책 글 → 카드 → 조각 문장 → 모름(answer.py:1-7).
- LLM 모드(`LLM_LIVE=true`이고 키가 있을 때만, chat/service.py:104-108)도 새 근거를 찾지 않아요. 카드 · 조각 묶음을 그 근거 원문만 넣어 다시 쓰기만 해요(turn.py:65-85 · 126, llm_mode.py:56-91).

### 4.2 도구

| 도구 | 있나 | 위치 |
| --- | --- | --- |
| 프로젝트 사실 읽기(기능 service 공개 함수) | 있음. LLM이 부르는 도구가 아니라 chat.service가 턴 앞에 한 번 읽어 넘김 | chat/tools.py:40-215, chat/service.py:174-178 |
| LLM 도구 호출(function calling) | v3 턴에는 없음. `llm.chat_tools`는 있지만 v3에서 부르지 않음 | agent/llm.py:143 |
| 일정 MCP | `backend/app/mcp_server.py`는 있지만 v3 에이전트 · chat에서 MCP 클라이언트로 부르지 않음 | agent/v3 · chat 안에 호출 없음 |
| 지식 검색 · 카드 찾기 | 코드가 직접 부름(도구 아님) | answer.py:155-158 |

### 4.3 출처 표시 · 이미지

| 항목 | 지금 | 위치 |
| --- | --- | --- |
| 묶음 출처(문서 이름 · 종류 · 조각 번호) | 카드 · 조각 · 순서 묶음에만 `sources {ref, title, kind, publisher}`. 정해 둔 글 · 계산 · 모름 묶음은 없음. 이번 점검에서 출처가 붙은 답 29.7% | answer.py:127 · 200, orchestrator.py:119-130, schemas.py:189 |
| 공개 API | `AiSection.sources`에 ref · title(80자) · kind만. 문장별 인용 번호는 공개 응답에서 빠짐(`sentences: list[str]`). 문서 주소(url)는 넘기지 않음 | chat/schemas.py:40-55 · 118-137 |
| 화면 | 출처 문서 이름만 '출처 · …'로 보임(짧은 답 2개, 묶음마다 3개). 조각 번호는 안 보임 | frontend/components/ai/AiAnswer.tsx:78 · 85 · 94-95 |
| 이미지 | **내주는 길이 없음.** 카드 형식에 그림 칸이 없고(knowledge/cards.py:88-110), 답 · 카드 모양에도 없음. `UiCard.kind`에 `grade_preview`가 있지만 만드는 코드가 없음 | agent/v3/schemas.py:215-218 |

## 5. 고칠 것 (우선순위, 이번에는 고치지 않음)

| 순위 | 할 일 | 근거 | 위치 |
| --- | --- | --- | --- |
| 1 | 도장 낱말 `칠(?:하|을|해|이|은)`이 '며칠이'에 걸리지 않게(앞 글자 '며' 제외 등) | 오인식 8건, 싱크대 질문이 도장 기간 글로 답함 | trades.py:166 |
| 2 | 첫 공종 고르기: 장소 낱말(화장실 · 욕실)보다 작업 대상(문 · 문틀 · 타일 · 방수)을 앞에. '문' 단독도 목공 후보 | 첫 공종 틀림 136/884 | trades.py:307-322 · WORK_OVER |
| 3 | `done()`에서 프로젝트 없음 → guide 바꾸기 뒤에도 공종이 있으면 trade로 | rag300 32 · 은행 15건 공종 잃음 | gate.py:143-147 |
| 4 | price 표시에서 '얼마나 (걸|가|오래)' · '계약금 얼마나' 빼기 | 오탐 6건, 기간 질문 첫 문장이 금액 글 | policy.py:16-19 |
| 5 | 모름 비율 줄이기: held-out · 은행 기준으로 카드 열쇠 넓히기, dev 문장 그대로 열쇠에 넣는 것 멈추기 | 모름 58.2%, 초보 dev 카드 53% vs held-out 12% | agent/cards/*.jsonl |
| 6 | 계산 요청 · 모델명 · 업체 이름 규칙 넓히기('얼마나 나올지 계산', '모델명 하나만', '후기 좋은 곳 이름') | 범위 밖 기대 28 중 7 처리 안 됨 | policy.py:24-31 · 68-73 |
| 7 | 사진 · 이미지 요청에 "사진은 보여 드리지 못해요" 정해 둔 글(또는 이미지 길을 만들지 팀 결정) | 사진 질문 3개 모두 그냥 모름 | templates.py · gate.py |
| 8 | 영어 · 오타 낱말 몇 개(wallpaper · molding · 도베 · 걸래받이) | 영어 1/5 | trades.py 낱말 |
| 9 | 긴 글: 검색에 앞 80자만 쓰므로 조각마다 나눠 찾거나, 공종 셋 이상이면 multi | 508자 글이 trade 하나 · 모름 | search3.py:44, gate.py:179 |
| 10 | '실측은 언제 와요' 꼴(조사 뒤 '언제')을 SCHEDULE_MINE에 | 프로젝트 있어도 guide 모름 | gate.py:32-36 |
| 11 | 공개 응답에 문장별 인용 번호(또는 묶음 ref)를 화면에 보일지 결정 | 지금은 문서 이름만 보임 | chat/schemas.py:48 · AiAnswer.tsx |
| 12 | 카드 검토 상태: 416장 모두 author_checked. 다른 사람 확인(ok) 절차 | 2.4 | agent/cards/*.jsonl |
| 13 | ask_back 세트(21)와 intent 범위 밖 라벨 일부는 v2 기준이라 v3 정답으로 다시 붙이기 | 13/21 일치, '현금영수증' 류 | evaluation/ask_back · intent |

## 6. 못 한 것

- LLM 모드(글 다시 쓰기)와 그 출력 검사는 돌리지 않았어요(유료 호출 금지).
- 답 내용이 맞는지(사실 · 근거 맞음)는 채점하지 않았어요. 담당 · 공종 · 답 모양만 셌어요.
- 운영 DB 지식 버전으로는 돌리지 않았어요(저장소 CSV 색인만).
- judge_packs의 e3 · e4 · brief 묶음은 답 채점용이라 이번 담당 점검에 넣지 않았어요.
