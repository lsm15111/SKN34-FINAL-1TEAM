# 믿집 mvp 얹기 변경 기록

- 작업 폴더: `C:\Workspace\SKN34\SKN34-FINAL-1TEAM-mvp` (worktree), 브랜치 `feat-mvp-layer` (팀 `upstream/dev` 98b8032에서)
- 원칙: 팀 파일은 고치지 않고 새 파일만 더한다. 금액 · 수량은 `calc`, 단가 · 출처는 `refprice`에 둔다
- 검증 방법: 손으로 검산한 pytest + MVP JS(v10)와 같은 입력을 넣어 줄 · 합계 · 문구까지 대조
- 커밋 · 푸시: 아직 안 함
- 로컬 확인: `ruff check` · `ruff format --check` 통과, 계산 테스트 50개 통과(DB 없이), JS 대조 3종 다른 값 0, DB 없이 API 점검 통과, `pnpm typecheck` · `lint` · `build` 통과, 화면 점검(360px 포함)
- 못 한 것: DB를 쓰는 API 테스트(`tests/test_mvp.py`)는 로컬 DB에 pgvector가 없어 못 돌림 → CI에 맡김

## 진행 표

| 순서 | 파일 | 하는 일 | 상태 | JS 대조 |
| --- | --- | --- | --- | --- |
| 1 | `calc/plan_qty.py` | 도면 공간 → 벽 · 천장 면적, 롤 수, 몰딩 · 걸레받이, 방문, 창 폭 | 끝 | 120가지, 다른 값 0 (0.1 반올림 차이만) |
| 2 | `refprice/mvp_materials.py` | 목공 자재 21개 · 정해진 단가 18개 · 등급별 처음 자재 | 끝 | 1번 대조에 포함 |
| 3 | `calc/mvp_mokgong.py` | 고른 자재 + 정해진 단가로 목공 금액 · 기간 | 끝 | 1,280가지, 다른 값 0 |
| 4 | `calc/mvp_common.py` · `calc/mvp_dobae.py` | 공통 줄 모양 · 공공 기준 도배 + 도면 면적 | 끝 | 576가지, 다른 값 0 (철거 줄 풀이 문구만 바꿈) · 팀 도배와 금액 같음 |
| 5 | `refprice/mvp_market.py` · `calc/market_band.py` | 시장 기준 금액 · 범위, 공공 → 시장 차이 단계, 추가 항목 범위 | 끝 | 1,444가지, 다른 값 0 |
| 6 | `refprice/mvp_plans.*` · `mvp/` API · `main.py` 한 줄 · `schema.d.ts` | 예시 평면도 20곳, API 4개 | 끝 (DB 테스트는 CI) | DB 없이 API 점검 통과, 미리 보기 도배 = 팀 표준견적서 |
| 7 | `/projects/[id]/mvp` 화면 | 평면도 고르기 · 등급 · 목공 자재 · 다시 계산한 견적 · 시장 범위 | 끝 | 가짜 로그인 API로 화면 점검, 360px 가로 스크롤 없음 · 버튼 40px 이상 |

## 파일별 변경 사항

### 1. `calc/plan_qty.py` (새 파일) · `tests/test_calc_plan_qty.py`

- MVP `CALC9.fromPlan`을 옮겼어요. 입력은 공간 치수(mm), 결과는 공간별 · 합계 수량
- 가정값(문 0.9 × 2.1m, 남는 양 10%, 롤 규격 등)은 `PlanRules`에 버전과 함께 모음
- MVP와 다른 점
  - 반올림을 팀 `m2`(정확한 반올림)로 해서, 딱 반(예: 10.05)인 값은 JS보다 0.1 높게 나와요. JS는 부동소수 오차로 내림
  - 잘못된 입력(음수 치수, 천장 높이 0)은 오류로 막아요
  - `windows_m`(벽지 바르는 공간의 창 폭 합) 추가: 목공 커튼박스 길이에 씀. MVP는 화면 쪽에서 따로 더했음
- 평형으로 어림하는 값(est)은 옮기지 않았어요. 평형 어림은 팀 견적 계산이 맡아요

### 2. `refprice/mvp_materials.py` (새 파일)

