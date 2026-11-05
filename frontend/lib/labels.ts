// API 코드값 ↔ 화면 말. 질문 흐름(보내기)과 프로젝트 화면(보이기)이 같이 쓴다.
import type { components } from "./backend/schema";

type S = components["schemas"];
export type Budget = NonNullable<S["ProjectCreate"]["budget"]>;
export type MokItem = S["MokgongIn"]["items"][number];
export type DobaeGrade = S["DobaeIn"]["grade"];

export const BUDGETS: { key: Budget; label: string }[] = [
  { key: "u300", label: "300만 원 이하" },
  { key: "300-500", label: "300만~500만 원" },
  { key: "500-700", label: "500만~700만 원" },
  { key: "700-1000", label: "700만~1,000만 원" },
  { key: "o1000", label: "1,000만 원 넘게" },
  { key: "undecided", label: "아직 정하지 않았어요" },
];

export const MOK_ITEMS: { key: MokItem; label: string; desc: string }[] = [
  { key: "molding", label: "천장 몰딩", desc: "교체" },
  { key: "base", label: "걸레받이", desc: "교체" },
  { key: "door", label: "방문 교체", desc: "문틀 · 문짝" },
  { key: "flatten", label: "천장 평탄화", desc: "석고보드" },
];

// 도배 유형. 계산 엔진은 저가형을 합지, 기본형을 실크로 계산한다(backend/app/calc/dobae.py).
export const DOBAE_GRADES: { key: DobaeGrade; label: string; desc: string }[] = [
  { key: "economy", label: "저가형", desc: "종이 벽지(합지)예요. 얇아서 벽 굴곡이 비칠 수 있어요." },
  { key: "basic", label: "기본형", desc: "실크 벽지예요. 도톰하고 물걸레로 닦을 수 있어요." },
];

export const WHEN_LABEL = { date: "날짜가 정해졌어요", movein: "이사하는 날만 정해졌어요", months: "1~2달 안에", unknown: "아직 몰라요" } as const;

export function sizeLabel(s: { band?: string | null; basis?: string | null; m2?: string | number | null }) {
  if (s.band) return s.band === "50" ? "50평 이상" : `${s.band}평대`;
  return `${s.basis === "exclusive" ? "전용" : "공급"} ${s.m2}㎡`;
}
export const budgetLabel = (k: string | null | undefined) => BUDGETS.find((b) => b.key === k)?.label ?? "정하지 않음";
export const mokLabel = (k: string) => MOK_ITEMS.find((m) => m.key === k)?.label ?? k;
export const gradeLabel = (k: string | null | undefined) => DOBAE_GRADES.find((g) => g.key === k)?.label ?? "유형 미정";

export const tradeLabel = (k: string) => (k === "dobae" ? "도배" : k === "mokgong" ? "목공" : k);
/** 공정별 기능공 이름 (공정표 '기간은 이렇게 계산해요') */
export const crewLabel = (k: string) => (k === "dobae" ? "도배공" : k === "mokgong" ? "목수" : "기능공");

/** 견적 줄 포함 상태 6종 (AGENTS.md 3장). 합계에는 '포함'과 '따로 계산'만 들어간다 */
export const LINE_STATES: Record<string, string> = {
  included: "포함", bundled: "묶음 포함", separate: "따로 계산", optional: "선택", after_visit: "실측 후", excluded: "안 함",
};
export const lineStateLabel = (k: string) => LINE_STATES[k] ?? "확인 중";
/** 금액이 있어도 합계 밖인 줄: 괄호 금액으로 보인다 */
export const outsideTotal = (k: string) => k === "optional" || k === "after_visit";

/** 단가 버전 "2026H2" → "2026 하반기" */
export function priceVerLabel(v: string) {
  const m = /^(\d{4})H([12])$/.exec(v);
  return m ? `${m[1]} ${m[2] === "1" ? "상반기" : "하반기"}` : v;
}

/** 고객 화면의 공정 순서: 공사 순서(목공 → 도배). 탭 · 공정별 상태 · 공정표 · 공사 이름이 같이 쓴다 */
export const TRADE_ORDER = ["mokgong", "dobae"] as const;

/** 이동 경로 · 서류 머리의 공사 이름: "서울 노원구 · 목공 · 도배" */
export function projectTitle(region: string, trades: string[]) {
  const t = TRADE_ORDER.filter((k) => trades.includes(k)).map(tradeLabel);
  return [region, ...t].join(" · ");
}

