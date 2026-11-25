// 견적서 줄 표(design-system 3.3 QuoteLines): 표준견적서 · 가견적(업체 단가 줄) · 부분 공사.
// 담긴 칸이 560px보다 좁으면 줄 목록(이름 16/600 + 아래 '130.1㎡ × 5,993원', 오른쪽 금액 16/700), 넓으면 표(줄 · 수량 · 단가 · 금액).
// 금액 · 수량 · 단가 · 합계는 모두 계산 엔진 값이에요. 이 조각은 더하지 않아요. 합계 위에 2px 진한 줄(서류형).
// 합계에는 '포함' · '따로 계산'만 들어가요. 선택 · 실측 후는 괄호 + '합계 밖', 묶음 포함 · 안 함은 '—'.
// 공급가 · 부가세를 나눠 보이는 곳은 표준견적서 합계 칸 하나(vatSplit)예요(copy-guide F1-2).
import { decText, wonFull, numText } from "@/lib/v5/format";
import { LINE_STATES, outsideTotal } from "@/lib/v5/labels";
import s from "@/components/ui/QuoteLines.module.css";

export type LineState = "included" | "bundled" | "separate" | "optional" | "after_visit" | "excluded";
export type QuoteLine = {
  key: string;
  name: string;
  /** 업체 화면(D02 · V02)만 보여요: 1201 같은 단가 양식 줄 번호. 고객 화면은 빼요(CF-42) */
  code?: string;
  /** 줄 아래 설명 앞부분(예: '풀 포함' · '시장 평균 가격') */
  note?: string;
  qty?: number | string | null;
  /** 수량 단위(㎡ · 평 · 품). 업체 단가 줄은 '평'처럼 분명히(L01) */
  unit?: string;
  unitPrice?: number | null;
  amount: number | null;
  state?: LineState;
  /** 상태 말 대신 보일 까닭(계산 엔진 줄 근거 글). 예: 전체 철거면 '기존 벽지 철거' 줄은 '안 함' 대신 '전체 철거 공사에서 떼요(도배 견적 밖)' */
  stateText?: string;
};
export type QuoteTotals = { supply?: number; vat?: number; total: number };

const qtyText = (l: QuoteLine) => (l.qty == null ? "" : `${typeof l.qty === "string" ? decText(l.qty) : l.qty.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${l.unit ?? ""}`);
const isOut = (l: QuoteLine) => (l.state ? outsideTotal(l.state) : false);
const isDash = (l: QuoteLine) => l.state === "excluded" || l.state === "bundled" || l.amount == null;
const stateWord = (l: QuoteLine) => l.stateText ?? (l.state && l.state !== "included" && l.state !== "separate" ? LINE_STATES[l.state] : "");

function detail(l: QuoteLine) {
  const q = qtyText(l);
  const formula = q && l.unitPrice != null ? `${q} × ${wonFull(l.unitPrice)}` : q;
  return [l.note, isOut(l) ? stateWord(l) : "", formula, isOut(l) ? "합계 밖" : !isOut(l) && stateWord(l) ? stateWord(l) : ""].filter(Boolean).join(" · ");
}
function amountText(l: QuoteLine, unit = true) {
  if (isDash(l)) return "—";
  const v = unit ? wonFull(l.amount!) : numText(l.amount!);
  return isOut(l) ? `(${v})` : v;
}

export function QuoteLines({ lines, totals, vatSplit, showCode, caption }: {
  lines: QuoteLine[];
  totals?: QuoteTotals;
  vatSplit?: boolean;
  showCode?: boolean;
  /** 표 이름(화면 읽기). 예: '표준견적서 줄' */
  caption: string;
}) {
  const split = vatSplit && totals?.supply != null && totals?.vat != null;
  return (
    <div className={s.wrap}>
      {/* 좁은 칸: 줄 목록 */}
      <ul className={s.list} aria-label={caption}>
        {lines.map((l) => (
          <li key={l.key} className={`${s.row} ${isOut(l) || isDash(l) ? s.out : ""}`}>
            <div className={s.rl}>
              <b>{showCode && l.code ? <span className={s.code}>{l.code} </span> : null}{l.name}</b>
              {detail(l) ? <span className="mj-num">{detail(l)}</span> : null}
            </div>
            <span className={`${s.rv} mj-num`}>{amountText(l)}</span>
          </li>
        ))}
        {totals ? (
          split ? (
            <>
              <li className={`${s.row} ${s.first}`}><div className={s.rl}><b>공급가</b></div><span className={`${s.rv} ${s.sm} mj-num`}>{wonFull(totals.supply!)}</span></li>
              <li className={s.row}><div className={s.rl}><b>부가세</b></div><span className={`${s.rv} ${s.sm} mj-num`}>{wonFull(totals.vat!)}</span></li>
              <li className={`${s.row} ${s.tot}`}><div className={s.rl}><b>합계</b></div><span className={`${s.rv} mj-num`}>{wonFull(totals.total)}</span></li>
            </>
          ) : (
            <li className={`${s.row} ${s.tot} ${s.first}`}><div className={s.rl}><b>합계</b><span>부가세 포함</span></div><span className={`${s.rv} mj-num`}>{wonFull(totals.total)}</span></li>
          )
        ) : null}
      </ul>

      {/* 넓은 칸: 표 */}
      <table className={s.table}>
        <caption className="mj-sr">{caption}</caption>
        <thead>
          <tr>
            {showCode ? <th scope="col" className={s.cCode}>코드</th> : null}
            <th scope="col">줄</th>
            <th scope="col" className={s.r}>수량</th>
            <th scope="col" className={s.r}>단가</th>
            <th scope="col" className={s.r}>금액(원)</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.key} className={isOut(l) || isDash(l) ? s.out : undefined}>
              {showCode ? <td className={`${s.cCode} mj-num`}>{l.code}</td> : null}
              <th scope="row">
                <b>{l.name}</b>
                {l.note || stateWord(l) ? <span className={s.sub}>{[l.note, stateWord(l), isOut(l) ? "합계 밖" : ""].filter(Boolean).join(" · ")}</span> : null}
              </th>
              <td className={`${s.r} mj-num`}>{qtyText(l) || "—"}</td>
              <td className={`${s.r} mj-num`}>{l.unitPrice != null ? numText(l.unitPrice) : "—"}</td>
              <td className={`${s.r} mj-num`}>{amountText(l, false)}</td>
            </tr>
          ))}
        </tbody>
        {totals ? (
          <tfoot>
            <tr>
              <th scope="row" colSpan={showCode ? 4 : 3}>{split ? <>공급가 <span className="mj-num">{numText(totals.supply!)}</span> + 부가세 <span className="mj-num">{numText(totals.vat!)}</span></> : "합계 · 부가세 포함"}</th>
              <td className={`${s.r} mj-num`}><b>{numText(totals.total)}</b></td>
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
