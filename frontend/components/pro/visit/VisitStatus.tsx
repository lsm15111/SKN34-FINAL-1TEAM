// 실측 요청의 나머지 모습(9판에 따로 그린 화면이 없는 상태): 고객 차례 · 실측 확정 · 실측 받음 · 견적서 보냄 · 업체 확정 · 끝남.
// 작업함 · 일정 탭 줄이 이 주소로 와요. 다음 할 일 단추 하나만 둬요(실측 견적서 올리기 · 채팅 열기).
// 실측 날 전에는 견적서를 보낼 수 없어서 채팅이 주 단추고, 견적서 단추는 꺼 두고 언제부터인지 이름으로 알려요(QA r6 M1).
import { Main, PageHead } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { BigFigure } from "@/components/ui/Money";
import { StateTag } from "@/components/ui/StateTag";
import type { VendorVisitV3 } from "@/lib/api/vendor";
import { dateSeoul, dateShort, dueText, halfDayText, rangeText } from "@/lib/format";
import { DECLINE_LABEL, visitState, type StateTone } from "@/lib/labels";
import { enc } from "../send";
import { LOC_NOTE } from "../text";
import { Notice } from "@/components/ui/Notice";
import { Eyebrow, Group, Row, Rows, Small } from "../ui/parts";
import { factLine, visitTitle } from "./facts";

export function VisitStatus({ v, now }: { v: VendorVisitV3; now: string }) {
  const st = v.state ? { tone: v.state.icon as StateTone, label: v.state.label } : visitState(v.status, "vendor");
  const b = v.booked;
  const quoteHref = `/vendor/requests/${enc(v.id)}/quote`;
  const chatHref = v.thread_id ? `/chat/${enc(v.thread_id)}` : null;
  const canQuote = v.status === "booked" || v.status === "visited";
  /** 실측 날 전(실측 확정 · 날이 오늘 뒤) */
  const early = canQuote && !!b && b.day > dateSeoul(now);
  let body: React.ReactNode = null;
  switch (v.status) {
    case "offered":
      body = (
        <>
          <p>고객이 날짜를 고르는 중이에요.</p>
          {v.window ? <Rows label="보낸 기간"><Row label="보낸 기간" sub={v.window.excluded.length ? `${v.window.excluded.map((d) => `${Number(d.slice(8, 10))}일`).join(" · ")} 빼고` : undefined} value={rangeText(v.window.start, v.window.end, { weekday: true })} /><Row label="고객이 고르는 기한" value={dueText(v.window.pick_due_at, { now })} /></Rows> : null}
          <Small>고객이 7일 안에 고르지 않으면 이 기간이 풀려 다른 요청에 다시 열려요.</Small>
        </>
      );
      break;
    case "proposed":
      body = (
        <>
          <p>고객이 제안한 날을 고르는 중이에요.</p>
          {v.proposal ? <Rows label="제안한 반나절">{v.proposal.slots.map((x) => <Row key={`${x.day}${x.half}`} label={halfDayText(x.day, x.half)} />)}</Rows> : null}
          {v.proposal ? <Small>{dueText(v.proposal.due_at, { now })} 고객이 골라요.</Small> : null}
        </>
      );
      break;
    case "booked":
    case "visited":
      body = b ? <BigFigure size="mid" label={v.status === "booked" ? "실측 날짜" : "실측한 날"} caption={null}>{halfDayText(b.day, b.half, true)}</BigFigure> : null;
      break;
    case "quoted":
      body = <p>실측 견적서를 보냈어요. 고객이 확정하면 알림으로 알려 드려요.</p>;
      break;
    case "chosen":
      body = <p>고객이 이 견적서로 확정했어요. 공사 날짜는 작업함 &lsquo;공사&rsquo; 탭에서 올려요.</p>;
      break;
    case "declined":
      body = <p>못 받는다고 알렸어요{v.decline_code ? ` · ${DECLINE_LABEL[v.decline_code as keyof typeof DECLINE_LABEL] ?? "그 밖"}` : ""}.</p>;
      break;
    case "expired":
      body = <p>답 기한이 지났어요. 고객이 다시 요청하면 작업함에 새로 와요.</p>;
      break;
    default:
      body = <p>이 요청은 끝났어요.</p>;
  }
  return (
    <>
      <Main narrow>
        <PageHead title="실측 요청" crumbs={[{ label: "작업함", href: "/vendor" }, { label: visitTitle(v) }]} />
        <Group>
          <StateTag tone={st.tone}>{st.label}</StateTag>
          <Eyebrow>{factLine(v)}</Eyebrow>
          {body}
        </Group>
        {v.change && v.change.status === "open" ? (
          <Notice tone="info">고객이 일정 바꾸기를 요청했어요 · {halfDayText(v.change.from_day, v.change.from_half)} → {halfDayText(v.change.to_day, v.change.to_half)} · {dueText(v.change.due_at, { now })} 채팅에서 답해요.</Notice>
        ) : null}
        <Small>{LOC_NOTE}</Small>
      </Main>
      {canQuote || chatHref || v.status === "chosen" ? (
        <BottomBar>
          {chatHref ? <Button size="lg" variant={canQuote && !early ? "secondary" : "primary"} href={chatHref}>채팅 열기</Button> : null}
          {early && b ? <Button size="lg" variant="secondary" disabled>{`견적서는 ${dateShort(b.day)}부터`}</Button>
            : canQuote ? <Button size="lg" href={quoteHref}>실측 견적서 올리기</Button> : null}
          {v.status === "chosen" ? <Button size="lg" href="/vendor?tab=jobs">공사 탭 보기</Button> : null}
        </BottomBar>
      ) : null}
    </>
  );
}
