// 내 프로젝트 카드 (디자인 예시 05): 단계 띠 + 공정마다 차례 한 줄(내 차례 · 업체 차례 · 일정 확정).
// 카드 아무 곳이나 누르면 진행 현황으로 간다(제목 링크를 카드 전체로 넓힘). 공정 줄 문구는 그 위에 따로 눌려 그 공정 화면으로 간다.
// 강조색은 '내 차례'와 지금 단계에만 쓴다.
import Link from "next/link";
import { TRADE_LABEL } from "@/lib/types";
import { TURN_LABEL, hrefOf, projectStep, turnOf, type TradeLine } from "@/lib/trade-status";
import { md } from "@/lib/format";
import { ProjectTrack } from "@/components/project/ProjectTrack";

export function ProjectCard({ id, title, sub, created, lines, demo }: { id: string; title: string; sub?: string; created: string; lines: TradeLine[]; demo?: boolean }) {
  return (
    <article className="mj-pcard" aria-labelledby={`pc-${id}`}>
      <div className="mj-pcard-head">
        <h3 id={`pc-${id}`} className="mj-h3"><Link href={`/projects/${id}`} className="mj-pcard-link">{title}</Link>{demo ? <> <span className="mj-badge">예시</span></> : null}</h3>
        <span className="mj-small mj-num">{sub ? `${sub} · ` : ""}만든 날 {md(created)}</span>
      </div>
      <ProjectTrack now={projectStep(lines)} />
      <ul className="mj-pcard-lines" aria-label="공정별 차례">
        {lines.map((l) => {
          const turn = turnOf(l);
          return (
            <li key={l.trade}>
              <b>{TRADE_LABEL[l.trade]}</b>
              <span className={`mj-turn mj-turn-${turn}`}>{TURN_LABEL[turn]}</span>
              <Link href={hrefOf(id, l)}>{l.text}</Link>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
