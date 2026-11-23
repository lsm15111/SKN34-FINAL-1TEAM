// 내 공사 카드(C42 폰 · D09 웹 2열): 공사 이름 · 작은 줄 · 6단계 · 지금 할 일 · 업체 줄(상태 칩 · 다음 할 일 · 기한).
// 단계 · 할 일 · 기한 · 금액은 API 값 그대로예요. 업체 줄은 실측 일정 상태판 값을 읽어요(없으면 업체 이름 · 상태만).
import Link from "next/link";
import type { ApiMyProject } from "@/lib/api/schedule";
import type { BoardRow } from "@/lib/api/visit";
import { dateSeoul, dateShort, dueText, won } from "@/lib/format";
import { gradeLabel, sizeLabel, visitState } from "@/lib/labels";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { StateTag } from "@/components/ui/StateTag";
import { PROJECT_STEPS, Steps } from "@/components/ui/Steps";
import { Group, Row, Rows, Small } from "@/components/project/Kit";
import { boardState, slotText, windowText } from "@/components/visit/text";
import s from "./cards.module.css";

export type MyCard = { p: ApiMyProject; name: string; rows: BoardRow[] | null };

/** 이 사이트 안 경로만 단추로 이어요(할 일 link는 API 값) */
const inSite = (v: string) => v.startsWith("/") && !v.startsWith("//") && !v.startsWith("/\\");

/** 업체 줄 아래 작은 글: 기간 · 고른 날 · 제안한 날 · 실측 날 · 견적서 금액 + 기한 */
function rowSub(r: BoardRow): string | undefined {
  const due = r.next.due_at ? dueText(r.next.due_at) : null;
  switch (r.status) {
    case "requested": return due ? `업체 답 ${due}` : undefined;
    case "offered": return [r.window ? windowText(r.window) : null, due ? `${due} 골라요` : null].filter(Boolean).join(" · ") || undefined;
    case "picked": return [r.booked ? `${slotText(r.booked)} 보냄` : null, due ? `업체 답 ${due}` : null].filter(Boolean).join(" · ") || undefined;
    case "proposed": return [r.proposal ? r.proposal.slots.map((x) => slotText(x)).join(" · ") : null, due ? `${due} 골라요` : null].filter(Boolean).join(" · ") || undefined;
    case "booked": return r.booked ? `실측 ${slotText(r.booked, true)}` : undefined;
    case "visited": return due ? `실측 견적서 ${due}` : undefined;
    case "quoted": return r.quote ? `실측 견적서 ${won(r.quote.total)}` : undefined;
    case "chosen": return r.quote ? `확정 · ${won(r.quote.total)}` : undefined;
    default: return undefined;
  }
}

function VendorRows({ c, base }: { c: MyCard; base: string }) {
  const ids = new Set(c.p.vendors.map((v) => v.visit_id));
  const rows = (c.rows ?? []).filter((r) => ids.has(r.visit_id));
  if (rows.length) {
    return (
      <Rows label="담은 업체">
        {rows.map((r) => {
          const st = boardState(r);
          const href = r.status === "offered" || r.status === "proposed" ? `${base}/visits/${encodeURIComponent(r.visit_id)}` : `${base}/visits`;
          return <Row key={r.visit_id} list label={r.vendor_name} sub={rowSub(r)} value={<StateTag tone={st.tone}>{st.label}</StateTag>} href={href} />;
        })}
      </Rows>
    );
  }
  return (
    <Rows label="담은 업체">
      {c.p.vendors.map((v) => {
        const st = visitState(v.status, "customer");
        return <Row key={v.visit_id} list label={v.vendor_name} sub={v.next.due_at ? dueText(v.next.due_at) : undefined} value={<StateTag tone={st.tone}>{st.label}</StateTag>} href={`${base}/visits`} />;
      })}
    </Rows>
  );
}

function Card({ c }: { c: MyCard }) {
  const { p } = c;
  const base = `/projects/${encodeURIComponent(p.id)}`;
  const current = Math.max(0, Math.min(PROJECT_STEPS.length - 1, p.current));
  const small = [sizeLabel(p.size), p.trades.includes("dobae") ? gradeLabel(p.grades.dobae) : null, `마지막 소식 ${dateShort(dateSeoul(p.updated_at))}`].filter(Boolean).join(" · ");
  const todo = p.todo && p.todo.text ? p.todo : null;
  const todoHref = todo && inSite(todo.link) ? todo.link : null;
  const picked = p.vendors.length > 0;
  return (
    <li>
      <Group as="article" className={s.card}>
        <div className={s.head}>
          <h2 className={s.title}><Link className={s.name} href={base}>{c.name}<Icon name="chevron-right" size={18} /></Link></h2>
          <Small>{small}</Small>
        </div>
        <Steps current={current} />
        {picked ? (
          <>
            {todo ? (
              <div className={s.todo}>
                <p className={s.todoText}>{todo.text}</p>
                {todo.action && todoHref ? <div className={s.todoBtn}><Button size="sm" href={todoHref}>{todo.action}</Button></div> : null}
              </div>
            ) : null}
            <VendorRows c={c} base={base} />
          </>
        ) : (
          <div className={s.todo}>
            <p className={s.todoText}>{todo?.text || "업체를 담을 차례예요"}</p>
            <div className={s.todoBtn}><Button variant="text" arrow href={todoHref ?? `${base}/vendors`}>{todo?.action || "업체 보기"}</Button></div>
          </div>
        )}
      </Group>
    </li>
  );
}

export function ProjectCards({ items }: { items: MyCard[] }) {
  return (
    <ul className={s.grid} aria-label="내 공사 목록">
      {items.map((c) => <Card key={c.p.id} c={c} />)}
    </ul>
  );
}
