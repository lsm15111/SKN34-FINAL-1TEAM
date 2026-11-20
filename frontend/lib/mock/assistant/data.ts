// v4 비서 목업 값. 예시 숫자 · 날짜 · 업체는 모두 여기에만 둬요(계산 엔진 값이 아니에요).
// 화면 코드는 이 값을 직접 읽지 않고 lib/api/assistant.ts를 거쳐 받아요.

/** 서울 시각 문자열 */
export const T = (day: string, hm = "09:00") => `${day}T${hm}:00+09:00`;

export const HOME = {
  hits: [
    { id: "addr-1", name: "상계 푸른숲마을 7단지", road: "서울 노원구 상계숲길 27" },
    { id: "addr-2", name: "상계 푸른숲마을 6단지", road: "서울 노원구 상계숲길 15" },
    { id: "addr-3", name: "푸른숲 상계", road: "서울 노원구 동일로 1702" },
  ],
  complex: { name: "상계 푸른숲마을 7단지", road: "서울 노원구 상계숲길 27", households: 1284, approved_year: 1997, corridor: "계단식" },
  dongs: ["701동", "702동", "703동", "704동"],
  area: { exclusive_m2: "84.97", supply_m2: "112.40", pyeong_type: "34평형" },
  pyeongs: ["24평형", "32평형", "34평형", "40평형"],
  sources: ["건축물대장", "공동주택 단지 정보"],
};

export const STANDARD = {
  total_won: 3_148_560,
  label: "도배 · 실크 · 전용 84.97㎡ · 살면서 공사",
  lines: [
    { name: "벽지 · 풀", won: 1_412_300 },
    { name: "도배 품(기능공 6품)", won: 1_236_000 },
    { name: "짐 옮기기 · 보양", won: 213_000 },
  ],
  decided: ["벽지는 실크로 정했어요", "살면서 하는 공사예요"],
};

export type MockVendor = { key: string; id: string; name: string; photo: string; rating: number; reviews: number; done: number; est: number; reasons: string[]; badge?: string };
export const VENDORS: MockVendor[] = [
  { key: "gyeol", id: "v4m-gyeol", name: "결도배", photo: "/v2/img/looks/mw01.jpg", rating: 4.7, reviews: 23, done: 31, est: 4_182_300, reasons: ["세 곳 중 가견적이 가장 낮아요", "보통 하루 안에 답해요"] },
  { key: "bareun", id: "v4m-bareun", name: "바른벽", photo: "/v2/img/looks/nw01.jpg", rating: 4.9, reviews: 12, done: 18, est: 4_398_000, reasons: ["상계동에서 시공 12건", "실측 출장비가 없어요"] },
  { key: "maru", id: "v4m-maru", name: "마루와벽", photo: "/v2/img/looks/hg01.jpg", rating: 4.8, reviews: 41, done: 57, est: 4_615_500, reasons: ["리뷰 41개 · 별점 4.8", "날짜를 고르면 바로 확정돼요"], badge: "바로 확정" },
];
export const vendorOf = (key: string) => VENDORS.find((v) => v.key === key) ?? VENDORS[0];

export const PHOTOS = ["/v2/img/tone/room1.jpg", "/v2/img/tone/room2.jpg", "/v2/img/tone/room3.jpg", "/v2/img/tone/room4.jpg"];

/** 희망 기간 · 실측 후보(계산 엔진 calc.slots 몫) */
export const WISH = { start: "2026-11-23", end: "2026-12-04", work_wish_on: "2026-12-18", move_in: "2026-12-26" };
export const SLOTS = [
  { ref: "s1", vendor: "gyeol", day: "2026-11-24", half: "am" as const, why: ["공사 시작 24일 전이에요", "다른 실측과 안 겹쳐요"] },
  { ref: "s2", vendor: "gyeol", day: "2026-11-25", half: "pm" as const, why: ["다른 실측과 안 겹쳐요"] },
  { ref: "s3", vendor: "gyeol", day: "2026-11-26", half: "am" as const, why: ["평일 오전이에요"] },
];
export const MARU_SLOTS = [
  { ref: "m1", vendor: "maru", day: "2026-11-25", half: "am" as const, why: ["업체가 낸 날이에요", "다른 실측과 안 겹쳐요"] },
  { ref: "m2", vendor: "maru", day: "2026-11-26", half: "pm" as const, why: ["업체가 낸 날이에요"] },
];

