"use client";
// 카드 자리: v3 경로가 그대로 카드를 열어요(알림 · 공유 링크 · 메일 링크가 맞게). 해시(#)는 쓰지 않아요.
// /projects/{id} → 대화만 · /home(우리 집 정보 고치기) · /standard · /plan · /vendors · /visits · /quotes · /schedule · /docs ·
// /review → 전체 화면 카드
// /vendors/{vid}(/reviews) → 서랍(이 창 앞 칸에 큰 창이 있었으면 큰 창 그대로) · /quotes/{vid}/confirm → 가운데 창.
// 모두 창 하나(CardWindow)라 주소를 옮겨도 창은 그대로예요.
import { useSearchParams, useSelectedLayoutSegments } from "next/navigation";
import type { ReactNode } from "react";
import { CardWindow, type WindowKind, type WindowStep } from "./CardWindow";

const SCHEDULE: Record<string, string> = { dates: "공사 날짜", extra: "추가 금액", done: "공사 끝 확인" };

export function cardOf(segs: string[], view: string | null): { kind: WindowKind; title: string } | null {
  const [a, b, c] = segs;
  if (!a) return null;
  switch (a) {
    case "standard": return { kind: "sheet", title: "표준견적서" };
    // 우리 집 정보 고치기: 폼이 웹 1024 이상에서 오른쪽 '넣은 내용' 칸(저장 단추)까지 두 칸이라 가운데 창(560)이 아니라 큰 창이에요
    case "home": return { kind: "sheet", title: "우리 집 정보" };
    case "plan": return { kind: "sheet", title: "공정표" };
    case "vendors": return b ? { kind: "drawer", title: c === "reviews" ? "리뷰" : "업체 자세히" } : { kind: "sheet", title: "업체 보기" };
    // 실측 하나(visits/{id})는 날짜 고르기 · 업체가 낸 날 · 정해진 날을 같이 보여서 창 이름은 '실측 날짜'(안 제목이 지금 상태)
    case "visits": return { kind: "sheet", title: b === "new" ? "실측 일정 요청" : b ? "실측 날짜" : "실측 일정" };
    case "quotes": return c === "confirm" ? { kind: "dialog", title: "업체 확정" } : { kind: "sheet", title: "실측 견적서" };
    case "schedule": return { kind: "sheet", title: (view && SCHEDULE[view]) || "공사" };
    case "docs": return { kind: "sheet", title: "서류" };
    case "review": return { kind: "sheet", title: "리뷰 쓰기" };
    default: return { kind: "sheet", title: "자세히" };
  }
}

/** step: 창 안 지금 단계(Shell의 길). wide: 이 창 앞 칸에 큰 창이 있었음. onBack: 창 안 앞 단계가 있을 때만.
 *  hidden: 닫는 중(대화 자리로 돌아가는 사이 안 그려요) */
export function CardSlot({ step, wide, onBack, onClose, hidden, children }: {
  step: WindowStep; wide: boolean; onBack?: () => void; onClose: () => void; hidden: boolean; children: ReactNode;
}) {
  const segs = useSelectedLayoutSegments().filter((x) => !x.startsWith("__") && !x.startsWith("("));
  const view = useSearchParams().get("view");
  const card = cardOf(segs, view);
  if (!card || hidden) return null;
  // 업체 보기 같은 큰 창에서 연 업체 자세히는 서랍으로 줄이지 않아요(목록이 사라지지 않게, '앞 화면으로'로 돌아가요)
  const kind = card.kind === "drawer" && wide ? "sheet" : card.kind;
  return <CardWindow kind={kind} title={card.title} step={step} onBack={onBack} onClose={onClose}>{children}</CardWindow>;
}
