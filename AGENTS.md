# 믿집 작업 지침

사람과 AI 코딩 도구가 함께 지키는 규칙이다. 구조 · 흐름 · 검증처럼 꼭 지켜야 하는 것만 둔다. 실행 방법은 README에 있고, 설계 근거는 `docs/design/`, 되돌리기 어려운 결정은 `docs/adr/`에 쌓는다.

- 우선순위: 팀이 정한 결정(`docs/adr/`) > 이 문서 > 개인 습관. 서로 부딪히면 고치기 전에 묻는다.

## 1. 제품 흐름과 이름

- 1차 범위는 아파트 도배 · 목공이다. 흐름(요구사항 v3.2): 집 정보 · 공정 고르기 → 예상 공정표 · 표준견적서 → 업체 추천 → 가견적 요청 → 업체가 가견적서 제출 → 실측 요청 → 업체가 실측 견적서 제출 → 확정 또는 다시 고르기 → 확정 업체가 공사기간 등록 → 확정 공정표.
- 가견적서와 실측 견적서는 업체가 써서 낸다. 믿집은 공공 기준으로 계산한 표준견적서만 비교 기준으로 보여 준다 (ADR 0002).
- 업체는 기본 회원정보 + 사업자등록증으로 가입하고, 관리자가 승인해야 업체 기능을 쓴다.
- 범위 밖(바닥 · 욕실 · 전기 공정, 전자계약, 결제)은 이슈로만 남기고 코드에 자리를 미리 만들지 않는다.
- 화면과 코드에서 아래 이름만 쓴다.

| 화면 말 | 코드 이름 | 뜻 |
| --- | --- | --- |
| 표준견적서 | `standard_quote` | 공공 기준 단가로 믿집이 계산한 참고 금액. 업체 견적이 아니다 |
| 가견적 | `quote.kind = estimate` | 실측 전, 업체가 표준 행 양식에 써서 낸 견적 (FFV-03) |
| 실측 견적 | `quote.kind = final` | 업체가 실측하고 써서 낸 견적 (FFV-05) |
| 실측 | `visit` | 업체 방문 측정. 요청 → 확정 → 방문 → 견적 도착 |
| 공정표 | `schedule` | 반나절 단위 작업 순서와 날짜 |
| 기준 단가 | `ref_price` | 표준시장단가 · 시중노임단가 · 조달청 가격 등 공공 기준값 |
| 품 | `man_day` | 기능공 1명 1일 작업량 |
| 공급면적 / 전용면적 | `area_basis = supply / exclusive` | 평형(분양) / 실제 쓰는 면적 |
| 도배 유형: 저가형 / 기본형 | `grade = economy / basic` | 고객이 고르는 도배 등급 |

## 2. 구조와 호출 흐름

하나의 FastAPI 앱을 기능별 패키지로 나눈 모듈러 모놀리스다. 지금은 초기 설정(뼈대)만 있고, 기능은 이슈 단위로 아래 자리에 더한다.

| 부분 | 하는 일 |
| --- | --- |
| `frontend/` (Next.js) | 화면만. DB 접근 · LLM 호출 · 금액 계산을 하지 않는다 |
| `backend/app/` (FastAPI) | 유일한 공개 API. 기능 패키지 + 계산 엔진 `calc` + 에이전트 `agent` |
| `backend/app/worker.py` (arq) | LLM · 기준 단가 수집 · 알림 같은 느린 일 |
| PostgreSQL 17 | 원본 데이터. Redis는 큐 · 요청 제한 · 짧은 캐시만 (지워져도 되는 것) |
| Cloudflare (운영) | DNS · 사용자 쪽 HTTPS · 방화벽. EC2 앞단 |
| Caddy (운영) | 서버 쪽 HTTPS, `/api/*` → API, 나머지 → web |

**프런트 구조** (`frontend/`)

