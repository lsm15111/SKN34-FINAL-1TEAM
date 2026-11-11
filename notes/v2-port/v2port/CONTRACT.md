# v10 → 팀 프로젝트 /v2 이식 약속 (작업자 공통)

## 목표
- 커스텀 MVP v10(바닐라 JS 한 장)을 팀 저장소 `C:\Workspace\SKN34\SKN34-FINAL-1TEAM-mvp`(git worktree, 브랜치 `feat-mvp-layer`)의
  Next.js 화면 `/v2`로 **React로 다시 만든다**. 보이는 모습 · 흐름 · 문구는 v10과 **똑같이**.
- 다른 점은 하나: **금액 · 수량 · 날짜 계산과 LLM 호출은 백엔드**가 한다(팀 규칙). 화면은 고른 값을 보내고 결과를 그대로 보인다.
  - 추천 점수 · 정렬 · 검색(RAG BM25) · 의도 분류 같은 "돈이 아닌 계산"은 화면에 둬도 된다.
- v10 원본(데이터 상수 빼고): `scratchpad/v2port/v10_code.js` (3,961줄). 이 문서의 줄 번호는 이 파일 기준.
  - 주의: v10은 같은 이름 함수를 뒤에서 다시 정의하거나(`function x` 두 번 → 뒤엣것이 이김), `{ const base = x; x = function () { base(); ... } }`로 덧씌운다. **최종 동작**을 옮긴다.
  - CSS: `scratchpad/v2port/v10.css` → 이미 `frontend/components/v2/v2.module.css`로 옮겼다(.root 아래 :global). **클래스 이름을 v10과 똑같이** 쓰면 된다(className="card", "chip", "btn btn-pri" …). 새 CSS 파일 만들지 말 것.
  - 몸통 HTML: `scratchpad/v2port/v10_body.html`
- 원본 실행본으로 동작을 볼 수 있다: `C:\Workspace\SKN34\mitjip-mvp\site\v10.html` (자료 파일도 같은 폴더)

## 공통 틀 (이미 있음, 고치지 말 것. 필요하면 보고서에 적기)
`frontend/components/v2/`
- `store.ts`: `S`(v10 S 그대로, 직접 고치고 `touch()`), `V3`(견적서 · 공정표 상태), `DATA`(materials · styles), `asset(p)`("img/…" → "/v2/img/…"), `useV2()`(touch마다 다시 그림), `store`(localStorage), `wait(ms)`, `resetState()`, `chat.built`
- `engine.tsx`: `bot(text, ...nodes)`(Promise<MsgHandle>), `me(text)`, `addMsg(who, ...nodes)`, `quick([[label, fn], …])`, `clearQuick()`, `toast(text, undo?)`, `openOverlay((close) => node)` → `{close}` (시트 · 문서 · 사진 보기 모두 이걸로, 안에서 Esc 처리), `live(init)`(한 메시지 안에서 바뀌는 글: AI 답), `busy.asking`(AbortController | null), **`F`**(흐름 함수 표) · `register({...})`
  - MsgHandle: `.set(...nodes)` 내용을 바꿈, `.append(node)`, `.remove()`
  - v10 `doneCard(card)`(카드 잠그기) → 카드 컴포넌트 안 `useState`로 done을 두고 disabled 처리
