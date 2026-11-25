// 실측 견적서 비교(C33 폰 카드 · D18 웹 비교표 W4 A). 업체 양식 파일이라 줄끼리 견주지 않고 합계 · 기간 · 포함됐나요 · 유효기간 · 파일만 나란히 놓아요.
// 금액(합계 · 업체가 적은 금액 · 가견적과 차이)은 모두 계산 엔진 값이에요. 두 곳 사이 차이 금액 · 유효기간 알림 날짜는 API에 값이 없어 숫자 없이 써요.
import type { ReactNode } from "react";
import type { ApiCompare } from "@/lib/api/schedule";
import { dateSeoul, dateShort, euro, won } from "@/lib/v5/format";
import { visitState } from "@/lib/v5/labels";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CompareTable, type CompareCol, type CompareRow as TableRow } from "@/components/v5/ui/CompareTable";
import { Icon } from "@/components/ui/Icon";
import { Money } from "@/components/ui/Money";
import { Stars } from "@/components/ui/Stars";
import { FileRow, Group, GroupHead, InfoChips, Meta, Name, Notice, Small, Sub } from "@/components/project/Kit";
import { iGa } from "@/components/v5/visit/text";
import { RequoteButton } from "@/components/compare/RequoteButton";
import { incChips, quoteFileHref, quotedRows, receivedText, termText, vatText, type CompareRow, type VendorQuote } from "@/components/compare/v3";
import s from "@/components/compare/board.module.css";

type Quoted = CompareRow & { latest: VendorQuote };