- MVP `v10/mok10.js`의 `MOK10` 값을 스크립트로 그대로 옮김(값 · 출처 문구 오타 방지)
  - 자재 21개: 이름은 MVP 자재 데이터의 브랜드 + 이름
  - 정해진 단가: 문 설치 · 문짝 설치 · 덧방 문틀 · 문선 · 손잡이 · 슬라이딩 · 히든 · 몰딩 · 걸레받이, 무몰딩 · 히든 배수
  - 정해진 단가 항목 18개: 오늘 웹 조사로 채운 값과 근거 문구 포함
  - 등급별 처음 자재(`economy · basic · premium`)
- 시공 품 · 하루 목수 수는 팀 `refprice/book.py`의 `MOKGONG_2026H2`를 같이 씀(새로 만들지 않음)

### 3. `calc/mvp_mokgong.py` (새 파일) · `tests/test_calc_mvp_mokgong.py`

- MVP `CALC10.mokgong`을 옮김. 결과는 팀 `Quote` 모양(줄 · 공급가 · 부가세 · 합계 · 품 · 공정 단계 · 기간 · 가정)
- 줄은 팀 `Line`을 넓힌 `MvpLine`
  - `price_basis`: 공공 · 실견적 · 고른 자재 · 팀 가정값 · 업체 확인 다섯 가지
  - `calc`: 수량 풀이 문구
  - 팀 `basis`는 세 가지뿐이라 공공이 아닌 값은 `assumed`로 넣음
- 고른 것(`MokSel`): 문(작업 방식 · 자재 · 개수), 슬라이딩 · 히든도어, 몰딩 종류 · 자재, 걸레받이 자재, 정해진 단가 항목(자동 수량 또는 넣은 수량)
- 도면(`PlanQty`)이 있으면 몰딩 · 걸레받이 길이, 천장 넓이, 창 폭, 방문 수를 도면에서 읽음
- MVP와 다른 점
  - MVP는 화면이 천장 넓이 · 창 폭을 계산해서 넘겼는데, 이제 계산 엔진이 도면 수량에서 직접 읽어요
  - 잘못 고른 자재(문틀 교체에 문짝 자재, 몰딩 종류와 자재가 다름, 없는 항목)는 오류로 막아요. MVP는 화면이 막았음
  - 방문 작업을 골랐는데 문이 0개면 '기존 방문 · 문틀 철거' 줄을 넣지 않아요
- `default_sel(grade)` · `default_door_pick(grade, mode)`: 등급별 처음 고른 값

### 4. `calc/mvp_common.py` · `calc/mvp_dobae.py` (새 파일) · `tests/test_calc_mvp_dobae.py`

- `mvp_common.py`: MVP 계산 셋이 같이 쓰는 것(`MvpLine` · `PriceBasis` · `Grade` · 숫자 글 `num`). 목공 파일에 있던 것을 옮김
- `mvp_dobae.py`: MVP `CALC.dobae`(팀 도배 계산 + v9 도면 면적)를 옮김
  - 단가 · 가정값은 팀 `DOBAE_2026H2` 그대로
  - 도면이 없으면 팀 `dobae.quote`와 줄 · 금액 · 품 · 기간이 같아요(테스트로 확인)
  - 도면이 있으면 벽 · 천장 면적을 도면에서 읽고, 발코니 확장 가산(1.08)은 쓰지 않아요(도면에 이미 들어 있음)
  - 줄마다 수량 풀이(`calc`)를 붙임
- MVP와 다른 점
  - 프리미엄 등급을 받으면 실크(basic) 단가로 계산. MVP는 화면이 등급을 바꿔 넘겼음. 실제 쓴 벽지는 `paper_grade`에 남김
  - '기존 벽지 철거' 줄 풀이: "보통인부 노임 172,698원 × 0.01" → "벽지 떼내기 ㎡당 1,727원". 팀 단가표에 노임 값이 따로 없어서 숫자를 코드에 박지 않으려고

### 5. `refprice/mvp_market.py` · `calc/market_band.py` (새 파일) · `tests/test_calc_market_band.py`