```
app/<경로>/page.tsx      화면(라우트). 권한은 lib/session.ts의 requireRole로 확인
app/globals.css          디자인 토큰과 여러 화면이 같이 쓰는 공용 클래스. 옮겨 온 화면 전용 클래스가 아직 남아 있어서, 그 화면을 고칠 때 module.css로 옮긴다
components/<영역>/        화면 조각. 영역: site · start · project · vendors · my · auth · admin · ui
                         한 컴포넌트에만 쓰는 스타일은 옆에 <이름>.module.css로 둔다
lib/backend/server.ts    Server Component → FastAPI. 쿠키를 넘기고 읽기만 한다
lib/backend/client.ts    브라우저 → /api/*. 쓰기와 오류(ApiError)
lib/backend/schema.d.ts  API 타입. pnpm gen:api로 만들고 손으로 고치지 않는다
lib/api/<영역>.ts         서버 쪽 읽기의 입구. 영역마다 한 파일: project · vendor · quote · visit · schedule · admin
lib/mock/                예시 데이터. API가 생기면 lib/api/<영역>.ts 안에서만 바꾼다
lib/session.ts           로그인한 사람(GET /me)
lib/format.ts · labels.ts · trade-status.ts · types.ts   표시 형식 · 화면 말 · 공정 상태 · 타입
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
migrations/              Alembic. 0001(빈 시작점) → 0006
아직 없음: quote · visit · schedule · refprice · jobs · calc · agent
```

- 기능 안 파일은 필요한 것만 둔다: `router.py`(HTTP), `service.py`(업무 흐름 · 상태 · commit), `repository.py`(DB), `schemas.py`, `models.py`, `client.py`(외부 API).
- 둘 이상이 실제로 쓰는 코드만 `shared/`에 하는 일 이름으로 둔다. 관리자 API는 각 기능 router에 `/admin/...`으로 둔다.

**호출 흐름**

- 화면 읽기: Server Component → `lib/api/<영역>.ts` → `lib/backend/server.ts`(`API_INTERNAL_URL`, 브라우저 쿠키를 넘김) → API.
- 화면 쓰기: 브라우저 → 같은 주소 `/api/*`(`lib/backend/client.ts`) → 개발은 Next, 운영은 Caddy가 API로 넘긴다. Server Action은 쓰지 않는다.
- API 안: `CatchAll`(처리 못 한 오류 → 같은 오류 모양) → `BodyLimit`(경로별 본문 한도) → Origin 확인 → `router` → `deps`(세션 · 권한) → `service` → `repository` → PostgreSQL. 오류는 모두 `{"error": {code, message, fields?}}`.
- 느린 일: service가 같은 트랜잭션에 `jobs` 행을 남기고 commit 뒤 큐에 넣는다 → worker → `agent` · 외부 API → 결과 저장은 해당 기능 service.
- 예 (견적 받기, 기능이 생긴 뒤):

  ```
  Wizard(브라우저) → client.ts POST /files → files.router → files.service(사진 위치 정보 지움) → storage · PostgreSQL
  Wizard → client.ts POST /projects → project.router(고객 권한 · 요청 제한) → project.service.create
         → files.service(파일 연결) → project.repository → commit
  → /projects/{id} 이동 → page.tsx → lib/api/project.ts getMyProject → server.ts → GET /projects/{id}
  ```

- 호출 흐름을 바꿨다면 이슈 본문 '호출 흐름'에 한 줄로 적는다. 예: `web → /api/projects → project.service → files.service → PostgreSQL`.

**층 규칙** (위는 아래를 부를 수 있고 반대는 안 된다. `|`끼리는 서로 import하지 않는다)

```
조립   main.py | worker.py
흐름   schedule → visit → quote
대상   account | project | vendor
기반   files | refprice | jobs  → auth
도구   agent → calc
공통   shared → db | queue → config
```

- 다른 기능은 그 기능 service의 공개 함수로만 부른다. 다른 기능 models는 읽기 조인에만 쓰고, router끼리 import하지 않는다.
- 예외는 하나: `/me`가 업체 승인 상태를 읽으려고 `auth.service → vendor.repository`를 함수 안에서 늦게 import한다.
- `calc`는 DB · HTTP · 시계를 모르는 순수 함수다. 오늘 날짜는 인자로 받는다.

## 3. 돈 · 날짜 · 상태

