# v2 백엔드 API (작업자 E) — 화면 작업자 A~D가 읽는 약속

모두 로그인 필요(`current_user`). 경로 앞에 `/api`(화면은 `v2Post("quote", body)`).
응답 키 이름은 v10 JS 함수가 돌려주던 객체와 같다. 금액은 원 정수, 수량 · 품 · 일수는 숫자(소수 가능), 날짜는 "YYYY-MM-DD".
실패는 `{"error": {code, message}}`(입력 모양 틀림 422, 없는 도면 404, 계산 불가 422).
타입은 `frontend/lib/backend/schema.d.ts`의 `MvpV2…` 스키마.

---

## 공통 입력: `MvpV2QuoteIn` (= v10 v3Inputs가 읽던 상태)

```jsonc
{
  "pyeong": 32,              // S.info.pyeong (없으면 null → 32평으로 잡고 assumed에 적음)
  "living": "living",        // S.info.living: "living" | "vacant" | null
  "cats": ["wallpaper", "carpentry", "floor"],  // scopeCats().map(c => c.id) — CATS 순서 그대로
  "picks": { "wallpaper": "wp-…", "floor": "…" }, // S.picks 그대로(키 순서도 그대로: 견적 번호 해시에 씀)
  "plan": {                  // S.plan?.kind === "apt"일 때만, 아니면 null
    "id": "fp04", "expanded": true,      // S.plan.expanded !== false
    "kinds": ["living", "room"] | null,  // pp9Kinds()
    "spaces": ["room"] | null            // S.scope.spaces (kinds가 있을 때 도면 이름 "(거실 · 방만)"에 씀)
  },
  "balcony": false,          // V3.balcony
  "mok": { /* S.mok10 그대로(store.ts MokSt) */
    "door": { "mode": "none|replace|overlay|leaf", "pick": "id|null", "count": 3 | null },
    "slide": { "n": 0, "pick": "door-yerim-hidden-sliding-set" },
    "hidden": { "n": 0, "pick": "door-yerim-hidden-set" },
    "molding": { "type": "flat|step|minus|none", "pick": "id|null" },
    "base": { "pick": "id|null" },
    "extras": { "flatten_overlay": true, "coffer": 2 }   // true = 자동 수량, 숫자 = 넣은 수량
  } | null,                  // null이면 tier의 처음 값(v10 mok10St() 처음 값과 같음)
  "tier": "basic"            // S.tier (mok가 null일 때만 씀)
}
```

---

## 1. `POST /mvp/v2/quote` — v10 `buildQuote()` + 정밀 공정마다 `band` · `gap`

입력: `MvpV2QuoteIn`

출력 (`MvpV2QuoteOut`):
```jsonc
{
  "inp": { "py": 32, "area_m2": 105.8, "measured": {name, wall_m2, ceiling_m2, molding_m, base_m, doors} | null,
           "occupied": true, "balcony": false, "grade": "basic|economy", "mok": ["molding","base","door"],
           "doors": 5, "doors_auto": {"n": 5, "how": "32평 기준 방 3 + 욕실 2"}, "assumed": ["…"] },
  "precise": [   // 목공(있으면) → 도배 순서. v10 mok10Calc · CALC.dobae 결과 모양
    { "trade": "mokgong|dobae", "ko": "목공|도배",
      "lines": [{key, name, qty, unit, unit_price, amount, state, source, basis, calc}],
      "supply", "vat", "total", "man_days", "md_raw", "crew",
      "steps": [{key, name, half_days}], "days", "notes": [],
      "grade": "basic" | null,          // 도배만
      "extra_amount": 0 | null, "ver": "mok10-…" | null,   // 목공만
      "band": { "lo", "hi", "n", "p": [lo, hi],            // = marketBand(t) (v10 2096 최종판)
                "mk": { "trade", "grade": "silk|hapji"|null, "lines": [{key,name,qty,unit,unit_price,amount,note}],
                        "supply", "lo", "hi", "band": {lo, hi, lo80, hi80, n|null}, "version" } },
      "gap": { "from", "steps": [{key, name, why, d}], "to" } }   // = gapSteps(t)
  ],
  "ref": [ { "cat", "ko", "level", "lines": [{key, name, qty, unit, lo, hi, state, basis, source, calc,
             "pub": {unit_price, amount, source} | null, "note"}],
             "lo", "hi", "vlo", "vhi", "days", "crew", "steps": [{key, name, half_days}], "notes": [] } ],
  "missing": [], "supply", "vat", "total", "rlo", "rhi", "all_lo", "all_hi",
  "code": "MJ-2611-0423", "at": "2026-11-11", "band": {"lo", "hi"} | null,
  "formula_version": "2026.11.1", "price_ver": "2026H2"
}
```
- 목공 고른 것이 하나도 없으면 precise에 목공이 없다(v10과 같음).
- `inp.doors_auto` = v10 `mok10AutoDoors(py)`(목공 패널 "처음 값 N개(…)").

