// 기본 정보 · 요청 뒤 잠김(C50): 실측 요청을 보내면 업체가 받은 내용과 같아야 해서 바꿀 수 없어요(점검판 P3-1).
// 한 공사 화면의 '기본 정보'와 표준견적서 '바꾸기'가 이 화면을 열어요. 다른 조건으로 보려면 새로 받아요.
// 직접 할 일만은 요청 뒤에도 고쳐요(diy를 주면 아래 DiyEdit, 서버 PUT /projects/{id}/diy). 철거 범위를 포함한 나머지는 읽기만이에요.
import { Icon } from "@/components/ui/Icon";
import { dateShort } from "@/lib/v5/format";
import { summaryRows, type InfoDraft } from "@/lib/v5/guest/info";
import type { Caps } from "@/lib/v5/caps";
import { DiyEdit } from "./DiyEdit";
import s from "./info.module.css";
import q from "./standard.module.css";

export function InfoLocked({ draft, region, today, rooms, diy, caps }: {
  draft: InfoDraft; region: string; today: string; rooms?: number;
  /** 기능 확인(서버): 꺼져 있으면 방 개수 · 철거 범위 · 직접 할 일 줄과 직접 할 일 고치기를 그리지 않아요 */
  caps: Caps;
  /** 직접 할 일 고치기(만든 고객의 공사). after: 저장 뒤 갈 곳 · focus: 처음 초점 */
  diy?: { projectId: string; after?: string; focus?: boolean; mock?: boolean };
}) {
  const rows = summaryRows(draft, caps, { fullRegion: region, rooms, longDate: draft.start ? dateShort(draft.start, today) : undefined })
    .filter((r) => !(diy && r.label === "직접 할 일"));
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
      {diy && caps.v4 ? <DiyEdit projectId={diy.projectId} initial={draft.diy ?? null} after={diy.after} focus={diy.focus} mock={diy.mock} /> : null}
    </>
  );
}
