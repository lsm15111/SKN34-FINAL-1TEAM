// 기본 정보(C02 · D11) 값 · 검사 · 요약 글. 서버 · 브라우저가 같이 써요.
// 금액 · 수량은 여기서 만들지 않아요(서버 계산 엔진). 단위만 바꿔요: 평 → ㎡(넣기 도움, C03) · 만 원 → 원(예산 칸).
// 칸 이름은 API HomeInfoIn과 같아요(dev-03 mj_guest_v3 info). 넣는 동안은 덜 찬 값도 두니 Draft로 따로 둬요.
import type { Schemas } from "@/lib/backend/client";
import { dateShort, decText, won } from "@/lib/format";

export type HomeInfo = Schemas["HomeInfoIn"];
export type HomeInfoSaved = Schemas["HomeInfoOut"];
export type SpaceKind = HomeInfo["spaces"][number];
export type Face = HomeInfo["faces"][number];
export type Grade = HomeInfo["grade"];
export type Basis = HomeInfo["area_basis"];
/** 방 개수 칸 범위 · 평형 기본값 표(GET /guest/room-rule, 서버 계산 엔진 판) */
export type RoomRule = Schemas["RoomRuleOut"];
/** 철거 범위(v4 첫 대화 집 정보 카드). 백엔드 담당이 HomeInfoIn에 같은 키로 더해요 */
export type Demolition = "full" | "partial" | "none";
/** API 몸통 + 철거 범위(백엔드가 칸을 더하기 전에는 lib/guest/api sendHome이 빼고 다시 보내요) */
export type HomeBody = HomeInfo & { demolition?: Demolition };
const demolitionOf = (v: unknown): Demolition | null => (v === "full" || v === "partial" || v === "none" ? v : null);

/** 공사 희망 시기 칩(GET /guest/start-options, 날짜는 계산 엔진) */
export type StartWish = Schemas["StartWishOut"];
export type WishKey = StartWish["key"];
/** 공사 희망 시기 고른 것: 칩 · 아직 몰라요 · 날짜 고르기(v4 첫 대화) */
export type StartPick = WishKey | "unknown" | "date";
export const WISH_LABEL: Record<WishKey, string> = { this_month: "이번 달", next_month: "다음 달", in_2_3_months: "2~3달 뒤" };
export const START_PICKS: readonly StartPick[] = ["this_month", "next_month", "in_2_3_months", "unknown", "date"];

/** 직접 할 일(반셀프 칩). 키 · 이름 · 순서는 backend project/diy.py DIY와 같아요(새 칩은 끝에).
 *  벽지 직접 구매(paper_buy)를 고르면 표준견적서 도배지 줄이 '고객 구매'로 빠져요(계산 엔진) */
export type DiyKey = NonNullable<HomeInfo["diy"]>[number];
export const DIY: { key: DiyKey; label: string }[] = [
  { key: "paint", label: "페인트(문틀 · 몰딩)" },
  { key: "outlet", label: "콘센트 · 스위치 커버" },
  { key: "light", label: "조명 교체" },
  { key: "silicone", label: "실리콘 · 줄눈" },
  { key: "handle", label: "손잡이 · 문고리" },
  { key: "clean", label: "입주 청소" },
  { key: "paper_buy", label: "벽지 직접 구매" },
];
/** 고른 직접 할 일 글(내 말 줄): '페인트(문틀 · 몰딩), 입주 청소' · 빈 목록이면 '없어요' */
export const diyText = (keys: readonly string[]): string => DIY.filter((x) => keys.includes(x.key)).map((x) => x.label).join(", ") || "없어요";
/** 모은 조건 키(GET /projects/{id}/conditions의 diy.*) → 고른 직접 할 일(DIY 순서). 줄이 없으면 null(아직 안 물음),
 *  '없어요'(diy.none)만이면 빈 목록. 서버 project/diy.py picked_of와 같아요 */
