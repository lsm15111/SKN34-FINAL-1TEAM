"use client";
// 카드 자리: v3 경로가 그대로 카드를 열어요(알림 · 공유 링크 · 메일 링크가 맞게). 해시(#)는 쓰지 않아요.
// /projects/{id} → 대화만 · /standard · /plan · /vendors · /visits · /quotes · /schedule · /docs · /review → 전체 화면 카드
// /vendors/{vid}(/reviews) → 서랍 · /quotes/{vid}/confirm → 가운데 창.
import { useSearchParams, useSelectedLayoutSegments } from "next/navigation";
import type { ReactNode } from "react";
import { Drawer } from "./Drawer";
import { StepSheet } from "./StepSheet";

type SheetKind = "sheet" | "drawer" | "dialog";

const SCHEDULE: Record<string, string> = { dates: "공사 날짜", extra: "추가 금액", done: "공사 끝 확인" };

export function cardOf(segs: string[], view: string | null): { kind: SheetKind; title: string } | null {
  const [a, b, c] = segs;
  if (!a) return null;
  switch (a) {
    case "standard": return { kind: "sheet", title: "표준견적서" };
    case "plan": return { kind: "sheet", title: "공정표" };
    case "vendors": return b ? { kind: "drawer", title: c === "reviews" ? "리뷰" : "업체 자세히" } : { kind: "sheet", title: "업체 보기" };
    case "visits": return { kind: "sheet", title: b === "new" ? "실측 일정 요청" : b ? "실측 날짜 고르기" : "실측 일정" };
    case "quotes": return c === "confirm" ? { kind: "dialog", title: "업체 확정" } : { kind: "sheet", title: "실측 견적서" };
    case "schedule": return { kind: "sheet", title: (view && SCHEDULE[view]) || "공사" };
    case "docs": return { kind: "sheet", title: "서류" };
    case "review": return { kind: "sheet", title: "리뷰 쓰기" };
    default: return { kind: "sheet", title: "자세히" };
  }
}

export function CardSlot({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const segs = useSelectedLayoutSegments().filter((x) => !x.startsWith("__") && !x.startsWith("("));
  const view = useSearchParams().get("view");
  const card = cardOf(segs, view);
  if (!card) return null;
  if (card.kind === "drawer") return <Drawer title={card.title} onClose={onClose}>{children}</Drawer>;
  return <StepSheet title={card.title} dialog={card.kind === "dialog"} onClose={onClose}>{children}</StepSheet>;
}
