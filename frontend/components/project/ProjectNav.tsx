"use client";
// 프로젝트 안 이동. 차례가 있는 단계만 1~6 번호를 붙이고, 진행 현황(모아 보기)과 이력(기록)은 번호 없이 따로 둔다.
// 가견적 요청은 3 업체 고르기, 실측 요청은 4 가견적 비교, 업체 확정은 5 실측 견적 안에서 한다.
// ready=false: 실제 프로젝트에서 아직 API가 없는 단계. 번호와 이름만 보이고 누를 수 없다. live에 적은 단계만 누를 수 있다.
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ProjectStage } from "@/lib/types";

const STEPS = [
  { seg: "plan", label: "예상 공정표" },
  { seg: "standard", label: "표준견적서" },
  { seg: "vendors", label: "업체 고르기", also: ["request"] },
  { seg: "quotes", label: "가견적 비교" },
  { seg: "measure", label: "실측 견적" },
  { seg: "schedule", label: "확정 공정표" },
];
// 단계별로 끝난 단계 수. 예상 공정표 · 표준견적서는 프로젝트를 만들 때 함께 나온다.
const DONE: Record<ProjectStage, number> = { draft: 0, planned: 2, quoting: 3, comparing: 3, measuring: 4, confirmed: 5, scheduled: 6 };

export function ProjectNav({ id, stage, ready = true, live = [] }: { id: string; stage: ProjectStage; ready?: boolean; live?: string[] }) {
  const path = usePathname();
  const base = `/projects/${id}`;
  const done = DONE[stage];
  const isCur = (seg: string, also: string[] = []) => [seg, ...also].some((s) => path === `${base}/${s}`);
  return (
    <nav aria-label="프로젝트 단계" className="mj-pnav">
      <Link href={base} className="mj-pnav-side" aria-current={path === base ? "page" : undefined}>진행 현황</Link>
      <ol className="mj-steps">
        {STEPS.map((it, i) => {
          const cur = isCur(it.seg, it.also);
          const finished = i < done;
          if (!ready && !live.includes(it.seg)) {
            return (
              <li key={it.seg}>
                <span className="off"><span className="mj-step-n mj-num" aria-hidden="true">{i + 1}</span>{it.label}<span className="mj-sr"> · 아직 연결 전</span></span>
              </li>
            );
          }
          return (
            <li key={it.seg}>
              <Link href={`${base}/${it.seg}`} aria-current={cur ? "page" : undefined} className={finished && !cur ? "done" : undefined}>
                <span className="mj-step-n mj-num" aria-hidden="true">{i + 1}</span>{it.label}
                {finished ? <span className="mj-sr"> · 끝남</span> : i === done ? <span className="mj-sr"> · 지금 할 차례</span> : null}
              </Link>
            </li>
          );
        })}
      </ol>
      {ready ? <Link href={`${base}/history`} className="mj-pnav-side" aria-current={path === `${base}/history` ? "page" : undefined}>이력</Link> : null}
    </nav>
  );
}
