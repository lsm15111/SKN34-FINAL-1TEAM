// 비서 화면 아이콘(24 격자 · 선 2 · currentColor). 대부분 components/ui/Icon과 같은 Lucide 모양이고,
// 비서 카드에만 쓰는 몇 개(도는 원 · 건물 · 전구 · 받은 함 · 위 화살표)를 더했어요. 늘 글자와 같이 쓰고 그림은 읽지 않아요.
import type { ReactNode } from "react";

const P: Record<string, ReactNode> = {
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /></>,
  bell: <><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></>,
  back: <path d="m15 18-6-6 6-6" />,
  chev: <path d="m9 18 6-6-6-6" />,
  down: <path d="m6 9 6 6 6-6" />,
  check: <path d="M20 6 9 17l-5-5" />,
  circle: <circle cx="12" cy="12" r="7.5" />,
  dot: <circle cx="12" cy="12" r="5.5" fill="currentColor" stroke="none" />,
  spin: <path d="M21 12a9 9 0 1 1-6.2-8.56" />,
  alert: <><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5" /><path d="M12 16.5h.01" /></>,
  minus: <path d="M6 12h12" />,
  star: <path fill="currentColor" stroke="none" d="m12 2.5 2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z" />,
  file: <><path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z" /><path d="M14 2.5V8h5.5" /><path d="M8.5 13h7M8.5 17h5" /></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="2.5" /><circle cx="8.5" cy="8.5" r="1.6" /><path d="m21 15-5-5L5 21" /></>,
  calendar: <><rect x="3" y="4.5" width="18" height="17" rx="2.5" /><path d="M16 2.5v4M8 2.5v4M3 10h18" /></>,
  building: <><path d="M5 21V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v16" /><path d="M16 9h2a2 2 0 0 1 2 2v10" /><path d="M3 21h18" /><path d="M8.5 7h1M11.5 7h1M8.5 11h1M11.5 11h1M8.5 15h1M11.5 15h1" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 16v-4.5" /><path d="M12 8h.01" /></>,
  up: <><path d="M12 19V5" /><path d="m5.5 11.5 6.5-6.5 6.5 6.5" /></>,
  arrowUp: <><path d="M12 19V6" /><path d="m6 12 6-6 6 6" /></>,
  arrowDown: <><path d="M12 5v13" /><path d="m6 12 6 6 6-6" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  upload: <><path d="M12 15.5V4" /><path d="m7 9 5-5 5 5" /><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></>,
  chat: <path d="M20.5 14.5a2 2 0 0 1-2 2H8l-4.5 4V5.5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z" />,
  inbox: <><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></>,
  bulb: <><path d="M9 18h6M10 21.5h4" /><path d="M12 2.5a6.5 6.5 0 0 0-3.8 11.8c.5.4.8 1 .8 1.6V16h6v-.1c0-.6.3-1.2.8-1.6A6.5 6.5 0 0 0 12 2.5z" /></>,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  doc: <><rect x="4" y="3" width="16" height="18" rx="2.5" /><path d="M8 8h8M8 12h8M8 16h5" /></>,
  sparkle: <path d="M12 3.5 13.8 9a1.5 1.5 0 0 0 1 1l5.5 1.8-5.5 1.8a1.5 1.5 0 0 0-1 1L12 20.5l-1.8-5.5a1.5 1.5 0 0 0-1-1L3.7 12.2 9.2 10.4a1.5 1.5 0 0 0 1-1z" />,
  more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  external: <><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6" /><path d="M10 14 21 3" /></>,
  home: <><path d="M3 11 12 4l9 7v9H3z" /><path d="M9 20v-5h6v5" /></>,
};

export type IconName = keyof typeof P;

export function I({ n, className, size }: { n: IconName; className?: string; size?: number }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {P[n]}
    </svg>
  );
}

/** 믿집 로고(집 그림): 지붕은 글자색, 문은 파랑 */
export function Logo() {
  return (
    <svg viewBox="0 0 24 24" width={24} height={24} aria-hidden="true" focusable="false">
      <path d="M3 11 12 4l9 7v9H3z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9 20v-5h6v5" fill="none" stroke="var(--mj-primary)" strokeWidth="2" />
    </svg>
  );
}
