// 예시 데이터. 업체 · 단지 · 회원은 모두 가상이고, 금액 · 수량 · 일정은 fixtures.json(계산 엔진 결과)에서만 가져온다.
import fixtures from "./fixtures.json";
import type { HistoryItem, Member, Project, QuoteRequest, Vendor } from "../types";

export const FX = fixtures as unknown as {
  area: { supply: number; jeon: number; supplyPy: number; dobaePy: number };
  spaces: { id: string; name: string }[];
  standard: import("../types").StandardQuote;
  vendors: Omit<Vendor, "owner" | "bizNo" | "intro" | "portfolio" | "registeredAt" | "status">[];
  recommend: Record<"dobae" | "mokgong", import("../types").Recommendation[]>;
  quotes: Record<"dobae" | "mokgong", import("../types").VendorQuote[]>;
  compare: Record<"dobae" | "mokgong", import("../types").Compare>;
  finals: Record<"dobae" | "mokgong", import("../types").FinalQuote>;
  expected: import("../types").ExpectedSchedule;
  confirmed: Record<"dobae" | "mokgong", import("../types").ConfirmedPart>;
};

import { COMPLEXES } from "./complexes";
export { COMPLEXES };

const VENDOR_EXTRA: Record<string, Pick<Vendor, "intro" | "portfolio" | "registeredAt">> = {
  v1: { intro: "도배만 해요. 마포 · 서대문 쪽 아파트를 주로 맡아요.", portfolio: [{ title: "34평형 실크 도배", caption: "[시공 사례 사진 자리] 업체가 올린 사진이 들어가요" }, { title: "24평형 합지 도배", caption: "[시공 사례 사진 자리]" }], registeredAt: "2026-08-12" },
  v2: { intro: "몰딩 · 걸레받이 · 문틀 같은 목공만 해요.", portfolio: [{ title: "몰딩 · 걸레받이 교체", caption: "[시공 사례 사진 자리]" }], registeredAt: "2026-08-20" },
  v3: { intro: "도배와 목공을 한 팀이 이어서 해요. 천장 초배를 기본으로 넣어요.", portfolio: [{ title: "34평형 도배 · 몰딩", caption: "[시공 사례 사진 자리]" }, { title: "41평형 도배", caption: "[시공 사례 사진 자리]" }], registeredAt: "2026-07-30" },
  v4: { intro: "도배 · 목공 팀을 따로 두고 일정 맞춰 들어가요. 토요일에는 쉬어요.", portfolio: [{ title: "32평형 도배 · 목공", caption: "[시공 사례 사진 자리]" }], registeredAt: "2026-09-02" },
  v5: { intro: "도배 · 목공을 해요. 기존 벽지 철거비는 따로 받아요.", portfolio: [{ title: "25평형 도배", caption: "[시공 사례 사진 자리]" }], registeredAt: "2026-07-18" },
};

export const VENDORS: Vendor[] = FX.vendors.map((v, i) => ({
  ...v,
  owner: "대표 (예시)",
  bizNo: `000-00-0${String(1001 + i)} (예시)`,
  intro: VENDOR_EXTRA[v.id]?.intro ?? "업체가 쓰는 소개 글이 들어가요.",
  portfolio: VENDOR_EXTRA[v.id]?.portfolio ?? [{ title: "시공 사례", caption: "[시공 사례 사진 자리]" }],
  registeredAt: VENDOR_EXTRA[v.id]?.registeredAt ?? "2026-09-15",
  status: "active",
}));

// 추천 이유에서 근거가 없는 두 가지를 뺀다: 믿집 밖 시공 건수(셀 수 없음), 희망일 시작 가능(업체 일정을 받지 않음).
const NO_BASIS = [/^최근 1년 .*시공/, /희망일/];
export const RECOMMEND = Object.fromEntries(
  Object.entries(FX.recommend).map(([t, list]) => [t, list.map((r) => ({ ...r, pros: r.pros.filter((x) => !NO_BASIS.some((re) => re.test(x))) }))]),
) as typeof FX.recommend;

