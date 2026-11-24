// 실측 일정 상태판(C14 · C15 · C18 · C20 · C32 · D03). 서버 화면이에요.
// 폰 · 태블릿(<1024): 흰 띠(요청 머리) → 업체 카드 → 흰 띠(담은 업체 수). 웹(≥1024): 업체를 열로 둔 비교표(W4 A · CompareTable).
// 두 배치는 CSS로만 갈라요(dev-08). 상태 · 기한 · 남은 칸은 모두 API 값이고, 화면은 말만 붙여요(copy-guide 1.9 · F4).
import type { BoardRow, VisitBoard, VisitProject } from "@/lib/api/visit";
import { dateShort, dueText, eulReul, won } from "@/lib/format";
import { Button } from "@/components/ui/Button";
import { CompareTable, type CompareCol, type CompareRow } from "@/components/ui/CompareTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { StateTag } from "@/components/ui/StateTag";
import { Eyebrow, Group, GroupHead, InfoChips, Name, Quote, Small, Strip, Sub, Title } from "@/components/project/Kit";
import { AgainButton, CancelRequestButton, VisitedButtons } from "./BoardActions";
import { DueChip } from "./Due";
import { RequestSheetButton } from "./RequestSheet";
import { boardState, cancelLabel, dayCell, dueCell, eunNeun, headText, iGa, nextText, PROPOSAL_REASON, slotText, windowText } from "./text";
import s from "./visit.module.css";

const ACTIVE = new Set(["requested", "offered", "picked", "proposed", "booked", "visited", "quoted", "chosen"]);
const enc = encodeURIComponent;

type Links = { pick: (vid: string) => string; vendors: string; quotes: string; schedule: string; chat: (tid: string) => string; newReq: string };
const linksOf = (pid: string): Links => ({
  pick: (vid) => `/projects/${enc(pid)}/visits/${enc(vid)}`,
  vendors: `/projects/${enc(pid)}/vendors`,
  quotes: `/projects/${enc(pid)}/quotes`,
  schedule: `/projects/${enc(pid)}/schedule`,
  chat: (tid) => `/chat/${enc(tid)}`,
  newReq: `/projects/${enc(pid)}/visits/new`,
});

/** 고객 차례인 기한(날짜 고르기 · 제안한 날 고르기)만 배지로 보여요. 업체 차례 기한은 문장으로(C14) */
// 제안 온 카드는 끝 문장('…까지 고를 수 있어요')이 기한을 말해서 머리 배지를 두지 않아요(C20)
const dueBadge = (r: BoardRow) => r.next.who === "customer" && r.next.kind === "pick" && r.next.due_at;

