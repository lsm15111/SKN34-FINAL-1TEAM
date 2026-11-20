// C5 실측 견적서 비교(업체 = 열): 낼 금액(앞 판과 차액) · 가견적과 차이 · 공사 기간 · 유효기간 · 철거 · 폐기물 · 벽지 · 하자 보수 · 파일.
// 금액 · 차이는 계산 엔진 값(서버)이에요. 표준견적서와 견준 %는 넣지 않아요(리드 결정). 업체 견적서는 줄로 바꾸지 않아요(파일 + 칸).
import Link from "next/link";
import type { CompareCol } from "@/lib/api/assistant";
import { dateShort, won, wonDelta } from "@/lib/format";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

const yes = (v: boolean | null | undefined, miss = "안 적혀 있어요") => (v === true ? "포함" : v === false ? "빠짐" : <em className={c.miss}>{miss}</em>);
const months = (n: number | null | undefined) => (n == null ? "—" : n % 12 === 0 ? `${n / 12}년` : `${n}개월`);

export function QuoteCompareCard({ card, ctx }: CardProps<"quote_compare">) {
  const d = card.data;
  const cols = d.cols;
  const td = (x: CompareCol, v: React.ReactNode) => <td key={x.visit_id} className={x.state === "waiting" ? c.waitCol : undefined}>{x.state === "waiting" ? "" : v}</td>;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>실측 견적서 비교</h3>
        <SourceTag src="calc" />
      </div>
      <div className={c.cmpWrap}>
        <table className={c.cmp}>
          <caption className="mj-sr">업체별 실측 견적서. 금액은 부가세 포함이에요</caption>
          <thead>
            <tr>
              <th scope="col"><span className="mj-sr">항목</span></th>
              {cols.map((x) => (
                <th key={x.visit_id} scope="col" className={x.state === "waiting" ? c.waitCol : undefined}>
                  {x.vendor_name}
                  <small className={k.num}>{x.state === "waiting" ? x.wait_note ?? "기다리는 중" : `${x.version}판 · ${x.received_on ? dateShort(x.received_on) : ""}`}</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr><th scope="row">낼 금액</th>{cols.map((x) => td(x, <><b className={k.num}>{x.total_won != null ? won(x.total_won) : "—"}</b>{x.changed ? <span className={`${c.up} ${k.num}`}>{x.changed.from_version}판보다 {wonDelta(x.changed.diff_won)}</span> : null}</>))}</tr>
            <tr><th scope="row">가견적과 차이</th>{cols.map((x) => td(x, <span className={k.num}>{x.diff_vs_estimate_won != null ? wonDelta(x.diff_vs_estimate_won) : "—"}</span>))}</tr>
            <tr><th scope="row">공사 기간</th>{cols.map((x) => td(x, x.days != null ? `${x.days}일` : "—"))}</tr>
            <tr><th scope="row">유효기간</th>{cols.map((x) => td(x, x.valid_until ? <span className={x.valid_soon || x.expired ? `${c.warn} ${k.num}` : k.num}>{dateShort(x.valid_until)}{x.expired ? " · 지났어요" : x.valid_soon ? " · 곧 끝나요" : ""}</span> : "—"))}</tr>
            <tr><th scope="row">철거 · 폐기물</th>{cols.map((x) => td(x, <>{yes(x.demolish)} · {yes(x.waste)}</>))}</tr>
            <tr><th scope="row">벽지</th>{cols.map((x) => td(x, x.paper ?? "—"))}</tr>
            <tr><th scope="row">하자 보수</th>{cols.map((x) => td(x, months(x.warranty_months)))}</tr>
            <tr><th scope="row">파일</th>{cols.map((x) => td(x, x.file ? <Link className={x.file.kind === "image" ? `${c.file} ${c.fileImg}` : c.file} href={x.file.href} scroll={false}><I n={x.file.kind === "image" ? "image" : "file"} />{x.file.label}</Link> : "—"))}</tr>
          </tbody>
        </table>
      </div>
      {d.gap_won != null ? <p className={c.gap}><SourceTag src="calc" />두 곳이 <b className={k.num}>{won(d.gap_won)}</b> 차이 나요</p> : null}
      {d.ask_chips.length ? (
        <div className={c.askTo}>
          <span>업체에 물을 말</span>
          {d.ask_chips.map((q) => <button key={q} type="button" className={`${k.chip} ${k.chipSm}`} disabled={ctx.busy} onClick={() => ctx.send(q)}><I n="chat" />{q}</button>)}
        </div>
      ) : null}
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.href} scroll={false}>비교표 크게 보기</Link>
      </div>
    </section>
  );
}
