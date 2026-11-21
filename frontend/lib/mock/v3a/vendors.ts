// 예시: 업체 보기 · 자세히 · 리뷰 · 담기(api.md 4장 모양). 9판 C10 · C11 · C12 · C48 · D06 · D07의 업체 셋을 옮겼어요.
// 가견적 줄 합 = 공급가, 공급가 + 부가세 = 합계가 맞게 넣었어요(화면은 이 값을 그대로 보여요).
import type { Schemas } from "@/lib/backend/client";
import { MOCK_PROJECT, MOCK_VENDOR, type MockKey } from "./mode";

type S = Schemas;
export type VendorList = S["VendorListOut"];
export type VendorCardData = S["VendorCardOut"];
export type VendorDetail = S["VendorDetailOut"];
export type ReviewPage = S["ReviewPageOut"];
export type Shortlist = S["ShortlistOut"];

const card = (c: Partial<VendorCardData> & Pick<VendorCardData, "vendor_id" | "name">): VendorCardData => ({
  sgg: "노원구", estimate_total: null, vs_standard_pct: null, rating: null, review_count: 0, done_count: 0,
  visit_fee: 0, instant_badge: false, state: "ok", shortlisted: false, ...c,
});

const GYEOL = card({ vendor_id: MOCK_VENDOR.gyeol, name: "결도배", estimate_total: 2774200, vs_standard_pct: "41", rating: "4.7", review_count: 3, done_count: 3, shortlisted: true });
const MARU = card({ vendor_id: MOCK_VENDOR.maru, name: "마루와벽", estimate_total: 3186150, vs_standard_pct: "61", rating: "4.8", review_count: 5, done_count: 5, instant_badge: true, shortlisted: true });
const HAN = card({ vendor_id: MOCK_VENDOR.hangyeol, name: "한결인테리어", rating: "5.0", review_count: 1, done_count: 1, state: "no_estimate" });

const base = (key: MockKey, area: string, region: string): Omit<VendorList, "local" | "nearby" | "nearby_sgg" | "shortlist" | "slots_left"> => ({
  project_id: MOCK_PROJECT[key], trade: "dobae", region, area_name: area, standard_total: key === "part" ? 638501 : 1974069, consent_ver: "v3", vendors: [],
});

export function mockVendorList(key: MockKey): VendorList {
  if (key === "zero") {
    return {
      ...base(key, "강북구", "서울 강북구"),
      local: [],
      nearby: [{ ...GYEOL, shortlisted: false }, { ...MARU, sgg: "노원구 · 도봉구", shortlisted: false }],
      nearby_sgg: ["노원구", "도봉구"],
      shortlist: { count: 0, left: 3 }, slots_left: 3,
    };
  }
  if (key === "part") {
    // 부분 공사 예시(C60)도 실크 집이에요. 결도배의 '이 벽지는 안 해요'(D07 A)는 업체 자세히에서 합지로 바꿔 보면 나와요
    return {
      ...base(key, "노원구", "서울 노원구"),
      local: [{ ...GYEOL, shortlisted: false }, { ...MARU, shortlisted: false }, HAN],
      nearby: [], nearby_sgg: [], shortlist: { count: 0, left: 3 }, slots_left: 3,
    };
  }
  return { ...base(key, "노원구", "서울 노원구"), local: [GYEOL, MARU, HAN], nearby: [], nearby_sgg: [], shortlist: { count: 2, left: 1 }, slots_left: 1 };
}

export function mockShortlist(key: MockKey): Shortlist {
  const items = key === "full" || key === "final"
    ? [
        { vendor_id: MOCK_VENDOR.gyeol, name: "결도배", slot: 1, estimate_total: 2774200, state: "ok" as const, visit_id: null, visit_status: null, added_at: "2026-11-18T09:20:00+09:00" },
        { vendor_id: MOCK_VENDOR.maru, name: "마루와벽", slot: 2, estimate_total: 3186150, state: "ok" as const, visit_id: null, visit_status: null, added_at: "2026-11-18T09:22:00+09:00" },
      ]
    : [];
  return { project_id: MOCK_PROJECT[key], trade: "dobae", items, count: items.length, left: 3 - items.length };
}