export function QuoteBoard({ projectId, compare, slots, threads }: {
  projectId: string;
  compare: ApiCompare;
  /** 업체(visit_id)마다 실측 반나절 글 '12.15(화) 오전'(실측 일정 상태판 값) */
  slots: Record<string, string>;
  /** 업체(visit_id)마다 대화 id(채팅으로 묻기) */
  threads: Record<string, string | null>;
}) {
  const rows = quotedRows(compare);
  const waiting = compare.vendors.filter((r) => !r.latest);
  const deal = compare.deal;
  // 서버 계산 값: 두 곳 차이(gap_total) · 유효기간 알림 시각(valid_soon_at, 이른 것 먼저)
  const gap = compare.gap_total != null && rows.length >= 2 ? `${rows.length === 2 ? "두 곳이" : "가장 비싼 곳과 싼 곳이"} ${won(compare.gap_total)} 차이 나요. ` : "";
  const soon = [...new Set(rows.flatMap((r) => r.valid_soon_at ?? []).map((x) => dateSeoul(x)))].sort();
  const validNote = soon.length
    ? `유효기간이 다가오면 ${soon.map((x) => dateShort(x)).join(" · ")}에 알려 드려요. 지나면 확정할 수 없고 견적서를 다시 요청해요.`
    : "유효기간 3일 · 1일 전에 알려 드려요. 지나면 확정할 수 없고 견적서를 다시 요청해요.";
  const pid = encodeURIComponent(projectId);
  const askRow = rows.find((r) => incChips(r.latest).some((c) => c.tone === "warn")) ?? rows[0];
  const askThread = askRow ? threads[askRow.visit_id] : null;

  const action = (r: Quoted): ReactNode => {
    if (deal) return deal.visit_id === r.visit_id ? <Badge tone="ok">확정</Badge> : <Badge tone="mute">닫힘</Badge>;
    if (r.expired) {
      if (r.requote_at) return <span className={s.cellNote}>{dateShort(r.requote_at)}에 견적서를 다시 요청했어요</span>;
      return <RequoteButton projectId={projectId} visitId={r.visit_id} vendorName={r.vendor_name} />;
    }
    return <Button variant="weak" size="sm" href={`/v5/projects/${pid}/quotes/${encodeURIComponent(r.visit_id)}/confirm`}>{euro(r.vendor_name)} 확정</Button>;
  };
  const files = (r: Quoted) => (r.latest.files.length
    ? <div className={s.cellStack}>{r.latest.files.map((f) => <FileRow key={f.file_id} name={f.filename} type={f.content_type} size={f.size} href={quoteFileHref(projectId, r.latest.id, f.file_id)} />)}</div>
    : "—");
  const expiredLine = <span className={s.expired}><Icon name="error" size={16} />지났어요 · 확정할 수 없어요</span>;

  const columns: CompareCol[] = rows.map((r) => ({ key: r.visit_id, name: r.vendor_name, dim: r.expired && !deal, highlight: deal?.visit_id === r.visit_id }));
  const cell = (fn: (r: Quoted) => ReactNode) => Object.fromEntries(rows.map((r) => [r.visit_id, fn(r)]));
  /** 업체가 적은 금액이 합계와 같은지(적은 금액이 없으면 견줄 게 없어서 null) */
  const sameAsTotal = (r: Quoted): boolean | null => (r.latest.entered_amount == null ? null : r.latest.entered_amount === r.latest.total);
  const table: TableRow[] = [
    { key: "total", label: "합계 · 부가세 포함", hint: "믿집이 계산했어요", big: true, cells: cell((r) => <Money value={r.latest.total} size="mid" />) },
    // 업체가 적은 금액은 합계와 다를 때(부가세 빼고 · 면세)만 줄을 둬요. 부가세 포함으로 적었으면 합계와 같아서 겹쳐요
    ...(rows.some((r) => sameAsTotal(r) === false)
      ? [{ key: "entered", label: "업체가 적은 금액", cells: cell((r) => (sameAsTotal(r) ? "합계와 같아요" : r.latest.entered_amount != null ? `${won(r.latest.entered_amount)} · ${vatText(r.latest.vat_mode)}` : "—")) }]
      : []),
    { key: "days", label: "공사 기간", cells: cell((r) => (r.latest.days != null ? `${r.latest.days}일` : "—")) },
    { key: "inc", label: "포함됐나요?", hint: "차이가 크면 빠진 것을 물어보세요", cells: cell((r) => <InfoChips items={incChips(r.latest)} label={`${r.vendor_name} 포함됐나요`} />) },
    { key: "valid", label: "유효기간", hint: "3일 · 1일 전에 알려요", cells: cell((r) => (r.latest.valid_until ? <span className={s.cellStack}><span className="mj-num">{dateShort(r.latest.valid_until)}까지</span>{r.expired && !deal ? expiredLine : null}</span> : "—")) },
    { key: "visit", label: "실측", cells: cell((r) => slots[r.visit_id] ?? (r.visit_day ? dateShort(r.visit_day) : "—")) },
    { key: "sent", label: "받은 날", cells: cell((r) => (r.latest.sent_at ? dateShort(r.latest.sent_at) : "—")) },
    { key: "review", label: "리뷰", cells: cell((r) => (r.rating?.avg ? <Stars value={Number(r.rating.avg)} count={r.rating.count} size="sm" /> : "리뷰 없음")) },
    { key: "files", label: "견적서 파일", hint: "업체가 만든 양식", cells: cell(files) },
    { key: "act", label: "확정", action: true, cells: cell(action) },
  ];

  return (
    <>
      {deal ? (
        <Notice tone="blue" role="status">
          <span className={s.dealNote}><span><b>{euro(deal.vendor_name)} 확정했어요.</b> 공사 날짜는 {iGa(deal.vendor_name)} 올려요.</span><Button variant="text" arrow href={`/v5/projects/${pid}/schedule`}>공사 날짜 보기</Button></span>
        </Notice>
      ) : null}

      {/* 폰 · 태블릿: 업체 카드(C33) */}
      <div className={s.phone}>
        <ul className={s.cards} aria-label="실측 견적서">
          {rows.map((r) => (
            <Group as="li" key={r.visit_id} className={r.expired && !deal ? s.cardDim : undefined}>
              <GroupHead>
                <Name>{r.vendor_name}</Name>
                {r.expired && !deal ? <Badge tone="bad">유효기간 지남</Badge> : <Small>{receivedText(r.latest.sent_at)}</Small>}
              </GroupHead>
              <span className={s.total}><Money value={r.latest.total} size="mid" /></span>
              {r.expired && !deal
                ? <Sub>{r.latest.valid_until ? `${dateShort(r.latest.valid_until)}까지 유효 · 지났어요 · 확정할 수 없어요` : "지났어요 · 확정할 수 없어요"}</Sub>
                : <Sub>{termText(r.latest)}</Sub>}
              <InfoChips items={incChips(r.latest)} label={`${r.vendor_name} 포함됐나요`} />
              {r.latest.files.map((f) => <FileRow key={f.file_id} name={f.filename} type={f.content_type} size={f.size} href={quoteFileHref(projectId, r.latest.id, f.file_id)} />)}
              <div>{action(r)}</div>
            </Group>
          ))}
          {waiting.map((r) => {
            // 실측 전(실측 확정)과 실측 뒤(실측 견적서 기다림)를 실측 일정 화면과 같은 말로 갈라요
            const st = visitState(r.status, "customer");
            return (
              <Group as="li" key={r.visit_id}>
                <GroupHead><Name>{r.vendor_name}</Name><Badge tone={st.tone === "ok" ? "ok" : "wait"}>{st.label}</Badge></GroupHead>
                <Small>견적서가 오면 여기에 같이 보여요</Small>
              </Group>
            );
          })}
        </ul>
        {!deal && askRow ? (
          <Notice tone="sub">
            <span className={s.askRow}><span>{gap}차이가 크면 빠진 것을 채팅으로 물어보세요</span><Button variant="text" arrow href={askThread ? `/chat/${encodeURIComponent(askThread)}` : "/chat"}>{askRow.vendor_name}에 묻기</Button></span>
          </Notice>
        ) : null}
        {!deal ? <Notice tone="gray">{validNote}</Notice> : null}
      </div>

      {/* 웹: 업체를 열로 둔 비교표(D18) */}
      <div className={s.web}>
        <Group>
          <CompareTable caption="실측 견적서 비교" columns={columns} rows={table} />
        </Group>
        {waiting.length ? <Small>{waiting.map((r) => r.vendor_name).join(" · ")} 실측 견적서는 아직 안 왔어요</Small> : null}
        <p className={s.foot}>
          <span>{deal ? "확정한 견적서는 바뀌지 않아요." : "확정은 한 곳만 해요. 확정하면 다른 곳 견적서는 닫혀요."}</span>
          <Button variant="text" arrow href={askThread ? `/chat/${encodeURIComponent(askThread)}` : "/chat"}>채팅으로 묻기</Button>
        </p>
      </div>

      <Meta>견적서 파일은 업체가 만든 양식이에요. 합계 · 부가세는 믿집이 계산했어요.</Meta>
    </>
  );
}