- MVP `MARKET`(v5 시장 기준) + v10 목공 덧붙임(정해진 가격 항목을 시장 기준에도 더함)을 옮김
- `dobae` · `mokgong`: 시장 기준 줄 · 금액(부가세 별도) · 범위(만 원 단위) · 근거 견적 수
  - 도배는 도면 면적이면 도면용 띠(`band_plan`), 아니면 일반 띠
  - 목공 정해진 가격 항목은 범위 폭 없이 같은 금액을 더함
- `extras_range`: 받은 견적 맞춰 보기용 흔한 추가 항목(중문 · 단내림 · 가벽 · 단열 · 아트월 · 간접등) + 9mm 문선 범위
- `gap_steps`: 공공 기준(부가세 포함) → 시장 기준(부가세 별도)을 값 하나씩 바꿔 가며 달라진 금액
  - 출발점 값 한 벌(`PUBLIC_EQ_*`)과 바꾸는 순서 · 이유 문구(`GAP_*`)는 `refprice/mvp_market.py`에
- MVP와 다른 점
  - 방문 어림 개수 함수(`doors_default`)를 데이터로 바꿈: 평 경계 `(28, 38)` + 개수 `(4, 5, 6)`. 공공 쪽은 `(2, 3, 4)`
  - 짐 있는 집 줄 설명이 "노무비의 2%"로 고정이던 것을 값에서 만들어요(시장 값은 그대로 2%)

### 6. 예시 평면도 · `mvp` API

- `refprice/mvp_plans.json` · `mvp_plans.py` (새 파일): MVP v9 평면도 20곳(공간 치수 mm, 읽은 방법, 확신, 출처 · 링크)
  - 팀 `ref_floorplan_rows` 표는 문서에서 읽은 수량 줄(페이지 · 합계 줄) 모양이라 공간 치수와 맞지 않아 쓰지 않았어요
  - 그림 크기 · 면적표 칸(`w_px` · `h_px` · `table`)은 빼고 옮김. 평면도 그림은 화면 쪽에 둘 예정
- `mvp/` (새 기능 패키지): `router.py` · `service.py` · `schemas.py`

| API | 하는 일 | 권한 |
| --- | --- | --- |
| `GET /mvp/plans` | 예시 평면도 목록(공급면적 순) | 로그인 |
| `GET /mvp/plans/{plan_id}/qty?expanded=&kinds=` | 평면도 수량(확장 여부 · 공간 종류 고르기) | 로그인 |
| `GET /mvp/materials` | 목공 자재 21개 · 정해진 단가 항목 18개 · 등급별 처음 자재 | 로그인 |
| `POST /mvp/projects/{id}/preview` | 이 집 견적 미리 보기: 공공 기준(도배 · 목공) + 시장 기준 · 범위 + 공공 → 시장 차이 | 만든 사람 · 관리자 (남의 것 404) |

- 미리 보기는 저장하지 않아요. 그래서 새 표 · migration이 없어요
- 프로젝트는 `project.service.get_for`(공개 함수)로만 읽고, 면적은 팀 `calc.standard_quote.house_area`를 그대로 써요
  - 평면도를 고르면 면적은 평면도 공급면적, 수량은 평면도에서
  - 등급은 요청값 → 프로젝트 도배 등급 → basic 순서
  - 목공 고른 값이 없으면 등급별 처음 자재
- 수량 입력은 참 · 거짓(자동 수량)과 숫자(0~10,000, 소수 한 자리)를 엄격히 나눠요. 1이 '참'으로 바뀌는 문제를 막으려고
- 계산 오류(잘못 고른 자재 등)는 422 `invalid`, 없는 평면도는 404
- `calc/mvp_mokgong.py`에 더한 것: 면적 기준(공급 · 전용), 도면이 없을 때 방문 수 어림(방 + 욕실: 28평 아래 3 · 38평 아래 5 · 그 위 6)

### 팀 파일에 더한 것 (공용 줄)

- `backend/app/main.py`: `mvp_router` import 한 줄 + `ROUTERS` 한 줄 (이름 순 자리)
- `frontend/lib/backend/schema.d.ts`: CI와 같은 방법으로 다시 만듦(openapi-typescript 7.13.0). 더한 줄만 있음(+582)
  - 처음엔 응답 이름 `ExtraOut`이 팀 이름과 겹쳐 팀 타입을 덮었어요 → 새 이름에 모두 `Mvp`를 붙여 해결