// ───── 업체 자세히(D07 · C11): 가견적 1201~1208

type Line = S["EstimateV3LineOut"];
/** 표준견적서에 없는 줄(퍼티 · 식대 · 운송비)은 in_standard false — 비교 %에서 빠져요(API와 같은 규칙) */
const OUTSIDE = new Set(["putty", "meal", "truck"]);
/** 고객 화면 이름 · 짧은 뜻(API label · note, 백엔드 계산 엔진 줄 정의와 같은 값) */
const LABEL: Record<string, string> = { paper_silk: "실크벽지", paper_hapji: "합지벽지" };
const NOTE: Record<string, string> = { putty: "사전퍼티 또는 밀작업", material: "풀 · 부직포 · 네바리 · 실리콘 등", labor: "품 = 1명이 하루 하는 일" };
const L = (code: string, key: string, name: string, qty: string, unit: string, unit_price: number | null, amount: number, mode: Line["mode"] = "price"): Line =>
  ({ code, key, name, label: LABEL[key] ?? name, note: NOTE[key] ?? "", qty, unit, unit_price, amount, mode, included_in: null, in_standard: !OUTSIDE.has(key), optional: false });

/** 마루와벽 실크(318만 6,150원) · 합지(287만 4,300원) — D07 AI 답의 숫자와 같아요 */
const MARU_LINES: Record<"basic" | "economy", Line[]> = {
  basic: [
    L("1201", "putty", "퍼티작업", "21.0", "평", 20000, 420000),
    L("1204", "paper_silk", "실크", "63.0", "벽지 평", 9500, 598500),
    L("1205", "material", "부자재", "21.0", "평", 13000, 273000),
    L("1206", "labor", "인건비", "5.0", "품", 300000, 1500000),
    L("1207", "meal", "식대", "5", "품", 15000, 75000),
    L("1208", "truck", "운송비", "1", "대", 30000, 30000),
  ],
  economy: [
    L("1201", "putty", "퍼티작업", "21.0", "평", 20000, 420000),
    L("1203", "paper_hapji", "합지", "63.0", "벽지 평", 5000, 315000),
    L("1205", "material", "부자재", "21.0", "평", 13000, 273000),
    L("1206", "labor", "인건비", "5.0", "품", 300000, 1500000),
    L("1207", "meal", "식대", "5", "품", 15000, 75000),
    L("1208", "truck", "운송비", "1", "대", 30000, 30000),
  ],
};
const MARU_SUM = { basic: { supply: 2896500, vat: 289650, total: 3186150, pct: "61" }, economy: { supply: 2613000, vat: 261300, total: 2874300, pct: "46" } };

/** 결도배 실크(277만 4,200원). 식대는 다른 줄에 포함, 합지는 '빼기' */
const GYEOL_LINES: Line[] = [
  L("1201", "putty", "퍼티작업", "21.0", "평", 15000, 315000),
  L("1204", "paper_silk", "실크", "63.0", "벽지 평", 9000, 567000),
  L("1205", "material", "부자재", "21.0", "평", 10000, 210000),
  L("1206", "labor", "인건비", "5.0", "품", 280000, 1400000),
  { ...L("1207", "meal", "식대", "5", "품", null, 0, "included"), included_in: "1206" },
  L("1208", "truck", "운송비", "1", "대", 30000, 30000),
];

const PHOTO = (i: number, space: string, title: string, paper: "basic" | "economy", m2: string, taken: string) =>
  ({ id: `a3a20000-0000-4000-8000-00000000000${i}`, file_id: `a3a30000-0000-4000-8000-00000000000${i}`, title, space, paper, area_m2: m2, area_basis: "supply" as const, area_text: `공급 ${m2}㎡`, taken_on: taken, pyeong: null });

