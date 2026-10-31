import { LINE_BASIS, type LineBasis } from "@/lib/labels";

const CLS: Record<LineBasis, string> = { public: "mj-b-public", assumed: "mj-b-assumed", none: "mj-b-check" };

/** 견적 줄 근거 배지: 공공 기준 · 가정 · 실측 후 확인 */
export function BasisBadge({ basis }: { basis: LineBasis }) {
  return <span className={`mj-badge ${CLS[basis]}`}>{LINE_BASIS[basis].label}</span>;
}