export const PROJECTS: Project[] = [
  {
    id: "p1", title: "늘봄마을 2단지 34평형", createdAt: "2026-10-20", stage: "scheduled",
    complex: COMPLEXES[0], unitTypeId: "c1-34", area: { supply: FX.area.supply, jeon: FX.area.jeon, supplyPy: FX.area.supplyPy }, balconyExt: true,
    houseType: "apt", builtYear: 2009, startPlan: { kind: "date", date: "2026-11-16" }, occupied: true, budget: "500만~700만 원",
    spaces: FX.spaces,
    trades: { dobae: { spaces: FX.spaces.map((s) => s.id), grade: "basic" }, mokgong: { spaces: FX.spaces.map((s) => s.id), items: ["천장 몰딩", "걸레받이"] } },
    photos: [{ spaceId: "living", name: "거실 벽.jpg" }, { spaceId: "room3", name: "작은방 창가.jpg" }], floorPlan: null,
  },
];

const req = (trade: "dobae" | "mokgong", vendorId: string, receivedAt: string): QuoteRequest => ({ trade, vendorId, status: "registered", requestedAt: "2026-10-20", receivedAt });
export const QUOTE_REQUESTS: Record<string, QuoteRequest[]> = {
  p1: [
    req("dobae", "v1", "2026-10-21"), req("dobae", "v3", "2026-10-21"), req("dobae", "v4", "2026-10-22"),
    req("mokgong", "v3", "2026-10-21"), req("mokgong", "v5", "2026-10-21"), req("mokgong", "v4", "2026-10-22"),
  ],
};

export const VISITS: Record<string, { trade: "dobae" | "mokgong"; vendorId: string; at: string; status: "done" }[]> = {
  p1: [{ trade: "dobae", vendorId: "v1", at: "2026-10-24 10:00", status: "done" }, { trade: "mokgong", vendorId: "v3", at: "2026-10-26 14:00", status: "done" }],
};

export const HISTORY: Record<string, HistoryItem[]> = {
  p1: [
    { date: "2026-10-20", kind: "프로젝트", text: "프로젝트를 만들고 예상 공정표를 받았어요" },
    { date: "2026-10-20", kind: "표준견적서", text: "공공 기준 표준견적서를 만들었어요 (2026 하반기 단가)" },
    { date: "2026-10-20", kind: "가견적 요청", text: "결도배 · 바름집수리 · 온빛인테리어에 요청했어요", trade: "dobae" },
    { date: "2026-10-20", kind: "가견적 요청", text: "바름집수리 · 마루와벽 · 온빛인테리어에 요청했어요", trade: "mokgong" },
    { date: "2026-10-21", kind: "가견적 도착", text: "결도배 · 바름집수리 가견적이 등록됐어요", trade: "dobae" },
    { date: "2026-10-21", kind: "가견적 도착", text: "바름집수리 · 마루와벽 가견적이 등록됐어요", trade: "mokgong" },
    { date: "2026-10-22", kind: "가견적 도착", text: "온빛인테리어 가견적이 등록됐어요", trade: "dobae" },
    { date: "2026-10-22", kind: "가견적 도착", text: "온빛인테리어 가견적이 등록됐어요", trade: "mokgong" },
    { date: "2026-10-22", kind: "실측 요청", text: "결도배에 실측을 요청했어요", trade: "dobae" },
    { date: "2026-10-22", kind: "실측 요청", text: "바름집수리에 실측을 요청했어요", trade: "mokgong" },
    { date: "2026-10-27", kind: "실측 견적 도착", text: "결도배 실측 견적이 등록됐어요", trade: "dobae" },
    { date: "2026-10-27", kind: "실측 견적 도착", text: "바름집수리 실측 견적이 등록됐어요", trade: "mokgong" },
    { date: "2026-10-28", kind: "업체 확정", text: "도배는 결도배, 목공은 바름집수리로 확정했어요" },
    { date: "2026-10-29", kind: "공사기간 등록", text: "확정 업체가 공사기간을 등록해 확정 공정표가 만들어졌어요" },
  ],
};

export const MEMBERS: Member[] = Array.from({ length: 8 }, (_, i) => ({
  id: `m${i + 1}`,
  name: `예시 회원 ${String(i + 1).padStart(2, "0")}`,
  email: `user${String(i + 1).padStart(2, "0")}@mitjip.test`,
  joinedAt: ["2026-09-03", "2026-09-11", "2026-09-20", "2026-10-02", "2026-10-09", "2026-10-15", "2026-10-21", "2026-10-28"][i],
  projects: [1, 0, 2, 1, 0, 1, 1, 0][i],
  status: i === 4 ? "suspended" : "active",
  role: "customer",
}));
