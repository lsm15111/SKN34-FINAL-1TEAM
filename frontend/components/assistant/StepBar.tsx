"use client";
// 단계 띠 7칸(v2 .steps): 집 정보 · 표준견적서 · 업체 · 실측 · 견적서 · 공정표 · 공사. 3px 막대 + 13px 글자.
// 지난 단계 검정 · 지금 파랑 · 앞 단계 흐림. 지난 칸 · 지금 칸을 누르면 그 단계의 전체 화면 카드가 열려요(집 정보는 대화 속 집 카드로).
// 대화가 길면 오른쪽에 '오늘 정할 일 n ›'(웹)이 붙어요.
import Link from "next/link";
import { I } from "./kit/icons";
import s from "./assistant.module.css";

export const STEP_LABELS = ["집 정보", "표준견적서", "업체", "실측", "견적서", "공정표", "공사"] as const;

export function StepBar({ base, editHref, current, onHome, today, onToday }: {
  base: string;
  /** 집 카드가 대화에 없을 때 가는 곳(v3 기본 정보 고치기) */
  editHref: string;
  current: number;
  /** 집 정보 칸: 대화 속 집 카드로 가요(없으면 v3 기본 정보 고치기) */
  onHome: () => boolean;
  today: number;
  onToday: () => void;
}) {
  const href = ["", `${base}/standard`, `${base}/vendors`, `${base}/visits`, `${base}/quotes`, `${base}/plan`, `${base}/schedule`];
  return (
    <div className={s.stepper} data-stepper="">
      <nav className={s.steps} aria-label="공사 단계">
        {STEP_LABELS.map((label, i) => {
          const cls = i < current ? `${s.step} ${s.stepDone}` : i === current ? `${s.step} ${s.stepNow}` : `${s.step} ${s.stepLater}`;
          const cur = i === current ? ("step" as const) : undefined;
          if (i > current) return <span key={label} className={cls} aria-disabled="true">{label}</span>;
          if (i === 0) return <a key={label} className={cls} href={editHref} aria-current={cur} onClick={(e) => { if (onHome()) e.preventDefault(); }}>{label}</a>;
          return <Link key={label} className={cls} href={href[i]} aria-current={cur} scroll={false}>{label}</Link>;
        })}
      </nav>
      {today > 0 ? (
        <button type="button" className={s.pin} onClick={onToday}><I n="bell" />오늘 정할 일 <span className={s.cnt}>{today}</span><I n="chev" /></button>
      ) : null}
    </div>
  );
}
