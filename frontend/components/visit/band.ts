// 위쪽 공사 띠(W1 A · ProjectBand)의 '지금 할 일 · 기다림'을 실측 일정 상태판에서 만들어요(B2a 레이아웃이 가져다 써요).
// 할 일 = 고객 차례(next.who customer), 기다림 = 업체 차례. 기한 글은 API 시각을 dueText로 모양만 바꿔요.
import type { BandTask } from "@/components/site/ProjectBand";
import type { VisitBoard } from "@/lib/api/visit";
import { dueText } from "@/lib/format";
import { iGa } from "./text";

export function visitBandTasks(board: VisitBoard, projectId: string): { todo: BandTask[]; waiting: BandTask[] } {
  const pid = encodeURIComponent(projectId);
  const todo: BandTask[] = [];
  const waiting: BandTask[] = [];
  let confirm = false;
  for (const r of board.board) {
    const name = r.vendor_name;
    const due = r.next.due_at && !r.next.overdue ? dueText(r.next.due_at) : undefined;
    const pick = `/projects/${pid}/visits/${encodeURIComponent(r.visit_id)}`;
    if (r.next.who === "customer") {
      if (r.next.kind === "pick") todo.push({ label: `${name} 날짜 고르기`, href: pick, due });
      else if (r.next.kind === "proposal") todo.push({ label: `${iGa(name)} 제안한 날 고르기`, href: pick, due });
      else if (r.next.kind === "change") todo.push({ label: `${name} 일정 바꾸기 답하기`, href: r.thread_id ? `/chat/${encodeURIComponent(r.thread_id)}` : `/projects/${pid}/visits` });
      else if (r.next.kind === "visit") todo.push({ label: `${name} 실측 받았는지 알려 주기`, href: `/projects/${pid}/visits` });
      else if (r.next.kind === "confirm" && !confirm) { confirm = true; todo.push({ label: "견적서 비교하고 한 곳 확정하기", href: `/projects/${pid}/quotes` }); }
    } else if (r.next.who === "vendor") {
      const what = r.next.kind === "reply" ? "답 기다림" : r.next.kind === "accept" ? "수락 기다림" : r.next.kind === "change" ? "일정 바꾸기 답 기다림" : r.next.kind === "quote" ? "견적서 기다림" : null;
      if (what) waiting.push({ label: `${name} ${what}`, due });
    }
  }
  return { todo, waiting };
}
