// 비교표(W4 A · design-system 3.3 CompareTable): 업체를 열로(최대 3), 첫 열 170 라벨.
// 쓰는 곳: 실측 일정(상태 · 날짜 · 다음 할 일 · 기한 · D03) · 실측 견적서(합계 · 차이 · 공사 기간 · 포함됐나요 · 유효기간 · 파일 · 확정 · D18).
// 담긴 칸이 600px보다 좁으면(폰) 업체마다 카드를 세로로, 줄 순서는 같게 그려요(C14 · C33).
// 할 일 있는 열은 옅은 파랑, 유효기간 지난 열은 회색 글자. 담을 수 있는 곳이 남으면 표 아래 한 줄('1곳 더 담을 수
// 있어요' + 다음 길)만 두고 빈 열 · 빈 카드는 그리지 않아요(2026-11-23 사용자: 한 곳만 담았을 때 '빈 칸' 줄이 보임).
// 첫 열 머리는 '업체명'(열 머리가 업체 이름이라서, 2026-11-23 사용자: '견줄 것'은 맞지 않음).
import type { ReactNode } from "react";
import s from "./CompareTable.module.css";

export type CompareCol = { key: string; name: string; /** 할 일 있는 열 */ highlight?: boolean; /** 유효기간 지남 */ dim?: boolean; /** 열 머리 오른쪽(받은 날 · 배지) */ aside?: ReactNode };
export type CompareRow = { key: string; label: string; /** 라벨 아래 작은 글 */ hint?: string; /** 큰 숫자 줄 */ big?: boolean; /** 단추 줄(라벨 없음) */ action?: boolean; cells: Record<string, ReactNode> };

export function CompareTable({ caption, columns, rows, empty, max = 3 }: {
  caption: string;
  columns: CompareCol[];
  rows: CompareRow[];
  /** 표 아래 한 줄(담을 수 있는 곳이 남았을 때) */
  empty?: { title: string; action?: ReactNode };
  max?: number;
}) {
  const more = columns.length < max ? empty : undefined;
  return (
    <div className={s.wrap}>
      {/* 넓은 칸: 표 */}
      <div className={s.tblBox}>
        <table className={s.table}>
          <caption className="mj-sr">{caption}</caption>
          <thead>
            <tr>
              <th scope="col" className={s.lab}>업체명</th>
              {columns.map((c) => (
                <th key={c.key} scope="col" className={[c.highlight ? s.hl : null, c.dim ? s.dim : null].filter(Boolean).join(" ") || undefined}>
                  <span className={s.colName}>{c.name}</span>{c.aside ? <span className={s.colAside}>{c.aside}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={[r.big ? s.big : null, r.action ? s.act : null].filter(Boolean).join(" ") || undefined}>
                <th scope="row" className={s.lab}>{r.action ? <span className="mj-sr">{r.label}</span> : <>{r.label}{r.hint ? <span className={s.hint}>{r.hint}</span> : null}</>}</th>
                {columns.map((c) => (
                  <td key={c.key} className={[c.highlight ? s.hl : null, c.dim ? s.dim : null].filter(Boolean).join(" ") || undefined}>{r.cells[c.key] ?? "—"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 좁은 칸: 업체마다 카드 */}
      <ul className={s.cards} aria-label={caption}>
        {columns.map((c) => (
          <li key={c.key} className={[s.card, c.highlight ? s.cardHl : null, c.dim ? s.dim : null].filter(Boolean).join(" ")}>
            <div className={s.cardHead}><b>{c.name}</b>{c.aside}</div>
            <dl className={s.kv}>
              {rows.filter((r) => !r.action).map((r) => (
                <div key={r.key} className={r.big ? s.kvBig : undefined}>
                  <dt>{r.label}</dt>
                  <dd>{r.cells[c.key] ?? "—"}</dd>
                </div>
              ))}
            </dl>
            {rows.filter((r) => r.action).map((r) => <div key={r.key} className={s.cardAct}>{r.cells[c.key]}</div>)}
          </li>
        ))}
      </ul>
      {more ? (
        <div className={s.more}>
          <p>{more.title}</p>
          {more.action}
        </div>
      ) : null}
    </div>
  );
}
