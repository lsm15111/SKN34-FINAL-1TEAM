// 확정 공정표 아래 업체 연락처 (시안 WPlanDone '업체 연락처'): 공정마다 확정한 업체 · 대표 · 번호(글자로만).
// 연락처는 실측 요청 목록(GET visits)이 공개 규칙대로 준 것만 받는다. 없으면 이 칸을 그리지 않는다.
import type { Schemas } from "@/lib/backend/client";
import { phoneText, tradeLabel } from "@/lib/labels";
import s from "./plan.module.css";

export type PlanContact = { trade: string; vendorName: string; ct: Schemas["ContactOut"]; until?: string | null };

export function PlanContacts({ rows }: { rows: PlanContact[] }) {
  const shown = rows.filter((r) => r.ct.phone);
  if (!shown.length) return null;
  return (
    <section aria-labelledby="pc-h" className={s.contacts}>
      <h2 id="pc-h" className={s.ctH}>업체 연락처</h2>
      <ul className={`mj-num ${s.ctList}`}>
        {shown.map(({ trade, vendorName, ct }) => (
          <li key={trade}>
            <p className={s.ctTrade}>{tradeLabel(trade)}</p>
            <p className={s.ctMain}>{vendorName}{ct.owner_name ? ` · 대표 ${ct.owner_name}` : ""}<br /><b className={s.phone}>{phoneText(ct.phone ?? "")}</b></p>
          </li>
        ))}
      </ul>
    </section>
  );
}
