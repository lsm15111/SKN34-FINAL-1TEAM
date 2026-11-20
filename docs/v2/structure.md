# v2 프로젝트 구조

기준: 2026-11-19 `dev` 커밋 `6d41f94` (PR #140·#148 병합). 현재 코드의 패키지와 호출을 기록한다. 전체 업무 흐름 및 팀의 계층 규칙은 [AGENTS.md](../../AGENTS.md) 2장, 실제 기능별 완료 판정은 [기능 개발표](../feature-roadmap.md)를 따른다. 이전 26개 커밋 시안은 [초기 구현 계획](features.md)에 별도 보존했다.

## backend/app

| 패키지 | 층 | 하는 일 |
| --- | --- | --- |
| `calc/` | 도구 | 도배·목공 표준견적·가견적·일정·차이·진행단계 계산. `v2_quote` · `v2_plan` · `quick_budget` · `plan_qty` · `precise_*` 등 v2 계산 경로도 포함 |
| `refprice/` | 기반 | 현재 계산용 `book`·단가·공휴일·도면 자료, 기준 자료 버전과 정형 4종 저장 모델·적재 코드. DB 적재 자료가 모든 계산의 자동 입력으로 사용되는 것은 아님 |
| `knowledge/` | 기반 | 기준 데이터 RAG 청크·임베딩, 활성 버전 조회, BM25와 pgvector 검색 결과 결합, 인용 검증·추천 질문·CSV 변환 |
| `notify/` | 기반 | 화면 알림 쓰기(같은 트랜잭션, `dedup_key`) · 목록 · 읽음 |
| `files/` | 기반 | 올리기 · 사진 처리 · 저장. kind에 `price_doc` · `quote_doc` · `work_photo` |
| `auth/` · `account/` | 기반 · 대상 | 가입(휴대폰 칸) · 로그인 · 세션 · 탈퇴 |
| `project/` | 대상 | 집 정보 만들기 · 보기 · 고치기, 요청 번호, `lock_for_visit()` |
| `vendor/` | 대상 | 업체 가입 · 심사(보완 · 이력) · 업체 정보 · 연락 방식 · 자주 묻는 5가지 · 링크 · 사진 · 가견적 단가 묶음 |
| `quote/` | 흐름 | 표준견적서 버전(`ensure_standard`). 업체 실측 견적 파일은 `visit/`이 처리 |
| `visit/` | 흐름 | 업체 목록·가견적, 실측 요청·동의·취소·거절, 업체 견적 파일·버전·권한, 연락처 공개 검사 |
| `schedule/` | 흐름 | 예상·확정 공정표, 업체 확정·다시 고르기, 날짜 제안·고객 수락·변경 요청, 추가 금액, 공사 완료 확인 |
| `v2/` | 흐름 | `router.py`: `/v2/quote`·`plan`·`quick-budget`·`check`·`calc7`·`ask`·`cases` 등. `service.py`는 저장 없는 계산, `case_service.py`는 인테리어 한 건의 JSON 상태와 서버 재계산 견적·일정을 저장 |
| `chat/` | 흐름 | `chats`·`chat_messages` 모델, 최근 대화 읽기·`rev` 조건부 저장. 독립 `chat/router.py`는 빈 파일이고 공개 SSE 라우트에 등록되지 않음 |
| `agent/` | 도구 | `gate`·`intent`·`llm`·`trades/` 설정은 실제 호출. `trade_agent.py`는 실패를 돌려주는 뼈대이며 하위 공종 호출은 미구현 |
| `worker.py` | 조립 | arq 연결 `ping`, 시연일 때만 `demo_reply`. 일반 예약 작업·유료 LLM 설명·단가 자동 수집·메시지 발송은 미구현 |
| `mcp_server.py` | 조립 | 0바이트 빈 파일. 일정 MCP 서버·실제 클라이언트 연결은 미구현 |

기존 업무 기능은 `schedule → visit → quote → (vendor | project) → (files | refprice | notify) → auth` 흐름을 기준으로 호출한다. v2 상담은 `v2 → chat`(저장), `v2 → agent/knowledge/calc`(분류·검색·계산)로 연결된다. 서로 다른 기능은 공개 `service` 함수를 사용한다. 규칙과 실제 코드의 차이는 [AGENTS.md](../../AGENTS.md)에 구현·후속으로 구분한다.

## 현재 v2 상담·저장 흐름

```text
브라우저 /v2 (고객만)
  → /api/v2/ask → v2.router → ask_chat.start
  → chat.service.get_for · recent (기존 대화일 때만)
  → ask.start → 이미지 없는 일반 상담이면 무문자 질문 사전 고정 안내(미저장)
  → 같은 조건에서 낱말이 있을 때만 agent.gate(의도 분류, 필요 시 Jev)
  → 분류 후 out_of_scope 중 도배·목공 고유 증상어가 있으면 trade(source=rule, confidence=0)
  → chat_v4 + 공정 설정·지식 검색 → LLM ↔ 서버 도구(계산·검색)
  → 화면 도구를 요청하면 Redis에 턴 저장 → 브라우저 실행
  → /api/v2/ask/{turn_id} → ask_chat.resume → ask.take · ask.resume
  → guard 검사 · 인용 검사 → 완료한 일반 상담만 chat.service.save_turn
  → JSON 답변 (SSE 미구현)
```

- 일반 상담은 성공한 최종 답만 `chats`·`chat_messages`에 저장한다. 범위 밖 고정 안내와 실패 답은 기록하지 않는다. 번호표 `rev` 불일치는 409, 같은 Redis 턴의 늦은 재개는 404다.
- 무문자 게이트와 의도 분류는 모두 `kind=chat`이고 첨부 이미지가 **없을 때만** 적용한다. 무문자 질문에는 관문·LLM을 호출하지 않고 저장하지 않는다. 이미지 있는 채팅과 견적·공정표 설명은 두 검사를 건너뛰고 별도 경로로 처리한다.
- 도배·목공 고유 증상어는 [공종 낱말 설정](../../backend/app/agent/trades/__init__.py)의 `symptom_words`에서 확인한다. 모델·waiting·Jev 분류 결과가 `out_of_scope`일 때만 [`keep_in_scope`](../../backend/app/agent/route.py)로 `trade` 재지정하며, 일상어 `실크`·`낙서`·`테두리`만으로는 전환하지 않는다([이슈 #147](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/147)·[PR #148](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/pull/148)).
- 집 정보 담기 제안의 거주(`living`) 의미는 모델이 판단한다. 서버는 근거 문구(`living_said`)가 이번 고객 발화에 있는지 확인하고, 짧은 네/아니요 답이라면 직전 AI 질문도 확인한다. 근거는 모델 기록에 남지만 브라우저 도구 인자에서는 제거한다. 인용 문구 확인은 의미 판단의 정확성을 보장하지 않는다.
- 상담 도구 `price_reference`는 평형·도면이 모두 없으면 견적·기간 계산 대신 입력을 요청한다. 원시 `POST /v2/quote`의 평형 미입력 32평 기본 계산과 구분한다.
- 화면에서 고른 인테리어 상태는 별도로 `/v2/cases`의 `v2_cases`에 저장한다. 저장 시 화면에서 보낸 견적·공정표 입력을 서버가 재계산한다. `v2_cases`와 `chats` 사이에는 외래키가 없다.
- `LLM_LIVE=false`일 때는 스텁을 쓴다. 실제 모델·브라우저·AWS의 정상 동작은 이 파일을 읽은 것으로 검증되지 않는다.

[에이전트 계약](../agent-contract.md) · [v2 ERD](erd.md) · [테스트 안내](../testing.md)

## frontend

```
app/                      기존 회원·프로젝트·업체 라우트는 별도 기능과 연결
  v2/page.tsx             고객 전용 /v2 상담
components/
  site/                   역할별 머리 · 알림 종 · 바닥글 · 상태 화면
  start/                  견적 받기(목차 + 긴 폼) · DateCalendar · 사진
  project/                내 공사 지금 할 일 · 표준견적서 · 공정표 · 공사 날짜 · 서류
  vendors/                업체 고르기 · 업체 자세히 · 실측 요청 · 견적서 비교 · 확정
  pro/                    업체 화면: 작업함 · 업체 정보 · 실측 견적서 올리기 · 공사 일정
  my/ · auth/ · admin/     내 정보 · 가입 · 로그인 · 관리자 심사
  ui/                     ActButton · Money · Dialog 같은 공용 조각
  v2/                     V2App · store · cases · 예산 · 자재 · 견적서 · 공정표 · 화면 도구
lib/api/                  project · vendor · quote · visit · schedule · admin · notify
lib/backend/client.ts     브라우저에서 /api/* 호출, v2/api.ts · cases.ts가 이용
lib/backend/server.ts     서버 컴포넌트의 FastAPI 읽기
lib/mock/                 일부 예시 데이터가 남아 있음 (관리자 회원 목록 등)
```

`frontend/components/v2/data.ts`의 `SHOWN_CATS = ["wallpaper"]`이므로 v2 화면에는 도배만 노출한다. 기존 업무 화면·백엔드의 목공 계산 지원과 구별한다. 실제 현재 라우트는 `frontend/app/`에서 확인하고, 당시 시안 경로 표는 [초기 v2 기능 계획](features.md)을 참고한다.