- `flow.ts`: `scopeCats()`, `score`, `recommend`, `sortMats`, `rankOf`, `lowP`, `autoPick()`, `fillPicks()`, `tierFromBudget()`, `priceFlags`, `setStep`, `resumeStep`, `proceed(next)`, `stepFn(id)`, `STEP_NAMES`, `lookSrcs(lk)`, `styleSrcs(st, i)`, `styleOf(id)`, `matOf(id)`
- `data.ts`: STYLES, CATS, CAT, TIERS(베이직 · 스탠다드 · 프리미엄), TIER_ORDER, TIER_NOTE, GUIDE, SPACES, PLANS(대표 평면 svg), STEPS, STEP_INDEX, MODE_LABEL, SORTS, `manwon`, `priceText`, `unitShort`, 타입 Material · Style · Cat
- `looks.ts`: LOOKS(LOOK_FIX 반영됨), LOOK_BY, lookOf, lookPhotos, TONE_KEY, TONE_KO, rgbOf, mixHex, toneFit
- `photo.tsx`: `<Photo srcs alt cls>{children}</Photo>`(v10 photo()), `matSrcs(m)`, `setImgMode`, `<EmptyToggle />`, `view.empty`
- `dates.ts`: toDate, toStr, md("11.16(월)"), longDay, todaySeoul, moveDay, moveLabel
- `Board.tsx`: 내 집 보드(다 됨). `flashBoard()`로 반짝임(v10 renderBoard(true)), `boardUi.setOpen(false)`
- `V2App.tsx`: 머리 · #chat 나누기 · startFlow · 단계 칸 · 처음부터 · 입력창. `goChat(mode, extra)`(첫 화면에서 상담 시작), `start`
- `api.ts`: `v2Post<T>(path, body)` = POST `/api/mvp/v2/{path}`, `v2Get`, `mvpGet<T>(path)` = GET `/api/mvp/{path}`
- 팀 날짜 선택기: `@/components/start/DateCalendar` (`<DateCalendar today label value onChange />`, "YYYY-MM-DD") — v10 cal8 · dateField8 대신 이것
- 팀 오류 글: `errorText(e)` from `@/lib/backend/client`

## F 표 이름 (이 이름으로 register하고, 다른 파일 함수는 F.이름으로 부른다)
| 담당 | register할 함수 |
| --- | --- |
| A 시작 · 고르기 | welcome, reopenStyles, collapseRail, chooseStyle, chooseLook, afterStyle, startLook(styleId, lookId) → boolean, openLooks, guideStep(fromStart), infoStep, scopeStep, budgetStep, photoStep, planStep, planQtyTool(보드 '도면으로 수량'), resetLocal(처음부터 때 지울 모듈 변수) |
| B 자재 | matStep, refreshMat, setAllTier, openSheet(m), finish, mok10Sync, setMatFull, summaryText |
| C 견적서 · 공정표 | quoteStep, schedStep, openQuoteDoc, openPlanDoc, explainQuote, bandWhy, quoteCheck 관련 |
| D 첫 화면 · 검색 · 도구 · AI | askClaude(q, {label, images, withPhotos}), askAboutStyle(st), askAboutMat(m), askCompare(cat), askPhotos, askReview, calcStep(kind), checkStep(which), roomSvg(lk) → data URI 문자열, lookCredit(lk), agentAnswer({label, ask, system, allowed, tools}), ragSearch(q,k,trade), Home 화면 |
- 단계 함수 표(v10 STEP_FN)는 `flow.ts`의 `stepFn(id)`가 `STEP_NAMES`로 F를 찾는다. D가 `calc`, `check` 단계도 F에 넣는다(calcStep · checkStep).

## 파일 담당 (자기 폴더만 만든다/고친다)
- A: `components/v2/intake/*`
- B: `components/v2/materials/*`
- C: `components/v2/doc/*`
- D: `components/v2/home/*`(Home.tsx 자리 있음, 갈아 끼움), `components/v2/ai/*`, `components/v2/tools/*`
- 각 폴더에 `index.ts`를 두고 그 안에서 `register({...})`를 부른다. 모든 index.ts는 `components/v2/modules.ts`가 import한다(내가 만든다).
- 백엔드 작업자 E: `backend/app/calc/v2_*.py`, `backend/app/refprice/v2_*`, `backend/app/mvp/*`(router.py에 /v2 경로 더하기), `backend/tests/test_calc_v2_*.py` · `test_mvp_v2.py`, `backend/app/agent/llm.py`(함수 하나 더하기만)