export function diyOfKeys(keys: readonly string[]): DiyKey[] | null {
  const got = new Set(keys.filter((k) => k.startsWith("diy.")));
  return got.size ? DIY.map((x) => x.key).filter((k) => got.has(`diy.${k}`)) : null;
}
/** 고치기 화면의 직접 할 일 칩(첫 대화와 같은 칩 + 없어요) · 그 묶음 id(보드에서 열면 처음 초점) */
export const DIY_CHIPS: { value: string; label: string }[] = [...DIY.map((x) => ({ value: x.key, label: x.label })), { value: "none", label: "없어요" }];
export const DIY_FIELD_ID = "inf-diy";
/** 직접 할 일 칩에 켜 둘 값: 고른 칩 · 없어요(빈 목록) · 아직 안 물었으면 아무것도 */
export const diyPicks = (diy: readonly DiyKey[] | null | undefined): string[] => (diy == null ? [] : diy.length ? [...diy] : ["none"]);
/** 칩을 누른 뒤 값: '없어요'는 다른 칩과 같이 고르지 않고, 다 끄면 '없어요'(빈 목록)예요 */
export function diyFromPicks(next: readonly string[], prev: readonly string[]): DiyKey[] {
  if (next.find((x) => !prev.includes(x)) === "none") return [];
  return DIY.map((x) => x.key).filter((k) => next.includes(k));
}
/** 철거 범위 글(요약 줄 · 보드, 서버 calc.dobae.DEMOLITION과 같은 말) */
export const DEMOLITION_TEXT: Record<Demolition, string> = { full: "전체 철거", partial: "부분 철거", none: "철거 안 함" };

/** 넣는 중인 답(기기에 저장하는 모양). 다 차면 toHomeInfo로 API 몸통이 돼요 */
export type InfoDraft = {
  scope: "full" | "partial";
  spaces: SpaceKind[];
  faces: Face[];
  /** 방 개수 1~5. 비우면 면적으로 채운 기본값(roomsOf) */
  rooms: number | null;
  sido: string;
  sgg: string;
  emd: string;
  /** 사람이 넣은 ㎡ 글 그대로("69.4") */
  area: string;
  basis: Basis;
  occupied: boolean | null;
  grade: Grade | null;
  /** 만 원 글 그대로("300"). 비우면 '아직 몰라요' */
  budget: string;
  /** 서울 날짜 "2027-01-04". 비우면 '아직 몰라요' */
  start: string | null;
  /** 철거 범위(v4 첫 대화에서만 물어요. 없으면 보내지 않아요) */
  demolition?: Demolition | null;
  /** 공사 희망 시기 고른 것(v4 첫 대화). 칩이면 start는 그 칩의 계산 엔진 날짜, 아직 몰라요면 start 비움 */
  when?: StartPick | null;
  /** 직접 할 일(v4 첫 대화, 표준견적서 뒤). 안 물었으면 null · 없어요면 빈 목록 */
  diy?: DiyKey[] | null;
};

export const EMPTY_DRAFT: InfoDraft = {
  scope: "full", spaces: [], faces: ["wall", "ceiling"], rooms: null, sido: "", sgg: "", emd: "",
  area: "", basis: "supply", occupied: null, grade: null, budget: "", start: null,
};

export const SPACES: { key: SpaceKind; label: string }[] = [
  { key: "living", label: "거실" }, { key: "kitchen", label: "주방" }, { key: "master", label: "안방" },
  { key: "room1", label: "작은방 1" }, { key: "room2", label: "작은방 2" }, { key: "room3", label: "작은방 3" },
  { key: "room4", label: "작은방 4" }, { key: "hall", label: "복도" },
  { key: "entry", label: "현관" }, { key: "dress", label: "드레스룸" },
];
export const FACES: { key: Face; label: string }[] = [{ key: "wall", label: "벽" }, { key: "ceiling", label: "천장" }];
export const spaceLabel = (k: string) => SPACES.find((s) => s.key === k)?.label ?? k;
/** API를 못 읽었을 때: 칸 범위 · 방 칩 순서만(기본값 표는 비워 두고 fallback 3개) */
export const ROOM_RULE_EMPTY: RoomRule = {
  price_ver: "", share_ver: "", min: 1, max: 5, fallback: 3, bands: [],
  room_kinds: ["master", "room1", "room2", "room3", "room4"],
};

