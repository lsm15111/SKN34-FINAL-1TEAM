"use client";
// 넣는 중 나가기 경고(인테리어 받기 첫 화면, 2026-11-24 사용자): 저장 전 답이 있으면(on) 다른 화면으로 가기 전에 묻는 창을 띄워요.
// - 이 앱 안 링크(머리 메뉴 · 로고 · 폰 ‹ · 로그인): 눌러도 가지 않고 창 → [나가기]면 그 주소로 가요. 같은 화면 링크(용어 칸 ?term= · #)는 그대로예요.
//   window 붙잡기 단계에서 기본 동작만 막아요(next/link는 막힌 누르기면 옮기지 않고, 링크의 onClick(펼침 메뉴 닫기)은 그대로 돌아요).
// - 브라우저 · 폰 뒤로: 기록 한 칸(mjLeave)을 넣어 두고 그 칸이 빠지면 창 → [머무르기]면 칸을 다시 넣고, [나가기]면 한 칸 더 뒤로 가요.
//   아래 시트가 넣은 칸(useModal mjModal)이 위에 있으면 걷힐 때까지 기다렸다 넣어요(시트를 닫는 뒤로와 섞이지 않게).
// - 브라우저 닫기 · 새로고침 · 다른 사이트로: beforeunload(브라우저 기본 창).
// - release: 저장하며 놓아줘요. 넣어 둔 칸을 걷고 끝날 때까지 기다려서, 바로 화면을 옮겨도 기록에 헛도는 칸이 남지 않아요.
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";

type Ask = { href: string } | { back: true };
type Mark = { mjLeave?: boolean; mjModal?: boolean } | null;
const mark = (): Mark => window.history.state as Mark;

export function useLeaveGuard(on: boolean) {
  const router = useRouter();
  const [ask, setAsk] = useState<Ask | null>(null);
  /** 기록 칸(mjLeave)을 넣어 두었어요 */
  const armed = useRef(false);
  /** 놓아줬어요(나가는 중 · 저장함). 다시 넣기 시작하면(on) 풀어요 */
  const gone = useRef(false);
  const fallback = useRef(0);

  const arm = useCallback(() => {
    if (armed.current || gone.current) return;
    window.history.pushState({ ...window.history.state, mjLeave: true }, "");
    armed.current = true;
  }, []);

  useEffect(() => {
    if (!on) return;
    gone.current = false;
    let timer = 0;
    const tryArm = () => {
      if (mark()?.mjModal) { timer = window.setTimeout(tryArm, 150); return; }
      arm();
    };
    timer = window.setTimeout(tryArm, 0);
    const onBefore = (e: BeforeUnloadEvent) => {
      if (gone.current) return;
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (gone.current || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
      if (!(a instanceof HTMLAnchorElement) || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname) return;
      e.preventDefault();
      setAsk({ href: `${url.pathname}${url.search}${url.hash}` });
    };
    const onPop = () => {
      // 시트 · 용어 칸이 넣은 칸에서 돌아오면 우리 칸(mjLeave)에 닿아요. 우리 칸이 빠졌을 때만 물어요
      if (!armed.current || gone.current || mark()?.mjLeave) return;
      armed.current = false;
      setAsk({ back: true });
    };
    window.addEventListener("beforeunload", onBefore);
    window.addEventListener("click", onClick, true);
    window.addEventListener("popstate", onPop);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("beforeunload", onBefore);
      window.removeEventListener("click", onClick, true);
      window.removeEventListener("popstate", onPop);
      // 이 화면 그대로 놓아줬는데(on → false) 넣어 둔 칸이 위에 남았으면 걷어요(뒤로 한 번이 헛돌지 않게)
      if (armed.current && !gone.current && mark()?.mjLeave) window.history.back();
      armed.current = false;
    };
  }, [on, arm]);
  useEffect(() => () => window.clearTimeout(fallback.current), []);

  const stay = () => {
    const was = ask;
    setAsk(null);
    if (was && "back" in was) arm(); // 뒤로로 빠진 칸을 다시 넣어요
  };
  const leave = () => {
    const was = ask;
    setAsk(null);
    if (!was) return;
    gone.current = true;
    if ("href" in was) {
      // 넣어 둔 칸 위면 그 칸을 새 화면으로 바꿔 써요(새 화면에서 뒤로 한 번이면 이 화면 앞으로)
      if (armed.current && mark()?.mjLeave) router.replace(was.href);
      else router.push(was.href);
      armed.current = false;
      return;
    }
    const here = window.location.href;
    window.history.back();
    // 앞 칸이 없으면(새 탭에서 바로 열었음) 그대로라 처음 화면으로 가요
    fallback.current = window.setTimeout(() => { if (window.location.href === here) router.push("/"); }, 600);
  };

  /** 저장하며 놓아줘요: 넣어 둔 칸을 걷고 그 뒤로 가기가 끝날 때까지 기다려요(바로 이어 화면을 옮겨도 섞이지 않게) */
  const release = useCallback(async () => {
    gone.current = true;
    if (!armed.current || !mark()?.mjLeave) { armed.current = false; return; }
    armed.current = false;
    await new Promise<void>((done) => {
      let t = 0;
      const end = () => { window.removeEventListener("popstate", end); window.clearTimeout(t); done(); };
      window.addEventListener("popstate", end);
      t = window.setTimeout(end, 400);
      window.history.back();
    });
  }, []);

  const dialog = (
    <Dialog
      open={!!ask}
      onClose={stay}
      title="이 화면을 나갈까요?"
      actions={
        <>
          <Button variant="secondary" size="lg" onClick={stay}>머무르기</Button>
          <Button size="lg" onClick={leave}>나가기</Button>
        </>
      }
    >
      <p>입력한 정보는 저장되지 않아요.</p>
    </Dialog>
  );
  return { dialog, release };
}