function CardBody({ r, pid, L }: { r: BoardRow; pid: string; L: Links }) {
  const v = r.vendor_name;
  switch (r.status) {
    case "requested":
      return (
        <>
          {r.next.due_at ? <Sub>{dueText(r.next.due_at)} 답해요</Sub> : null}
          {r.can.cancel ? <div className={s.cardFoot}><CancelRequestButton projectId={pid} visitId={r.visit_id} vendorName={v} /></div> : null}
        </>
      );
    case "offered":
      return (
        <>
          {r.window ? <Sub>{windowText(r.window)}</Sub> : null}
          <div className={s.cardAct}><Button size="sm" href={L.pick(r.visit_id)}>날짜 고르기</Button></div>
        </>
      );
    case "picked":
      return (
        <>
          {r.booked ? <Sub>{eulReul(slotText(r.booked))} 보냈어요</Sub> : null}
          {r.next.due_at ? <Small>{dueText(r.next.due_at)} {iGa(v)} 답해요 · 그때까지 이 날짜를 잡아 둬요</Small> : null}
        </>
      );
    case "proposed": {
      const p = r.proposal;
      const why = p ? [p.reason_code ? PROPOSAL_REASON[p.reason_code] : null, p.note].filter(Boolean).join(" · ") : "";
      return (
        <>
          <Sub>{r.booked ? `고른 ${eunNeun(slotText(r.booked, true))} 어렵대요` : "고른 날은 어렵대요"}</Sub>
          {why ? <Quote>{why}</Quote> : null}
          {p?.slots.length ? (
            <>
              <Eyebrow>제안한 날</Eyebrow>
              <InfoChips label="제안한 날" items={p.slots.map((x) => ({ text: slotText(x), spoken: `제안: ${slotText(x)}`, tone: "warn" as const }))} />
            </>
          ) : null}
          <div className={s.cardAct}><Button size="sm" href={L.pick(r.visit_id)}>제안한 날 보기</Button></div>
          {p ? <Small>{dueText(p.due_at)} 고를 수 있어요</Small> : null}
        </>
      );
    }
    case "booked":
      if (r.can.visited && r.booked) {
        return (
          <>
            <Title as="h3">{slotText(r.booked, true)} 실측을<br />받으셨어요?</Title>
            <VisitedButtons projectId={pid} visitId={r.visit_id} />
            <Small>
              {r.next.due_at ? `받았다고 하면 업체가 ${dueText(r.next.due_at)} 견적서를 보내요.` : "받았다고 하면 업체가 실측 3일 뒤 18:00까지 견적서를 보내요."} 안 왔으면 기록하고 담은 업체에서 빼요.
            </Small>
          </>
        );
      }
      return (
        <>
          {r.booked ? <Sub>{slotText(r.booked, true)}</Sub> : null}
          {r.change?.status === "open" ? <Small>일정 바꾸기 요청 · {slotText({ day: r.change.to_day, half: r.change.to_half })} · {dueText(r.change.due_at)} {iGa(v)} 답해요</Small> : null}
          {r.thread_id ? <div className={s.cardLink}><Button variant="text" arrow href={L.chat(r.thread_id)}>채팅 열기</Button></div> : null}
        </>
      );
    case "visited":
      return (
        <>
          {r.booked ? <Sub>{slotText(r.booked, true)} 실측 받음</Sub> : null}
          {r.next.due_at ? <Small>{dueText(r.next.due_at)} {iGa(v)} 견적서를 보내요</Small> : null}
          {r.thread_id ? <div className={s.cardLink}><Button variant="text" arrow href={L.chat(r.thread_id)}>채팅 열기</Button></div> : null}
        </>
      );
    case "quoted":
      return (
        <>
          {r.quote ? <Sub>{dateShort(r.quote.sent_at)} 받음 · {won(r.quote.total)}</Sub> : null}
          <div className={s.cardLink}><Button variant="text" arrow href={L.quotes}>견적서 비교</Button></div>
        </>
      );
    case "chosen":
      return (
        <>
          {r.quote ? <Sub>확정 · {won(r.quote.total)}</Sub> : null}
          <div className={s.cardLink}><Button variant="text" arrow href={L.schedule}>공사 날짜 보기</Button></div>
        </>
      );
    case "expired":
      return (
        <>
          <Sub>
            {r.expired_reason === "pick"
              ? r.window ? `${dueText(r.window.pick_due_at)} 날짜를 고르지 않았어요` : "기한까지 날짜를 고르지 않았어요"
              : r.next.due_at ? `${dueText(r.next.due_at)} 답하지 않았어요` : "기한까지 답하지 않았어요"}
          </Sub>
          <div className={s.btnRow}>
            <Button variant="secondary" size="sm" href={L.vendors}>다른 업체 담기</Button>
            {r.can.again ? <AgainButton projectId={pid} visitId={r.visit_id} vendorName={v} /> : null}
          </div>
        </>
      );
    case "cancelled":
      return (
        <>
          <Sub>취소한 이유 · {cancelLabel(r.cancel_code)}</Sub>
          {r.can.again ? <div className={s.btnRow}><AgainButton projectId={pid} visitId={r.visit_id} vendorName={v} /></div> : null}
        </>
      );
    case "declined":
      return (<><Sub>다른 업체를 담을 수 있어요</Sub><div className={s.cardLink}><Button variant="text" arrow href={L.vendors}>다른 업체 담기</Button></div></>);
    case "no_show":
      return (<><Sub>안 왔다고 기록했어요</Sub><div className={s.cardLink}><Button variant="text" arrow href={L.vendors}>다른 업체 담기</Button></div></>);
    default:
      return <Sub>이 요청은 닫혔어요</Sub>;
  }
}

/** 표 단추 줄(D03): 카드와 같은 일을 작게 */
function TableAction({ r, pid, L }: { r: BoardRow; pid: string; L: Links }) {
  const v = r.vendor_name;
  switch (r.status) {
    case "requested": return r.can.cancel ? <CancelRequestButton projectId={pid} visitId={r.visit_id} vendorName={v} /> : <>—</>;
    case "offered": return <Button size="sm" href={L.pick(r.visit_id)}>날짜 고르기</Button>;
    case "proposed": return <Button size="sm" href={L.pick(r.visit_id)}>제안한 날 보기</Button>;
    case "booked":
      if (r.can.visited) return <VisitedButtons projectId={pid} visitId={r.visit_id} />;
      return r.thread_id ? <Button variant="text" arrow href={L.chat(r.thread_id)}>채팅 열기</Button> : <>—</>;
    case "visited": return r.thread_id ? <Button variant="text" arrow href={L.chat(r.thread_id)}>채팅 열기</Button> : <>—</>;
    case "quoted": return <Button variant="text" arrow href={L.quotes}>견적서 비교</Button>;
    case "chosen": return <Button variant="text" arrow href={L.schedule}>공사 날짜 보기</Button>;
    case "expired":
      return (
        <div className={s.btnRow}>
          <Button variant="secondary" size="sm" href={L.vendors}>다른 업체 담기</Button>
          {r.can.again ? <AgainButton projectId={pid} visitId={r.visit_id} vendorName={v} /> : null}
        </div>
      );
    case "cancelled": return r.can.again ? <AgainButton projectId={pid} visitId={r.visit_id} vendorName={v} /> : <>—</>;
    case "declined":
    case "no_show": return <Button variant="text" arrow href={L.vendors}>다른 업체 담기</Button>;
    default: return <>—</>;
  }
}