## 1-1. `GET /mvp/v2/market-extras` — 받은 견적 맞춰 보기 목공 칸 목록
출력: `[{key, name, per: "곳"|"식", lo, hi, n}]` (= v10 `MARKET.P.mokgong.extras`)

## 1-2. 이미 있던 API에 더한 것
- `GET /mvp/materials`: `products[].per` = "짝" | "세트" | null (v10 MOK10.prod per), `fixed` = `{minus_mult, hidden_mult, molding_per_py, base_per_py}` (v10 MOK10.fixed, 숫자는 글 "2"처럼 옴)
- `GET /mvp/plans`: 목록마다 `sup_note` (공급면적 출처 글, 없으면 null)
- `GET /mvp/plans/{id}/qty?expanded=&kinds=&ceiling=`: `ceiling`(기본 true, v10 qtyCard '천장도 도배') · 응답 `est` = `{py, wall_m2, ceiling_m2, molding_m, base_m}` (v10 CALC9 est, 평형으로 어림한 값)

---

## 2. `POST /mvp/v2/plan` — v10 `buildPlan()` (planTrades · defaultStart · fixPlan)

입력 (`MvpV2PlanIn`):
```jsonc
{
  "quote": MvpV2QuoteIn,                 // 공정 단계 · 기간은 서버가 견적을 다시 계산해서 쓴다
  "move": "2026-12" | "2026-12-20" | "", // S.info.move
  "cons": { "weekendWork": false, "endBy": "", "startAfter": "", "avoid": ["2026-12-03"] },  // V3.cons 그대로
  "props":    { "mokgong": { "start": "…", "end": "…", "crew": 2 } },   // V3.props (업체가 낸 날짜)
  "accepted": { "dobae":   { "start": "…", "end": "…" } },               // V3.accepted (고객이 수락한 날짜)
  "trial": { "trade": "mokgong", "start": "…", "end": "…" } | null       // 아래 trial 설명
}
```
출력 (`MvpV2PlanOut`) = v10 `V3.plan`:
```jsonc
{
  "start", "end", "work_days",
  "blocks": [{ "trade", "ko", "kind": "work|dry|clean", "start", "end", "days", "crew": 2|null,
               "state": "expected|pending|confirmed" }],
  "days": [{ "date", "off": bool, "holiday": "성탄절"|null, "items": [{trade, ko, todo: []}] }],
  "trades": [{ "trade", "ko", "steps": [{key,name,half_days}], "crew", "fixed": {start}|null, "state", "need" }],
  "warn": ["목표(2026-12-19)보다 3일 늦어요. …", "목공와 도배 날짜가 겹쳐요"],
  "today": "2026-11-11", "tomorrow": "2026-11-12",
  "due_next": "2026-11-12 18:00",        // CALC.dueAt(todaySeoul(), 1) — '다른 날짜 요청' 기록 · 안내 문구
  "weeks": [{ "n": 1, "start": "2026-11-09", "end": "2026-11-15", "blocks": [block…] }],  // v10 weekList 묶음(월~일, n주차)
  "trial": null | {
    "trade", "start", "end",
    "moved": [{ "trade", "ko", "start" }],  // customerDateCard: 이 날짜로 하면 밀리는 공정(v10 그대로 건조 · 청소 포함)
    "clash": bool,                          // 다른 공정의 수락한 날짜와 겹침(수락 못 함)
    "error": "시작일은 내일부터 1년 안으로 골라 주세요." | null,   // vendorDateCard 검사 문구(이유 칸 검사는 화면)
    "work_days": 3, "need": 2.5, "short": false   // 일하는 날 수 · 필요한 기간 · 짧음 경고(toast)
  }
}
```
- 고객 카드: `trial = {trade, start: prop.start, end: prop.end}` → `moved` · `clash`.
- 업체 카드: [공사 날짜 내기] 누를 때 `trial = {trade, start, end}` → `error`가 있으면 그 글, 없으면 저장 · `short`면 toast.
- 공휴일: 팀 공휴일 + v10이 더 넣은 노동절 · 제헌절(v10 HOLIDAYS_EXTRA).

---

## 3. `POST /mvp/v2/check` — 받은 견적 맞춰 보기(quoteCheck go() 숫자 부분 + 덧씌움 범위 막대)

