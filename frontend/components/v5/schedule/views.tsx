// 공사 화면 세 가지(서버): 공사 날짜(C35 · 기다림 · 다른 날짜 요청함 · 확정 · 확정 뒤 날짜 바꾸기 요청) · 추가 금액(C37) · 공사 끝 확인(C38).
// 화면마다 { body(Main 안), bar(Main 바로 뒤 아래 단추 띠) }를 돌려줘요. 금액 · 날짜 · 기한은 API 값 그대로예요.
// 9판의 '바뀌면 332만 2,000원'(승인하면 합계) · '공사 금액 · 추가 포함 합계'는 API에 값이 없어 따로 보여요(합치지 않아요).
import type { ReactNode } from "react";
import { dateLong, dateShort, dueText, listStamp, won } from "@/lib/v5/format";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Money } from "@/components/ui/Money";
import { Eyebrow, Group, Notice, Pics, Quote, Row, Rows, Small, Sub, Title } from "@/components/project/Kit";
import { iGa } from "@/components/v5/visit/text";
import { DatesActions, DatesChangeBar } from "./DatesActions";
import { DoneActions } from "./DoneActions";
import { ExtraActions } from "@/components/schedule/ExtraActions";
import { WorkDays } from "@/components/schedule/WorkDays";
import { currentExtra, daysText, donePhotoHref, extraPhotoHref, type TradeDatesV3 } from "@/components/schedule/v3text";
import s from "@/components/schedule/v3.module.css";

type View = { body: ReactNode; bar: ReactNode };
type Ctx = { projectId: string; t: TradeDatesV3; holidays: { day: string; name: string }[]; finalVersion: number; today: string; startDate: string | null; /** 지금 요청하면 업체 기한(서버 계산, C52) */ requestDue?: string | null };

const base = (id: string) => `/v5/projects/${encodeURIComponent(id)}`;

function dealRow(t: TradeDatesV3) {
  const q = t.deal.quote;
  return <Row label="확정 금액" sub={`${t.deal.vendor_name} · ${dateShort(q.sent_at)} 견적서`} value={<Money value={q.total} size="line" />} />;
}