## 백엔드 API 약속 (E가 만들고 A~D가 부른다). 모두 로그인 필요. 응답 키 이름은 v10 JS 결과와 **같게**
1. `POST /mvp/v2/quote` = v10 `buildQuote()` (v10_code.js 1435~1497) + 정밀 공정마다 `band`(=marketBand(t), 2096) · `gap`(=gapSteps(t), 2102)
   - 입력: `{ pyeong: number|null, living: "living"|"vacant"|null, cats: string[](범위 안 공정 id, scopeCats 결과), picks: {cat: material_id}, plan: {id, expanded, kinds: string[]|null}|null, balcony: boolean, mok: S.mok10 모양(store.ts MokSt)|null }`
   - 출력: `{ inp: {py, area_m2, measured: {name, wall_m2, ceiling_m2, molding_m, base_m, doors, ...}|null, occupied, balcony, grade, mok: string[], doors, assumed: string[]}, precise: [{trade, ko, lines: [{key,name,qty,unit,unit_price,amount,state,source,basis,calc}], supply, vat, total, man_days, md_raw, crew, steps: [{key,name,half_days}], days, notes, grade?, extra_amount?, ver?, band: {lo,hi,n,p:[lo,hi], mk:{trade, grade?, lines:[{key,name,qty,unit,unit_price,amount,note}], supply, lo, hi, band:{lo,hi,lo80,hi80,n?}, version}}|null, gap: {from, steps:[{key,name,why,d}], to}}], ref: [refTrade 결과 (1461~1485)], missing: string[], supply, vat, total, rlo, rhi, all_lo, all_hi, code, at, band: {lo,hi}|null }`
2. `POST /mvp/v2/plan` = v10 공정표 만들기(`planTrades` · `buildPlan` 1713~1747, 화면 덧씌움 2515~2575 포함). 입력 · 출력은 E가 v10 코드에 맞춰 정하고 `scratchpad/v2port/API.md`에 적는다(C는 그걸 읽는다).
3. `POST /mvp/v2/check` = 받은 견적 맞춰 보기의 숫자 부분(`quoteCheck` 2146~2208, 덧씌움 2816~2835). 입력 · 출력은 E가 API.md에.
4. `POST /mvp/v2/calc7` = 셀프 계산기 `CALC7`(2698~2723). 입력 · 출력은 E가 API.md에.
5. `POST /mvp/v2/extras-range` = `MARKET.extrasRange(picks, casing)` (2063 근처) — 이미 있는 `calc.market_band.extras_range` 사용
6. `POST /mvp/v2/llm` = AI 한 번 부르기(v10 runLocal의 fetch 한 번). 브라우저가 도구를 실행하고 다시 부른다(최대 5번).
   - 입력: `{ system: string, messages: [{role: "user"|"assistant"|"tool", content: string | [{type:"text",text}|{type:"image",data(base64 jpeg)}], tool_calls?: [{id,name,arguments}], tool_call_id?: string}], tools: [{name, description, parameters(JSON schema)}] }`
   - 출력: `{ text: string, tool_calls: [{id, name, arguments: object}], stop: "tool_calls"|"stop"|"refusal" }`
   - 팀 `app/agent/llm.py`(OpenAI, `LLM_LIVE=false`면 스텁)로만 부른다. 실패는 `{"error": {code, message}}`
   - `GET /mvp/v2/llm/health` → `{ ok, live }` (v10 api/health 자리)
- 이미 있음: `GET /mvp/plans`(예시 평면도 20곳 목록, 그림 경로 `img` = "img/plans/fp12.jpg"), `GET /mvp/plans/{id}/qty?expanded=&kinds=`(v10 CALC9.fromPlan 결과와 같은 수량), `GET /mvp/materials`(목공 자재 · 정해진 단가 항목 · 등급별 처음 자재 = v10 MOK10 prod · extras · init)

## 규칙
- 화면 글은 v10 그대로(해요체). 숫자를 화면에서 더하거나 곱해 새 금액을 만들지 않는다(표시 형식 바꾸기만: toLocaleString, 만 원 단위로 반올림해 보이기는 v10과 같으면 됨).
- TypeScript strict. `any`는 꼭 필요한 곳만. 서버 컴포넌트 아님: 파일 맨 위 `"use client";`(로직만 있는 .ts는 필요 없음).
- 주석 · 커밋은 한국어로 짧게. 팀 파일(위 공통 틀 밖, 다른 사람 폴더)은 고치지 않는다.
- 확인: `cd frontend && pnpm typecheck && pnpm lint` (다른 작업자 파일 오류는 무시하고 내 파일만 0개). 백엔드는 `uv run ruff check`, `uv run ruff format --check`, `uv run pytest <내 테스트> --noconftest`.
- 커밋 · 푸시 하지 않는다(내가 모아서 한다).
- 끝나면 보고: 만든 파일, register한 F 이름, 부르는 F 이름 · API, v10과 다르게 한 곳, 못 한 것.