const profile = (vid: string, name: string, owner: string, areas: string[], opened: string, verified: string): S["PublicProfileOut"] => ({
  vendor_id: vid, biz_name: name, trades: ["dobae"],
  areas: areas.map((sgg) => ({ sido: "seoul", sgg, label: sgg })),
  verified_at: `${verified}T10:00:00+09:00`, contact_method: null, call_start: null, call_end: null,
  visit_fee: 0, visit_fee_refund: false, tax_kind: "general", owner_name: owner, biz_no: "2148603518",
  opened_on: opened, address_area: "서울 노원구", interior_license: null, insurance: null, faqs: [], links: [], portfolio: [], updated_at: null,
});

const MARU_PHOTOS = [
  PHOTO(1, "living", "거실", "basic", "79.3", "2026-10-12"),
  PHOTO(2, "master", "안방", "basic", "79.3", "2026-10-12"),
  PHOTO(3, "room1", "작은방", "economy", "59.9", "2026-09-03"),
  PHOTO(4, "hall", "복도", "basic", "84.9", "2026-08-21"),
  PHOTO(5, "kitchen", "주방", "basic", "84.9", "2026-08-21"),
  PHOTO(6, "entry", "현관", "economy", "59.9", "2026-07-30"),
];

export function mockVendorDetail(key: MockKey, vid: string, grade?: "basic" | "economy" | null): VendorDetail | null {
  const pid = MOCK_PROJECT[key];
  // 예시 공사는 모두 실크(basic)로 골랐어요(SAMPLE_INFO · PART_INFO). grade를 주면 그 벽지로 미리 보기
  const g = grade ?? "basic";
  const common = { project_id: pid, trade: "dobae", standard_total: key === "part" ? 638501 : 1974069, in_area: key !== "zero", area_name: key === "zero" ? "강북구" : "노원구", dong: key === "zero" ? "수유동" : "상계동", estimate: null, visit: null, not_included: [] };
  if (vid === MOCK_VENDOR.maru) {
    const sum = MARU_SUM[g];
    return {
      ...common,
      profile: { ...profile(vid, "마루와벽", "이마루", ["노원구", "도봉구", "강북구", "성북구"], "2018-04-02", "2026-11-03"), portfolio: MARU_PHOTOS },
      verified_on: "2026-11-03", years_open: 8,
      estimate_v3: { rows_ver: "dobae_v3", set_id: "a3a40000-0000-4000-8000-000000000002", version: 3, grade: g, tax_kind: "general", lines: MARU_LINES[g], supply: sum.supply, vat: sum.vat, total: sum.total, vs_standard_pct: sum.pct, paper_ok: true },
      grade: g, reply_hours: 20,
      // 보이는 벽지와 다른 벽지의 차이(다른 벽지 − 보이는 벽지)
      grade_diff: g === "basic" ? -311850 : 311850,
      state: "ok", instant_badge: true,
      rating: { avg: "4.8", count: 5, done_count: 5, tags: { seam: 3, on_time: 2, kind: 1, tidy: 1 } },
      review_links: [
        { sort: 1, label: "네이버 플레이스", url: "https://example.com/place/maru", status: "shown" },
        { sort: 2, label: "블로그 후기", url: "https://example.com/blog/maru", status: "shown" },
      ],
      shortlisted: key === "full" || key === "final",
    };
  }
  if (vid === MOCK_VENDOR.gyeol) {
    const no = g === "economy";
    return {
      ...common,
      profile: { ...profile(vid, "결도배", "박결", ["노원구"], "2021-06-14", "2026-10-20"), portfolio: MARU_PHOTOS.slice(0, 3) },
      verified_on: "2026-10-20", years_open: 5,
      estimate_v3: no ? null : { rows_ver: "dobae_v3", set_id: "a3a40000-0000-4000-8000-000000000001", version: 2, grade: "basic", tax_kind: "general", lines: GYEOL_LINES, supply: 2522000, vat: 252200, total: 2774200, vs_standard_pct: "41", paper_ok: true },
      grade: g, reply_hours: 30,
      grade_diff: null,
      state: no ? "paper_unsupported" : "ok", instant_badge: false,
      rating: { avg: "4.7", count: 3, done_count: 3, tags: { seam: 2, tidy: 1 } },
      review_links: [],
      shortlisted: key === "full" || key === "final",
    };
  }
  if (vid === MOCK_VENDOR.hangyeol) {
    return {
      ...common,
      profile: profile(vid, "한결인테리어", "최한결", ["노원구", "중랑구"], "2015-02-09", "2026-11-10"),
      verified_on: "2026-11-10", years_open: 11,
      estimate_v3: null, grade: g, reply_hours: null, grade_diff: null, state: "no_estimate", instant_badge: false,
      rating: { avg: "5.0", count: 1, done_count: 1, tags: { kind: 1 } },
      review_links: [], shortlisted: false,
    };
  }
  return null;
}

