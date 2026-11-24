"use client";
// 용어 자세히 칸: 웹(≥768)은 오른쪽 480px 서랍, 폰은 아래 시트. 주소 ?term=이 있으면 보던 백과 화면 위에 열려 있어요(뒤로 가기로 닫혀요).
// 백과 화면마다 같은 칸을 그려요(TermDetail OpenTerm). 링크는 보던 주소에 ?term=만 붙이고 스크롤을 옮기지 않아서 뒤 화면이 그대로예요.
// 링크(카드 · 글의 관련 용어 · 용어 풍선 · 찾기 창)로 열었으면 닫을 때 뒤로 가서 온 곳으로 돌아가고,
// 주소로 바로 왔으면 ?term=만 지워요(기록이 두 번 쌓이지 않게).
// 칸 안 다른 용어로 옮길 때는 기록을 바꿔 써서(replace) 한 번 닫으면 처음 온 곳으로 돌아와요.
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { useModal } from "@/components/ui/useModal";
import { withTerm } from "@/lib/guide/shared";
import s from "./guide.module.css";

// 용어 칸을 여는 이동을 누른 때. 칸이 처음 그려질 때 10초 안에 누른 것만 '링크로 열었다'고 봐요(끊긴 이동이 남지 않게)
let openedAt = 0;
const FRESH_MS = 10_000;

/** 용어 칸을 여는 이동이에요: 닫을 때 뒤로 가서 온 곳으로 돌아가요 */
export function markTermOpen() {
  openedAt = Date.now();
}

/** 보던 화면 주소에 ?term=만 바꿔 붙인 주소(term이 없으면 ?term=만 뺀 주소) */
function useHereWithTerm(term?: string) {
  return withTerm(usePathname(), useSearchParams().toString(), term);
}

/** 용어 칸을 여는 링크: 보던 화면 위에 열고 스크롤은 그대로 둬요. inPanel: 칸 안에서 다른 용어로 옮겨요 */
export function TermLink({ term, inPanel, ...rest }: Omit<ComponentProps<typeof Link>, "href"> & { term: string; inPanel?: boolean }) {
  const href = useHereWithTerm(term);
  return (
    <Link
      {...rest}
      href={href}
      scroll={false}
      replace={inPanel}
      onClick={(e) => {
        rest.onClick?.(e);
        if (!inPanel && !e.defaultPrevented && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) markTermOpen();
      }}
    />
  );
}

export function TermPanel({ id, label, head, children }: { id: string; label: string; head: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const closeHref = useHereWithTerm();
  // 처음 그릴 때 한 번 읽어요(칸이 열려 있는 동안 다른 용어로 옮겨도 그대로예요)
  const [fromLink] = useState(() => Date.now() - openedAt < FRESH_MS);
  const back = useRef(fromLink);
  useEffect(() => { openedAt = 0; }, []);
  const close = () => {
    if (back.current) {
      back.current = false;
      router.back();
    } else router.replace(closeHref, { scroll: false });
  };
  const m = useModal(ref, true, close);
  // 다른 용어로 옮기면 맨 위부터 읽어요
  useEffect(() => { body.current?.scrollTo(0, 0); }, [id]);
  // 뒤로 · 앞으로 가기로 옮기면 다음 닫기는 ?term=만 지워요
  useEffect(() => {
    const onPop = () => { back.current = false; };
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