### 7. 화면 `/projects/[id]/mvp` (새 파일만)

| 파일 | 하는 일 |
| --- | --- |
| `app/projects/[id]/mvp/page.tsx` | 서버 컴포넌트. 프로젝트 · 평면도 목록 · 목공 자재를 읽어 넘김. 권한은 팀 `projects/[id]/layout.tsx`(고객만, 남의 것 404)를 그대로 탐 |
| `lib/api/mvp.ts` | 서버 쪽 읽기 입구(`/mvp/plans`, `/mvp/materials`)와 API 타입 이름 |
| `components/mvp/MvpBoard.tsx` | `"use client"`. 고른 값이 바뀌면 0.25초 뒤 미리 보기 API를 다시 부르고, 마지막 요청의 답만 보임 |
| `components/mvp/PlanPicker.tsx` | 1. 비슷한 평면도 고르기(20곳 + '평면도 없이'), 확장 여부, 출처 링크 |
| `components/mvp/MokPanel.tsx` | 2. 등급(베이직 · 스탠다드 · 프리미엄), 방문 작업 · 자재 · 개수, 슬라이딩 · 히든도어, 천장 몰딩 종류 · 자재, 걸레받이, 그 밖의 목공 18항목(접어 둠) |
| `components/mvp/PreviewResult.tsx` | 3. 공정별 공공 기준 합계(부가세 포함) · 기간 · 품, 업체 견적 보통 범위(부가세 별도) · 근거 견적 수, 표준견적서와 다른 이유, 줄별 금액 · 계산 방법 |
| `components/mvp/labels.ts` | MVP 화면 말(등급 이름, 문 작업, 몰딩 종류, 단가 근거). 팀 `lib/labels.ts`는 그대로 |
| `components/mvp/mvp.module.css` | 팀 토큰만 사용. 960px 이상은 두 칸(오른쪽 결과 고정), 그 아래는 한 칸 |

- 화면은 금액을 만들지 않아요. 고른 값만 보내고 API 숫자를 그대로 보여요
- 등급을 바꾸면 몰딩 · 걸레받이 · 문 자재를 그 등급의 처음 자재로 다시 고르고, 문 작업 방식 · 정해진 단가 항목은 그대로 둬요(MVP와 같음)
- 확인: `pnpm typecheck` · `pnpm lint` · `pnpm build` 통과. 가짜 로그인 · 프로젝트 API(진짜 `/mvp` router · calc)로 화면을 띄워 고르기 · 다시 계산 · 360px · 넓은 화면을 봄
- 고친 것(점검 중 찾음): CSS 모듈에 클래스 없는 선택자(`details summary`)가 있어 빌드가 깨짐 → 클래스 아래로, 평면도 목록 줄이 겹쳐 보임 → 목록을 block으로
- 아직 안 옮긴 것
  - 스타일 사진 고르기 · 첫 화면 사진 줄: 사진 출처 확인이 먼저예요
  - 평면도 그림: 공개 평면도 그림을 저장소에 넣어도 되는지 확인이 먼저예요. 지금은 이름 · 크기 · 출처 링크만
  - 대화(상담) 연결: 팀 결정(보류) 뒤


## v2 화면 옮기기 (11-11 방향 바꿈)

사용자 결정: v10을 팀 프로젝트의 `/v2` 경로로 **React로 다시 만들어** 그대로 옮긴다. AI 상담은 팀 `llm.py`(OpenAI), 사진은 579장 모두, `/projects/[id]/mvp` 화면 커밋은 되돌림(계산 엔진 · API 커밋은 둠).

| 커밋 | 내용 |
| --- | --- |
| `5883913` chore: 도면 · 자재로 견적 보기 화면 되돌리기 | `/projects/[id]/mvp` · `components/mvp` · `lib/api/mvp.ts` 뺌 |
| `38f1c3b` chore: v2 화면 사진 · 자료 더하기 | `frontend/public/v2/`: 사진 579장(28MB) · data.json · rag5.json · estimate_ref.json |
| `5ebfc48` feat: v2 상담 화면 공통 틀 더하기 | 아래 '공통 틀' |

