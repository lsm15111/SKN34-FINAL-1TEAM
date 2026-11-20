# 믿집 작업 지침

사람과 AI 코딩 도구가 함께 지키는 규칙이다. 구조 · 흐름 · 검증처럼 꼭 지켜야 하는 것만 둔다. 실행 방법은 README에 있다.

- 우선순위: 팀이 정한 결정 > 이 문서 > 개인 습관. 서로 부딪히면 고치기 전에 묻는다.
- 기준 자료 버전은 `status BOOLEAN`(기본값 `False`)으로 활성 여부만 관리하며 상태 변경 이력을 저장하지 않는다.
- 기준 데이터·전처리 테이블·RAG 관련 작업 전 [기준 데이터 사용 안내](docs/reference-data.md)를 확인한다.

## 1. 제품 흐름과 이름

**현행 v3 구현 기준: 2026-11-19 `dev` `344f6dc` (PR #151 병합).** 아래 기존 제품 설명은 v2 흐름을 포함한다. v3 호출·데이터 흐름은 [v3 구조](docs/v3/architecture.md)·[v3 데이터 모델](docs/v3/data-model.md), v2 기준 구현 기록은 [v2 구조](docs/v2/structure.md)를 본다.

- 1차 범위는 아파트 도배 · 목공이다. 기존 v2 흐름: 집 정보 · 공정 고르기 → 예상 공정표 · 표준견적서 → 상담 → 업체 고르기(업체별 가견적) → 실측 요청(연결만) → 업체가 실측 견적서 파일 제출 → 확정 또는 다시 고르기 → 확정 업체가 공사 날짜 올림 → 고객 수락 → 확정 공정표 → 업체별 일정 확인 → 업체가 확정 또는 연기 → 연기면 고객 승인 뒤 공정표 재조정 → 영향받는 업체 재확인 → 전체 확정.
- 지금 v2 화면은 도배만 연다(`frontend/components/v2/data.ts`의 `SHOWN_CATS`). 첫 질문(목적 고르기) → 빠른 예산(질문 세 개로 보는 시장 범위) → 표준견적서 → 예상 공정표로 이끈다. 벽지 값은 실크벽지 두 종류의 평당 자재값(`refprice/book.py`의 `SILK_2026`)이고, 지금은 업체 견적서 1건 값이라 자료가 모이면 바꾼다.
- 가견적은 업체가 직접 넣고 확인한 단가로 계산 엔진이 만든다. 확인 전에는 고객에게 보이지 않는다.
- v2 실측 요청은 연결만 한다. v3는 업체의 가능 기간·반나절 선택·확정과 답변 기한을 서버에서 처리한다(`visit` · `calc/slots.py` · `jobs`). 고객 연락처는 고객이 업체마다 동의했을 때만 업체에 간다.
- 실측 견적서는 업체가 자기 양식 파일(PDF · 엑셀 · 사진)로 내고, 낼 금액 · 부가세 방식 · 공사 기간 · 유효기간만 칸에 적는다. 믿집 양식은 공공 기준으로 계산한 표준견적서 하나다.
- 업체는 기본 회원정보 + 사업자등록증으로 가입하고, 관리자가 승인해야 업체 기능을 쓴다.
- 도배 · 목공 외 공종의 **시공 연결·금액 계산**, 전자계약·결제는 현행 1차 범위 밖이다. v3 AI는 그 밖의 공종도 지식 안내할 수 있으나 금액·기간을 임의 산출하지 않는다.
- v3는 비회원 표준견적서(저장 없음) → 가입·공사 생성, 업체 담기 → 실측 기간·반나절 선택 → 업체와 채팅 → 견적서 비교·확정 → 공사 일정·추가 금액·완료 → 리뷰 흐름을 제공한다. 신고·관리자 처리도 별도 `report` 패키지에 있다. 개발 여부와 실서버 배포 여부를 구분한다.
- 화면과 코드에서 아래 이름만 쓴다.

| 화면 말 | 코드 이름 | 뜻 |
| --- | --- | --- |
| 표준견적서 | `standard_quote` | 공공 기준 단가로 믿집이 계산한 참고 금액. 업체 견적이 아니다 |
| 가견적 | `estimate` | 실측 전, 업체가 확인한 단가(`vendor_price`) × 표준 수량으로 계산 엔진이 만든 금액 |
| 실측 견적서 | `vendor_quote` | 업체가 실측하고 낸 견적서 파일 + 요약 칸. 다시 올리면 버전이 쌓인다 |
| 실측 | `visit` | 실측 요청. 요청함 → 견적서 옴 → 확정 또는 닫힘. 방문 날짜는 고객과 업체가 직접 정한다 |
| 업체 확정 | `deal` | 고객이 고른 업체와 확정한 견적서 버전 |
| 공정표 | `schedule` | 반나절로 계산해 하루 단위 날짜로 잡은 작업 순서 |
| 알림 | `notification` | 화면 알림(종 아이콘). 문자 · 메일은 보내지 않는다 |
| 기준 단가 | `ref_price` | 표준시장단가 · 시중노임단가 · 조달청 가격 등 공공 기준값 |
| 품 | `man_day` | 기능공 1명 1일 작업량 |
| 공급면적 / 전용면적 | `area_basis = supply / exclusive` | 평형(분양) / 실제 쓰는 면적 |
| 도배 유형: 저가형 / 기본형 | `grade = economy / basic` | 고객이 고르는 도배 등급 |
| 대화 | `chat` | 고객이 에이전트와 주고받는 채팅 |
| 브리프 | `brief` | 공종 에이전트가 고객에게 물어 모은 공정별 조건 |
| 가이드 | `guide` | 처음 고객의 궁금증과 시작 순서를 안내하는 공통 대화. 오케스트레이터가 맡는다 |
| 공종 에이전트 | `trade` | 공정별 설정(도배 · 목공)을 불러 우리 집에 필요한 조건 · 주의점을 정리해 오케스트레이터에 돌려주는 에이전트 하나. 의도 라벨 `trade`는 공정 상담 역할 |
| 견적 설명 | `quote_explanation` | 저장된 금액을 풀이하는 설명. 금액을 만들지 않는다 |
| 일정 변경 | `schedule_change` | 업체가 연기를 요청하고 고객이 승인하는 공정표 변경 |

## 2. 구조와 호출 흐름

하나의 FastAPI 앱을 기능별 패키지로 나눈 모듈러 모놀리스다. 기존 v2 계산·상담과 v3 손님 견적·실측 일정·채팅·리뷰·신고·기한 `jobs`가 공존한다. 일정 MCP와 worker의 자동 LLM 설명·기준 단가 수집은 후속이다. 구현·검증 근거는 [기능 개발표](docs/feature-roadmap.md), 버전별 경로는 [v3 구조](docs/v3/architecture.md)와 [v2 구조](docs/v2/structure.md)에서 구분한다.

| 부분 | 하는 일 |
| --- | --- |
| `frontend/` (Next.js) | 화면만. DB 접근 · LLM 호출 · 금액 계산을 하지 않는다 |
| `backend/app/` (FastAPI) | 유일한 공개 API. 기능 패키지 + 계산 엔진 `calc` + 에이전트 `agent` |
| `backend/app/worker.py` (arq) | `ping`, 1분 주기 `sweep_jobs`(실측·견적·공사 기한 처리), 선택적 시연 `DEMO_AUTO`. 자동 LLM 설명·기준 단가 수집·바깥 발송은 후속 |
| `backend/app/mcp_server.py` | 일정 MCP 서버를 둘 예정인 빈 파일(현재 0바이트, 미구현) |
| PostgreSQL 17 + pgvector | 원본 데이터와 지식 검색. Redis는 큐 · 요청 제한 · 짧은 캐시만 (지워져도 되는 것) |
| Cloudflare (운영) | DNS · 사용자 쪽 HTTPS · 방화벽. EC2 앞단 |
| Caddy (운영) | 서버 쪽 HTTPS, `/api/*` → API, 나머지 → web |

**프런트 구조** (`frontend/`)

```
app/<경로>/page.tsx      화면(라우트). 권한은 lib/session.ts의 requireRole로 확인
app/globals.css          디자인 토큰과 여러 화면이 같이 쓰는 공용 클래스. 옮겨 온 화면 전용 클래스가 아직 남아 있어서, 그 화면을 고칠 때 module.css로 옮긴다
components/<영역>/        화면 조각. 영역: site · start · project · vendors(고객이 보는 업체) · pro(업체 화면) · my · auth · admin · chat · ui
                         한 컴포넌트에만 쓰는 스타일은 옆에 <이름>.module.css로 둔다
lib/backend/server.ts    Server Component → FastAPI. 쿠키를 넘기고 읽기만 한다
lib/backend/client.ts    브라우저 → /api/*. 쓰기 · 오류(ApiError)
lib/backend/schema.d.ts  API 타입. pnpm gen:api로 만들고 손으로 고치지 않는다
lib/api/<영역>.ts         서버 쪽 읽기의 입구. 영역마다 한 파일: project · vendor · quote · visit · schedule · admin · notify · chat
lib/mock/                예시 데이터. API가 생기면 lib/api/<영역>.ts 안에서만 바꾼다
lib/session.ts           로그인한 사람(GET /me)
lib/format.ts · labels.ts · types.ts   표시 형식 · 화면 말 · 타입
```

**백엔드 구조** (`backend/app/`)

```
main.py                  앱 조립: 미들웨어 · router 등록(ROUTERS) · /health/live · /health/ready
worker.py                arq worker
config.py · db.py · queue.py   설정 · DB 세션 · 큐 연결
shared/                  errors · clock · ids · ratelimit · regions · request_guards
auth/                    가입 · 로그인 · 세션 · 권한(deps) · 관리자 계정 만들기(cli)
account/                 탈퇴
files/                   올리기 · 사진 처리(images) · 저장(storage)
project/                 프로젝트 만들기 · 보기
vendor/                  업체 가입 신청 · 관리자 승인
../migrations/           Alembic. 현재 0001~0035 중 0031을 뺀 34개 revision 파일. 실제 DB 적용 여부는 환경별 확인하고, 적용된 migration은 수정하지 않는다
calc/                    계산 엔진(순수 함수): 도배 · 목공 · 표준견적서 · 공정표 · 시장 범위(market_band) · 빠른 예산(quick_budget) · v2 견적(v2_quote)
refprice/                기준 단가 · 시장 실견적 · 도면 · 휴일 · 실크벽지 평당 값(book) · 기준 자료 적재(ingest)
quote/ · visit/ · schedule/   표준견적서 · 실측 견적서 / 업체 고르기 · 실측 요청 / 공정표 · 업체 확정
notify/                  화면 알림 (다른 service는 add만 부른다)
guest/                   비회원 표준견적서 계산(저장 없음)
jobs/                    PostgreSQL 영속 기한 일·수거·완료 상태
thread/ · realtime/      고객·업체 채팅·읽음·차단, Redis Stream 실시간 알림(SSE)
review/ · report/         리뷰·답글, 신고·관리자 조치
```

**v2 AI 상담** (C안: v2 한 턴 루프 + 입구 관문 + 대화 저장, #110)

```
v2/ask_chat.py           대화 표에 잇기: 열기(get_for · recent) → ask.start / resume → 끝난 턴만 저장(save_turn). 새 대화는 첫 저장 때 만든다. 답 끝 [되물음] 표시로 waiting
v2/ask.py                한 턴: 입구 관문 → 오케스트레이터 역할 루프(LLM ↔ 도구) → 출력 검사. 화면 도구를 기다리는 턴은 Redis에 10분
v2/ask_tools.py          도구 정의와 역할별 도구. 서버 도구(계산 엔진 · 지식 검색)는 서버가, 화면 도구(고객 상태 제안 · 단계 카드)는 브라우저가 실행. 추천 질문은 도구가 아니고 서버가 고른다
v2/guard.py              출력 검사: 문장 단위 숫자 · 근거 · 금지 표현, 전화번호 · 동호수 가림
v2/level.py              고객 수준: 첫 화면 목적 + 이번 질문 낱말 → 이번 턴 말하기 깊이 (LLM 없이)
v2/prompts/              역할별 지시문 <역할>_v<번호>.md
chat/                    대화 저장: 열기(get_for) · 지난 대화(recent) · 저장(save_turn, 번호표 rev)
agent/                   에이전트. 기능 service를 import하지 않는다
  llm.py                 LLM SDK 호출 한 곳: 팀 LLM · Jev · 임베딩 · 스텁(LLM_LIVE=false)
  gate.py                입구 관문: route → intent → 신뢰도 낮으면 Jev → Jev 실패면 되묻기
  route.py               코드 라우터: 기다리던 담당(waiting) · 프로젝트 유무 · 도배 · 목공 낱말이 있으면 범위 밖으로 끝내지 않기
  intent.py              직접 학습한 의도 분류 모델 추론: 문장 → (라벨, 신뢰도)
  schemas.py             의도 · 에이전트 입출력 Pydantic 모델
  trade_agent.py         공종 에이전트(뼈대, 후속 구현): 공정별 설정 + 검색으로 조건 · 주의점 · 근거 번호. 고객에게 말하지 않는다
  trades/                공정별 설정 dobae.py · mokgong.py(주의점 · 실측 변수 · 준비 · 공정 상담 지시문 이름). 견적 설명 · 공정표 역할도 읽는다
knowledge/               지식 검색(BM25 + 임베딩 RRF · 공정 범위 무게) · 추천 질문 고르기(suggest) · 지식 CSV 만들기(json_csv) · 적재
mcp_server.py            일정 MCP 예정 파일(현재 비어 있음)
```

**v3 AI 상담**: `chat/router.py`의 `POST /ai/turns` → `chat/service.py`(대화·프로젝트 확인, 짧은 세션) → `agent/v3/gate.py`(분류기·규칙, Jev 호출 없음) → `agent/v3/turn.py`(담당·카드·검색·출력 검사) → 저장·commit → `token`(완성된 문장)·`card`·`done` SSE 순으로 전달한다. **생성 중인 모델 토큰을 실시간 전송하는 방식은 아니다.** 기본 무료 모드이며 `LLM_LIVE=true`와 키가 함께 있어야 일부 답변만 LLM으로 다시 쓴다. 높은 점수 카드·정해진 글·계산 결과는 그대로 둘 수 있다([v3 AI 설계·현황](docs/v3/agents.md), [AI 협약](docs/agent-contract.md)).

- 기능 안 파일은 필요한 것만 둔다: `router.py`(HTTP), `service.py`(업무 흐름 · 상태 · commit), `repository.py`(DB), `schemas.py`, `models.py`, `client.py`(외부 API).
- 둘 이상이 실제로 쓰는 코드만 `shared/`에 하는 일 이름으로 둔다. 관리자 API는 각 기능 router에 `/admin/...`으로 둔다.

**호출 흐름**

- 화면 읽기: Server Component → `lib/api/<영역>.ts` → `lib/backend/server.ts`(`API_INTERNAL_URL`, 브라우저 쿠키를 넘김) → API.
- 화면 쓰기: 브라우저 → 같은 주소 `/api/*`(`lib/backend/client.ts`) → 개발은 Next, 운영은 Caddy가 API로 넘긴다. Server Action은 쓰지 않는다.
- API 안: `CatchAll`(처리 못 한 오류 → 같은 오류 모양) → `BodyLimit`(경로별 본문 한도) → Origin 확인 → `router` → `deps`(세션 · 권한) → `service` → `repository` → PostgreSQL. 오류는 모두 `{"error": {code, message, fields?}}`.
- v3 기한 일: 업무 service가 영속 `jobs` 행을 만들고 `worker.sweep_jobs`가 1분마다 DB에서 만기 일만 수거하여 `visit/quote/schedule`의 처리 함수를 실행한다. 상태·기한을 다시 검사하고 처리·건너뜀·재시도 결과를 저장한다. 자동 LLM 설명·외부 발송은 아직 연결되지 않았다.
- 화면 알림: 상태를 바꾸는 service가 같은 트랜잭션에 `notify.service.add`로 쓴다(`dedup_key`로 한 번만). 문자 · 메일 같은 바깥 발송만 `jobs` → worker로 보낸다.
- v2 대화: 브라우저 → `/api/v2/ask` → `v2.router` → `v2.ask_chat.start` → `chat.service.get_for` · `recent`(짧은 세션. 남의 대화 404, rev · waiting · 지난 대화) → `v2.ask.start` → 입구 관문(`gate.classify(message, waiting)`) → 공정 고르기(코드) · 첫 근거 검색(`knowledge.service`) → 오케스트레이터 역할 루프(LLM ↔ 도구: 서버 도구는 계산 엔진 · 지식 검색) → 출력 검사(`v2.guard`) · 인용 검사 · 추천 질문 고르기 → `v2.ask_chat`이 [되물음] 표시 판정 → `chat.service.save_turn`(새 대화면 이때 만들고, rev가 다르면 409) → 답 · `chat_id`.
- 화면 도구: 루프가 화면 도구를 부르면 턴을 Redis에 두고 `turn` · `tool_calls`로 응답 → 브라우저가 실행 → `/api/v2/ask/{turn}` → `v2.ask_chat.resume` → `v2.ask.take`(겹친 재개 · 틀린 결과 처리는 협약 8장) → 루프를 이어 간다.
- 일정: v2는 업체의 공사 날짜 제안·고객 수락·변경안 경로를 유지한다. v3는 실측 가능 기간과 반나절 확정, 기한 만료·공사 완료 자동 처리까지 구현했다. 여러 업체 연기 영향을 일정 MCP로 자동 재조정·재확정하는 것은 후속이다.
- 예 (기존 견적 받기 기능의 호출 형태):

  ```
  Wizard(브라우저) → client.ts POST /files → files.router → files.service(사진 위치 정보 지움) → storage · PostgreSQL
  Wizard → client.ts POST /projects → project.router(고객 권한 · 요청 제한) → project.service.create
         → files.service(파일 연결) → project.repository → commit
  → /projects/{id} 이동 → page.tsx → lib/api/project.ts getMyProject → server.ts → GET /projects/{id}
  ```

- 호출 흐름을 바꿨다면 이슈 본문 '호출 흐름'에 한 줄로 적는다. 예: `web → /api/projects → project.service → files.service → PostgreSQL`.

**층 규칙** (위는 아래를 부를 수 있고 반대는 안 된다. `|`끼리는 서로 import하지 않는다)

```
조립   main.py | worker.py | mcp_server.py
흐름   v2 → chat → schedule → visit → quote
대상   account | project | vendor
기반   files | refprice | jobs | knowledge | notify  → auth
도구   agent → calc
공통   shared → db | queue → config
```

- 다른 기능은 그 기능 service의 공개 함수로만 부른다. 다른 기능 models는 읽기 조인에만 쓰고, router끼리 import하지 않는다.
- 예외는 하나: `/me`가 업체 승인 상태를 읽으려고 `auth.service → vendor.repository`를 함수 안에서 늦게 import한다.
- `calc`는 DB · HTTP · 시계를 모르는 순수 함수다. 오늘 날짜는 인자로 받는다.
- `agent`는 기능 service를 import하지 않는다. 기능 데이터는 `v2/ask_tools.py`의 도구로 넘겨받는다. 믿집 일정 MCP를 구현하면 MCP 클라이언트로만 부른다.

## 3. 돈 · 날짜 · 상태

- 금액, 수량, 기간, 날짜는 계산 엔진(`calc`)만 만든다. 화면, 에이전트, 프롬프트에서 계산하지 않는다. 업체가 적은 줄 금액은 입력값이고 합계 · 부가세는 계산 엔진이 만든다.
- 금액은 원 단위 정수(`int`, DB `bigint`). 반올림은 계산 엔진 한 곳에서만 한다. 부가세는 따로 저장하고, 고객이 보는 금액은 부가세 포함으로 보여 주며 'VAT' 대신 '부가세'라고 쓴다. 공급가와 부가세를 나눠 보여 주는 곳은 견적서 합계 칸 하나다.
- 면적은 ㎡(`numeric(7,1)`)와 기준(공급 · 전용)을 함께 저장한다. 평은 표시할 때만 계산한다. 품은 0.5 단위로 올림한다.
- 날짜는 서울 기준 `date`, 시각은 `timestamptz`. 공휴일은 데이터로 둔다.
- 표준견적서 줄은 표준 행 키와 포함 상태 6종(포함 · 묶음 포함 · 따로 계산 · 선택 · 실측 후 · 안 함)으로 저장한다. 합계에는 '포함'과 '따로 계산'만 들어간다.
- 업체 실측 견적서는 줄로 바꾸지 않는다. 파일과 업체가 적은 칸을 버전으로 쌓고, 공급가 · 부가세 · 합계는 계산 엔진이 만든다. 고객이 확정한 버전은 바꾸지 않는다.
- 견적에는 만든 때의 산식 · 단가 버전을 고정한다. 가견적은 업체가 확인한 단가 묶음 버전을 고정한다. 기준 단가는 출처 · 적용일 · 버전과 함께 쌓고, 수집이 일부라도 실패하면 기존 값을 그대로 둔다.
- 상태는 기능별 service 한 곳에서만 바꾼다: 허용 전이 확인 → 조건부 UPDATE(1행이 아니면 409) → 같은 트랜잭션에 이력 행. 업체 확정 · 다시 고르기 · 공정표 확정 · 일정 변경 승인은 사람이 누른 요청으로만 일어난다.
- 현재 업체 날짜 제안은 `DateProposal.plan_version`에 기준 공정표 버전을 담고, 고객 날짜 수락은 `AcceptIn.seen_version`으로 화면이 본 최신 확정 버전을 확인한다. 버전 충돌·동시 수락·일정 겹침은 409로 막는다(`schedule.service`, `tests/test_final_plan.py`). **후속 일정 MCP**가 만드는 별도의 연기 승인 대기 건도 버전 검사를 적용하고, 같은 응답이 두 번 와도 알림은 한 번만 보내도록 한다.

## 4. 에이전트

**현행 v3**는 `agent/v3/`의 관문·가이드·공종·견적 설명·일정 및 복합 요청 조립을 쓴다. 단일 역할은 직접 답하고 복합은 코드 오케스트레이터가 조각을 합친다. 관문은 분류기+공종 낱말+규칙으로 결정하며 **Jev를 호출하지 않는다**. 무료 답(카드·검색·계산)이 기본이고 `LLM_LIVE`와 키가 있으면 허용된 답 조각만 재작성한 뒤 검사한다. 도배·목공은 계산도 가능하지만 다른 10공종은 지식 안내에 한정한다. 실제 구현은 [v3 협약 설명](docs/agent-contract.md)과 `agent/v3/turn.py`·`gate.py`를 우선한다.

**아래는 계속 실행되는 `/v2/ask` C안 규칙 및 후속 설계를 구분해 남긴다.** v3의 구현·완료 여부를 이 설명으로 판정하지 않는다.

- v2 C안에서는 고객과 말하는 LLM이 오케스트레이터 하나다. 역할 넷(가이드 · 공정 상담 · 견적 설명 · 공정표)을 바꿔 맡으며 역할별 지시문 · 도구 일부를 구현했다. 공종 에이전트 **하나**를 오케스트레이터의 하위 호출로 연결하는 것은 v2 후속 목표다.
- v2 구현: 가이드 · 공정 상담은 지시문 `chat_v4.md` 하나를 같이 쓰고, 관문 라벨에 맞는 역할 힌트를 붙인다. 공정 상담은 질문 낱말로 공정 하나가 분명하면 코드가 고른 그 공정 지시문(`trade_dobae_v1` · `trade_mokgong_v1`)과 공정 설정을 더하고, 그 공정 + 공통 자료를 먼저 찾는다. 자료 검색(`search_knowledge`)은 서버 도구다(`knowledge.service`). 추천 질문은 LLM 도구가 아니고 서버가 질문 은행에서 답할 수 있는 것만 고른다.
- 가이드 역할은 처음 고객의 궁금증 · 시작 순서 · 기본 정보 · 제출 서류를 답한다. 프로젝트 없이 동작하고 로그인한 고객만 쓴다. 일반 금액 · 기간은 말하지 않고 표준견적서로 안내한다. 복합 요청에서 오케스트레이터가 공종 하위 에이전트의 결과까지 합치는 흐름은 후속이다. 고객에게 되묻는 것은 오케스트레이터만 한다.
- v2 공종 하위 에이전트는 하나로 설계한다(후속). 공정별 설정(도배 · 목공)과 지식 검색으로 필요한 조건 · 주의점 · 근거 번호를 정한 스키마로 돌려주며 고객에게 직접 말하지 않는다. 오케스트레이터는 그 주의점을 바꾸지 않고 출처를 붙여 보여 준다. 공정 고르기는 LLM 없이 코드가 한다(질문 낱말 → 도배 · 목공, 둘 다면 둘 다). 브리프는 공정별로 나눠 낸다. v2 `trade_agent.py`는 실패를 반환하는 뼈대이고 하위 호출은 아직 없다.
- 현재 **일반 상담(`kind=chat`)이고 첨부 이미지가 없을 때만** `?` · `ㅠㅠ`처럼 낱말 없는 질문을 입구 관문 전에 고정 안내로 끝내며, LLM을 부르거나 대화 이력에 저장하지 않는다. 이 조건에서 낱말이 있을 때만 `gate.classify`를 거친다. 이미지 있는 채팅과 견적·공정표 설명 요청은 무문자 검사와 의도 분류를 모두 건너뛴다(PR #140).
- `set_home_info`의 거주 여부(`living`)는 **모델이 의미를 판단**한다. 서버는 모델이 근거로 제시한 `living_said`가 고객 발화에 실제 있는지만 확인하며, 짧은 네/아니요 답에는 바로 앞 AI 질문도 비교한다. 해당 근거는 모델 대화 이력에 남기되 고객 화면 도구 인자에서는 제거한다. 문구 존재 검사는 거주 의미의 진실성을 보증하지 않는다(PR #140).
- 공정별 설정(주의점 · 실측 변수 · 준비 사항 · 증상 → 공정 단어)은 한 곳에 두고 견적 설명 · 공정표 역할도 같이 읽는다.
- 견적 설명 역할은 계산 엔진이 만든 표준견적서 · 가견적 · 실측 견적서의 차이를 풀이만 한다. 화면에서 `/v2/ask`의 `quote_explanation` 종류로 질문할 수 있다. 견적 도착 뒤 worker가 자동으로 부르는 부분은 후속이다.
- 표준견적서와 확정 공정표는 에이전트가 아니다. 코드와 계산 엔진이 만든다. 공정표 역할은 말을 제약으로 바꾸고 결과를 설명한다. 공정 간 연기 영향 설명·일정 MCP 연결은 후속이며, 구현 시 MCP는 공정표 역할만 쓴다.
- 업체 추천은 에이전트가 아니다. 기존 `visit`의 업체 목록·가견적과 코드 정렬이 구현돼 있다. 조건 필터와 계산 점수로 3곳을 고르고 공종 에이전트 브리프로 선호를 반영하는 것은 팀의 후속 설계다.
- v2 입구 관문은 코드 라우터와 직접 학습한 의도 분류 모델이다. 신뢰도가 낮으면 Jev로 한 번 판단한다. Jev 실패 시 `classify`가 `None`을 반환하며, v2에서 선택지로 되묻는 완성 흐름은 후속(#123)이다. Jev 신뢰도로는 되묻지 않는다(#70). 범위 밖 요청은 LLM 없이 안내한다.
- 코드 라우터는 세 가지를 본다. 앞의 둘은 먼저, 셋째는 분류가 끝난 뒤에 본다. 역할이 고객 답을 기다리는 대화(waiting)면 다른 의도가 확실할 때만 역할을 옮긴다. 견적 설명 · 일정인데 프로젝트가 없으면 오케스트레이터로 보낸다. v2 상담은 프로젝트 대신 화면이 보낸 견적 · 공정표 정보를 서버가 다시 계산하므로 이 규칙을 쓰지 않는다(`gate.classify(message, waiting)`만 부른다). 셋째: 분류 결과(Jev 포함)가 범위 밖이어도 문장에 도배 · 목공 낱말(`agent/trades`의 `symptom_words`, 일상어 '실크' · '낙서' · '테두리'는 뺌)이 있으면 고정 안내로 끝내지 않고 공정 상담으로 보낸다(#147).
- waiting: 오케스트레이터가 고객에게 되물어 답을 기다릴 때만 답 끝에 `[되물음]` 표시를 붙인다(`chat_v4.md`). `v2.ask_chat`이 표시를 떼고 그 턴의 관문 라벨(없으면 `orchestrator`)을 waiting에 남긴다. 답이 표시로 끝나지 않거나 출력 검사가 문장을 뺐으면 비운다. 다음 턴에 기다리던 역할을 이어 받으면(출처 `rule`) 신뢰도와 상관없이 그 역할 힌트를 붙인다.
- 의도는 공정 이름이 아니라 맡을 역할로 나눈다: 오케스트레이터(가이드) · 공종(공정 상담) · 견적 설명 · 일정(공정표) · 범위 밖. 안내(처음 궁금증 · 시작 순서 · 용어)와 여러 일이 섞인 요청은 '오케스트레이터'로 묶는다. 예: "목공 견적이 왜 비싸요?"는 견적 설명이다.
- 의도 라벨이 곧 역할이다. 범위 밖은 LLM 없이 고정 안내하고 일반 대화에는 저장하지 않는다(#128·PR #129). 화면 버튼은 입구 관문 없이 해당 역할을 지정할 수 있다. worker의 자동 설명 호출은 후속이다.
- LLM SDK 호출은 `app/agent/llm.py` 한 곳에서만 한다. v2의 Jev는 입구 분류에만 쓰고 답변 글을 쓰지 않으며, Jev로 보내는 문장의 전화번호 · 동호수는 가린다. v3 관문에서는 Jev를 호출하지 않는다.
- v2 대화 LLM은 `/v2/ask`에서 돌린다. 대화 상태는 턴 시작에 짧은 DB 세션으로 복원하고, LLM을 기다리는 동안 세션을 쥐지 않는다. 화면 도구 결과를 기다리는 턴은 Redis에 잠깐 두고(지워져도 되는 값), 저장은 턴의 마지막 요청에서 새 세션으로 한 번 한다. v2 답은 commit 뒤 JSON으로 보낸다. **v3 `/ai/turns`는 commit 뒤 완성된 답을 SSE 문장·카드·완료 이벤트로 나눠 보낸다.** 견적 도착 뒤 worker의 자동 AI 설명은 후속이다.
- 같은 대화의 동시 요청은 번호표(`rev`)로 막는다. 열 때 본 `rev`가 저장할 때 그대로일 때만 조건부 UPDATE로 1 올리고, 아니면 아무것도 쓰지 않고 409다. 만료 시각으로 잠그지 않는다(한 질문이 요청 여러 번에 걸치고 화면이 중간에 버릴 수 있어서). DB 락을 쥔 채 LLM을 기다리지 않는다.
- rev는 같은 대화의 다른 질문끼리, Redis 턴은 같은 질문의 화면 도구 재개끼리 겹침을 막는다. 자세한 구분은 협약 8장.
- 프로젝트 정보처럼 항상 필요한 입력은 코드가 먼저 읽어 에이전트에 넘긴다.
- 현재 구현한 상한: `v2/ask.py`의 도구 **라운드 최대 4회**(`MAX_TOOL_ROUNDS`), 한 턴 LLM 호출 최대 6회(`MAX_CALLS`), 시간당 상담 요청 60회(`ASK_PER_HOUR`, 로컬 환경 예외). 턴당 공종 하위 호출 3회와 사용자별 일일 토큰 제한은 팀이 정한 후속 목표이며 아직 구현되지 않았다.
- 에이전트는 DB에 쓰지 않고 확정 · 저장 권한이 없다. 후속 일정 MCP의 `request_schedule_change`만 공정표를 바꾸지 않는 승인 대기 건을 저장하도록 설계한다. 슬롯과 일정 변경은 고객이 누른 요청으로 반영한다. 출력은 Pydantic 스키마로 검사하고, 숫자는 계산 엔진 결과와 맞지 않으면 버린다. 대화는 문장 단위로 숫자를 검사한 뒤 보낸다.
- 사용자와 `project_id`는 서버가 세션으로 고정하고 LLM 출력으로 받지 않는다. 업체가 쓴 글은 지시문에 넣지 않고 데이터로만 넘긴다.
- 믿집 MCP는 일정 MCP 하나를 직접 만들고 외부 MCP 서버는 쓰지 않는다는 설계다. 지금 `mcp_server.py`는 빈 파일이고 일정 도구 호출도 없다. 시방서 검색은 현재 `knowledge.service` 함수로 둔다.
- 계획한 일정 MCP 도구는 `get_schedule`, `list_schedule_alerts`, `preview_schedule_change`, `request_schedule_change`, `draft_schedule_notice`이고, 로그인 필수 · 본인 프로젝트만이다. 공정표 반영 · 확정 · 알림 발송 · 고객 견적 · 브리프 원문은 넣지 않는다.
- LLM이 실패하면 계산 결과만 보여 주고 "설명을 만들지 못했어요"라고 알린다. 규칙으로 만든 가짜 설명으로 채우지 않는다.
- 상담 도구 `price_reference`는 고객 평형·선택 도면이 모두 없으면 금액·기간을 계산하지 않고 평형을 묻도록 안내한다. 별도 `POST /v2/quote` 계산 API는 평형 미입력 시 기존 32평 기본값을 사용할 수 있으므로 둘을 혼동하지 않는다(PR #140).
- 프롬프트는 버전을 붙이고, 바꾸는 PR은 커밋 type `prompt`로 하고 eval 결과를 붙인다. 팀이 정한 평가 목표(공정표 15 · 의도 분류 200 · RAG 30 · 공종 10 · 오케스트레이터 30 · 가이드 50 · 견적 설명 문제 행 시나리오)는 구현과 검증을 거쳐 확정한다. 지금 있는 세트: `evaluation/rag`(검색 90 · 300) · `evaluation/answer`(답 품질 30) · `evaluation/trade`(공정 고르기 · 공정별 답 9 + 9) · `evaluation/ask_back`(되물음) · `evaluation/intent`.
- eval 데이터의 팀 분할 원칙은 **dev : held-out = 2:1**이다. 이 비율은 위 평가 목표 문항 수와 별개이며 실제 세트 구성·점수는 각 평가 기록에서 확인한다.
- CI에서 유료 호출은 0회다(`LLM_LIVE=false` 스텁). 스텁 통과를 에이전트 품질 확인으로 말하지 않는다.

## 5. 코드 작성

**고치는 범위**

- 요청한 것만 고친다. 고칠 파일은 꼭 필요한 것만 고르고, 요청 범위 밖의 리팩터링 · 파일 이동 · 이름 바꾸기 · 일괄 포맷을 하지 않는다.
- 작업하다 보인 다른 문제는 고치지 않고 이슈로 남긴다. 기존 코드를 이 문서에 맞추려고 한꺼번에 고치지 않는다.
- interface · base class · factory는 실제 구현이 둘 이상이거나 외부 경계일 때만 만든다.
- 새 의존성이나 외부 서비스는 추가하기 전에 이슈로 알린다.

**backend**

- 트랜잭션 안에서 외부 API · LLM을 부르지 않는다. 사진 처리 같은 느린 일은 DB를 쓰기 전에 끝내고, 디스크에 쓴 파일은 DB 저장이 실패하면 지운다.
- 이벤트 루프를 막는 일(비밀번호 해시, 그림 처리, 파일 쓰기)은 작업 스레드로 넘긴다.
- 같은 요청이 동시에 두 번 와도 500이 되지 않게: 고유성은 DB 제약으로 지키고 IntegrityError는 409로 바꾼다.
- 스키마는 Alembic migration으로만 바꾼다. autogenerate 결과는 읽고 고친 뒤 커밋하고(CHECK는 손으로 더함), 이미 적용된 migration은 고치지 않고 새 revision을 더한다.
- 고유성 · 참조 · 값 범위는 DB 제약(UNIQUE, FK, CHECK)으로도 지킨다. JSONB는 통째로 남기는 기록에만 쓴다.
- 로그 · 오류 메시지에 입력값과 개인정보를 넣지 않는다.

**frontend**

- Server Component가 기본이고, `"use client"`는 상호작용이 필요한 곳에만 붙인다.
- API를 바꿨으면 `pnpm gen:api`로 `lib/backend/schema.d.ts`를 다시 만든다.
- 색 · 글자 크기는 `globals.css` 토큰만 쓴다. `globals.css`에는 토큰과 여러 화면이 같이 쓰는 공용 클래스(`mj-` 접두어)만 두고, 한 화면 · 컴포넌트에만 쓰는 스타일은 그 옆 `*.module.css`에 둔다.
- 화면 문구는 '-해요'체로 쓰고 영어 상태값을 보이지 않는다.

## 6. Git · 이슈 · PR

- 팀 저장소(upstream)를 fork한 내 저장소(origin)에서 작업한다.
- 기능 개발 기준과 기능 PR 대상은 팀 `dev`다. `dev`에서 통합·검증하고 `main`은 검증한 배포 버전을 보관한다. 현재 GitHub 기본 브랜치는 `dev`다(2026-11-18 확인). 일상 절차는 [팀 기여 가이드](CONTRIBUTING.md)를 따른다. 과거 전환 절차는 [보존 기록](docs/archive/2026-11-dev-main-transition.md)에 있다.
- 순서: 이슈 생성 → 최신 `dev`에서 작업 브랜치 생성 → 구현·검증·이슈 본문 작성 → 작성자 본인이 최신 dev로 rebase → 이슈를 연결한 dev PR → CI · 승인 1명 · squash 병합 → 이슈 종료.
- 로컬·CI에서 검증한 뒤 공식 저장소 `dev` → `main` 승격 PR을 만들고 merge commit으로 병합한다. 포함한 작업 PR과 배포 영향을 명시한다. `main` Push CI 성공 → 해당 main 커밋의 AWS 자동배포 → 서버 상태 확인 순서다.
- dev 병합은 AWS에 배포하지 않는다. 서버에서 발견한 문제도 작업 이슈·dev 대상 수정 PR로 처리한 뒤 main으로 승격한다. 별도 운영 환경(`prod`)은 아직 없다.
- 타인의 PR에 동기화 merge 커밋을 임의로 넣지 않는다. 다른 목적의 수정은 별도 이슈·PR로 나누고, 병합 전 최종 작성자와 squash 메시지의 공동 작성자 줄을 확인한다.
- 브랜치: `작업유형-기능이름`. 영어 소문자를 하이픈으로 잇는다. 예: `feat-vendor-signup`, `fix-login-error`. 작업유형은 커밋 type과 같다.
- 커밋 제목: `type: 한국어 요약`. type은 `feat · fix · docs · test · chore · refactor · prompt · eval`.
- 이슈 제목도 커밋 제목 형식으로 쓴다. 기능 PR 제목은 이슈 제목과 같고, squash 병합 때 그대로 dev의 커밋 제목이 된다.
- 이슈 본문(작업이 끝난 뒤): 개요 / 호출 흐름(바뀐 경우) / 검증 결과(실제로 돌린 것만 `[x]`) / 못 한 것. [이슈 템플릿](.github/ISSUE_TEMPLATE/task.md)을 참고한다.
- PR 본문: 바뀐 것만 짧은 목록으로 적고 관련 이슈와 바뀐 문서를 연결한다. 실제 테스트 결과는 이슈 본문에 남긴다([PR 템플릿](.github/pull_request_template.md)).
- PR 올리기 전에 최신화하고 rebase한다:

  ```bash
  git fetch upstream
  git switch dev && git merge --ff-only upstream/dev && git push origin dev
  git switch <브랜치> && git rebase dev && git push --force-with-lease origin <브랜치>
  ```

- PR 크기 제한은 두지 않는다. 한 PR에 기능 여러 개를 담을 때는 커밋을 기능 하나 단위로 나눈다.
- 충돌을 줄이고 풀 때:
  - 공용 목록(`backend/app/main.py`의 `ROUTERS`, `backend/migrations/env.py`의 models import)은 한 줄에 하나씩 이름 순으로 더한다.
  - lock 파일(`uv.lock` · `pnpm-lock.yaml`)과 `schema.d.ts`가 충돌하면 손으로 고치지 않는다. dev 쪽을 받고 `uv lock` · `pnpm install` · `pnpm gen:api`로 다시 만든다.
  - rebase 뒤 migration head가 둘이면(CI가 잡는다) 내 revision의 번호와 `down_revision`을 dev의 최신 head 다음으로 바꾼다.
- 커밋 · PR에 `Co-Authored-By` 같은 공동 작성자 줄이나 도구 홍보 문구를 넣지 않는다.
- 이슈 · PR · 커밋 · 문서 · 코드 주석은 한국어로 짧게 쓴다. 바뀐 것만 적고 과정 설명은 쓰지 않는다. 브랜치와 코드 이름은 영어로 쓴다.
- `.env`는 커밋하지 않는다. 새 환경변수는 `.env.example`에 한국어 주석과 함께 더한다.
- AI 코딩 도구는 사람이 요청했을 때만 커밋 · 푸시한다.

## 7. 검증과 완료

- CI(`.github/workflows/ci.yml`)가 PR마다 저장소 점검(`.github/scripts/check_repo.py`), backend(ruff, migration head 하나, 실제 DB로 pytest), frontend(API 타입 비교, typecheck · lint · build)를 돌린다.
- 로컬에서는 바꾼 범위만 확인한다.
  - backend: `uv run pytest <대상>`, `uv run ruff check`, `uv run ruff format --check`
  - frontend: `pnpm typecheck`, `pnpm lint`. API를 바꿨으면 `pnpm gen:api`
  - migration: `docker compose run --rm migrate`로 실제 DB에 올리고 `alembic check`로 모델과 차이가 없는지 본다
  - compose · Dockerfile: `docker compose config --quiet`
  - 저장소 점검: `python .github/scripts/check_repo.py`
  - 화면: 폰 너비 360px에서 가로 스크롤이 없고, 버튼 · 입력 칸이 40px 이상인지 본다
- 반드시 테스트할 것:
  - 계산 엔진
  - 상태 변경과 동시 요청(409)
  - 권한: 남의 것은 404, 역할이 다르면 403
  - 입력 한도: 본문 크기, 파일 형식 · 크기
  - 파일 처리: 사진의 위치 정보가 지워졌는지
- 테스트를 지우거나 건너뛰게 하거나 실패를 통과로 바꾸지 않는다.
- 완료는 최신 커밋의 필수 CI가 모두 통과했을 때만 말한다. CI를 못 보면 '검증 대기'라고 한다.
- 보고는 세 가지로 나눈다:
  - 로컬에서 돌린 명령과 결과
  - CI에 맡긴 것
  - 못 한 것과 그 이유
- `docker compose down -v`(DB 볼륨 삭제)는 팀원 본인이 결정한다. AI 도구가 대신 실행하지 않는다.