- 금액, 수량, 기간, 날짜는 계산 엔진(`calc`)만 만든다. 화면, 에이전트, 프롬프트에서 계산하지 않는다. 업체가 적은 줄 금액은 입력값이고 합계 · 부가세는 계산 엔진이 만든다.
- 금액은 원 단위 정수(`int`, DB `bigint`). 반올림은 계산 엔진 한 곳에서만 한다. 부가세는 따로 저장하고 화면에 'VAT 별도/포함'을 붙인다.
- 면적은 ㎡(`numeric(7,1)`)와 기준(공급 · 전용)을 함께 저장한다. 평은 표시할 때만 계산한다. 품은 0.5 단위로 올림한다.
- 날짜는 서울 기준 `date`, 시각은 `timestamptz`. 공휴일은 데이터로 둔다.
- 견적 줄은 표준 행 키와 포함 상태 6종(포함 · 묶음 포함 · 따로 계산 · 선택 · 실측 후 · 안 함)으로 저장한다. 합계에는 '포함'과 '따로 계산'만 들어간다.
- 견적에는 만든 때의 산식 · 단가 버전을 고정한다. 기준 단가는 출처 · 적용일 · 버전과 함께 쌓고, 수집이 일부라도 실패하면 기존 값을 그대로 둔다.
- 상태는 기능별 service 한 곳에서만 바꾼다: 허용 전이 확인 → 조건부 UPDATE(1행이 아니면 409) → 같은 트랜잭션에 이력 행. 업체 확정 · 다시 고르기 · 공정표 확정은 사람이 누른 요청으로만 일어난다.

## 4. 에이전트

- 에이전트는 예상 공정표(FAG-01), 업체 추천(FAG-02), 확정 공정표(FAG-03) 셋이다. 네 번째는 ADR로 정한 뒤에 만든다.
- LLM SDK 호출은 `app/agent/llm.py` 한 곳에서만 한다. 공급자는 ADR로 정한 하나만 쓴다.
- 에이전트는 DB에 쓰지 않고 확정 · 저장 권한이 없다. 출력은 Pydantic 스키마로 검사하고, 숫자는 계산 엔진 결과와 맞지 않으면 버린다. 업체 추천은 후보 목록 밖의 id를 버린다.
- LLM이 실패하면 계산 결과만 보여 주고 "설명을 만들지 못했어요"라고 알린다. 규칙으로 만든 가짜 설명으로 채우지 않는다.
- 프롬프트는 버전을 붙이고, 바꾸는 PR은 커밋 type `prompt`로 하고 eval 결과를 붙인다. eval 세트(추천 20 · 공정표 15)는 `evaluation/`에 두고 dev와 held-out을 2:1로 나눈다.
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
- 순서: 이슈를 제목만 써서 만든다 → 브랜치에서 작업한다 → 끝나면 이슈 본문을 쓴다 → 최신화하고 rebase한다 → PR → 승인 1명 · squash 병합 → 이슈를 닫는다.
- 브랜치: `작업유형-기능이름`. 영어 소문자를 하이픈으로 잇는다. 예: `feat-vendor-signup`, `fix-login-error`. 작업유형은 커밋 type과 같다.
- 커밋 제목: `type: 한국어 요약`. type은 `feat · fix · docs · test · chore · refactor · prompt · eval`.
- 이슈 제목도 커밋 제목 형식으로 쓴다. PR 제목은 이슈 제목과 같고, squash 병합 때 그대로 main의 커밋 제목이 된다.
- 이슈 본문(작업이 끝난 뒤): 무엇을 왜 / 호출 흐름(바뀐 경우) / 검증 결과(실제로 돌린 것만 `[x]`) / 못 한 것.
- PR 본문: 바뀐 것만 짧은 목록으로 적는다.
- PR 올리기 전에 최신화하고 rebase한다:

  ```bash
  git fetch upstream
  git switch main && git merge --ff-only upstream/main && git push origin main
  git switch <브랜치> && git rebase main && git push --force-with-lease origin <브랜치>
  ```

- PR은 400줄 이하(lock · 생성 파일 제외).
- 충돌을 줄이고 풀 때:
  - 공용 목록(`backend/app/main.py`의 `ROUTERS`, `backend/migrations/env.py`의 models import)은 한 줄에 하나씩 이름 순으로 더한다.
  - lock 파일(`uv.lock` · `pnpm-lock.yaml`)과 `schema.d.ts`가 충돌하면 손으로 고치지 않는다. main 쪽을 받고 `uv lock` · `pnpm install` · `pnpm gen:api`로 다시 만든다.
  - rebase 뒤 migration head가 둘이면(CI가 잡는다) 내 revision의 번호와 `down_revision`을 main의 최신 head 다음으로 바꾼다.
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
- 되돌리기 어려운 결정은 `docs/adr/`에, 진행 현황은 `docs/status.md` 하나에만 적는다.
