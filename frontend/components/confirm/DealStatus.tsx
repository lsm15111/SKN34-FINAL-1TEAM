// 확정한 뒤 두 줄 (시안 WConfirm '확정한 뒤'): "도배는 마루와벽으로 확정했어요 · 11.8(일) 10:12" + 공사 날짜 기다림 · 기한.
// 기한(dates_due_at) · 기한 지남(overdue)은 API 값 그대로다. 확정 화면 · 비교 화면이 같이 쓴다.
import { Check, Warn } from "@/components/vendors/icons";
import { eunNeun } from "@/components/vendors/text";
import { euro } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { DEAL_LABEL, dates, when, type Deal } from "./text";
import s from "./confirm.module.css";

export const Clock = () => (
  <svg width="16" height="16" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="7" cy="7" r="5.5" /><path d="M7 4v3.2l2 1.3" /></svg>
);

/** titled: 화면 제목이 이미 '확정했어요'라고 말함 → 첫 줄은 확정한 때만 */
export function DealStatus({ d, titled = false }: { d: Deal; titled?: boolean }) {
  const tName = tradeLabel(d.trade);
  return (
    <div className={s.dealLines}>
      {titled ? (
        <p className="mj-small mj-num">{when(d.confirmed_at)}에 확정</p>
      ) : (
        <p className={`mj-st mj-st-ok mj-num ${s.stLine} ${s.stBig}`}><Check size={16} />{eunNeun(tName)} {euro(d.vendor_name)} 확정했어요 · {when(d.confirmed_at)}</p>
      )}
      {d.status !== "confirmed" ? (
        <p className={`mj-st mj-st-ok mj-num ${s.stLine}`}>{dates(d) ? `공사 날짜 ${dates(d)} · ` : ""}{DEAL_LABEL[d.status] ?? "확정함"}</p>
      ) : d.overdue ? (
        <>
          <p className={`mj-st mj-st-bad mj-num ${s.stLine}`}><Warn />공사 날짜 기한이 지났어요 · {when(d.dates_due_at)}까지였어요</p>
          <p className="mj-small">업체에 먼저 연락해 보세요. 날짜가 오면 알림으로 알려 드려요.</p>
        </>
      ) : (
        <p className={`mj-st mj-st-wait mj-num ${s.stLine}`}><Clock />공사 날짜를 기다려요 · {when(d.dates_due_at)}까지</p>
      )}
    </div>
  );
}
