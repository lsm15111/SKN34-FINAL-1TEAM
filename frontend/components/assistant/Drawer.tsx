"use client";
// 서랍(2.1): 대화를 보며 같이 볼 것(업체 자세히 · 사례 · 리뷰 · 견적서 파일 · 기억). 웹은 오른쪽 480(보드 자리 위), 폰은 아래 시트 90%.
// 닫기 = 뒤로 가기. 서랍 안 사진(?photo=n)은 v3처럼 얕게 붙어 뒤로 가기로 닫혀요.
import { useId, type ReactNode } from "react";
import { SheetHead, useOverlay } from "./StepSheet";
import s from "./assistant.module.css";

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const id = useId();
  const head = useOverlay(onClose);
  return (
    <>
      <div className={s.drawerBg} onClick={onClose} aria-hidden="true" />
      <div className={s.drawer} role="dialog" aria-modal="true" aria-labelledby={id}>
        <SheetHead id={id} title={title} head={head} onClose={onClose} />
        <div className={s.sheetBody}>{children}</div>
      </div>
    </>
  );
}
