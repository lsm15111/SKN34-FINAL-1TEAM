"use client";
// 비슷한 예시 평면도 고르기. 고르지 않으면 평형으로 어림한다.
import type { MvpPlan } from "@/lib/api/mvp";
import { decText } from "@/lib/format";
import s from "./mvp.module.css";

export function PlanPicker({
  plans,
  planId,
  expanded,
  onPlan,
  onExpanded,
}: {
  plans: MvpPlan[];
  planId: string | null;
  expanded: boolean;
  onPlan: (id: string | null) => void;
  onExpanded: (v: boolean) => void;
}) {
  const picked = plans.find((p) => p.id === planId) ?? null;
  return (
    <section className={s.card} aria-labelledby="mvp-plan-t">
      <h2 id="mvp-plan-t" className="mj-h2">1. 비슷한 평면도 고르기</h2>
      <p className="mj-small">우리 집과 방 수 · 크기가 비슷한 평면도를 고르면 방마다 잰 길이 · 면적으로 다시 계산해요.</p>
      <div className={s.planList} role="radiogroup" aria-label="평면도">
        <label className={s.planRow}>
          <input type="radio" name="mvp-plan" checked={planId === null} onChange={() => onPlan(null)} />
          <span>
            <b>평면도 없이 계산</b>
            <span className="mj-small">평형으로 어림해요 (표준견적서와 같은 방법)</span>
          </span>
        </label>
        {plans.map((p) => (
          <label key={p.id} className={s.planRow}>
            <input type="radio" name="mvp-plan" checked={planId === p.id} onChange={() => onPlan(p.id)} />
            <span>
              <b>
                {p.name} {p.type}
              </b>
              <span className="mj-small">
                공급 {p.supply_py}평({decText(p.supply_m2)}㎡) · 방 {p.rooms} · 욕실 {p.baths} · {p.layout}
                {p.year ? ` · ${p.year}년` : p.stage ? ` · ${p.stage}` : ""}
              </span>
            </span>
          </label>
        ))}
      </div>
      {picked ? (
        <div className={s.planPicked}>
          {picked.has_ext ? (
            <label className={s.check}>
              <input type="checkbox" checked={expanded} onChange={(e) => onExpanded(e.target.checked)} />
              발코니를 확장했어요
            </label>
          ) : (
            <p className="mj-small">확장 전 평면도예요. 발코니를 확장했다면 실측 때 늘어난 만큼 더해요.</p>
          )}
          <p className="mj-small">
            출처:{" "}
            <a className="mj-lnk" href={picked.src_url} target="_blank" rel="noreferrer">
              {picked.src}
            </a>
          </p>
        </div>
      ) : null}
    </section>
  );
}