/** 화면에 보이는 방 개수: 넣은 값, 없으면 면적으로 표에서 찾은 기본값(서버 calc.dobae.default_rooms와 같은 표) */
export function roomsOf(d: Pick<InfoDraft, "rooms" | "area" | "basis" | "spaces">, rule: RoomRule): number {
  if (d.rooms) return d.rooms;
  const n = Number(d.area.trim());
  let r = rule.fallback;
  if (d.area.trim() && Number.isFinite(n) && n > 0) {
    const bands = rule.bands.filter((b) => b.area_basis === d.basis);
    if (bands.length) r = bands.reduce((acc, b) => (n >= Number(b.min_m2) ? b.rooms : acc), bands[0].rooms);
  }
  // 고른 방 칩이 더 많으면 그만큼(옛 공사 호환, 서버 rooms_of와 같음)
  const need = Math.max(0, ...d.spaces.map((k) => rule.room_kinds.indexOf(k) + 1));
  return Math.min(Math.max(r, need), rule.max);
}

/** 방 개수에 맞춘 공간 칩: 거실 · 주방 · 안방 · 작은방 1 … · 복도 · 현관 · 드레스룸 */
export function chipsFor(rooms: number, rule: RoomRule): SpaceKind[] {
  const rk = rule.room_kinds.slice(0, rooms) as SpaceKind[];
  return ["living", "kitchen", ...rk, "hall", "entry", "dress"];
}

/** 켠 칩 · 면 → 범위. 칩을 다 켜고 벽 + 천장이면 전체, 아니면 부분(켠 칩만) */
export function scopeOf(on: SpaceKind[], faces: Face[], chips: SpaceKind[]): Pick<InfoDraft, "scope" | "spaces" | "faces"> {
  const spaces = chips.filter((k) => on.includes(k));
  const both = faces.includes("wall") && faces.includes("ceiling");
  if (spaces.length === chips.length && both) return { scope: "full", spaces: [], faces: ["wall", "ceiling"] };
  return { scope: "partial", spaces, faces: FACES.map((f) => f.key).filter((f) => faces.includes(f)) };
}

/** 켜진 칩(전체면 모두) */
export const onChips = (d: Pick<InfoDraft, "scope" | "spaces">, chips: SpaceKind[]): SpaceKind[] => (d.scope === "full" ? chips : chips.filter((k) => d.spaces.includes(k)));

export const GRADE_WORD: Record<Grade, string> = { economy: "합지", basic: "실크" };

/** 면 글: 벽 + 천장 · 벽만 · 천장만 */
export function facesText(faces: readonly string[]): string {
  const w = faces.includes("wall");
  const c = faces.includes("ceiling");
  return w && c ? "벽 + 천장" : w ? "벽만" : c ? "천장만" : "";
}

/** 공사 범위 글: '전체 · 벽 + 천장' · '부분 · 거실 · 주방 · 벽만' */
export function scopeText(d: Pick<InfoDraft, "scope" | "spaces" | "faces">): string {
  if (d.scope === "full") return "전체 · 벽 + 천장";
  return ["부분", ...d.spaces.map(spaceLabel), facesText(d.faces)].filter(Boolean).join(" · ");
}

/** ㎡ 글 → 화면 글 "69.4" (끝 0 정리 없이 넣은 그대로, 소수 한 자리) */
const AREA_RE = /^\d{1,3}(\.\d)?$/;

/** 평 → ㎡ 넣기 도움(C03): 21 → "69.4". 계산 · 견적서는 ㎡로 하고, 평은 넣을 때만 써요. 숫자가 아니면 null */
export const PYEONG_M2 = 3.3058;
export function pyeongToM2(p: string): string | null {
  const n = Number(p.trim());
  if (!p.trim() || !Number.isFinite(n) || n <= 0 || n >= 1000) return null;
  return (Math.round(n * PYEONG_M2 * 10) / 10).toFixed(1);
}

