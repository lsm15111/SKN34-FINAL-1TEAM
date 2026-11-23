// 공사 한 건(V23 v_job, D25 A): 상태 · 공사 날짜 · 견적서 · 추가 금액 · 동 · 호수 · 연락처(채팅) · 기록을 한곳에서.
// 추가 금액 올리기(?step=extra, V12) · 공사 끝 알리기(?step=done, V13, CF-23)로 이어져요. 금액 · 날은 API 값 그대로예요.
// 첫 공사 날 전이면 '공사 전', 끝 알리기는 마지막 공사 날부터라 그 전에는 단추 이름으로 언제부터인지 알려요(QA r6 M13).
// canChange면 공사 날짜 줄 아래 [날짜 바꾸기](?step=dates, 이유 칸)로 수락한 날짜를 바꾸자고 보내요. 고객이 수락해야 바뀌어요.
import { Main, PageHead } from "@/components/site/Frame";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import type { JobV3, VendorJobLog } from "@/lib/api/vendor";
import { dateSeoul, dateShort, listStamp, won } from "@/lib/format";
import { enc } from "../send";
import { logText } from "../text";
import { Notice } from "@/components/ui/Notice";
import { Eyebrow, Group, Row, Rows, Small } from "../ui/parts";
import { occ, visitTitle } from "../visit/facts";
import { daysText } from "./days";
import s from "./jobs.module.css";

const ANSWER: Record<string, string> = { pending: "고객 답 기다림", approved: "승인", rejected: "거절", asked: "채팅으로 물어봐요" };

function jobState(j: JobV3, today: string): { tone: BadgeTone; label: string } {
  if (j.status === "done" || j.status === "closed") return { tone: "mute", label: "공사 끝" };
  if (j.done_posted_at || j.work_done_on) return { tone: "wait", label: "고객 확인 기다림" };
  if (j.dates_state === "proposed" || j.dates_state === "change_proposed") return { tone: "wait", label: "날짜 수락 기다림" };
  if (j.dates_state === "scheduled") return j.work_days.length && today < j.work_days[0] ? { tone: "ok", label: "공사 전" } : { tone: "ok", label: "공사 중" };
  return { tone: "now", label: "공사 날짜 올리기" };
}

export function JobView({ job, log, now, canChange = false }: { job: JobV3; log: VendorJobLog; /** 지금 시각(서버 값) */ now: string; /** 수락한 날짜를 바꾸자고 보낼 수 있어요 */ canChange?: boolean }) {
  const v = job.visit;
  const today = dateSeoul(now);
  const st = jobState(job, today);
  /** 마지막 공사 날(끝 알리기를 누를 수 있는 날) */
  const lastDay = job.work_days.reduce<string | null>((m, d) => (m === null || d > m ? d : m), null);
  const days = job.work_days.length ? job.work_days : job.proposal?.days ?? [];
  const crew = job.accepted_crew ?? job.proposal?.crew ?? null;
  const items = job.extras.items.filter((x) => !x.superseded);
  const okN = items.filter((x) => x.answer === "approved").length;
  const waitN = items.filter((x) => x.answer === "pending").length;
  const working = job.dates_state === "scheduled" && !job.done_posted_at && !job.work_done_on && job.status !== "done";
  const href = `/vendor/jobs/${enc(job.deal_id)}`;
  return (
    <>
      <Main narrow>
        <PageHead title="공사 한 건" crumbs={[{ label: "작업함", href: "/vendor?tab=jobs" }, { label: visitTitle(v) }]} />
        <Group>
          <Badge tone={st.tone}>{st.label}</Badge>
          <h2 className={s.jt}>{visitTitle(v)} · {occ(v)}</h2>
          <p className={`${s.js} mj-num`}>{["도배 전체", days.length ? daysText(days, true) : null, job.quote.days ? `${job.quote.days}일` : null, crew ? `${crew}명` : null].filter(Boolean).join(" · ")}</p>
        </Group>
        <Group flush>
          <Rows label="공사 한 건">
            <Row label="상태" value={`${st.label}${working && job.day_no ? ` · ${job.day_no}일째` : ""}`} />
            <Row
              label="공사 날짜"
              sub={job.proposal?.decided_at && job.dates_state === "scheduled" ? `고객이 ${dateShort(job.proposal.decided_at)} 수락` : job.dates_state === "proposed" ? "고객 수락 기다림" : job.dates_state === "change_proposed" && job.proposal ? `${daysText(job.proposal.days)}로 바꾸자고 보냄 · 고객 답 기다림` : undefined}
              value={days.length ? daysText(days) : "—"}
            />
            {/* CF-38: '버전' 대신 보낸 날 */}
            <Row label="견적서" sub={`${dateShort(job.quote.sent_at)}에 보냄 · 확정`} value={won(job.quote.total)} />
            <Row
              label="추가 금액"
              sub={items.length ? [okN ? `승인 ${okN}건` : null, waitN ? `기다림 ${waitN}건` : null].filter(Boolean).join(" · ") || `${items.length}건` : "아직 없어요"}
              value={job.extras.ok.total ? won(job.extras.ok.total) : "—"}
            />
            {job.thread_id ? <Row label="동 · 호수 · 연락처" sub="고객이 채팅으로 알려 줘요" href={`/chat/${enc(job.thread_id)}`} /> : null}
          </Rows>
          {canChange ? <div className={s.rowAct}><Button variant="text" arrow href={`${href}?step=dates`}>날짜 바꾸기</Button></div> : null}
        </Group>
        {items.length ? (
          <Group flush>
            <Eyebrow>추가 금액</Eyebrow>
            <Rows label="추가 금액">
              {items.map((x) => <Row key={x.id} label={x.title} sub={`${ANSWER[x.answer] ?? "고객 답 기다림"} · ${dateShort(x.created_at)}`} value={won(x.total)} />)}
            </Rows>
            <Small>고객이 승인하기 전에는 합계에 넣지 않아요.</Small>
          </Group>
        ) : null}
        {job.done_posted_at || job.work_done_on ? (
          <Notice tone="info">공사 끝을 알렸어요. 고객이 확인하면 공사가 끝나요{job.auto_done_at ? ` · 확인이 없으면 ${dateShort(job.auto_done_at)}에 저절로 끝나요` : ""}.</Notice>
        ) : null}
        {log.length ? (
          <Group flush>
            <Eyebrow>기록</Eyebrow>
            <Rows label="기록">
              {log.map((l, i) => <Row key={`${l.at}-${i}`} label={listStamp(l.at)} sub={logText(l.code)} />)}
            </Rows>
          </Group>
        ) : null}
      </Main>
      {working ? (
        <BottomBar>
          <Button size="lg" variant="secondary" href={`${href}?step=extra`}>추가 금액 올리기</Button>
          <Button size="lg" href={`${href}?step=done`} disabled={!job.can_finish}>{job.can_finish || !lastDay ? "공사 끝 알리기" : `공사 끝은 ${dateShort(lastDay)}부터`}</Button>
        </BottomBar>
      ) : null}
    </>
  );
}
