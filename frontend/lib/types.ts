// 화면이 받는 데이터 모양. 백엔드가 붙으면 OpenAPI에서 생성한 타입으로 바꾼다.

export type Trade = "dobae" | "mokgong";
export const TRADES: Trade[] = ["dobae", "mokgong"];
export const TRADE_LABEL: Record<Trade, string> = { dobae: "도배", mokgong: "목공" };

export type LineState = "in" | "bundle" | "sep" | "opt" | "cond" | "no";
export const LINE_STATE_LABEL: Record<LineState, string> = { in: "포함", bundle: "묶음", sep: "별도", opt: "선택", cond: "실측 후", no: "안 함" };

export type Role = "customer" | "vendor" | "admin";
// vendorStatus: 업체 회원만 pending(승인 대기) · approved · rejected
export interface Session { id: string; email: string; name: string; role: Role; vendorStatus: string | null; vendorRejectReason: string | null }

export interface UnitType { id: string; py: number; supply: number; jeon: number; households: number; rooms: number }
export interface Complex { id: string; name: string; sido: string; sgg: string; dong: string; road: string; households: number; builtYear: number; types: UnitType[] }

export interface Space { id: string; name: string }

export interface VendorPortfolio { title: string; caption: string }
// 업체 정보는 출처별로 나눠 보인다 (docs/design/mypage-vendor-info.md 4장):
// 믿집이 확인한 것 (registeredAt = 승인일, license = 실내건축공사업 등록 확인),
// 업체가 적은 것 (years · since · crew · as · weekend · visitFee · intro · notes · portfolio),
// 믿집 기록 (rating · reviews · response). 연락은 안심번호로만 해서 전화번호는 두지 않는다.
export interface Vendor {
  id: string; name: string; trades: Trade[]; years: number; since: number; areas: string[];
  crew: Partial<Record<Trade, number>>; rating: number; reviews: number;
  license: boolean; response: string; as: Partial<Record<Trade, string>>; notes: string[];
  weekend: "sat" | "none"; visitFee: number;
  owner: string; bizNo: string; intro: string; portfolio: VendorPortfolio[];
  registeredAt: string; status: "active" | "paused";
}

export interface Recommendation { vendorId: string; rank: number; score: number; total: number; pros: string[]; cons: string[] }

export interface QuoteLine { k: string; name: string; qty: number | null; unit: string; amount: number | null; state: LineState; note: string }
export interface VendorQuote { vendorId: string; total: number; vat: number; direct: number; margin: number; marginRate: number; lo: number; hi: number; lines: QuoteLine[] }
export interface FinalQuote { vendorId: string; total: number; vat: number; estimateTotal: number; deltaTotal: number; findings: string[]; lines: QuoteLine[]; diff: { name: string; from: number | null; to: number | null; delta: number }[] }

export interface CompareCell { amount: number | null; text: string }
export interface CompareRow { key: string; label: string; std: CompareCell; vendors: Record<string, CompareCell> }
export interface Compare { rows: CompareRow[]; total: CompareRow }

export interface StdLine { k: string; trade: Trade; name: string; qty: number | null; unit: string; unitPrice: number | null; amount: number | null; src: string; kind: "public" | "none" }
export interface StandardQuote {
  id: string; createdAt: string; basisDate: string; sources: string[];
  qty: { wall: number; ceil: number; totalM2: number; molding: number; base: number; basis: string };
  lines: StdLine[]; totals: Record<Trade | "all", number>; excluded: string[]; notice: string;
}

export interface SlotRef { date: string; half: "am" | "pm" }
export interface ScheduleTask { k: string; label: string; team: string; s: number; e: number; why: string; from: SlotRef; to: SlotRef }
export interface Todo { who: string; when: string; t: string; d: string }
export interface ExpectedSchedule { start: string; end: string; days: string[]; tasks: ScheduleTask[]; todos: Todo[]; weekendNote: string }
export interface ConfirmedPart { vendorId: string; start: string; end: string; days: string[]; tasks: ScheduleTask[] }

export type QuoteRequestStatus = "requested" | "received" | "registered";
export interface QuoteRequest { trade: Trade; vendorId: string; status: QuoteRequestStatus; requestedAt: string; receivedAt?: string }

export type ProjectStage = "draft" | "planned" | "quoting" | "comparing" | "measuring" | "confirmed" | "scheduled";
export const STAGE_LABEL: Record<ProjectStage, string> = {
  draft: "작성 중", planned: "예상 공정표", quoting: "가견적 요청", comparing: "가견적 비교", measuring: "실측", confirmed: "업체 확정", scheduled: "공사 일정 확정",
};

export interface Project {
  id: string; title: string; createdAt: string; stage: ProjectStage;
  complex: Complex; unitTypeId: string; area: { supply: number; jeon: number; supplyPy: number }; balconyExt: boolean;
  houseType: "apt"; builtYear: number; startPlan: { kind: "date" | "movein" | "months" | "unknown"; date?: string };
  occupied: boolean; budget: string | null;
  spaces: Space[]; trades: { dobae: { spaces: string[]; grade: "economy" | "basic" } | null; mokgong: { spaces: string[]; items: string[] } | null };
  photos: { spaceId: string; name: string }[]; floorPlan: string | null;
}

export interface HistoryItem { date: string; kind: string; text: string; trade?: Trade }
export interface Member { id: string; name: string; email: string; joinedAt: string; projects: number; status: "active" | "suspended"; role: Role }
