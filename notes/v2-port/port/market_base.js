const MARKET = (() => {
  const C = CALC;
  const won = (x) => Math.floor(x + 0.5 + 1e-7), m2 = (x) => Math.floor(x * 10 + 0.5 + 1e-7) / 10;
  const PY = 3.3058;
  /* 기본값(v5 실험 결과로 덮어쓴다). 범위 lo~hi는 '보통 이 정도' 띠를 만들 때 쓴다 */
  const P = {
    version: "market-2026.11-v5.1",
    dobae: {
      area_factor: { silk: 2.24, hapji: 2.16 },      // 공급㎡ → 도배 면적(벽 + 천장). 실견적 롤 수 관행(롤/평 0.53 · 0.50)
      ceiling_share: 0.37,                             // 천장 비중(벽 · 천장 롤이 나뉜 견적)
      labor_wall: 5993, labor_ceiling: 8531,           // 공공 시공 단가(원/㎡)에
      labor_mult: { silk: 0.94, hapji: 0.55 },         // 시장 생산성 보정(합지는 실크의 약 절반 품)
      paper: { silk: 2909, hapji: 1273 },              // 원/㎡(롤 16.5㎡ 기준 자재만)
      paper_ratio: 1.2,
      sub_per_py: { silk: 6700, hapji: 3000 },         // 초배 · 풀 · 부직포 등(원/공급평)
      occupied_mult: 0.02,                             // 짐 있는 집(노무비에)
      balcony_factor: 1.08,
      min_job: 300000,                                 // 집 전체라도 이보다 낮게는 안 받음
      fixed: 0,                                        // 집 크기와 상관없는 고정비(출장 · 준비 · 보양). 0이면 줄을 넣지 않음
      // 2025년 이후 실견적(3 · 4차 806건): 실제 ÷ 시장 기준의 중간 50% · 80%. 출처마다 같은 무게(한 출처 쏠림 막기)
      // 출처 하나씩 빼고 시험: 중간 50% 띠 안 51%, 80% 띠 안 78%
      band: { silk: { lo: 0.89, hi: 1.27, lo80: 0.80, hi80: 1.53 }, hapji: { lo: 0.90, hi: 1.19, lo80: 0.82, hi80: 1.44 } },
      checked: { silk: 679, hapji: 127, year: "2025~2026" },
      band_plan: { silk: { lo: 0.95, hi: 1.35, lo80: 0.83, hi80: 1.63, n: 604 }, hapji: { lo: 0.85, hi: 1.15, lo80: 0.78, hi80: 1.32, n: 110 } }
    },
    mokgong: {
      molding_per_py: 2.4, base_per_py: 1.8,
      molding_m: 13000,                                // 원/m(시공 + 자재)
      base_m: 5837,                                    // 원/m(공공 시공 3,757 + 자재 2,080)
      base_only_min: 400000,
      door_set: 400000, door_leaf: 195000,             // 원/개(공급가, ABS)
      doors_default: (py) => (py < 28 ? 4 : py < 38 ? 5 : 6),
      flatten_per_m2: 31991,                           // 공공과 같음(실견적 2건뿐)
      removal_lump: 0,                                 // 철거 · 폐기물은 견적마다 달라 '맞춰 보기'에서 따로(6만~20만 원). 실험에서 넣지 않을 때가 더 맞음
      overhead: 0.0,
      band: { lo: 0.80, hi: 1.25, lo80: 0.6, hi80: 1.5 },   // 계산 항목만 있는 목공 견적 36건(적어서 넓게)
      checked: { pure: 36 },
      /* 흔한 추가 항목(4차 실견적 줄별 내역, 부가세 별도 공급가). per: 곳 = 곳 수만큼, 식 = 한 번. n = 근거 줄 수 */
      extras: [
        { key: "jungmun", name: "현관 중문(3연동)", per: "식", lo: 900000, hi: 1100000, n: 4 },
        { key: "aircon", name: "에어컨 단내림", per: "곳", lo: 400000, hi: 550000, n: 4 },
        { key: "wall", name: "가벽(문 포함)", per: "곳", lo: 1300000, hi: 1700000, n: 2 },
        { key: "insul", name: "단열(방 · 확장부)", per: "곳", lo: 500000, hi: 1500000, n: 7 },
        { key: "artwall", name: "아트월 · TV 매립", per: "식", lo: 550000, hi: 1000000, n: 4 },
        { key: "lightbox", name: "간접등 박스", per: "식", lo: 300000, hi: 800000, n: 3 }
      ],
      casing9: { with_door: [50000, 150000], alone: [150000, 220000] }   // 9mm 문선(문당). 문 교체와 함께면 차액만
    }
  };
  /* 받은 견적 맞춰 보기용: 고른 추가 항목의 범위를 더한다. picks = { key: 곳 수 }, casing = { doors, with_door } */
  function extrasRange(picks = {}, casing = null, p = P.mokgong) {
    let lo = 0, hi = 0; const notes = [];
    for (const e of p.extras) {
      const c = picks[e.key]; if (!c) continue;
      const k = e.per === "곳" ? c : 1;
      lo += e.lo * k; hi += e.hi * k;
      notes.push(`${e.name}${e.per === "곳" ? ` ${k}곳` : ""}: ${e.per === "곳" ? "곳당 " : ""}${e.lo / 10000}만~${e.hi / 10000}만 원 (실견적 ${e.n}줄${e.n < 4 ? ", 근거 적음" : ""})`);
    }
    if (casing && casing.doors > 0) {
      const [a, b] = casing.with_door ? p.casing9.with_door : p.casing9.alone;
      lo += a * casing.doors; hi += b * casing.doors;
      notes.push(`9mm 문선 ${casing.doors}개: 문당 ${a / 10000}만~${b / 10000}만 원${casing.with_door ? " (문 교체 값에 더 붙는 만큼)" : ""}`);
    }
    return { lo, hi, notes };
  }
  const L = (key, name, qty, unit, unit_price, amount, note) => ({ key, name, qty, unit, unit_price, amount, note });
  function dobae({ area_m2, area_basis = "supply", grade = "basic", include_ceiling = true, occupied = false, balcony_ext = false, measured = null }, p = P.dobae) {
    const g = grade === "economy" || grade === "hapji" ? "hapji" : "silk";
    const supply_m2 = area_basis === "supply" ? area_m2 : area_m2 * 1.2;
    const py = supply_m2 / PY;
    let gross = supply_m2 * p.area_factor[g]; if (balcony_ext) gross *= p.balcony_factor;
    let ceiling = m2(gross * p.ceiling_share), wall = m2(m2(gross) - ceiling);
    if (measured) { wall = m2(measured.wall_m2); ceiling = m2(measured.ceiling_m2); gross = wall + ceiling; } // v9: 도면에서 잰 면적
    const ceilUsed = include_ceiling ? ceiling : 0;
    const paperArea = m2(wall + ceilUsed), paperQty = m2(paperArea * p.paper_ratio);
    const lw = won(p.labor_wall * p.labor_mult[g]), lc = won(p.labor_ceiling * p.labor_mult[g]);
    const lines = [
      L("wall", "벽 도배 시공", wall, "㎡", lw, won(wall * lw), measured ? `도면 ${measured.name}에서 잰 벽 면적` : `도배 면적 = 공급 ${m2(supply_m2)}㎡ × ${p.area_factor[g]} (롤 수 관행)`),
      L("ceiling", "천장 도배 시공", ceilUsed, "㎡", lc, won(ceilUsed * lc), measured ? `도면에서 잰 천장 면적` : `천장 = 도배 면적 × ${p.ceiling_share}`),
      L("paper", `벽지 (${g === "hapji" ? "합지" : "실크"})`, paperQty, "㎡", p.paper[g], won(paperQty * p.paper[g]), "바를 면적 × 1.2"),
      L("sub", "초배 · 풀 · 부자재", m2(py), "평", p.sub_per_py[g], won(py * p.sub_per_py[g]), "공급평당")
    ];
    if (p.fixed) lines.push(L("fixed", "출장 · 준비 · 보양", null, "식", null, p.fixed, "집 크기와 상관없이 한 번"));
    if (occupied) lines.push(L("occupied", "짐 있는 집 작업", null, "식", null, won((lines[0].amount + lines[1].amount) * p.occupied_mult), "노무비의 2%"));
    let supply = lines.reduce((a, l) => a + l.amount, 0);
    if (supply < p.min_job) { lines.push(L("min", "최소 작업 금액 맞춤", null, "식", null, p.min_job - supply, "")); supply = p.min_job; }
    const r1000 = (x) => Math.round(x / 10000) * 10000;
    const b = (measured && p.band_plan && p.band_plan[g]) || p.band[g] || p.band;
    return { trade: "dobae", grade: g, lines, supply, lo: r1000(supply * b.lo), hi: r1000(supply * b.hi), band: b, version: P.version };
  }
  function mokgong({ area_m2, area_basis = "supply", items = ["molding", "base"], doors = 0, door_frame = true, measured = null }, p = P.mokgong) {
    const supply_m2 = area_basis === "supply" ? area_m2 : area_m2 * 1.2, py = supply_m2 / PY, excl = supply_m2 / 1.2;
    const lines = [];
    if (items.includes("molding")) { const len = measured ? m2(measured.molding_m) : m2(py * p.molding_per_py); lines.push(L("molding", "천장 몰딩 (시공 + 자재)", len, "m", p.molding_m, won(len * p.molding_m), measured ? `도면 ${measured.name}에서 잰 천장 둘레` : `공급 ${m2(py)}평 × ${p.molding_per_py}m`)); }
    if (items.includes("base")) { const len = measured ? m2(measured.base_m) : m2(py * p.base_per_py); lines.push(L("base", "걸레받이 (시공 + 자재)", len, "m", p.base_m, won(len * p.base_m), measured ? `도면 ${measured.name}에서 잰 바닥 둘레` : `공급 ${m2(py)}평 × ${p.base_per_py}m`)); }
    if (items.includes("door")) { const n = doors || p.doors_default(py); lines.push(L("door", door_frame ? "방문 (문틀 · 문짝 · 문선)" : "방문 (문짝만)", n, "개", door_frame ? p.door_set : p.door_leaf, won(n * (door_frame ? p.door_set : p.door_leaf)), doors ? "" : "방 + 욕실 수로 어림")); }
    if (items.includes("flatten")) { const a = m2(excl * 0.3); lines.push(L("flatten", "천장 평탄화", a, "㎡", p.flatten_per_m2, won(a * p.flatten_per_m2), "전용 × 0.3")); }
    if (p.removal_lump > 0 && items.some((i) => ["molding", "base", "door", "flatten"].includes(i))) lines.push(L("removal", "철거 · 폐기물 · 양중", null, "식", null, p.removal_lump, "시장 관행 한 번"));
    let supply = lines.reduce((a, l) => a + l.amount, 0);
    if (p.overhead) { const o = won(supply * p.overhead); lines.push(L("overhead", "공과잡비 · 이윤", null, "식", null, o, "")); supply += o; }
    if (items.length === 1 && items[0] === "base" && supply < p.base_only_min) { lines.push(L("min", "최소 작업 금액 맞춤", null, "식", null, p.base_only_min - supply, "")); supply = p.base_only_min; }
    const r = (x) => Math.round(x / 10000) * 10000;
    return { trade: "mokgong", lines, supply, lo: r(supply * p.band.lo), hi: r(supply * p.band.hi), band: p.band, version: P.version };
  }
  return { P, dobae, mokgong, extrasRange };
})();
