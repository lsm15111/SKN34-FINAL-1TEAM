// 내 공사 목록 (시안 WMy · 3안). 공사마다 카드 하나: 이름(지역 · 공정) · 집 정보, 지금 할 일 버튼, 6단계 진행 표시.
// 단계 · 할 일은 서버 값을 그대로 쓰고, 화면 말만 붙인다(./text.ts).
import Link from "next/link";
import type { ApiProjectItem } from "@/lib/api/project";
import { dateSeoul, md } from "@/lib/format";
import { gradeLabel, projectTitle, sizeLabel, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import { STEP_NAMES, stepNote } from "./text";
import s from "./my.module.css";

function Check() {
  return <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M2.5 6.3l2.3 2.3L9.5 3.8" /></svg>;
}

function Steps({ p }: { p: ApiProjectItem }) {
  // 공사 날짜를 수락한 뒤(공사 · 끝남)는 여섯 단계를 다 마친 것이다
  const allDone = p.phase === "work" || p.phase === "done";
  const note = stepNote(p, allDone);
  return (
    <ol className={s.stp}>
      {STEP_NAMES.map((name, i) => {
        const n = i + 1;
        const state = allDone || n < p.current ? "dn" : n === p.current ? "cu" : "";
        const last = n === STEP_NAMES.length;
        return (
          <li key={name} className={`${s.sp} ${state ? s[state] : ""}`}>
            <span className={`${s.dt} ${state ? s[state] : ""}`}>{state === "dn" ? <Check /> : null}</span>
            <span className={s.spL}>{name}<span className="mj-sr">, {state === "dn" ? "끝남" : state === "cu" ? "지금" : "아직"}</span></span>
            {note && (state === "cu" || (allDone && last)) ? <span className="mj-small">{note}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

function Card({ p }: { p: ApiProjectItem }) {
  const title = projectTitle(p.region, p.trades);
  const trades = TRADE_ORDER.filter((t) => p.trades.includes(t)).map((t) => {
    const grade = t === "dobae" ? p.grades[t] : null;
    return grade ? `${tradeLabel(t)} ${gradeLabel(grade)}` : tradeLabel(t);
  });
  const home = `/projects/${p.id}`;
  return (
    <li className={s.pj}>
      <div className={s.pjH}>
        <div className={s.pjT}>
          <h2 className="mj-h2"><Link className={s.tl} href={home}>{title}</Link></h2>
          <p className="mj-sub"><span className="mj-code">{p.code}</span> · {[`아파트 ${sizeLabel(p.size)}`, ...trades].join(" · ")} · <span className="mj-num">{md(dateSeoul(p.updated_at))}</span>에 바뀜</p>
        </div>
        <div className={s.acts}>
          {p.todo ? <Link className="mj-btn mj-btn-pri" href={p.todo.link}>{p.todo.action}<span className="mj-sr"> · {title}</span></Link> : null}
        </div>
      </div>
      <Steps p={p} />
    </li>
  );
}

export function ProjectList({ items }: { items: ApiProjectItem[] }) {
  return (
    <ul className={s.pjs}>
      {items.map((p) => <Card key={p.id} p={p} />)}
    </ul>
  );
}
