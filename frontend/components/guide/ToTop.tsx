"use client";
// 백과 '맨 위로' 단추(오른쪽 아래). 한 화면 반쯤 내려가면 떠요(NN/g: 긴 화면에서 쓰고, 위에 있을 땐 숨김 · 오른쪽 아래가 기대 자리).
// 누르면 부드럽게 맨 위로 가고(움직임 줄이기 설정이면 바로), 초점을 화면 제목으로 옮겨 키보드로 이어 읽기 좋게 해요.
// 초점이 단추에 있는 동안에는 숨기지 않아요(키보드 사용자가 초점을 잃지 않게).
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import s from "./guide.module.css";

const SHOW_AFTER = 1.5; // 창 높이의 몇 배를 내려가면 보일지

export function ToTop() {
  const [show, setShow] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);

  // 스크롤 때마다 바로 재요(값이 같으면 다시 그리지 않아서 가벼워요)
  useEffect(() => {
    const check = () => {
      const far = window.scrollY > window.innerHeight * SHOW_AFTER;
      setShow((v) => far || (v && document.activeElement === btn.current));
    };
    check();
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, []);

  function toTop() {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = window.scrollY;
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
    // 부드러운 스크롤이 시작도 못 했으면(화면에 안 그려지는 탭 등) 바로 옮겨요. 그사이 손으로 움직였으면 두어요(AiPanel과 같은 방식)
    if (!reduce) window.setTimeout(() => { if (Math.abs(window.scrollY - from) < 1) window.scrollTo({ top: 0 }); }, 700);
    const target = document.querySelector<HTMLElement>("main h1") ?? document.getElementById("main");
    if (!target) return;
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  }

  return (
    <button ref={btn} type="button" className={s.toTop} data-show={show} aria-label="맨 위로" title="맨 위로" onClick={toTop} onBlur={() => { if (window.scrollY <= window.innerHeight * SHOW_AFTER) setShow(false); }}>
      <Icon name="chevron-up" size={24} />
    </button>
  );
}
