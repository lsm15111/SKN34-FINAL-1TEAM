const CALC = (() => {
  const FORMULA_VERSION = "2026.11.1", PRICE_VER = "2026H2", PYEONG_M2 = 3.3058, VAT = 0.1;
  const EPS = 1e-7;
  const won = (x) => Math.floor(x + 0.5 + EPS);
  const m2 = (x) => Math.floor(x * 10 + 0.5 + EPS) / 10;
  const halfUp = (x) => Math.ceil(x * 2 - EPS) / 2;
  const halfDays = (md, crew) => Math.max(Math.ceil((md / crew) * 2 - EPS), 1);
  const pyToM2 = (p) => m2(p * PYEONG_M2);
  function withVat(supply) { const vat = won(supply * VAT); return { supply, vat, total: supply + vat }; }
  function fromEntered(amount, mode) {
    if (mode === "excluded") return withVat(amount);
    if (mode === "included") { const supply = won(amount / 1.1); return { supply, vat: amount - supply, total: amount }; }
    return { supply: amount, vat: 0, total: amount };
  }
  const COUNTED = new Set(["included", "separate"]);
  const sumLines = (lines) => lines.filter((l) => COUNTED.has(l.state) && l.amount != null).reduce((a, l) => a + l.amount, 0);
  const line = (key, name, qty, unit, unit_price, amount, state, source, basis = "public", calc = "") => ({ key, name, qty, unit, unit_price, amount, state, source, basis, calc });

  /* ---- 도배 (refprice/book.py DOBAE_2026H2) ---- */
  const LABOR_NORMAL = 172698;
  const DB = {
    labor_wall: 5993, labor_ceiling: 8531, labor_ratio: 0.96, paper: { basic: 3325, economy: 1300 }, primer: 242,
    removal: won(0.01 * LABOR_NORMAL), paper_ratio: 1.2, primer_wall_ratio: 1.2, primer_ceiling_ratio: 0.8,
    md_wall: 0.024, md_ceiling: 0.027 * 1.3, occupied_output: 0.85, area_factor: { supply: 2.5, exclusive: 3.0 },
    ceiling_share: 0.25, balcony_factor: 1.08, crew: 4,
    src: {
      wall: "표준시장단가 2026 하반기 · 도배지바름 콘크리트 · 모르타르 벽",
      ceiling: "표준시장단가 2026 하반기 · 도배지바름 석고 · 합판 천장",
      paper_basic: "조달청 가격정보 비닐벽지 (2026-10 조회, 실크 대용)",
      paper_economy: "팀 가정값 (합지는 공공 가격이 없어요)",
      primer: "조달청 가격정보 초배지 (2026-10 조회) · 소요량 표준품셈",
      occupied: "표준품셈 · 짐 있는 집 시공량 15% 감산, 노무비에만",
      removal: "표준품셈 벽지 떼내기 × 2026.9.1 보통인부 노임",
      none: "공공 단가가 없어 업체 견적에서 확인해요"
    }
  };
  function dobae({ area_m2, area_basis = "supply", grade = "basic", include_ceiling = true, occupied = false, balcony_ext = false, measured = null }) {
    if (!(area_m2 > 0)) throw new Error("면적은 0보다 커야 해요");
    const f = DB.area_factor[area_basis];
    let gross = area_m2 * f; if (balcony_ext) gross *= DB.balcony_factor;
    let ceiling = m2(gross * DB.ceiling_share), wall = m2(m2(gross) - ceiling);
    if (measured) { wall = m2(measured.wall_m2); ceiling = m2(measured.ceiling_m2); gross = wall + ceiling; } // v9: 도면에서 잰 면적
    const ceilUsed = include_ceiling ? ceiling : 0, paperArea = m2(wall + ceilUsed);
    const paperQty = m2(paperArea * DB.paper_ratio), primerQty = m2(wall * DB.primer_wall_ratio + ceilUsed * DB.primer_ceiling_ratio);
    const gname = grade === "economy" ? "합지" : "실크";
    const L = [
      line("wall", "벽 도배 시공 (풀 포함)", wall, "㎡", DB.labor_wall, won(wall * DB.labor_wall), "included", DB.src.wall, "public",
        measured ? `도면 ${measured.name}에서 방마다 잰 벽 면적(문 · 창 뺌)` : `벽 면적 = 도배 면적 ${m2(gross)}㎡ − 천장 ${ceiling}㎡ (도배 면적 = ${area_basis === "supply" ? "공급" : "전용"} ${area_m2}㎡ × ${f}${balcony_ext ? " × 1.08" : ""})`),
      line("ceiling", "천장 도배 시공 (풀 포함)", ceiling, "㎡", DB.labor_ceiling, include_ceiling ? won(ceiling * DB.labor_ceiling) : null, include_ceiling ? "included" : "excluded", DB.src.ceiling, "public",
        measured ? `도면 ${measured.name}에서 잰 천장 면적` : `천장 = 도배 면적 × 0.25`),
      line("paper", `도배지 (${gname})`, paperQty, "㎡", DB.paper[grade], won(paperQty * DB.paper[grade]), "included", DB.src["paper_" + grade], grade === "basic" ? "public" : "assumed",
        `바를 면적 ${paperArea}㎡ × 소요량 1.2`),
      line("primer", "초배지", primerQty, "㎡", DB.primer, won(primerQty * DB.primer), "included", DB.src.primer, "public",
        `벽 ${wall}㎡ × 1.2 + 천장 ${ceilUsed}㎡ × 0.8`)
    ];
    if (occupied) {
      const labor = L[0].amount + (include_ceiling ? L[1].amount : 0);
      L.push(line("occupied", "짐 있는 집 작업 할증", null, "식", null, won(labor * DB.labor_ratio * (1 / DB.occupied_output - 1)), "included", DB.src.occupied, "public",
        `시공 노무비 ${labor.toLocaleString("ko-KR")}원 × 노무 비율 0.96 × (1 ÷ 0.85 − 1)`));
    }
    L.push(line("removal", "기존 벽지 철거", paperArea, "㎡", DB.removal, won(paperArea * DB.removal), "after_visit", DB.src.removal, "public", `보통인부 노임 172,698원 × 0.01`));
    L.push(line("waste", "폐기물 처리", null, "식", null, null, "after_visit", DB.src.none, "none"));
    if (occupied) L.push(line("moving", "짐 이동 · 보양", null, "식", null, null, "after_visit", DB.src.none, "none"));
    const supply = sumLines(L);
    let md = wall * DB.md_wall + ceilUsed * DB.md_ceiling; if (occupied) md /= DB.occupied_output;
    const man_days = halfUp(md);
    const steps = [];
    if (occupied) steps.push({ key: "prep", name: "짐 정리 · 보양", half_days: 1 });
    steps.push({ key: "paper", name: include_ceiling ? "벽지 바르기 (벽 · 천장)" : "벽지 바르기 (벽)", half_days: halfDays(man_days, DB.crew) });
    steps.push({ key: "finish", name: "마감 · 확인 · 청소", half_days: 1 });
    const notes = [...(measured ? [`벽 · 천장 면적은 도면 ${measured.name}에서 방마다 재서 더했어요(문 · 창 뺌). 실측 전 어림이라 실측 때 다시 재요.`] : [`도배 면적은 ${area_basis === "supply" ? "공급면적" : "전용면적"} × ${f}로 추정했어요. 실측 때 방마다 다시 재요.`, "천장은 도배 면적의 25%로 잡았어요."]), `하루 도배공 ${DB.crew}명이 들어가는 것으로 기간을 잡았어요.`];
    if (balcony_ext && !measured) notes.push("발코니 확장은 도배 면적을 1.08배로 잡았어요.");
    return { trade: "dobae", ko: "도배", lines: L, ...withVat(supply), man_days, md_raw: md, crew: DB.crew, steps, days: steps.reduce((a, s) => a + s.half_days, 0) / 2, notes, grade };
  }

  /* ---- 목공 (MOKGONG_2026H2) ---- */
  const MG = {
    molding: 8168, molding_mat: 3000, molding_ratio: 1.1, base: 3757, base_mat: 2000, base_ratio: 1.04,
    door_install: 82339, door_leaf_install: won(82339 / 2), door_set_mat: 260000, door_leaf_mat: 150000,
    casing: 2314, casing_per_door: 10.2, frame: 11054, board: 12937, ceiling_mat: 8000,
    md_molding: 0.035, md_base: 2 / 165, md_door: 0.313, md_casing: 0.010, md_frame: 0.0323, md_board: 2 / 45,
    molding_per_py: 2.4, base_per_py: 1.8, supply_per_exclusive: 1.2, flatten_share: 0.3, crew: 2,
    src: {
      molding: "표준시장단가 2026 하반기 · 몰딩 설치 (재료 제외)", base: "표준시장단가 2026 하반기 · 걸레받이 MDF (재료 제외)",
      door: "표준시장단가 2026 하반기 · 목재창호 설치 여닫이 1.0~3.0㎡ (재료 제외)", casing: "표준시장단가 2026 하반기 · 문선 (재료 제외)",
      frame: "표준시장단가 2026 하반기 · 경량천장틀 BAR 간격 450", board: "표준시장단가 2026 하반기 · 천장 석고판 1겹",
      ceiling_mat: "팀 가정값 (천장틀 · 석고보드 자재 공공 가격이 없어요)", door_mat: "팀 가정값 (ABS 문 자재 공공 가격이 없어요)",
      molding_mat: "팀 가정값 (몰딩 자재 공공 가격이 없어요)", base_mat: "팀 가정값 (걸레받이 자재 공공 가격이 없어요)",
      leaf: "팀 가정값 (문짝만 설치는 문 설치 공공 단가의 절반)", none: "공공 단가가 없어 업체 견적에서 확인해요"
    }
  };
  function mokgong({ area_m2, area_basis = "supply", items = ["molding", "base"], occupied = false, doors = 0, door_frame = true, measured = null }) {
    if (!(area_m2 > 0)) throw new Error("면적은 0보다 커야 해요");
    if (!items.length) throw new Error("목공 항목을 하나 이상 골라야 해요");
    if (items.includes("door") && !(doors > 0)) throw new Error("방문 개수를 넣어야 해요");
    const supply_m2 = area_basis === "supply" ? area_m2 : m2(area_m2 * MG.supply_per_exclusive);
    const exclusive = area_basis === "supply" ? m2(area_m2 / MG.supply_per_exclusive) : area_m2;
    const py = supply_m2 / PYEONG_M2;
    const L = []; let mdCeil = 0, mdDoor = 0, mdTrim = 0;
    if (items.includes("flatten")) {
      const fl = m2(exclusive * MG.flatten_share), c = `전용 ${exclusive}㎡ × 0.3`;
      L.push(line("frame", "천장 평탄화 · 경량천장틀", fl, "㎡", MG.frame, won(fl * MG.frame), "included", MG.src.frame, "public", c));
      L.push(line("board", "천장 평탄화 · 석고보드 1겹", fl, "㎡", MG.board, won(fl * MG.board), "included", MG.src.board, "public", c));
      L.push(line("ceiling_mat", "천장틀 · 석고보드 자재", fl, "㎡", MG.ceiling_mat, won(fl * MG.ceiling_mat), "included", MG.src.ceiling_mat, "assumed", c));
      mdCeil = fl * (MG.md_frame + MG.md_board);
    }
    if (items.includes("door")) {
      if (door_frame) {
        const cas = m2(MG.casing_per_door * doors);
        L.push(line("door", "방문 교체 (문틀 · 문짝)", doors, "개", MG.door_install, won(doors * MG.door_install), "included", MG.src.door, "public", `방문 ${doors}개`));
        L.push(line("casing", "문선 설치 (문 둘레 양면)", cas, "m", MG.casing, won(cas * MG.casing), "included", MG.src.casing, "public", `문 하나에 양면 10.2m × ${doors}개`));
        L.push(line("door_mat", "방문 자재 (ABS 문틀 · 문짝 · 문선)", doors, "개", MG.door_set_mat, won(doors * MG.door_set_mat), "included", MG.src.door_mat, "assumed", `방문 ${doors}개`));
        mdDoor = doors * MG.md_door + cas * MG.md_casing;
      } else {
        L.push(line("door", "방문 교체 (문짝만)", doors, "개", MG.door_leaf_install, won(doors * MG.door_leaf_install), "included", MG.src.leaf, "assumed", `방문 ${doors}개`));
        L.push(line("door_mat", "방문 자재 (ABS 문짝)", doors, "개", MG.door_leaf_mat, won(doors * MG.door_leaf_mat), "included", MG.src.door_mat, "assumed", `방문 ${doors}개`));
        mdDoor = doors * MG.md_door;
      }
    }
    if (items.includes("molding")) {
      const len = measured ? m2(measured.molding_m) : m2(py * MG.molding_per_py), mat = m2(len * MG.molding_ratio);
      L.push(line("molding", "천장 몰딩 설치", len, "m", MG.molding, won(len * MG.molding), "included", MG.src.molding, "public", measured ? `도면 ${measured.name}에서 잰 천장 둘레` : `공급 ${m2(py)}평 × 2.4m`));
      L.push(line("molding_mat", "몰딩 자재", mat, "m", MG.molding_mat, won(mat * MG.molding_mat), "included", MG.src.molding_mat, "assumed", `몰딩 ${len}m × 1.1`));
      mdTrim += len * MG.md_molding;
    }
    if (items.includes("base")) {
      const len = measured ? m2(measured.base_m) : m2(py * MG.base_per_py), mat = m2(len * MG.base_ratio);
      L.push(line("base", "걸레받이 설치 (MDF)", len, "m", MG.base, won(len * MG.base), "included", MG.src.base, "public", measured ? `도면 ${measured.name}에서 잰 바닥 둘레(문 · 큰 창 뺌)` : `공급 ${m2(py)}평 × 1.8m`));
      L.push(line("base_mat", "걸레받이 자재", mat, "m", MG.base_mat, won(mat * MG.base_mat), "included", MG.src.base_mat, "assumed", `걸레받이 ${len}m × 1.04`));
      mdTrim += len * MG.md_base;
    }
    const after = (k, n) => L.push(line(k, n, null, "식", null, null, "after_visit", MG.src.none, "none"));
    if (items.includes("flatten")) after("remove_ceiling", "기존 등박스 · 우물천장 철거");
    if (items.includes("door") && door_frame) after("remove_door", "기존 방문 · 문틀 철거");
    if (items.includes("molding") || items.includes("base")) after("remove_trim", "기존 몰딩 · 걸레받이 철거");
    after("waste", "폐기물 처리");
    if (occupied) after("moving", "짐 이동 · 보양");
    const steps = [];
    if (occupied) steps.push({ key: "prep", name: "짐 정리 · 보양", half_days: 1 });
    if (items.some((i) => i === "flatten" || i === "molding" || i === "base")) steps.push({ key: "remove", name: "철거 · 바탕 정리", half_days: 1 });
    if (mdCeil) steps.push({ key: "ceiling", name: "천장 평탄화 (틀 · 석고보드)", half_days: halfDays(mdCeil, MG.crew) });
    if (mdDoor) steps.push({ key: "door", name: "방문 교체", half_days: halfDays(mdDoor, MG.crew) });
    if (mdTrim) steps.push({ key: "trim", name: ["몰딩", "걸레받이"].filter((_, i) => items.includes(["molding", "base"][i])).join(" · "), half_days: halfDays(mdTrim, MG.crew) });
    steps.push({ key: "finish", name: "정리 · 청소", half_days: 1 });
    const man_days = halfUp(mdCeil + mdDoor + mdTrim);
    const notes = [];
    if (area_basis === "exclusive") notes.push("공급면적은 전용면적 × 1.2로 환산했어요.");
    if (items.includes("molding")) notes.push(measured ? `몰딩 길이는 도면 ${measured.name}에서 방마다 잰 천장 둘레예요. 실측 때 다시 재요.` : "몰딩 길이는 공급 1평에 2.4m로 집 전체를 잡았어요. 실측 때 방마다 다시 재요.");
    if (items.includes("base")) notes.push(measured ? `걸레받이 길이는 도면 ${measured.name}에서 방마다 잰 바닥 둘레예요(문 · 큰 창 뺌). 실측 때 다시 재요.` : "걸레받이 길이는 공급 1평에 1.8m로 집 전체를 잡았어요. 실측 때 방마다 다시 재요.");
    if (items.includes("flatten")) notes.push("평탄화 면적은 전용면적의 30%(거실 천장 정도)로 잡았어요.");
    if (items.includes("door")) notes.push(door_frame ? "문 설치 · 문선은 표준시장단가(재료 제외), 문 자재는 ABS 문 기준 팀 가정값이에요. 문 하나에 문선 양면 10.2m로 잡았어요." : "문짝만 설치는 문 설치 공공 단가의 절반, 문짝 자재는 팀 가정값이에요.");
    notes.push(`하루 목수 ${MG.crew}명이 들어가는 것으로 기간을 잡았어요.`);
    return { trade: "mokgong", ko: "목공", lines: L, ...withVat(sumLines(L)), man_days, crew: MG.crew, steps, days: steps.reduce((a, s) => a + s.half_days, 0) / 2, notes };
  }

  /* ---- 공정표 (calc/schedule.py fix_plan, refprice/holidays.py) ---- */
  const HOLIDAYS = {
    "2026-01-01": "신정", "2026-02-16": "설날 연휴", "2026-02-17": "설날", "2026-02-18": "설날 연휴", "2026-03-02": "삼일절 대체공휴일", "2026-05-05": "어린이날",
    "2026-05-25": "부처님오신날 대체공휴일", "2026-06-03": "전국동시지방선거", "2026-08-17": "광복절 대체공휴일", "2026-09-24": "추석 연휴", "2026-09-25": "추석",
    "2026-09-26": "추석 연휴", "2026-10-05": "개천절 대체공휴일", "2026-10-09": "한글날", "2026-12-25": "성탄절",
    "2027-01-01": "신정", "2027-02-08": "설날 연휴", "2027-02-09": "설날 대체공휴일", "2027-03-01": "삼일절", "2027-05-05": "어린이날", "2027-05-13": "부처님오신날",
    "2027-08-16": "광복절 대체공휴일", "2027-09-14": "추석 연휴", "2027-09-15": "추석", "2027-09-16": "추석 연휴", "2027-10-04": "개천절 대체공휴일",
    "2027-10-11": "한글날 대체공휴일", "2027-12-27": "성탄절 대체공휴일"
  };
  /* 팀 목록(refprice/holidays.py)에 없는 공휴일: 2026-04-28 국무회의 '관공서의 공휴일에 관한 규정' 개정(노동절 · 제헌절).
     2027 대체공휴일은 우주항공청 2027 월력요항 보도 기준. teamOnly 모드에서는 빼서 팀 엔진과 같게 계산한다 */
  const HOLIDAYS_EXTRA = { "2026-05-01": "노동절", "2026-07-17": "제헌절", "2027-05-03": "노동절 대체공휴일", "2027-07-19": "제헌절 대체공휴일" };
  let teamOnly = false;
  const holidayOf = (s) => HOLIDAYS[s] || (!teamOnly && HOLIDAYS_EXTRA[s]) || null;
  const DRY_DAYS = 2, CLEAN_DAYS = 1;
  const iso = (d) => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
  const day = (s) => new Date(s + "T00:00:00Z");
  const addDays = (s, n) => { const d = day(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const isOff = (s, weekendWork = false, extraOff = []) => (!weekendWork && [0, 6].includes(day(s).getUTCDay())) || !!holidayOf(s) || extraOff.includes(s);
  function nextWork(s, o) { let d = s; for (let i = 0; i < 3 * 366 && isOff(d, o.weekendWork, o.avoid); i++) d = addDays(d, 1); return d; }
  const tradeDays = (steps) => Math.floor((steps.reduce((a, s) => a + s.half_days, 0) + 1) / 2);
  /* trades: [{trade, ko, steps, crew, fixed?:{start,end}}] 순서대로. 도배가 있으면 끝난 다음 날부터 달력 2일 건조, 이어서 입주 청소 1일 */
  function fixPlan(trades, start, o = {}) {
    o = { weekendWork: false, avoid: [], ...o };
    const blocks = [], days = new Map(); let cursor = start, prepDone = false;
    for (const t of trades) {
      let steps = t.steps.filter((s) => !(s.key === "prep" && prepDone));
      if (t.steps.some((s) => s.key === "prep")) prepDone = true;
      const n = Math.max(tradeDays(steps), 1), work = [];
      let d = nextWork(t.fixed?.start || cursor, o);
      while (work.length < n) { work.push(d); d = nextWork(addDays(d, 1), o); }
      const halves = steps.flatMap((s) => Array(s.half_days).fill(s.name)), total = halves.length;
      work.forEach((w, k) => {
        let names = halves.filter((_, hI) => Math.floor((hI * n) / total) === k);
        if (!names.length) names = [halves[Math.floor((k * total) / n)]];
        const e = days.get(w) || []; e.push({ trade: t.trade, ko: t.ko, todo: [...new Set(names)] }); days.set(w, e);
      });
      blocks.push({ trade: t.trade, ko: t.ko, kind: "work", start: work[0], end: work[work.length - 1], days: n, crew: t.crew, state: t.state || "expected" });
      cursor = addDays(work[work.length - 1], 1);
    }
    if (trades.some((t) => t.trade === "dobae")) {
      const s = cursor, e = addDays(s, DRY_DAYS - 1);
      blocks.push({ trade: "dry", ko: "자연 건조", kind: "dry", start: s, end: e, days: DRY_DAYS, state: "expected" });
      for (let i = 0; i < DRY_DAYS; i++) days.set(addDays(s, i), [{ trade: "dry", ko: "자연 건조", todo: ["창문을 닫고 자연 건조"] }]);
      cursor = addDays(e, 1);
    }
    blocks.push({ trade: "clean", ko: "입주 청소", kind: "clean", start: cursor, end: addDays(cursor, CLEAN_DAYS - 1), days: CLEAN_DAYS, state: "expected" });
    days.set(cursor, [{ trade: "clean", ko: "입주 청소", todo: ["입주 청소 · 고객이 직접"] }]);
    const out = []; const end = blocks[blocks.length - 1].end;
    for (let d = start; d <= end; d = addDays(d, 1)) out.push({ date: d, off: isOff(d, o.weekendWork, o.avoid), holiday: holidayOf(d), items: days.get(d) || [] });
    return { start, end, blocks, days: out, work_days: blocks.filter((b) => b.kind === "work").reduce((a, b) => a + b.days, 0) };
  }
  /* 기한: 서울 날짜 + N일 18:00 */
  const dueAt = (isoDate, n) => `${addDays(isoDate, n)} 18:00`;
  const percentVs = (amount, std) => std > 0 ? Math.floor(((amount - std) / std) * 1000 + 0.5 + EPS) / 10 : null;
  return { FORMULA_VERSION, PRICE_VER, PYEONG_M2, won, m2, halfUp, halfDays, pyToM2, withVat, fromEntered, sumLines, dobae, mokgong, fixPlan, isOff, nextWork, addDays, iso, day, HOLIDAYS, tradeDays, dueAt, percentVs, DB, MG, HOLIDAYS_EXTRA, setTeamOnly: (v) => { teamOnly = !!v; } };
})();
