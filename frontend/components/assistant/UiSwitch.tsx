"use client";
// 겉모양 바꾸기: 쿠키 mj_ui를 쓰고 같은 주소를 다시 그려요(서버 레이아웃이 쿠키를 읽어요).
// - UiSwitchBar: v3 화면 위 개발용 띠(운영 빌드에는 NEXT_PUBLIC_UI_SWITCH=1일 때만)
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import s from "./assistant.module.css";

const COOKIE = "mj_ui";

export function setUi(mode: "v3" | "v4") {
  document.cookie = `${COOKIE}=${mode}; path=/; max-age=${60 * 60 * 24 * 180}; samesite=lax`;
}

export function UiSwitchButton({ to, className, children }: { to: "v3" | "v4"; className?: string; children: ReactNode }) {
  const router = useRouter();
  return (
    <button type="button" className={className} onClick={() => { setUi(to); router.refresh(); }}>
      {children}
    </button>
  );
}

export function UiSwitchBar() {
  return (
    <div className={s.switchBar}>
      <span>지금은 v3 화면이에요</span>
      <UiSwitchButton to="v4" className={s.textBtn}>비서 화면(v4)으로 보기</UiSwitchButton>
    </div>
  );
}
