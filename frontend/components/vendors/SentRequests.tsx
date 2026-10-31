// 이 프로젝트에서 믿집 업체에 보낸 가견적 요청과 상태 (요청했어요 · 업체가 확인했어요). 상태 글은 API가 준다.
import type { SentRequest } from "@/lib/api/quote";
import { dateSeoul, md } from "@/lib/format";
import s from "./SentRequests.module.css";

export function SentRequests({ items }: { items: SentRequest[] }) {
  return (
    <section className="mj-panel" aria-labelledby="sent-h">
      <h2 id="sent-h" className="mj-h3">요청한 가견적 <span className="mj-num">{items.length}건</span></h2>
      <ul className={s.list}>
        {items.map((r) => (
          <li key={r.id} className={s.item}>
            <span className={s.who}><b>{r.vendor_name}</b> · {r.trade_label}</span>
            <span className={`mj-badge ${r.status === "viewed" ? "mj-b-ok" : "mj-b-wait"}`}>{r.status_label}</span>
            <span className="mj-tiny mj-num">요청 {md(dateSeoul(r.created_at))}{r.viewed_at ? ` · 확인 ${md(dateSeoul(r.viewed_at))}` : ""}</span>
          </li>
        ))}
      </ul>
      <p className="mj-tiny">업체가 요청을 열어 보면 &lsquo;업체가 확인했어요&rsquo;로 바뀌어요. 업체 가견적서를 받아 비교하는 화면은 다음에 열려요.</p>
    </section>
  );
}
