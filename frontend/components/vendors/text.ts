// 업체 고르기 · 업체 자세히 · 실측 요청(시안 WVendors · WVendorDetail · WVisit)에만 쓰는 화면 말 · 표시 함수.
// 금액 · 퍼센트는 API(계산 엔진)가 준 값을 형식만 바꿔 보인다. 서버 · 브라우저 양쪽에서 쓴다.
import type { Schemas } from "@/lib/backend/client";
import { CONTACT_WAY, DECLINE_LABEL, type ContactMethod } from "@/lib/labels";
import { dateSeoul, decText, md, stampSeoul, won } from "@/lib/format";

export type VTrade = "dobae" | "mokgong";
export type VendorRow = Schemas["VendorRowOut"];
export type Visit = Schemas["VisitOut"];
export type Area = Schemas["AreaOut"];
export type Created = Schemas["VisitCreateOut"];

export const isTrade = (v: unknown): v is VTrade => v === "dobae" || v === "mokgong";
const METHODS = ["phone", "sms", "kakao", "web"] as const;
export const asMethod = (v: string | null | undefined): ContactMethod | null => (METHODS as readonly string[]).includes(v ?? "") ? (v as ContactMethod) : null;

/** 이 공정 칸을 차지하는 요청(요청함 · 견적서 옴 · 확정) */
export const isLive = (status: string) => status === "requested" || status === "quoted" || status === "chosen";

// 받침에 맞춰 조사를 붙인다. 숫자로 끝나면 읽는 소리(영 · 일 · 이 …)로 보고, 그 밖의 글자면 둘 다 적는다.
const DIGIT_JONG = [21, 8, 0, 16, 0, 0, 1, 8, 8, 0]; // 영 일 이 삼 사 오 육 칠 팔 구의 받침
function jong(word: string): number | null {
  const last = word.slice(-1);
  if (/[0-9]/.test(last)) return DIGIT_JONG[Number(last)];
  const c = word.charCodeAt(word.length - 1);
  return c >= 0xac00 && c <= 0xd7a3 ? (c - 0xac00) % 28 : null;
}
/** "마루와벽이" · "결도배가" */
export const iGa = (w: string) => { const j = jong(w); return `${w}${j === null ? "이(가)" : j ? "이" : "가"}`; };
/** "노원구는" · "목공은" */
export const eunNeun = (w: string) => { const j = jong(w); return `${w}${j === null ? "은(는)" : j ? "은" : "는"}`; };
/** "마루와벽과" · "결도배와" */
export const gwaWa = (w: string) => { const j = jong(w); return `${w}${j === null ? "과(와)" : j ? "과" : "와"}`; };

/** 활동 지역: 이 집 구를 앞에 두고 2곳 + 외 N곳. "노원구 · 도봉구 외 2곳" */
export function areasText(areas: Area[], here?: string): string {
  const names = areas.map((a) => a.sgg);
  const sorted = here && names.includes(here) ? [here, ...names.filter((n) => n !== here)] : names;
  const head = sorted.slice(0, 2).join(" · ");
  return sorted.length > 2 ? `${head} 외 ${sorted.length - 2}곳` : head;
}

/** "09:00:00" → "09:00" */
export const hm = (t: string | null | undefined) => (t ? t.slice(0, 5) : "");
/** 연락 받는 시간 "09:00~18:00" (없으면 빈 글) */
export const callHours = (start: string | null | undefined, end: string | null | undefined) => (start && end ? `${hm(start)}~${hm(end)}` : "");

/** 실측 비용: "실측 무료" · "출장비 2만 원" */
export function feeText(fee: number | null | undefined): string {
  if (fee == null) return "실측 비용은 업체에 물어봐요";
  return fee > 0 ? `출장비 ${won(fee)}` : "실측 무료";
}

/** 연락 카드 한 줄: "전화로 연락해요 · 통화 09:00~18:00 · 실측 무료" */
export function contactLine(c: { contact_method: string | null; call_start: string | null; call_end: string | null; visit_fee: number | null; visit_fee_refund: boolean }): string {
  const m = asMethod(c.contact_method);
  const parts: string[] = [];
  if (m) parts.push(CONTACT_WAY[m]);
  const h = callHours(c.call_start, c.call_end);
  if (h && (m === "phone" || m === "sms")) parts.push(`통화 ${h}`);
  parts.push(feeText(c.visit_fee));
  return parts.join(" · ");
}