/** C35 공사 날짜 · 그 앞뒤 상태 */
export function datesView({ projectId, t, holidays, finalVersion, today, startDate, requestDue }: Ctx): View {
  const v = t.deal.vendor_name;
  const p = t.proposal;
  const proposed = (t.dates_state === "proposed" || t.dates_state === "change_proposed") && p && p.status !== "accepted";
  if (proposed && p) {
    const days = p.days.length ? p.days : [p.start, p.end].filter((d, i, a) => a.indexOf(d) === i);
    // 수락한 날짜를 바꾸자고 했으면 지금 날짜를 같이 보이고, 수락하면 이미 있는 확정 공정표가 바뀌어요(QA r7 N7)
    const change = t.dates_state === "change_proposed";
    const accept = change ? "수락하면 공사 날짜와 확정 공정표가 바뀌어요." : "수락하면 확정 공정표가 만들어져요.";
    return {
      body: (
        <>
          <Group>
            {/* 수락한 날짜를 업체가 바꾸자고 했으면 그 이유(업체가 적은 글, 고객에게 보여요)를 같이 보여요 */}
            <Eyebrow>{change ? `${iGa(v)} 바꾸자고 한 공사 날짜` : `${iGa(v)} 올린 공사 날짜`}</Eyebrow>
            <p className={`${s.big} mj-num`}>{daysText(days)}</p>
            {change && p.reason ? <Quote>{p.reason}</Quote> : null}
            <Sub>{[`${p.workdays}일`, `${p.crew}명`, startDate && p.start === startDate ? "공사 시작 희망일과 같아요" : null].filter(Boolean).join(" · ")}</Sub>
          </Group>
          {change && t.deal.work_days.length ? (
            <Group>
              <Eyebrow>지금 공사 날짜</Eyebrow>
              <Sub>{daysText(t.deal.work_days)}</Sub>
            </Group>
          ) : null}
          <Group>
            <div className={s.cal}><WorkDays days={days} holidays={holidays} today={today} /></div>
          </Group>
          <Group list><Rows>{dealRow(t)}</Rows></Group>
          <Notice tone="gray">
            {t.requests_left > 0
              ? `${accept} 날짜가 안 맞으면 다른 날짜를 요청해요(2번까지).`
              : `${accept} 다른 날짜 요청은 2번을 다 썼어요. 날짜를 바꿔야 하면 채팅으로 이야기해요.`}
          </Notice>
        </>
      ),
      bar: (
        <DatesActions projectId={projectId} dealId={t.deal.id} proposalId={p.id} seenVersion={finalVersion} vendorName={v} requestsLeft={t.requests_left} options={t.start_options.map((o) => o.start)} today={today} requestDue={requestDue ?? null} />
      ),
    };
  }
  if (t.dates_state === "requested" || t.dates_state === "change_requested") {
    const r = t.request;
    const change = t.dates_state === "change_requested";
    return {
      body: (
        <>
          <Group hi>
            <Eyebrow>{change ? "공사 날짜 바꾸기를 요청했어요" : "다른 날짜를 요청했어요"}</Eyebrow>
            {r?.wish_dates.length ? <Title>원하는 시작일 {r.wish_dates.map((d) => dateShort(d)).join(" · ")}</Title> : null}
            {r?.reason ? <Quote>{r.reason}</Quote> : null}
            {r ? <Sub>{r.overdue ? `${iGa(v)} 새 날짜를 아직 올리지 않았어요 · 채팅으로 물어보세요` : `${iGa(v)} ${dueText(r.due_at)} 새 날짜를 올려요`}</Sub> : null}
          </Group>
          {change && t.deal.work_days.length ? (
            <Group>
              <Eyebrow>지금 공사 날짜</Eyebrow>
              <Sub>{daysText(t.deal.work_days)}</Sub>
            </Group>
          ) : p ? (
            <Group>
              <Eyebrow>먼저 올린 공사 날짜</Eyebrow>
              <Sub>{daysText(p.days)}</Sub>
            </Group>
          ) : null}
          <Group list><Rows>{dealRow(t)}</Rows></Group>
        </>
      ),
      bar: null,
    };
  }
  if (t.dates_state === "scheduled" || (p && p.status === "accepted")) {
    const days = t.deal.work_days.length ? t.deal.work_days : p?.days ?? [];
    // 수락한 뒤 · 공사 끝 알림 전(확정)에만 날짜를 바꿀 수 있어요(서버 규칙). 요청은 다른 날짜 요청과 합쳐 2번까지
    const changeable = t.deal.status === "scheduled" && t.dates_state === "scheduled";
    return {
      body: (
        <>
          <Group>
            <Eyebrow>{v} 공사 날짜 · 확정</Eyebrow>
            <p className={`${s.big} mj-num`}>{daysText(days)}</p>
            <Sub>확정 공정표가 만들어졌어요</Sub>
            <div><Button variant="text" arrow href={`${base(projectId)}/plan`}>확정 공정표 보기</Button></div>
          </Group>
          {days.length ? <Group><div className={s.cal}><WorkDays days={days} holidays={holidays} today={today} /></div></Group> : null}
          <Group list><Rows>{dealRow(t)}</Rows></Group>
          {changeable && t.requests_left <= 0 ? <Notice tone="gray">날짜 바꾸기 요청은 2번을 다 썼어요. 날짜를 바꿔야 하면 채팅으로 이야기해요.</Notice> : null}
        </>
      ),
      bar: changeable && t.requests_left > 0 ? (
        <DatesChangeBar projectId={projectId} dealId={t.deal.id} vendorName={v} requestsLeft={t.requests_left} options={t.start_options.map((o) => o.start)} today={today} requestDue={requestDue ?? null} />
      ) : null,
    };
  }
  if (t.dates_state === "closed") {
    return { body: <EmptyState icon="calendar" title="이 공사는 닫혔어요" action={<Button variant="text" arrow href={base(projectId)}>공사 보기</Button>} />, bar: null };
  }
  // waiting: 업체가 공사 날짜를 올리기 전
  return {
    body: (
      <>
        <Group hi>
          <Eyebrow>공사 날짜</Eyebrow>
          <Title>{iGa(v)} 공사 날짜를 올릴 때까지 기다려요</Title>
          <Sub>{t.deal.overdue ? "올릴 기한이 지났어요 · 채팅으로 물어보세요" : `${dueText(t.deal.dates_due_at)} 올려요`}</Sub>
        </Group>
        <Group list><Rows>{dealRow(t)}</Rows></Group>
      </>
    ),
    bar: null,
  };
}

/** C37 추가 금액 */
export function extraView({ projectId, t }: Ctx): View {
  const x = currentExtra(t);
  const v = t.deal.vendor_name;
  if (!x) {
    return { body: <EmptyState icon="doc" title="올라온 추가 금액이 없어요" action={<Button variant="text" arrow href={`${base(projectId)}/schedule?view=dates`}>공사 날짜 보기</Button>}>업체가 추가 금액을 올리면 여기서 승인하거나 거절해요</EmptyState>, bar: null };
  }
  const pending = x.answer === "pending";
  const state = x.answer === "approved" ? `승인했어요${x.acked_at ? ` · ${listStamp(x.acked_at)}` : ""}`
    : x.answer === "rejected" ? `거절했어요 · ${iGa(v)} 금액을 고쳐 다시 올릴 수 있어요`
      : x.answer === "asked" ? "채팅으로 물었어요 · 답을 듣고 승인하거나 거절해요" : null;
  return {
    body: (
      <>
        <Group>
          <Eyebrow>{iGa(v)} 추가 금액을 올렸어요</Eyebrow>
          <span className={s.bigAmount}><Money value={x.total} size="big" delta /></span>
          <Sub>{x.title}</Sub>
          {x.reason ? <Quote>{x.reason}</Quote> : null}
          <Pics label="추가 금액 사진" items={x.photos.map((ph, i) => ({ src: extraPhotoHref(projectId, t.deal.id, x.id, ph.file_id), alt: `${x.title} 사진 ${i + 1}` }))} />
        </Group>
        <Group list>
          <Rows>
            <Row label="원래 금액" sub="확정 · 부가세 포함" value={<Money value={t.deal.quote.total} size="line" />} valueSub />
            <Row label="추가 금액" sub={pending ? "승인하면 더해져요" : "부가세 포함"} value={<Money value={x.total} size="line" delta />} valueSub />
            {t.extras.ok.total > 0 && x.answer !== "approved" ? <Row label="이미 승인한 추가 금액" sub="부가세 포함" value={<Money value={t.extras.ok.total} size="line" delta />} valueSub /> : null}
            {pending && x.after_total != null ? <Row label="승인하면" sub="부가세 포함" value={<Money value={x.after_total} size="line" />} total /> : null}
          </Rows>
        </Group>
        {state ? <Notice tone={x.answer === "approved" ? "blue" : "sub"} role="status">{state}</Notice> : null}
        <Notice tone="gray">승인하기 전에는 합계에 넣지 않아요. 업체가 금액을 고치면 다시 승인해요. 돈은 업체와 직접 주고받아요.</Notice>
      </>
    ),
    bar: pending ? <ExtraActions projectId={projectId} dealId={t.deal.id} extraId={x.id} threadId={t.deal.thread_id ?? null} /> : null,
  };
}