/** 숫자 뒤 을/를: 마지막 자리를 읽는 소리로 골라요(69.4 → 를, 70 → 을) */
export function numEulReul(n: string): string {
  const last = n.trim().slice(-1);
  return "2459".includes(last) ? "를" : "을";
}

/** 만 원 글 → 원(서버 칸 budget_won). 비우면 null */
export function budgetWon(budget: string): number | null {
  const t = budget.replace(/[,\s]/g, "");
  return t ? Number(t) * 10000 : null;
}

export type InfoErrors = Partial<Record<"spaces" | "faces" | "region" | "area" | "occupied" | "grade" | "budget", string>>;
/** 틀린 칸 순서(첫 칸으로 초점을 옮겨요, I6 B) */
export const ERROR_ORDER: (keyof InfoErrors)[] = ["spaces", "faces", "region", "area", "occupied", "grade", "budget"];
export const ERROR_NAME: Record<keyof InfoErrors, string> = { spaces: "공간", faces: "면", region: "지역", area: "면적", occupied: "공사할 때 집", grade: "벽지", budget: "예산" };

/** 제출할 때 한 번 검사해요(I6 B). 오류 글은 [무엇이 문제] + [고치는 법](U5) */
export function checkDraft(d: InfoDraft): InfoErrors {
  const e: InfoErrors = {};
  if (d.scope === "partial") {
    if (!d.spaces.length) e.spaces = "공간을 하나 이상 켜 주세요.";
    if (!d.faces.length) e.faces = "벽 · 천장 중 하나 이상 골라 주세요.";
  }
  if (!d.sido || !d.sgg) e.region = "지역을 골라 주세요. 시 · 도와 시 · 군 · 구를 골라요.";
  const a = d.area.trim();
  const n = Number(a);
  const guessText = (v: number) => v.toFixed(1).replace(/\.0$/, "");
  if (!a) e.area = "면적을 넣어 주세요. 평으로 알면 칸 옆 단위를 '평'으로 바꿔요.";
  else if (!/^\d+(\.\d+)?$/.test(a) || !Number.isFinite(n)) e.area = "숫자로 넣어 주세요. 예: 69.4";
  else if (n <= 10) {
    const g = guessText(n * 10);
    e.area = n * 10 > 10 && n * 10 < 400 ? `방 한 칸보다 작아요. ${g}${numEulReul(g)} 넣으려던 건가요?` : "방 한 칸보다 작아요. 10㎡보다 크게 넣어 주세요.";
  } else if (n >= 400) {
    const g = guessText(n / 10);
    e.area = n / 10 > 10 && n / 10 < 400 ? `아파트 한 집보다 커요. ${g}${numEulReul(g)} 넣으려던 건가요?` : "400㎡보다 작게 넣어 주세요.";
  } else if (!AREA_RE.test(a)) e.area = "소수점은 한 자리까지 넣어 주세요. 예: 69.4";
  if (d.occupied === null) e.occupied = "공사할 때 집에 사는지 골라 주세요.";
  if (!d.grade) e.grade = "벽지를 골라 주세요. 합지 · 실크 중 하나예요.";
  const b = d.budget.replace(/[,\s]/g, "");
  if (b) {
    if (!/^\d{1,6}$/.test(b)) e.budget = "예산은 만 원 단위 숫자로 넣어 주세요. 예: 300";
    else if (Number(b) < 10) e.budget = "예산은 10만 원부터 넣을 수 있어요. 모르면 '아직 몰라요'를 골라요.";
  }
  return e;
}

/** 검사를 지난 답 → API 몸통(POST /guest/standard · POST /projects와 같은 칸). 철거 범위 · 직접 할 일은 고른 때만 붙여요 */
export function toHomeInfo(d: InfoDraft): HomeBody {
  const partial = d.scope === "partial";
  return {
    ...(d.demolition ? { demolition: d.demolition } : {}),
    ...(d.diy ? { diy: d.diy } : {}),
    trade: "dobae",
    scope: d.scope,
    spaces: partial ? d.spaces : [],
    faces: partial ? d.faces : ["wall", "ceiling"],
    rooms: d.rooms,
    housing: "apt",
    sido: d.sido,
    sgg: d.sgg, // 동은 보내지 않아요(시 · 군 · 구까지만 받아요)
    area_m2: d.area.trim(),
    area_basis: d.basis,
    occupied: d.occupied === true,
    grade: d.grade ?? "basic",
    budget_won: budgetWon(d.budget),
    start_date: d.start,
  };
}

