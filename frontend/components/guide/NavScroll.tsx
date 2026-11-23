"use client";
// 글 왼쪽 목록(웹 ≥1024): 목록에서 다른 글을 골라도 목록 스크롤이 맨 위로 돌아가지 않고 보던 자리에 그대로 있어요.
// 지금 글이 목록 칸 밖에 있으면(처음 들어왔을 때 등) 칸 안으로만 살짝 옮겨요. 페이지 스크롤은 건드리지 않아요.
import { useLayoutEffect, useRef, type ReactNode } from "react";

// 마지막으로 본 목록 스크롤(글을 옮겨 다녀도 이어 써요. 새로 고치면 처음부터예요)
let saved = 0;
const GAP = 8;

export function NavScroll({ className, children }: { className: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = saved;
    const cur = el.querySelector<HTMLElement>('[aria-current="page"]');
    if (cur) {
      const r = cur.getBoundingClientRect();
      const box = el.getBoundingClientRect();
      if (r.top < box.top) el.scrollTop -= box.top - r.top + GAP;
      else if (r.bottom > box.bottom) el.scrollTop += r.bottom - box.bottom + GAP;
    }
    saved = el.scrollTop;
    const keep = () => { saved = el.scrollTop; };
    el.addEventListener("scroll", keep, { passive: true });
    return () => el.removeEventListener("scroll", keep);
  }, []);
  // 글을 누르는 순간의 자리도 적어 둬요(스크롤 알림이 오기 전에 눌러도 그 자리로 돌아와요)
  return <div ref={ref} className={className} onClickCapture={() => { if (ref.current) saved = ref.current.scrollTop; }}>{children}</div>;
}