### 공통 틀 (`frontend/components/v2/`, `frontend/app/v2/page.tsx`)

- 디자인: v10 CSS 954줄을 `v2.module.css`로 옮김. 모든 규칙을 `.root :global(...)` 아래로 감싸 `/v2` 화면에만 적용, 클래스 이름은 v10 그대로
  - v10 색 · 글자 토큰은 `.root` 안에만 둠(팀 `globals.css` 토큰과 다름 — 팀 규칙 '토큰은 globals.css'와 어긋남, 아래 표)
- 상태: `store.ts` — v10 `S`(상담) · `V3`(견적서 · 공정표)를 그대로 두고, 고친 뒤 `touch()`하면 화면이 다시 그려짐(useSyncExternalStore). 저장은 이 브라우저에만(localStorage)
- 대화 엔진: `engine.tsx` — v10 `bot · me · addMsg · quick · toast`를 같은 이름으로, 시트 · 문서 · 사진 보기는 `openOverlay`, 단계 함수는 `F` 표에 이름으로 넣고 부름(파일끼리 import 고리 없게)
- 흐름 공통: `flow.ts` — 추천 점수 · 정렬 · 예산으로 등급 · 단계 이동 · 스타일 사진
- 화면 껍데기: `V2App.tsx` — 머리(사진 종류), `#chat`으로 첫 화면 / 상담 화면 나누기, 진행 칸, 처음부터, 입력창, `Board.tsx` 내 집 보드
- 자료: `data.ts`(스타일 · 공정 · 공사 순서 · 공간 · 대표 평면), `looks.ts`(느낌 사진 100장 목록), `public/v2/router.json`(의도 분류 가중치)
- 권한: `/v2`는 로그인한 고객만(팀 '에이전트는 로그인한 고객만'에 맞춤). v10은 로그인 없이 썼음

### 나눠 옮기는 중

| 작업 | 폴더 | v10 구역 |
| --- | --- | --- |
| A 시작 · 고르기 | `components/v2/intake` | 스타일 · 느낌 사진 · 공사 순서 · 집 정보(팀 날짜 선택기) · 범위 · 예산 · 사진 · 평면도 고르기 |
| B 자재 | `components/v2/materials` | 자재 고르기 · 비교 · 자세히 · 목공 패널 · 마무리 요약 |
| C 견적서 · 공정표 | `components/v2/doc` | 표준견적서(고객 · 업체 보기) · 공정표 · 시장 범위 · 다른 이유 · 받은 견적 맞춰 보기 |
| D 첫 화면 · 검색 · 도구 · AI | `components/v2/home` · `ai` · `tools` | 첫 화면 · 자료 검색 · 의도 분류 · AI 상담 · 셀프 계산기 · 체크리스트 |
| E 백엔드 | `backend/app/calc/v2_*` · `app/mvp` · `app/agent/llm.py`(함수 하나) | `/mvp/v2/quote · plan · check · calc7 · extras-range · llm` |

## 팀 코드와 어긋나는 점 (팀이 정할 것)