// ── 업체 가입 심사 (backend/app/vendor/models.py NEEDS_INFO_CODES · REJECT_CODES, service.py OPEN_FIELDS)

export type Reason = { key: string; label: string };
/** 보완 요청 사유. other(직접 쓰기)면 업체에 보낼 말이 꼭 있어야 한다 */
export const NEEDS_INFO_REASONS: Reason[] = [
  { key: "blurry", label: "사진이 흐려서 글자가 안 보여요" },
  { key: "name_mismatch", label: "상호가 신청서와 달라요" },
  { key: "owner_mismatch", label: "대표자가 신청서와 달라요" },
  { key: "other", label: "직접 쓰기" },
];
export const REJECT_REASONS: Reason[] = [
  { key: "wrong_business", label: "업종이 인테리어 공사와 맞지 않아요" },
  { key: "closed", label: "휴업 · 폐업 상태예요" },
  { key: "other", label: "직접 쓰기" },
];
/** 사유 화면 말. 직접 쓰기(other)는 사유 줄 없이 보낼 말만 보여서 null */
export function reasonLabel(action: string, code: string | null | undefined): string | null {
  if (!code || code === "other") return null;
  const list = action === "reject" || action === "rejected" ? REJECT_REASONS : NEEDS_INFO_REASONS;
  return list.find((r) => r.key === code)?.label ?? null;
}
/** 보완 요청 사유마다 업체 홈 첫 줄 */
export function needsInfoTitle(code: string | null | undefined): string {
  return code === "name_mismatch" ? "상호를 등록증과 같게 고쳐 주세요" : code === "owner_mismatch" ? "대표자를 등록증과 같게 고쳐 주세요" : "사업자등록증을 다시 올려 주세요";
}
/** 보완 요청 사유마다 업체에게 열리는 칸 (화면 안내용. 실제로 여는 것은 서버) */
export function needsInfoOpenText(code: string | null | undefined): string {
  return code === "name_mismatch" ? "상호 · 사업자등록증 파일" : code === "owner_mismatch" ? "대표자 이름 · 사업자등록증 파일" : "사업자등록증 파일";
}
export const VENDOR_STATUS_LABEL: Record<string, string> = { pending: "심사 기다림", needs_info: "보완 요청", approved: "승인", rejected: "거절" };
/** 처리 기록 '한 일' */
export const REVIEW_ACTION_LABEL: Record<string, string> = {
  apply: "업체가 가입 신청", resubmit: "업체가 보완해서 다시 보냄", reapply: "업체가 다시 신청",
  approve: "승인", needs_info: "보완 요청", reject: "거절",
};
/** 다시 낸 신청의 바뀐 칸 (service.py changes 키) */
const CHANGED_LABEL: Record<string, string> = { biz_name: "상호", owner_name: "대표자", phone: "휴대폰", trades: "공정", areas: "활동 지역", file: "사업자등록증" };
export function changedText(changes: Record<string, unknown> | null | undefined): string {
  const ks = Object.keys(CHANGED_LABEL).filter((k) => changes && k in changes);
  return ks.length ? ks.map((k) => CHANGED_LABEL[k]).join(" · ") : "없음";
}
/** "2148603518" → "214-86-03518" (화면 표시만) */
export function bizNoText(v: string | null | undefined): string {
  const d = (v ?? "").replace(/\D/g, "");
  return d.length === 10 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : v ?? "";
}
/** "01061428830" → "010-6142-8830" (화면 표시만) */
export function phoneText(v: string | null | undefined): string {
  const d = (v ?? "").replace(/\D/g, "");
  if (d.length === 11) return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
  return v ?? "";
}

// 실측 · 연락 (업체 고르기 · 실측 요청 · 작업함이 같이 쓴다)
export type ContactMethod = "phone" | "sms" | "kakao" | "web";
/** 연락 방법 이름 */
export const CONTACT_LABEL: Record<ContactMethod, string> = { phone: "전화", sms: "문자", kakao: "카카오톡 채널", web: "홈페이지 상담" };
/** 업체가 정한 연락 방식 한 줄 */
export const CONTACT_WAY: Record<ContactMethod, string> = { phone: "전화로 연락해요", sms: "문자 주시면 연락드려요", kakao: "카카오톡 채널로 상담해요", web: "홈페이지에서 상담해요" };
/** 업체가 실측 요청을 못 받는 이유 */
export const DECLINE_LABEL: Record<"full" | "out_of_area" | "other", string> = { full: "일정이 꽉 찼어요", out_of_area: "지역 밖이에요", other: "그 밖" };