// ───── 리뷰(C48 · C49)

type Item = S["ReviewItemOut"];
const R = (i: number, rating: number, at: string, tags: Item["tags"], body: string, ctx: string, reply?: { body: string; at: string }): Item => ({
  id: `a3a50000-0000-4000-8000-00000000000${i}`, rating, tags, body, author_label: "김○○", context_label: ctx, photos: [], created_at: `${at}T15:00:00+09:00`, edited: false,
  reply: reply ? { body: reply.body, created_at: `${reply.at}T10:00:00+09:00`, edited_at: null } : null,
});

const MARU_REVIEWS: Item[] = [
  R(1, 5, "2026-11-02", ["seam", "on_time"], "이음매가 거의 안 보여요. 약속한 날 오후에 딱 끝났어요.", "노원구 아파트 · 실크"),
  R(2, 4, "2026-10-12", ["kind"], "결과는 좋았는데 첫날 시작이 1시간 늦었어요. 늦는다고 미리 채팅은 왔어요.", "도봉구 아파트 · 합지", { body: "늦어서 죄송했어요. 그 뒤로는 전날 도착 시각을 채팅으로 먼저 알려 드려요.", at: "2026-10-13" }),
  R(3, 5, "2026-09-20", ["tidy"], "남은 벽지를 따로 챙겨 주셔서 나중에 보수할 때 썼어요.", "노원구 아파트 · 실크"),
  R(4, 5, "2026-08-30", ["seam"], "몰딩 쪽 마감이 깔끔해요.", "노원구 아파트 · 실크"),
  R(5, 5, "2026-08-11", ["seam", "on_time"], "이틀 일정대로 끝났어요.", "강북구 아파트 · 실크"),
];

export function mockReviews(vid: string, sort: "latest" | "low"): ReviewPage | null {
  const d = mockVendorDetail("full", vid);
  if (!d) return null;
  const items = vid === MOCK_VENDOR.maru ? [...MARU_REVIEWS] : [];
  if (sort === "low") items.sort((a, b) => a.rating - b.rating || b.created_at.localeCompare(a.created_at));
  return { vendor_id: vid, rating: d.rating ?? { avg: null, count: 0, done_count: 0, tags: {} }, items, next_before: null, links: d.review_links };
}

/** 예시 사진(파일이 없어서 그린 자리 그림) */
export function mockPhotoSrc(i: number): string {
  const wall = ["#e9e4da", "#e3e8ee", "#efe7e1", "#e6ebe4", "#ece6ef", "#e8e8e3"][i % 6];
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 300'><rect width='400' height='300' fill='${wall}'/><rect y='230' width='400' height='70' fill='#c9b9a3'/><rect x='250' y='60' width='100' height='120' fill='#f7fafc' stroke='#b7c2cc' stroke-width='6'/><path d='M300 60v120M250 120h100' stroke='#b7c2cc' stroke-width='4'/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
