// 작업함(V03 v_inbox 폰 카드 · D04 d_inbox 웹 표 + 옆 자세히). 9판 N4 C: 상태는 작은 아이콘 + 글자, 색은 아이콘에만.
// 탭: 할 일 · 기다림 · 일정 · 공사 · 끝남(+ 웹 '전체'). 일정 탭은 반나절 목록(V08, Schedule)이에요.
// 웹 표의 줄을 누르면 ?sel=로 오른쪽 자세히가 바뀌어요(서버가 다시 그려요). 폰은 카드의 단추로 요청 화면에 가요.
// v4: 맨 위 '오늘 브리핑' · '비서 소식'(할 일 탭), 새 요청 줄의 웹 옆 자세히 맨 위에 비서 요청 브리핑(V1, components/pro/assistant)을 얹어요.
import Link from "next/link";
import { BriefCard } from "@/components/pro/assistant/BriefCard";
import { seedFromRow } from "@/components/pro/assistant/seed";
import { VendorFeed } from "@/components/pro/assistant/VendorFeed";
import { VendorToday } from "@/components/pro/assistant/VendorToday";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Menu } from "@/components/ui/Menu";
import { StateLegend, StateTag } from "@/components/ui/StateTag";
import type { InboxRowV3, InboxSort, InboxTab, VendorInboxPage, VendorInboxSummary, VendorSchedule, VendorVisitV3 } from "@/lib/api/vendor";
import { dateShort, halfDayText, listStamp, rangeText, timeSeoul, won } from "@/lib/format";
import { gradeLabel, type StateTone } from "@/lib/labels";
import { LOC_NOTE } from "../text";
import { Tabs, type TabOption } from "@/components/ui/Tabs";
import { PhoneOnly, Row, Rows, Small, WebOnly } from "../ui/parts";
import { VisitPhotos } from "../visit/facts";
import { Schedule } from "./Schedule";
import * as R from "./rows";
import s from "./inbox.module.css";

const TABS: { key: InboxTab; text: string; tone?: StateTone; webOnly?: boolean }[] = [
  { key: "all", text: "전체", webOnly: true },
  { key: "todo", text: "할 일", tone: "todo" },
  { key: "waiting", text: "기다림", tone: "wait" },
  { key: "sched", text: "일정", tone: "ok" },
  { key: "jobs", text: "공사", tone: "ok" },
  { key: "done", text: "끝남", tone: "done" },
];
const EMPTY: Record<InboxTab, { t: string; d: string }> = {
  all: { t: "받은 일이 아직 없어요", d: "고객이 실측을 요청하면 여기에 쌓여요." },
  todo: { t: "지금 할 일이 없어요", d: "새 실측 요청이 오면 알림으로 알려 드려요." },
  waiting: { t: "기다리는 일이 없어요", d: "고객 차례인 요청이 여기에 모여요." },
  sched: { t: "잡힌 실측이 없어요", d: "" },
  jobs: { t: "진행 중인 공사가 없어요", d: "고객이 실측 견적서를 확정하면 여기에 생겨요." },
  done: { t: "끝난 일이 없어요", d: "" },
};
const SORT_TEXT: Record<InboxSort, string> = { due: "기한 가까운 순", new: "받은 순" };

function qs(p: { tab?: string; sort?: string; sel?: string }) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v) q.set(k, v);
  const t = q.toString();
  return `/vendor${t ? `?${t}` : ""}`;
}

