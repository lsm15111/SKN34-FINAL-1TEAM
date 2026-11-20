"use client";
// 용어 자세히 칸: 웹(≥768)은 오른쪽 480px 서랍, 폰은 아래 시트. 주소 ?term=이 있으면 열려 있어요(뒤로 가기로 닫혀요).
// 카드(TermLink)로 열었으면 닫을 때 뒤로 가고, 주소로 바로 왔으면 ?term=만 지워요(기록이 두 번 쌓이지 않게).
// 칸 안 다른 용어로 옮길 때는 기록을 바꿔 써서(replace) 한 번 닫으면 목록으로 돌아와요.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ComponentProps, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { useModal } from "@/components/ui/useModal";
import s from "./guide.module.css";

let pushed = false;

/** 용어 칸을 여는 링크. 목록 스크롤은 그대로 둬요 */
export function TermLink({ inPanel, ...rest }: ComponentProps<typeof Link> & { inPanel?: boolean }) {
  return (
    <Link
      {...rest}
      scroll={false}
      replace={inPanel}
      onClick={(e) => {
        rest.onClick?.(e);
        if (!inPanel && !e.defaultPrevented && !e.metaKey && !e.ctrlKey && !e.shiftKey) pushed = true;
      }}
    />
  );
}

export function TermPanel({ id, label, closeHref, head, children }: { id: string; label: string; closeHref: string; head: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const close = () => {
    if (pushed) {
      pushed = false;
      router.back();
    } else router.replace(closeHref, { scroll: false });
  };
  const m = useModal(ref, true, close);
  // 다른 용어로 옮기면 맨 위부터 읽어요
  useEffect(() => { body.current?.scrollTo(0, 0); }, [id]);
  // 뒤로 · 앞으로 가기로 옮기면 다음 닫기는 ?term=만 지워요
  useEffect(() => {
    const onPop = () => { pushed = false; };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <dialog ref={ref} className={s.panel} aria-label={label} onCancel={m.onCancel} onClick={m.onClick}>
      <div className={s.panelIn}>
        <div className={s.panelHead}>
          {head}
          <button type="button" className={s.panelX} aria-label="닫기" onClick={close}><Icon name="close" /></button>
        </div>
        <div ref={body} className={s.panelBody}>{children}</div>
      </div>
    </dialog>
  );
}