| 무엇 | 팀 | mvp | 메모 |
| --- | --- | --- | --- |
| 등급 | `economy · basic` (화면: 저가형 · 기본형) | `economy · basic · premium` (화면: 베이직 · 스탠다드 · 프리미엄) | AGENTS.md 용어표 수정 필요. 코드에는 값만 두고 화면 이름은 `frontend/lib/labels.ts`에서 |
| 천장 넓이 어림 | 전용 = 공급 ÷ 1.2 | 도면 없을 때 천장 = 공급 ÷ 1.32 | `MokFixed.supply_per_floor` 하나로 모여 있어 바꾸기 쉬움 |
| 줄 근거 | public · assumed · none | + market · pick | `MvpLine.price_basis`로 더함 |
| 전용 → 공급 | `MokgongPrices.supply_per_exclusive` 1.2 | 시장 계산도 1.2 (`market_band.SUPPLY_PER_EXCLUSIVE`) | 같은 값이지만 상수가 둘 |
| 등급 프리미엄 도배 | 없음 | 실크 단가로 계산 | 프리미엄 벽지 단가가 생기면 `DobaePrices.paper`에 더할 자리 |
| 고객에게 보이는 금액 | 부가세 포함으로 보임 | 업체 견적 범위 · 줄 금액은 부가세 별도 | 업체 견적서가 보통 부가세 별도라 MVP대로 두고 '부가세 별도'를 붙임. 팀 규칙에 맞추려면 범위도 부가세 포함으로 바꿔야 함 |
| v2 디자인 토큰 | 색 · 글자 크기는 globals.css 토큰만 | v10 토큰을 `.root` 안에 따로 둠 | v10 모습을 그대로 살리려고. 팀 토큰으로 바꾸면 모습이 달라짐 |
| v2 계산 위치 | 금액 · 수량 · 날짜는 calc만 | 백엔드 `/mvp/v2/*`로 옮기는 중. 추천 점수 · 검색 · 의도 분류는 화면에 둠 | 돈 · 날짜가 아닌 계산 |
| 화면으로 들어오는 길 | — | 팀 화면에 링크가 없음 | 표준견적서 · 내 공사 화면에 링크 한 줄을 더할지(팀 파일 수정) 정해야 함 |

## MVP 화면(v10) 변경

- 등급 이름: 저가형 · 기본형 · 고급형 → 베이직 · 스탠다드 · 프리미엄 (`v10patch.py`, 저장 값은 그대로)
- "기본형으로 골라 뒀어요" → "스탠다드로 골라 뒀어요"
- '기본형 도면'(확장 안 한 평면)은 등급이 아니라 그대로


## 남은 작업 (11-11 기준, origin/feat-mvp-layer 푸시 뒤)

| # | 할 일 | 상태 · 막힌 것 |
| --- | --- | --- |
| 1 | `/v2` 처음부터 끝까지 눌러 보기 | 첫 화면 → 스타일 → 공사 순서 → 집 정보 → 범위 → 예산 → 사진 → 평면도 고르기까지 확인. 자재 → 마무리 → 견적서 → 공정표 → 받은 견적 맞춰 보기 → 계산기 · 체크리스트 → AI(스텁)는 아직 |
| 2 | 사진 넣은 AI 질문 | 팀 본문 한도 1MB(`app/shared/request_guards.py` LIMITS)에 걸려 413. `/mvp/v2/llm` 한 줄(예 8MB) 더할지 결정 필요(팀 파일) |
| 3 | DB 쓰는 API 테스트 | `tests/test_mvp.py` · `test_mvp_v2.py`. 로컬 DB에 pgvector가 없어 못 돌림 → CI(팀 저장소 PR 때) 또는 pgvector DB 이미지 만들기(내려받기 필요) |
| 4 | 실제 AI 답 확인 | OpenAI 실호출은 유료라 안 함. v10 프롬프트는 Claude용이라 답 품질 · 도구 호출 확인 필요(승인 뒤) |
| 5 | v10과 남은 차이 | 견적 2,100가지 중 19가지 · 맞춰 보기 1,200가지 중 2가지가 도면 수량 0.1 반올림 차이(정확한 십진수 vs JS 소수). 그 밖에 작업자 보고의 '다르게 한 곳'(평면도 카드 문구 · 지난 카드가 계속 바뀜 · 목공 금액은 API 결과 대기 중 '계산 중이에요' 등) |
| 6 | 팀이 정할 것 | 이름 `v2`(팀은 디자인 시안 v2로 씀) · v10 디자인 토큰 따로 둠 · 등급 이름(AGENTS 용어표) · LLM 공급자 · 상담 챗 보류 · 제조사 사진 저작권(7MB) · 공정표는 팀 `schedule.fix_plan`과 결과가 달라 v10 식을 따로 옮김 · 팀 화면에서 `/v2`로 들어오는 링크 |
| 7 | 정리 | 점검용 실행 설정 2개(본 폴더 `.claude/launch.json`의 mvp-layer-*), 본 폴더 `feat-demo-flow-polish`의 커밋 안 된 24개 파일 처리 |
| 8 | 팀 저장소 PR | 하지 않음(origin에만 푸시). 올리려면 dev 대상 PR · 기능별로 나누기 결정 |
