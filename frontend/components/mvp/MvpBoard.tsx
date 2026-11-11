"use client";
// 도면 · 자재로 견적 보기: 고른 값이 바뀔 때마다 미리 보기 API를 다시 부르고, 마지막 요청의 답만 보인다.
// 화면은 금액을 계산하지 않는다. 고른 값만 보내고 API(계산 엔진)가 준 숫자를 그대로 보인다.
import { useEffect, useRef, useState } from "react";
import type { MvpMaterials, MvpMokSel, MvpPlan, MvpPreview, MvpPreviewIn } from "@/lib/api/mvp";
import { call, errorText } from "@/lib/backend/client";
import { type Grade } from "./labels";
import { MokPanel } from "./MokPanel";
import { PlanPicker } from "./PlanPicker";
import { PreviewResult } from "./PreviewResult";
import s from "./mvp.module.css";

function firstOf(m: MvpMaterials, kind: string) {
  return m.products.find((p) => p.kind === kind)?.id ?? null;
}

/** 등급을 고르면 몰딩 · 걸레받이는 그 등급의 처음 자재로, 문 작업 방식과 정해진 단가 항목은 그대로 둔다 */
export function selFor(m: MvpMaterials, grade: Grade, prev?: MvpMokSel): MvpMokSel {
  const g = m.grades[grade];
  const mode = prev?.door?.mode ?? "none";
  return {
    door: { mode, pick: mode === "none" ? null : mode === "replace" ? g.door_set : g.leaf, count: prev?.door?.count ?? null },
    slide: prev?.slide ?? { n: 0, pick: firstOf(m, "slide") },
    hidden: prev?.hidden ?? { n: 0, pick: firstOf(m, "hidden") },
    molding_type: g.molding_type as MvpMokSel["molding_type"],
    molding: g.molding,
    base: g.base,
    extras: prev?.extras ?? {},
  };
}

export function MvpBoard({
  projectId,
  dobaeGrade,
  hasMokgong,
  plans,
  materials,
}: {
  projectId: string;
  dobaeGrade: string | null;
  hasMokgong: boolean;
  plans: MvpPlan[];
  materials: MvpMaterials;
}) {
  const [planId, setPlanId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [grade, setGrade] = useState<Grade>(dobaeGrade === "economy" ? "economy" : "basic");
  const [mok, setMok] = useState<MvpMokSel>(() => selFor(materials, dobaeGrade === "economy" ? "economy" : "basic"));
  const [result, setResult] = useState<MvpPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const seq = useRef(0);

  useEffect(() => {
    const n = ++seq.current;
    const body: MvpPreviewIn = { plan_id: planId, expanded, grade, mok: hasMokgong ? mok : null };
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const r = await call<MvpPreview>("POST", `/mvp/projects/${projectId}/preview`, body);
        if (n === seq.current) {
          setResult(r);
          setError("");
        }
      } catch (e) {
        if (n === seq.current) setError(errorText(e));
      } finally {
        if (n === seq.current) setBusy(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [projectId, planId, expanded, grade, mok, hasMokgong]);

  function pickGrade(g: Grade) {
    setGrade(g);
    setMok((prev) => selFor(materials, g, prev));
  }

  return (
    <div className={s.board}>
      <div className={s.choose}>
        <PlanPicker plans={plans} planId={planId} expanded={expanded} onPlan={setPlanId} onExpanded={setExpanded} />
        <MokPanel materials={materials} grade={grade} onGrade={pickGrade} sel={mok} onSel={setMok} hasMokgong={hasMokgong} />
      </div>
      <div className={s.result}>
        <PreviewResult result={result} busy={busy} error={error} />
      </div>
    </div>
  );
}