/** 실측 견적서(업체가 적은 칸 + 계산 엔진 합계 · 차액) */
export const QUOTES = {
  gyeol1: { version: 1, received_on: "2026-11-26", total_won: 4_180_000, diff_vs_estimate_won: -2_300, days: 2, valid_until: "2026-12-31", demolish: true, waste: true, paper: "LX 베스띠", warranty_months: 12, file: "PDF" },
  gyeol2: { version: 2, received_on: "2026-11-26", total_won: 4_290_000, diff_vs_estimate_won: 107_700, days: 2, valid_until: "2026-12-31", demolish: true, waste: true, paper: "LX 베스띠", warranty_months: 12, file: "PDF" },
  bareun1: { version: 1, received_on: "2026-11-25", total_won: 4_510_000, diff_vs_estimate_won: 112_000, days: 2, valid_until: "2026-11-27", demolish: true, waste: null, paper: "개나리 로하스", warranty_months: 6, file: "사진 3장" },
  /** 두 곳 차이(서버 gap_total) */
  gap1: 330_000,
  gap2: 220_000,
  /** 결도배 1판 → 2판 차액 */
  change: 110_000,
};

/** 공사 날짜(업체가 하루씩 고른 날) · 확정 공정표 */
export const WORK = {
  start: "2026-12-18", end: "2026-12-19", work_days: 2,
  days: [
    { day: "2026-12-17", am: null, pm: null, off: false },
    { day: "2026-12-18", am: "도배", pm: "도배" },
    { day: "2026-12-19", am: "도배", pm: "도배" },
    { day: "2026-12-20", am: null, pm: null, off: true },
  ],
};

export const KNOW = {
  move: {
    title: "살면서 도배할 때 짐은 방 가운데로",
    lines: ["벽에서 한 뼘 넘게 떼어 두면 일이 빨라요", "벽에 건 액자 · 시계는 전날 떼어 두세요", "콘센트 덮개는 업체가 떼고 다시 달아요"],
    source: "표준 시방서 · 믿집 정리",
    checklist: [
      { key: "furniture", label: "가구를 방 가운데로", done: false },
      { key: "frames", label: "액자 · 시계 떼기", done: false },
      { key: "parking", label: "주차 · 엘리베이터 예약", done: false },
    ],
  },
};

export const MEMORY_SEED = [
  { id: "mem-1", key: "avail_half" as const, value: "평일 오전이 편해요", evidence_message_id: "u-seed-1", evidence_quote: "평일 오전이 편해요" },
  { id: "mem-2", key: "material" as const, value: "아이 방은 냄새 적은 풀", evidence_message_id: "u-seed-2", evidence_quote: "아이 방은 냄새 적은 풀이면 좋겠어요" },
];

/** 업체 쪽(V1 · V3) */
export const VENDOR_SIDE = {
  estimate: 4_182_300,
  checklist: [
    { key: "1201", label: "퍼티 · 면 고르기", state: "ok" as const },
    { key: "1202", label: "초배지", state: "ok" as const },
    { key: "1203", label: "벽지 · 풀(실크)", state: "ok" as const },
    { key: "1204", label: "천장 몰딩 경계 마감", state: "check" as const, hint: "사진에 몰딩이 들뜬 곳이 있어요" },
    { key: "1206", label: "짐 옮기기 · 보양(사는 중)", state: "check" as const, hint: "고객이 살면서 하는 공사예요" },
    { key: "1207", label: "철거 · 폐기물 처리", state: "missing" as const, hint: "포함인지 적어 주세요" },
    { key: "1208", label: "운송비", state: "ok" as const },
  ],
  easy_miss: ["폐기물 처리 포함 여부", "부가세 방식(포함 · 별도)", "유효기간"],
};