export function Inbox({ tab, sort, summary, page, selRow, sel, now, schedule }: {
  tab: InboxTab;
  /** 기본은 기한 가까운 순(D04) */
  sort: InboxSort;
  summary: VendorInboxSummary | null;
  page: VendorInboxPage;
  /** 웹 옆 자세히로 연 줄(없으면 첫 줄) */
  selRow: InboxRowV3 | null;
  sel: VendorVisitV3 | null;
  now: string;
  schedule: VendorSchedule | null;
}) {
  const n = summary ? { all: summary.todo + summary.waiting + summary.sched + summary.jobs + summary.done, todo: summary.todo, waiting: summary.waiting, sched: summary.sched, jobs: summary.jobs, done: summary.done } : null;
  const tabsAll: TabOption[] = TABS.map((t) => ({ key: t.key, label: t.text, tone: t.tone, count: n?.[t.key], href: qs({ tab: t.key === "todo" ? undefined : t.key, sort: sort === "due" ? undefined : sort }) }));
  // '전체'는 웹 표(D04)에만 있어요. 폰 카드(V03)는 다섯 칸이에요
  const tabsPhone = tabsAll.filter((t) => !TABS.find((x) => x.key === t.key)?.webOnly);
  const rows = page.items;

  return (
    <>
      <h1 className="mj-sr">작업함</h1>
      {tab === "todo" || tab === "all" ? <><VendorToday /><VendorFeed now={now} /></> : null}
      <div className={s.top}>
        <WebOnly><Tabs variant="pill" label="작업함 탭" value={tab} items={tabsAll} /></WebOnly>
        <PhoneOnly><Tabs variant="pill" label="작업함 탭" value={tab} items={tabsPhone} /></PhoneOnly>
        {tab !== "sched" && rows.length > 1 ? (
          <div className={s.sort}>
            <Menu
              label="줄 순서"
              text={SORT_TEXT[sort]}
              items={(["due", "new"] as InboxSort[]).map((k) => ({ label: SORT_TEXT[k], href: qs({ tab: tab === "todo" ? undefined : tab, sort: k === "due" ? undefined : k }) }))}
            />
          </div>
        ) : null}
      </div>

      {tab === "sched" ? (
        <Schedule data={schedule} now={now} />
      ) : rows.length === 0 ? (
        <EmptyState icon="box" title={EMPTY[tab].t}>{EMPTY[tab].d || null}</EmptyState>
      ) : (
        <>
          {/* 폰 · 태블릿: 카드(V03) */}
          <ul className={s.cards} aria-label={`${TABS.find((t) => t.key === tab)?.text ?? ""} 목록`}>
            {rows.map((r) => <Card key={r.id + (r.deal_id ?? "")} r={r} now={now} />)}
          </ul>
          {/* 웹: 표 + 옆 자세히(D04) */}
          <div className={s.desk}>
            <div className={s.tableBox}>
              <table className={s.table}>
                <caption className="mj-sr">받은 요청 · 공사. 줄을 고르면 오른쪽에 자세히가 열려요</caption>
                <colgroup><col className={s.cWhen} /><col /><col className={s.cState} /><col className={s.cNext} /><col className={s.cDue} /></colgroup>
                <thead><tr><th scope="col">받은 때</th><th scope="col">집</th><th scope="col">상태</th><th scope="col">다음 할 일</th><th scope="col">기한</th></tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const on = selRow ? selRow.id === r.id && selRow.deal_id === r.deal_id : false;
                    return (
                      <tr key={r.id + (r.deal_id ?? "")} className={on ? s.sel : undefined}>
                        <td className="mj-num">{listStamp(r.received_at)}</td>
                        <td className={s.home}>
                          <Link href={qs({ tab: tab === "todo" ? undefined : tab, sort: sort === "due" ? undefined : sort, sel: r.deal_id ?? r.id })} aria-current={on ? "true" : undefined} scroll={false}>
                            <b>{R.rowTitle(r)}</b>
                          </Link>
                          <span className={s.sub}>{R.rowSubShort(r)}</span>
                        </td>
                        <td><span className={s.stCell}><StateTag tone={R.rowTone(r)}>{R.rowLabel(r)}</StateTag>{R.isHold(r) ? <Badge tone="mute">잡아 둠</Badge> : null}</span></td>
                        <td className={s.next} title={r.next?.label ?? undefined}>{r.next?.label ?? "—"}</td>
                        <td className={`mj-num ${r.next?.overdue ? s.late : ""}`}>{R.rowDue(r)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {selRow ? <Side r={selRow} v={sel} now={now} /> : null}
          </div>
        </>
      )}

      <StateLegend />
      {/* NF-07: 웹(D04)은 옆 자세히에 같은 안내가 있어요. 아래 줄은 카드(폰 · 태블릿)에서만 */}
      <PhoneOnly><Small>{LOC_NOTE}</Small></PhoneOnly>
    </>
  );
}

function Card({ r, now }: { r: InboxRowV3; now: string }) {
  const tone = R.rowTone(r);
  const next = R.rowNext(r, now);
  const act = R.rowAction(r);
  return (
    <li className={`${s.card} ${tone === "todo" ? s.cardTodo : ""}`}>
      <div className={s.ch}>
        <StateTag tone={tone}>{R.rowLabel(r)}</StateTag>
        {R.isHold(r) ? <Badge tone="mute">잡아 둠</Badge> : null}
        <span className={`${s.time} mj-num`}>{listStamp(r.received_at)}</span>
      </div>
      <h2 className={s.ct}><Link href={R.rowHref(r)}>{R.rowTitle(r)}<span className="mj-sr"> · {R.rowLabel(r)}{R.isHold(r) ? " · 잡아 둠" : ""}</span></Link></h2>
      {R.rowSub(r) ? <p className={`${s.cs} mj-num`}>{R.rowSub(r)}</p> : null}
      {next ? <p className={`${s.cn} mj-num`}><b>다음 할 일</b>{next}</p> : null}
      {act ? <Button block variant={act.variant} href={act.href}>{act.label}</Button> : null}
    </li>
  );
}

/** 웹 옆 자세히(D04 k-aside): 고른 줄의 집 · 희망 · 가견적 · 예산 · 받은 때 · 기한 · 사진 + 다음 단추 */
function Side({ r, v, now }: { r: InboxRowV3; v: VendorVisitV3 | null; now: string }) {
  const act = R.rowAction(r);
  const due = r.next?.due_at;
  return (
    <aside className={s.aside} aria-label="고른 줄 자세히">
      {r.status === "requested" && !R.isJob(r) ? <BriefCard key={r.id} visitId={r.id} seed={seedFromRow(r)} now={now} compact /> : null}
      <div className={s.ah}><StateTag tone={R.rowTone(r)}>{R.rowLabel(r)}</StateTag>{R.isHold(r) ? <Badge tone="mute">잡아 둠</Badge> : null}</div>
      <h2 className={s.at}>{R.rowTitle(r)}</h2>
      <Rows label="요청 내용">
        {r.home ? <Row label="집" value={r.home} /> : null}
        {R.isJob(r) && R.jobDays(r) ? <Row label="공사 날짜" value={R.jobDays(r)} /> : null}
        {R.isJob(r) && r.deal_total != null ? <Row label="확정 금액" sub="부가세 포함" value={won(r.deal_total)} /> : null}
        {!R.isJob(r) && r.wish_start && r.wish_end ? <Row label="희망 기간" value={rangeText(r.wish_start, r.wish_end, { weekday: true })} /> : null}
        {/* 기다림 탭에서도 내가 보낸 기간 · 고객이 고른 날이 보여요(QA r6 L18) */}
        {!R.isJob(r) && v?.window && (r.status === "offered" || r.status === "proposed") ? <Row label="보낸 기간" value={rangeText(v.window.start, v.window.end, { weekday: true })} /> : null}
        {!R.isJob(r) && v?.booked && (r.status === "picked" || r.status === "booked") ? <Row label={r.status === "picked" ? "고객이 고른 날" : "실측 날짜"} value={halfDayText(v.booked.day, v.booked.half)} /> : null}
        {!R.isJob(r) && r.work_wish_on ? <Row label="공사 시작 희망" value={dateShort(r.work_wish_on)} /> : null}
        {!R.isJob(r) && r.estimate_total != null ? <Row label="가견적" sub={gradeLabel(r.grade)} value={won(r.estimate_total)} /> : null}
        {!R.isJob(r) && r.budget_won != null ? <Row label="예산" sub="고객이 넣었어요" value={won(r.budget_won)} /> : null}
        <Row label="받은 때" value={`${dateShort(r.received_at)} ${timeSeoul(r.received_at)}`} />
        {due ? <Row label={r.status === "requested" ? "답 기한" : "기한"} value={`${dateShort(due)} ${timeSeoul(due)}`} /> : null}
      </Rows>
      {v ? <VisitPhotos v={v} /> : null}
      {!R.isJob(r) ? <Small>{LOC_NOTE}</Small> : null}
      {r.status === "requested" ? (
        <div className={s.acts}>
          <Button variant="secondary" size="sm" href={`${R.rowHref(r)}?decline=1`}>못 받아요</Button>
          <Button size="sm" href={R.rowHref(r)}>기간 답하기</Button>
        </div>
      ) : act ? (
        <div className={s.acts}><Button size="sm" variant={act.variant} href={act.href}>{act.label}</Button></div>
      ) : null}
    </aside>
  );
}