/** C38 공사 끝 확인 */
export function doneView({ projectId, t }: Ctx): View {
  const d = t.deal;
  const v = d.vendor_name;
  const money = (
    <Group list>
      <Rows>
        {d.grand_total != null && t.extras.ok.total > 0 ? (
          <Row label="공사 금액" sub={`추가 ${won(t.extras.ok.total)} 포함 · 부가세 포함`} value={<Money value={d.grand_total} size="line" />} total />
        ) : (
          <>
            <Row label="확정 금액" sub="부가세 포함" value={<Money value={d.quote.total} size="line" />} />
            {t.extras.ok.total > 0 ? <Row label="승인한 추가 금액" sub="부가세 포함" value={<Money value={t.extras.ok.total} size="line" delta />} valueSub /> : null}
          </>
        )}
      </Rows>
    </Group>
  );
  if (d.status === "checking") {
    return {
      body: (
        <>
          <Group>
            <Eyebrow>{iGa(v)} 공사를 끝냈대요</Eyebrow>
            {d.work_done_on ? <p className={`${s.big} mj-num`}>{dateLong(d.work_done_on)}</p> : null}
            {d.done_photos.length ? <Pics label="공사 끝 사진" items={d.done_photos.map((fid, i) => ({ src: donePhotoHref(projectId, d.id, fid), alt: `공사 끝 사진 ${i + 1}` }))} /> : null}
            {d.done_note ? <Quote>{d.done_note}</Quote> : null}
          </Group>
          {money}
          {d.auto_done_at ? (
            <Notice tone="warn">
              <span className={s.nw}>{dateShort(d.auto_done_at)}까지</span> 확인하지 않으면 자동으로 끝나요
              {d.done_remind_at ? <> · <span className={s.nw}>{dateShort(d.done_remind_at)}에</span> 한 번 알려 드려요</> : null}
            </Notice>
          ) : null}
          <Notice tone="gray">확인하면 공사가 끝나요. 그다음 리뷰를 쓸 수 있어요. 끝난 뒤에도 하자는 채팅으로 접수해요.</Notice>
        </>
      ),
      bar: <DoneActions projectId={projectId} dealId={d.id} threadId={d.thread_id ?? null} />,
    };
  }
  if (d.status === "fixing") {
    return {
      body: (
        <>
          <Group hi>
            <Eyebrow>고칠 곳을 알렸어요</Eyebrow>
            <Title>{iGa(v)} 고친 뒤 다시 공사 끝을 알려요</Title>
            {d.fixing_note ? <Quote>{d.fixing_note}</Quote> : null}
            {d.thread_id ? <div><Button variant="text" arrow href={`/chat/${encodeURIComponent(d.thread_id)}`}>채팅 열기</Button></div> : null}
          </Group>
          {money}
        </>
      ),
      bar: null,
    };
  }
  if (d.status === "done") {
    return {
      body: (
        <>
          <Group>
            <Eyebrow>공사 끝</Eyebrow>
            <Title>공사가 끝났어요</Title>
            {d.work_done_on ? <Sub>{dateLong(d.work_done_on)} 공사 끝</Sub> : null}
            <div className={s.links}>
              {d.review_open ? <Button variant="text" arrow href={`${base(projectId)}/review`}>리뷰 쓰기</Button> : null}
              {d.review_id ? <Small>리뷰를 썼어요</Small> : null}
              {d.thread_id ? <Button variant="text" arrow href={`/chat/${encodeURIComponent(d.thread_id)}`}>하자 접수</Button> : null}
            </div>
          </Group>
          {money}
        </>
      ),
      bar: null,
    };
  }
  return { body: <EmptyState icon="check" title="공사가 끝나면 여기서 확인해요" action={<Button variant="text" arrow href={`${base(projectId)}/schedule?view=dates`}>공사 날짜 보기</Button>}>{iGa(v)} 공사를 끝냈다고 알리면 와요</EmptyState>, bar: null };
}
