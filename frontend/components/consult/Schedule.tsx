// 예상 공정표: 계산 엔진이 이은 단계를 현장 순서(짐 정리 → 철거 → 본 공사 → 마감 공사 → 정리)로 묶어 세로로 보인다.
import type { Schemas } from "@/lib/backend/client";
import { duration, halfDays } from "@/lib/format";
import { PHASES } from "@/lib/labels";
import s from "./Schedule.module.css";

type Step = Schemas["ScheduleStepOut"];

export function Schedule({ steps, labels, total }: { steps: Step[]; labels: Record<string, string>; total: string }) {
  const phases = PHASES.map((p) => ({ ...p, steps: steps.filter((st) => st.phase === p.key) })).filter((p) => p.steps.length);
  return (
    <section className={`mj-panel ${s.card}`} aria-labelledby="sched-h">
      <div className={s.head}>
        <h2 id="sched-h" className="mj-h2">예상 공정표</h2>
        <p className="mj-small">반나절 단위로 잡은 작업 순서예요. 모두 <b className="mj-num">약 {duration(total)}</b> 걸리고, 날짜는 실측 뒤 업체가 정해요.</p>
      </div>
      <ol className={s.phases}>
        {phases.map((p) => (
          <li key={p.key} className={s.phase}>
            <span className={s.dot} aria-hidden="true" />
            <p className={s.phaseHead}>
              <b>{p.label}</b>
              {p.desc ? <> <span className="mj-small">{p.desc}</span></> : null}
            </p>
            <ol className={s.steps}>
              {p.steps.map((st, i) => (
                <li key={`${st.trade}-${st.key}-${i}`} className={s.step}>
                  <span className={`mj-badge mj-b-in ${s.trade}`}>{labels[st.trade] ?? "공정"}</span>{" "}
                  <span className={s.name}>{st.name}</span>{" "}
                  <span className={`mj-num ${s.dur}`}>{halfDays(st.half_days)}</span>
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ol>
    </section>
  );
}
