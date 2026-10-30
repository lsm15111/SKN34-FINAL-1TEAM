// 프로젝트 단계 띠 (디자인 예시 05에서 옮김). 끝난 칸은 체크, 지금 칸은 '지금' 표시.
// 아이콘은 24px 격자 · 선 1.8px로 프로젝트 이동 메뉴 아이콘과 같은 모양이다. 좁은 화면에서는 지금 칸 이름만 보인다.
const STEPS: { label: string; icon: React.ReactNode }[] = [
  { label: "예상 공정표", icon: <><path d="M4 6.5h8" /><path d="M8 12h10" /><path d="M13 17.5h7" /><path d="M4 4v16" /></> },
  { label: "표준견적서", icon: <><rect x="5" y="3.5" width="14" height="17" rx="2" /><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4" /></> },
  { label: "업체 고르기", icon: <><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 4.5 4.5" /></> },
  { label: "가견적 비교", icon: <><rect x="3.5" y="5" width="7.5" height="14" rx="1.5" /><rect x="13" y="5" width="7.5" height="14" rx="1.5" /><path d="M6 9h2.5M15.5 9h2.5M6 12.5h2.5M15.5 12.5h2.5" /></> },
  { label: "실측 견적", icon: <><rect x="2.5" y="8.5" width="19" height="7" rx="1.5" /><path d="M6.5 8.5v3M10 8.5v2M13.5 8.5v3M17 8.5v2" /></> },
  { label: "확정 공정표", icon: <><rect x="4" y="5.5" width="16" height="14.5" rx="2" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /><path d="m9 15 2 2 4-4" /></> },
];

export function ProjectTrack({ now }: { now: number }) {
  return (
    <ol className="mj-track" aria-label="프로젝트 단계">
      {STEPS.map((t, k) => (
        <li key={t.label} className={k < now ? "is-done" : k === now ? "is-cur" : undefined} aria-current={k === now ? "step" : undefined}>
          <span className="mj-track-dot">
            {k < now ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m3.5 8.5 3 3 6-6.5" /></svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{t.icon}</svg>
            )}
          </span>
          <span className="mj-track-label">{t.label}{k < now ? <span className="mj-sr"> · 끝남</span> : null}</span>
          {k === now ? <span className="mj-track-now">지금</span> : null}
        </li>
      ))}
    </ol>
  );
}