입력 (`MvpV2CheckIn`):
```jsonc
{
  "quote": MvpV2QuoteIn,
  "trade": "dobae|mokgong",
  "amount": 2500000,                    // 받은 금액(원). 서버가 Math.round
  "mode": "unknown|excluded|included",  // 부가세
  "scope": {                            // 체크한 칸
    "ceiling": true, "removal": false, "moving": false,      // 도배
    "casing9": false, "etc": false,                          // 목공 (removal도 목공에서 씀)
    "extras": { "aircon": 2, "jungmun": 1 }                  // 목공 x-{key} 체크한 것만: 곳 수(1~9, 식은 아무 값)
  }
}
```
출력 (`MvpV2CheckOut`):
```jsonc
{
  "warn": null | "받은 금액을 넣어 주세요." | "수납장 · 붙박이 …",  // 있으면 이것만 warn-line으로 보이고 나머지는 null
  "trade", "supply", "lo", "hi",
  "where": "low|in|high", "pct": 12.3, "head": "보통보다 12.3% 높아요",
  "notes": ["기존 벽지 철거: 시장 ㎡당 600~2,400원 × 109.1㎡"],   // extra.notes (warn이면 [])
  "why": ["…"],                          // 판정별 안내 목록 (warn이면 [])
  "vat_unknown": true,                   // "부가세 말이 없으면 …" 문구를 보일지
  "bar": { "band_left": 18.2, "band_width": 40.1, "me": 70.3 }   // 범위 막대 위치(%) — 덧씌움 2826~2832
}
```
- V5.checks.push({trade, supply, lo, hi, where})는 화면이 한다.
- 견적서에 그 공정이 없으면 422.

## 3-1. `POST /mvp/v2/estimate` — 업체 가견적 (v10 estimateFor)
입력: `{ trade, grade: "economy"|"basic"|null, lines: [{key, name, qty, state}], prices: {줄키: 단가}, std_total }`
- 도배 벽지 줄(key "paper")은 `prices["paper_" + (grade || "basic")]`를 쓴다(v10 V3.vp 키 그대로).
출력: `{ok: true, supply, vat, total, pct, why: null}` | `{ok: false, why: "'…' 단가를 넣어 주세요", 나머지 null}`

## 3-2. `POST /mvp/v2/entered` — 실측 견적서 요약 칸 (v10 CALC.fromEntered + percentVs)
입력: `{ amount, mode: "excluded"|"included"|"exempt", std_total: number|null }` → 출력 `{ supply, vat, total, pct|null }`

---

## 4. `POST /mvp/v2/calc7` — 셀프 계산기 CALC7 (화면 D의 tools/calc7.ts 모양)

입력: `{ kind: "wallpaper"|"trim"|"paint", ...v10 CALC7 입력 }` — 빈 칸 기본값(높이 2.3 등)은 v10 calcCard처럼 화면이 넣는다
- wallpaper: `{w, d, hgt, doors, windows, ceiling, rollW, rollLen, repeat, loss}`
- trim: `{w, d, doors, pieceLen, loss}` (doorW 기본 0.9)
- paint: `{w, d, hgt, doors, windows, ceiling, coats, cover}`
- hgt · rollW · rollLen · pieceLen · cover는 0보다 커야 한다(0이면 422)
출력: v10 CALC7 결과 객체 그대로
- wallpaper: `{wall_m2, ceiling_m2, strips, cStrips, per_roll, rolls_raw, rolls}`
- trim: `{molding_m, molding_pcs, base_m, base_pcs}`
- paint: `{area_m2, liters, n18, n4}`

---

## 5. `POST /mvp/v2/extras-range` — `MARKET.extrasRange(picks, casing)`
입력: `{ "picks": {"aircon": 2}, "casing": {"doors": 4, "with_door": true} | null }`
출력: `{ lo, hi, notes: [] }`

---

## 6. AI
- `POST /mvp/v2/llm` — CONTRACT.md 6번 그대로.
  - 입력 한도: system 60,000자, messages 30개, 이미지 4장(base64 jpeg 각 1.5MB 이하), tools 12개.
  - 출력 `{ text, tool_calls: [{id, name, arguments}], stop: "tool_calls"|"stop"|"refusal" }`
  - `LLM_LIVE=false`(로컬 · CI)면 `{text: "지금은 AI 답변을 쓸 수 없어요. 버튼으로 이어서 진행해 주세요.", tool_calls: [], stop: "stop"}`
  - `tool_calls[].arguments`는 객체(JSON 글 아님). 도구 결과는 `{role: "tool", tool_call_id, content: JSON 글}`, 사진은 `{type: "image", data}`.
  - 실패 502 `llm_failed`, 요청 많음 429 `rate_limited`(사용자별 1시간 120번), 사진 5장 이상 422 `too_many_images`.
  - 주의: 팀 BodyLimit 미들웨어 기본 본문 한도가 1MB라 사진을 넣으면 1MB를 넘는 요청은 413 `too_large`가 된다(팀 파일 `app/shared/request_guards.py` LIMITS에 `/mvp/v2/llm` 줄을 더해야 함 — 아직 안 함).
- `GET /mvp/v2/llm/health` → `{ ok: true, live: bool }`