export function Board({ board, project, shortlisted }: {
  board: VisitBoard;
  project: VisitProject;
  /** 담은 업체 수(GET …/shortlist count). slots_left는 살아 있는 요청만 세서 요청 전에는 담은 수를 알 수 없어요. 못 읽었으면 null */
  shortlisted: number | null;
}) {
  const pid = project.id;
  const L = linksOf(pid);
  const rows = board.board;
  const head = board.head;
  const left = Math.max(0, board.slots_left.dobae ?? 0);

  // 아직 요청 전: 담은 업체가 있으면 요청서로, 없으면(또는 못 읽었으면) 업체 보기로(W10 막다른 화면 없음)
  if (!head || !rows.length) {
    return shortlisted ? (
      <Group>
        <Title as="h2">담은 업체 {shortlisted}곳에 실측 일정을 요청할 차례예요</Title>
        <Sub>희망 기간과 사진을 넣고 한 번에 보내요.</Sub>
        <div className={s.cardAct}><Button href={L.newReq}>실측 일정 요청</Button></div>
      </Group>
    ) : (
      <EmptyState icon="calendar" title="실측을 요청할 업체를 먼저 담아요" action={<Button variant="text" arrow href={L.vendors}>업체 보기</Button>}>가견적을 비교하고 3곳까지 담을 수 있어요</EmptyState>
    );
  }

  const h = headText(head, rows.length);
  const active = rows.filter((r) => ACTIVE.has(r.status)).length;
  const more = left > 0 ? <Button variant="text" arrow href={L.vendors}>업체 더 담기</Button> : undefined;

  const cols: CompareCol[] = rows.map((r) => ({ key: r.visit_id, name: r.vendor_name, highlight: r.next.who === "customer" }));
  const cell = (fn: (r: BoardRow) => React.ReactNode) => Object.fromEntries(rows.map((r) => [r.visit_id, fn(r)]));
  const tableRows: CompareRow[] = [
    { key: "state", label: "상태", cells: cell((r) => { const st = boardState(r); return <StateTag tone={st.tone}>{st.label}</StateTag>; }) },
    { key: "day", label: "날짜", big: true, cells: cell((r) => { const d = dayCell(r); return d ? <b className={`${s.bigCell} mj-num`}>{d}</b> : "—"; }) },
    { key: "next", label: "다음 할 일", cells: cell((r) => nextText(r)) },
    { key: "due", label: "기한", cells: cell((r) => (r.next.due_at ? <time dateTime={r.next.due_at} className="mj-num">{r.next.overdue ? "지났어요" : dueCell(r.next.due_at)}</time> : "—")) },
    { key: "act", label: "할 수 있는 일", action: true, cells: cell((r) => <TableAction r={r} pid={pid} L={L} />) },
  ];

  return (
    <>
      {/* 웹: 제목 아래 요청 머리 한 줄 */}
      <div className={`${s.webOnly} ${s.headLine}`}>
        <p>{h.title}{h.wishLong ? ` · ${h.wishLong}` : ""}</p>
        <RequestSheetButton head={head} rows={rows} project={project} />
      </div>
      <div className={s.webOnly}>
        <CompareTable caption="업체별 실측 일정" columns={cols} rows={tableRows} empty={more ? { title: `${left}곳 더 담을 수 있어요`, action: more } : undefined} />
      </div>

      {/* 폰 · 태블릿: 카드 */}
      <div className={s.phoneStack}>
        <Strip label={h.title} sub={h.sub} action={<RequestSheetButton head={head} rows={rows} project={project} />} />
        <ul className={s.cards} aria-label="업체별 실측 일정">
          {rows.map((r) => {
            const st = boardState(r);
            const due = dueBadge(r);
            return (
              <Group key={r.visit_id} as="li" hi={r.next.who === "customer" && r.status !== "proposed"} warn={r.status === "proposed"}>
                <GroupHead>
                  <Name as="h2">{r.vendor_name}</Name>
                  <StateTag tone={st.tone}>{st.label}</StateTag>
                  {due ? <DueChip due={due} overdue={r.next.overdue} soon={r.next.soon} /> : null}
                </GroupHead>
                <CardBody r={r} pid={pid} L={L} />
              </Group>
            );
          })}
        </ul>
        <Strip label={`담은 업체 ${active}곳`} sub={left > 0 ? `${left}곳 더 담을 수 있어요` : undefined} action={more} />
      </div>
    </>
  );
}
