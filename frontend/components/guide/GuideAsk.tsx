"use client";
// 백과 'AI 채팅에 묻기' 창: 웹(≥768)은 오른쪽 440px 서랍, 폰은 전체 화면(뒤로 가기로 닫혀요).
// 한 번 연 뒤에는 닫아도 창을 그대로 두고 숨겨서, 백과 안에서 글을 옮겨 다녀도 대화가 이어져요(백과 layout에 하나).
// 고객만 물어볼 수 있어요. 손님은 로그인 안내를 보고, 업체 · 관리자에게는 단추 자체가 없어요(부르는 쪽이 숨겨요).
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { AiPanel } from "@/components/ai/AiPanel";
import { AsideHost } from "@/components/site/AsideSlot";
import { MQ } from "@/components/site/breakpoints";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useModal } from "@/components/ui/useModal";
import { ASK_EVENT } from "@/lib/guide/shared";
import s from "./guide.module.css";

export type AskWho = "customer" | "guest" | "none";

export function GuideAsk({ who }: { who: AskWho }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);
  const [draft, setDraft] = useState<{ text: string; key: number }>();
  const path = usePathname();
  const close = () => setOpen(false);
  const m = useModal(ref, open, close, { closeOnBack: () => !window.matchMedia(MQ.tablet).matches });

  useEffect(() => {
    if (who === "none") return;
    const on = (e: Event) => {
      const text = (e as CustomEvent<{ text?: string }>).detail?.text?.trim() ?? "";
      setUsed(true);
      if (text) setDraft({ text, key: Date.now() });
      setOpen(true);
    };
    window.addEventListener(ASK_EVENT, on);
    return () => window.removeEventListener(ASK_EVENT, on);
  }, [who]);

  // 찾기 창에서 넘긴 말이 있으면 입력 칸에 커서를 둬요(바로 고치거나 보내게)
  useEffect(() => {
    if (!open || !draft) return;
    const id = requestAnimationFrame(() => document.getElementById("ai-input")?.focus());
    return () => cancelAnimationFrame(id);
  }, [open, draft]);

  if (who === "none") return null;
  return (
    <dialog ref={ref} className={s.ask} aria-label="AI 채팅" onCancel={m.onCancel} onClick={m.onClick}>
      {who === "customer" ? (
        <div className={s.askIn}>
          {used ? (
            <AsideHost onClose={close}>
              <AiPanel screen="home" draft={draft} />
            </AsideHost>
          ) : null}
        </div>
      ) : (
        <div className={s.askGuest}>
          <div className={s.askGuestHead}>
            <h2>AI 채팅</h2>
            <button type="button" className={s.panelX} aria-label="닫기" onClick={close}><Icon name="close" /></button>
          </div>
          <p>로그인하면 백과를 읽다가 궁금한 것을 AI에게 물어볼 수 있어요.</p>
          <Button href={`/login?next=${encodeURIComponent(path)}`} block>로그인</Button>
          <Button href="/signup" variant="secondary" block>가입하기</Button>
        </div>
      )}
    </dialog>
  );
}