/** 고치기(PATCH /projects/{id}) 몸통. 동은 이 폼에서 받지 않지만 비서 대화로 받아 둔 동은 지켜요(안 보내면 지워져 공사 이름이
 *  '상계동 …'에서 '노원구 …'로 바뀌어요). 지역을 다시 고르면 폼이 동을 비워요 */
export function toEditBody(d: InfoDraft): HomeBody {
  return { ...toHomeInfo(d), ...(d.emd ? { emd: d.emd } : {}) };
}

/** 저장된 공사의 v3 기본 정보 → 넣는 중인 답(고치기 C02 · ?edit=) */
export function fromSaved(h: HomeInfoSaved): InfoDraft {
  return {
    scope: h.scope,
    spaces: h.spaces,
    faces: h.faces.length ? h.faces : ["wall", "ceiling"],
    rooms: h.rooms ?? null,
    sido: h.sido,
    sgg: h.sgg,
    emd: h.emd ?? "",
    area: String(h.area_m2).replace(/(\.\d)0+$/, "$1"),
    basis: h.area_basis === "exclusive" ? "exclusive" : "supply",
    occupied: h.occupied,
    grade: h.grade,
    budget: h.budget_won ? String(Math.round(h.budget_won / 10000)) : "",
    start: h.start_date,
    demolition: demolitionOf((h as { demolition?: unknown }).demolition),
  };
}

/** 고치기(/start?edit= · 대화 안 '우리 집 정보' 창)의 처음 값. v2로 만든 공사(기본 정보 v3 칸이 비었음)는 옛 칸에서 모아요 */
export function draftOfProject(p: Schemas["ProjectOut"]): InfoDraft {
  if (p.home) return fromSaved(p.home);
  return {
    ...EMPTY_DRAFT,
    sido: p.sido, sgg: p.sgg, emd: p.emd ?? "",
    area: p.size.m2 ? decText(String(p.size.m2)) : "",
    basis: p.size.basis === "exclusive" ? "exclusive" : "supply",
    occupied: p.occupied, grade: p.trades.dobae?.grade ?? null,
    budget: p.budget_won ? String(Math.round(p.budget_won / 10000)) : "",
    start: p.when.kind === "date" ? p.when.start ?? null : null,
  };
}

const placeOf =(d: Pick<InfoDraft, "sgg">) => d.sgg;
const areaOf = (d: Pick<InfoDraft, "area" | "basis">) => (d.area.trim() ? `${d.basis === "exclusive" ? "전용" : "공급"} ${d.area.trim()}㎡` : "");

/** 폰 아래 띠 요약 한 줄(C02): '도배 · 전체 · 벽 + 천장 · 아파트 · 상계동 공급 69.4㎡ · 빈 집 · 실크 · 예산 300만 원 · 1.4(월) 시작'. 안 넣은 칸은 빼요 */
export function summaryLine(d: InfoDraft): string {
  const place = [placeOf(d), areaOf(d)].filter(Boolean).join(" ");
  const budget = budgetWon(d.budget);
  return [
    "도배",
    scopeText(d),
    "아파트",
    place,
    d.occupied === null ? "" : d.occupied ? "사는 중" : "빈 집",
    d.grade ? GRADE_WORD[d.grade] : "",
    budget ? `예산 ${won(budget)}` : "",
    d.start ? `${dateShort(d.start)} 시작` : "",
  ].filter(Boolean).join(" · ");
}

