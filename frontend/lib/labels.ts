// API 코드값 ↔ 화면 말. 질문 흐름(보내기)과 프로젝트 화면(보이기)이 같이 쓴다.
import type { components } from "./backend/schema";
import type { TradeKey } from "./types";

type S = components["schemas"];
export type Budget = NonNullable<S["ProjectCreate"]["budget"]>;
export type MokItem = S["MokgongIn"]["items"][number];
export type DobaeGrade = S["DobaeIn"]["grade"];

// 견적 받기의 공정 고르기: 묶음과 화면 순서. 공정 이름은 TRADE_LABEL(lib/types.ts)
export const TRADE_GROUPS: { label: string; keys: TradeKey[] }[] = [
  { label: "벽 · 바닥 마감", keys: ["dobae", "floor", "paint", "film", "tile"] },
  { label: "공간 · 설비", keys: ["bath", "kitchen", "electric", "window"] },
  { label: "목공", keys: ["mokgong"] },
];
/** 공정을 보이는 순서 (고르기 · 공간 고르기 · 요약) */
export const TRADE_KEYS: TradeKey[] = TRADE_GROUPS.flatMap((g) => g.keys);
// 공정 카드의 한 줄 설명: 무엇을 하는 공정인지
export const TRADE_DESC: Record<TradeKey, string> = {
  dobae: "벽지 · 천장지를 새로 발라요",
  floor: "장판 · 마루 · 바닥 타일을 깔아요",
  paint: "벽 · 천장 · 문 · 베란다를 칠해요",
  film: "문 · 문틀 · 가구에 필름을 붙여요",
  tile: "현관 · 베란다 · 주방 벽에 붙여요",
  bath: "방수 · 타일 · 도기 · 수전을 고쳐요",
  kitchen: "싱크대 · 상판 · 후드를 바꿔요",
  electric: "조명 · 스위치 · 콘센트를 바꿔요",
  window: "낡은 창틀과 유리(새시)를 바꿔요",
  mokgong: "몰딩 · 걸레받이 · 방문을 바꿔요",
};

export const BUDGETS: { key: Budget; label: string }[] = [
  { key: "u300", label: "300만 원 이하" },
  { key: "300-500", label: "300만~500만 원" },
  { key: "500-700", label: "500만~700만 원" },
  { key: "700-1000", label: "700만~1,000만 원" },
  { key: "o1000", label: "1,000만 원 넘게" },
  { key: "undecided", label: "아직 정하지 않았어요" },
];

export const MOK_ITEMS: { key: MokItem; label: string; desc: string }[] = [
  { key: "molding", label: "천장 몰딩", desc: "천장과 벽이 만나는 선" },
  { key: "base", label: "걸레받이", desc: "바닥과 벽이 만나는 선" },
  { key: "door", label: "방문 교체", desc: "문틀 · 문짝" },
  { key: "flatten", label: "천장 평탄화", desc: "우물천장 · 등박스를 평평하게" },
];

// 도배 유형. 무엇이 들어가는지(벽지 종류 · 등급)는 아직 정하지 않았다.
export const DOBAE_GRADES: { key: DobaeGrade; label: string }[] = [
  { key: "economy", label: "저가형" },
  { key: "basic", label: "기본형" },
];

export const WHEN_LABEL = { date: "날짜가 정해졌어요", movein: "이사하는 날만 정해졌어요", months: "1~2달 안에", unknown: "아직 몰라요" } as const;

export function sizeLabel(s: { band?: string | null; basis?: string | null; m2?: string | number | null }) {
  if (s.band) return s.band === "50" ? "50평 이상" : `${s.band}평대`;
  return `${s.basis === "exclusive" ? "전용" : "공급"} ${s.m2}㎡`;
}
export const budgetLabel = (k: string | null | undefined) => BUDGETS.find((b) => b.key === k)?.label ?? "정하지 않음";
export const mokLabel = (k: string) => MOK_ITEMS.find((m) => m.key === k)?.label ?? k;
export const gradeLabel = (k: string | null | undefined) => DOBAE_GRADES.find((g) => g.key === k)?.label ?? "유형 미정";
