"use client";
// '견적 받기' 버튼. 누르면 질문 흐름을 화면 가운데 창(dialog)으로 띄운다.
// 창 밖은 눌리지 않고, Esc나 닫기 버튼으로 닫는다. 답은 자동 저장돼서 닫았다 열어도 이어서 쓸 수 있다.
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Wizard } from "./Wizard";

export function QuoteButton({ label = "견적 받기", className = "mj-btn mj-btn-pri mj-btn-sm", style }: { label?: string; className?: string; style?: React.CSSProperties }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const dlg = useRef<HTMLDialogElement>(null);
  const btn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const d = dlg.current;
    if (!open || !d) return;
    if (!d.open) d.showModal();
    const root = document.documentElement;
    const prev = root.style.overflow;
    root.style.overflow = "hidden";
    return () => { root.style.overflow = prev; };
  }, [open]);

  // /start 화면에는 같은 질문 흐름이 이미 열려 있다.
  if (pathname === "/start") return null;

  return (
    <>
      <button ref={btn} type="button" className={className} style={style} aria-haspopup="dialog" onClick={() => setOpen(true)}>{label}</button>
      <dialog ref={dlg} className="mj-dialog" aria-label="견적 받기" onClose={() => { setOpen(false); btn.current?.focus(); }}>
        {open ? <Wizard mode="dialog" onClose={() => dlg.current?.close()} /> : null}
      </dialog>
    </>
  );
}
