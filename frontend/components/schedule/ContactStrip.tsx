// 확정한 업체 연락처 줄 (시안 WSchedule '업체 연락처'). 연락처는 실측 요청 목록(GET visits)이 공개 규칙대로 준 것만 보인다.
// 번호는 글자로만 보인다(복사 · 전화 걸기 버튼 없음). 보이는 기한은 실측 요청 확인 창에서 알린다.
import { callHours } from "@/components/vendors/text";
import type { Schemas } from "@/lib/backend/client";
import { phoneText, tradeLabel } from "@/lib/labels";
import s from "./schedule.module.css";

type Contact = Schemas["ContactOut"];

export function ContactStrip({ trade, vendorName, ct }: { trade: string; vendorName: string; ct: Contact; until?: string | null }) {
  const hours = callHours(ct.call_start, ct.call_end);
  return (
    <section aria-labelledby="ct-h" className={s.contact}>
      <h2 id="ct-h" className={s.ctH}>업체 연락처</h2>
      <div className={`mj-num ${s.ctRow}`}>
        <p className={s.ctTrade}>{tradeLabel(trade)}</p>
        <p className={s.ctMain}>
          {vendorName}{ct.owner_name ? ` · 대표 ${ct.owner_name}` : ""}
          {ct.phone ? <> · <b className={s.phone}>{phoneText(ct.phone)}</b></> : null}
          {hours ? <span className="mj-small"> · 통화 가능 {hours}</span> : null}
        </p>
      </div>
    </section>
  );
}