/** 웹 '넣은 내용' 칸(D11) · 잠긴 기본 정보(C50)가 같이 쓰는 줄. 철거 범위 · 직접 할 일은 고른 때만 */
export function summaryRows(d: InfoDraft, opts: { longDate?: string; fullRegion?: string; rooms?: number } = {}): { label: string; value: string; sub?: string }[] {
  const budget = budgetWon(d.budget);
  const rooms = d.rooms ?? opts.rooms;
  const more = [
    ...(d.demolition ? [{ label: "철거 범위", value: DEMOLITION_TEXT[d.demolition] }] : []),
    ...(d.diy ? [{ label: "직접 할 일", value: diyText(d.diy) }] : []),
  ];
  return [
    { label: "공사 종류", value: "도배" },
    { label: "공사 범위", value: scopeText(d) },
    { label: "방 개수", value: rooms ? `${rooms}개` : "" },
    { label: "주거 종류", value: "아파트" },
    { label: "지역", value: opts.fullRegion ?? placeOf(d) },
    { label: "면적", value: areaOf(d) },
    { label: "공사할 때 집", value: d.occupied === null ? "" : d.occupied ? "사는 중" : "빈 집" },
    { label: "벽지", value: d.grade ? GRADE_WORD[d.grade] : "" },
    { label: "예산", value: budget ? won(budget) : d.budget.trim() ? "" : "아직 몰라요" },
    { label: "공사 시작 희망일", value: d.start ? opts.longDate ?? dateShort(d.start) : "아직 몰라요" },
    ...more,
  ];
}

type RegionList = { id: string; name: string; groups: { prefix: string; items: string[] }[] }[];
/** 지역 글 '서울 노원구' · '광주 광산구' · '세종 세종시'(지역 표의 이름을 써요, 동은 받지 않아요) */
export function placeText(regions: RegionList, p: { sido: string; sgg: string }): string {
  const r = regions.find((x) => x.id === p.sido);
  if (!r) return "";
  const g = r.groups.find((x) => x.items.includes(p.sgg));
  const head = p.sgg ? (g?.prefix ? [g.prefix, p.sgg] : [r.name, p.sgg]) : [r.name];
  return head.filter(Boolean).join(" ");
}

export const STEP_NAMES = ["기본 정보", "표준견적서", "업체 담기", "실측 일정", "실측", "실측 뒤"];
/** API 단계 번호(MyProjectOut.current, 1~6) → 단계 띠 칸(0~5) */
export const stepIndex = (current: number | null | undefined): number => Math.max(0, Math.min(5, (current ?? 2) - 1));
/** API 단계 번호 → 단계 이름 '업체 담기' */
export const stepName = (current: number | null | undefined): string => STEP_NAMES[stepIndex(current)];

/** 공사 이름 '상계동 아파트 도배'(동이 없으면 구) */
export function projectName(emd: string | null | undefined, region: string, trades: string[]): string {
  const place = emd || region.split(" ").at(-1) || region;
  const t = trades.length ? trades.map((k) => (k === "dobae" ? "도배" : k === "mokgong" ? "목공" : k)).join(" · ") : "도배";
  return `${place} 아파트 ${t}`;
}

/** 표준견적서 위 '이 조건으로 계산했어요' 줄(C07 · C57 · C60): '도배 전체 · 아파트 공급 69.4㎡ · 실크 · 빈 집' */
export function conditionText(h: { scope: string; spaces: readonly string[]; faces: readonly string[]; area_m2: string | number; area_basis: string; grade: string | null; occupied: boolean; rooms?: number | null }): string {
  const area = `${h.area_basis === "exclusive" ? "전용" : "공급"} ${String(h.area_m2).replace(/(\.\d)0+$/, "$1")}㎡${h.rooms ? ` · 방 ${h.rooms}개` : ""}`;
  const grade = h.grade === "economy" || h.grade === "basic" ? GRADE_WORD[h.grade] : "";
  if (h.scope === "partial") {
    return [`도배 부분`, ...h.spaces.map(spaceLabel), facesText(h.faces), `아파트 ${area}`, grade].filter(Boolean).join(" · ");
  }
  return [`도배 전체`, `아파트 ${area}`, grade, h.occupied ? "사는 중" : "빈 집"].filter(Boolean).join(" · ");
}
