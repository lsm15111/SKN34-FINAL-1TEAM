// 기본 정보 · 요청 뒤 잠김(C50): 실측 요청을 보내면 업체가 받은 내용과 같아야 해서 바꿀 수 없어요(점검판 P3-1).
// 한 공사 화면의 '기본 정보'와 표준견적서 '바꾸기'가 이 화면을 열어요. 다른 조건으로 보려면 새로 받아요.
import { Icon } from "@/components/ui/Icon";
import { dateShort } from "@/lib/format";
import { summaryRows, type InfoDraft } from "@/lib/guest/info";
import s from "./info.module.css";
import q from "./standard.module.css";

export function InfoLocked({ draft, region, today, rooms }: { draft: InfoDraft; region: string; today: string; rooms?: number }) {
  const rows = summaryRows(draft, { fullRegion: region, rooms, longDate: draft.start ? dateShort(draft.start, today) : undefined });
  return (
    <>
      <p className={s.locked} role="status"><Icon name="lock" size={18} />실측 요청을 보내서 기본 정보를 바꿀 수 없어요. 업체가 받은 내용과 같아야 해서요.</p>
      <section className={q.group} aria-label="넣은 기본 정보">
        <dl className={s.rows}>
          {rows.map((r) => (
            <div key={r.label} className={s.row}>
              <dt>{r.label}{r.sub ? <span>{r.sub}</span> : null}</dt>
              <dd className="mj-num">{r.value || "—"}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