/** 표준견적서 대비: "표준견적서보다 1.1% 적어요" (API 퍼센트 그대로, 부호만 뺀다) */
export function vsText(vs: string | null | undefined, dir: string | null | undefined): string {
  if (vs == null || !dir) return "";
  if (dir === "same") return "표준견적서와 같아요";
  return `표준견적서보다 ${decText(vs.replace(/^[-+]/, ""))}% ${dir === "less" ? "적어요" : "많아요"}`;
}

/** 실측 요청 상태 이름 */
export const VISIT_LABEL: Record<string, string> = {
  requested: "요청함 · 견적서 기다림",
  quoted: "견적서 옴",
  chosen: "업체 확정",
  cancelled: "요청 취소함",
  declined: "못 받음",
  closed: "닫힘",
};
/** 상태 모양 · 색 (mj-st-*) */
export const VISIT_TONE: Record<string, "now" | "ok" | "off" | "bad"> = {
  requested: "now", quoted: "ok", chosen: "ok", cancelled: "off", declined: "bad", closed: "off",
};
export const declineText = (code: string | null | undefined) => (code && code in DECLINE_LABEL ? DECLINE_LABEL[code as keyof typeof DECLINE_LABEL] : "");

type Shut = { status: string; close_reason?: string | null };
/** 고객이 '다시 고르기'로 닫은 요청 (close_reason reselected). '다시 고르는 중' 안내를 둘지 볼 때만 쓴다 */
export const isReselected = (v: Shut) => v.status === "closed" && v.close_reason === "reselected";
/** 닫힌 요청(closed)을 고객에게 어떻게 보일지. 업체 고르기 · 실측 · 업체 자세히가 이것 하나로 나눈다.
 * 'other': 이 공정에 살아 있는 확정이 있고(locked) 다른 업체 확정으로 닫힘(other_chosen, 까닭 없는 예전 요청 포함) → '다른 업체로 정했어요'
 * 'past': 그 밖의 닫힘 → '지난 실측 닫힘', 확정이 없으면 '다시 담기'. 닫힘이 아니면 null */
export function shutKind(v: Shut, locked: boolean): "other" | "past" | null {
  if (v.status !== "closed") return null;
  return locked && (v.close_reason === "other_chosen" || !v.close_reason) ? "other" : "past";
}

/** API 시각 → "11.2(월) 15:30" */
export const when = (iso: string | null | undefined) => (iso ? stampSeoul(new Date(iso)) : "");
/** 날짜 "2026-11-03" → "11.3(화)" */
export const day = (iso: string | null | undefined) => (iso ? md(iso.slice(0, 10)) : "");
/** API 시각 → 서울 날짜 "11.3(화)" */
export const daySeoul = (iso: string | null | undefined) => (iso ? md(dateSeoul(iso)) : "");

/** 보낸 뒤 못 보낸 업체 까닭 */
export const FAILED_TEXT: Record<string, string> = {
  unavailable: "지금 믿집에서 일할 수 없는 업체예요. 다른 업체를 담아 주세요.",
  already: "이미 실측을 요청한 업체예요.",
};

/** 업체 자세히 '자주 묻는 5가지' (업체 정보 화면과 같은 순서 · 이름) */
export const FAQ_LABEL: { key: Schemas["FaqIn"]["key"]; label: string }[] = [
  { key: "process", label: "진행 순서" },
  { key: "pricing", label: "견적 계산 방식" },
  { key: "extra_cost", label: "추가금이 생기는 경우" },
  { key: "duration", label: "공사 기간" },
  { key: "as_refund", label: "A/S · 환불" },
];

/** 연락 방식 버튼에 쓸 수 있는 주소인지 (http · https만) */
export const webUrl = (u: string | null | undefined) => (u && /^https?:\/\//i.test(u) ? u : null);
/** 전화 · 문자 주소에 넣을 숫자 */
export const telDigits = (p: string | null | undefined) => (p ?? "").replace(/[^\d+]/g, "");
