// 서류 모음 표 (시안 WDocs): 표준견적서 → 예상 공정표 → 실측 견적서(업체마다) → 확정 공정표.
// 추가 금액은 확정 견적서 줄 아래 따로 한 줄씩 둔다. 금액 · 날짜는 API 값을 형식만 바꾸고 더하지 않는다.
import Link from "next/link";
import type { ReactNode } from "react";
import type { ApiDeal, ApiDocs } from "@/lib/api/schedule";
import { dateSeoul, md, won } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { ACK_TEXT, PLAN_NAME, finalPlanSub, quoteSub } from "./text";
import s from "./docs.module.css";

type QuoteDoc = ApiDocs["quotes"][number];
type Version = QuoteDoc["versions"][number];
type ExtraGroup = ApiDocs["extras"][number];

/** 받은 시각 → "11.02(월)" */
const day = (t: string) => md(dateSeoul(t));

function Dash() {
  return <><span aria-hidden="true">—</span><span className="mj-sr">금액 없음</span></>;
}

/** 지난 판 접어 두기 (what: 표준견적서 · 공정표 · 견적서) */
function Past({ n, what, children }: { n: number; what: string; children: ReactNode }) {
  return (
    <details className={s.past}>
      <summary>
        <svg className={s.chev} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 3l4 4-4 4" /></svg>
        지난 {what} {n}개
      </summary>
      <ul>{children}</ul>
    </details>
  );
}

/** 실측 견적서 파일 이름 목록 (누르면 새 창으로 열려요) */
function Files({ v, name }: { v: Version; name: string }) {
  const files = v.files
    .map((f, i) => ({ f, href: v.file_links[i] }))
    .filter((x) => x.href)
    .sort((a, b) => a.f.sort - b.f.sort);
  if (!files.length) return null;
  return (
    <ul className={s.files} aria-label={`${name} 파일 ${files.length}개`}>
      {files.map(({ f, href }) => (
        <li key={f.file_id}><a href={href} target="_blank" rel="noopener">{f.filename}<span className="mj-sr"> · 새 창</span></a></li>
      ))}
    </ul>
  );
}

/** 파일이 하나뿐이면 그 주소 (줄 제목을 링크로 하고 파일 이름 줄은 두지 않는다) */
function onlyFile(v: Version): string | null {
  const links = v.file_links.filter(Boolean);
  return v.files.length === 1 && links.length === 1 ? links[0] : null;
}

/** 보이는 버전: 고객이 확정한 버전, 없으면 가장 나중 버전 */
function mainVersion(q: QuoteDoc): Version {
  return q.versions.find((v) => v.confirmed) ?? q.versions.reduce((a, b) => (b.version > a.version ? b : a));
}

function extraRows(g: ExtraGroup) {
  return g.items.map((x) => (
    <tr key={x.id} className={s.extra}>
      <th scope="row">
        <span className={s.exName}>업체가 알린 추가 금액</span>
        <span className={s.sub}>{x.title} · {ACK_TEXT[x.ack]}</span>
      </th>
      <td className={s.date}>{day(x.created_at)}</td>
      <td className={s.amt}>{won(x.total)}</td>
    </tr>
  ));
}

export function DocsTable({ docs, trades, deals }: { docs: ApiDocs; trades: string[]; deals: ApiDeal[] }) {
  const rows: ReactNode[] = [];
  let count = 0;

  // 표준견적서: 최신 판 한 줄(공정 합계), 지난 판은 접어 둔다
  const std = docs.standard.filter((x) => x.latest);
  if (std.length) {
    const old = docs.standard.filter((x) => !x.latest);
    const when = std.map((x) => x.computed_at).sort().at(-1) ?? std[0].computed_at;
    count += 1;
    rows.push(
      <tr key="standard">
        <th scope="row">
          <Link className={s.doc} href={std[0].link}>표준견적서</Link>
          <span className={s.sub}>{std.map((x) => tradeLabel(x.trade)).join(" · ")}</span>
          {old.length ? (
            <Past n={old.length} what="표준견적서">
              {old.map((x) => <li key={`${x.trade}-${x.version}`}>{tradeLabel(x.trade)} · {day(x.computed_at)} · {won(x.total)}</li>)}
            </Past>
          ) : null}
        </th>
        <td className={s.date}>{day(when)}</td>
        <td className={s.amt}>{won(docs.standard_total)}</td>
      </tr>,
    );
  }

  // 공정표: 종류마다 최신 판 한 줄, 지난 판은 접어 둔다
  const planRow = (kind: "expected" | "final", sub: string) => {
    const all = docs.plans.filter((x) => x.kind === kind);
    const cur = all.find((x) => x.latest);
    if (!cur) return;
    const old = all.filter((x) => !x.latest);
    count += 1;
    rows.push(
      <tr key={kind}>
        <th scope="row">
          <Link className={s.doc} href={cur.link}>{PLAN_NAME[kind]}</Link>
          {sub ? <span className={s.sub}>{sub}</span> : null}
          {old.length ? (
            <Past n={old.length} what="공정표">
              {old.map((x) => <li key={x.version}>{day(x.created_at)} · {md(x.start)} ~ {md(x.end)}</li>)}
            </Past>
          ) : null}
        </th>
        <td className={s.date}>{day(cur.created_at)}</td>
        <td className={s.amt}><Dash /></td>
      </tr>,
    );
  };
  planRow("expected", "");

  // 실측 견적서: 업체마다 한 줄. 확정한 견적서 아래에 그 공정의 추가 금액
  const placed = new Set<string>();
  for (const q of docs.quotes) {
    if (!q.versions.length) continue;
    const v = mainVersion(q);
    const old = q.versions.filter((x) => x.id !== v.id);
    const name = `${q.vendor_name} 실측 견적서`;
    const one = onlyFile(v);
    count += 1;
    rows.push(
      <tr key={q.visit_id} className={q.closed ? s.closed : undefined}>
        <th scope="row">
          {one ? <a className={s.doc} href={one} target="_blank" rel="noopener">{name}<span className="mj-sr"> · 새 창</span></a> : <span className={s.doc}>{name}</span>}
          <span className={s.sub}>{quoteSub(q.trade, q.closed, v.confirmed)}</span>
          {one ? null : <Files v={v} name={name} />}
          {old.length ? (
            <Past n={old.length} what="견적서">
              {old.map((x) => (
                <li key={x.id}>
                  {day(x.sent_at)} · {x.total != null ? won(x.total) : "금액 없음"}
                  <Files v={x} name={`${name} ${day(x.sent_at)}`} />
                </li>
              ))}
            </Past>
          ) : null}
        </th>
        <td className={s.date}>{day(v.sent_at)}</td>
        <td className={s.amt}>{v.total != null ? won(v.total) : <Dash />}</td>
      </tr>,
    );
    if (!q.closed && v.confirmed) {
      const g = docs.extras.find((e) => e.trade === q.trade && !placed.has(e.deal_id));
      if (g) {
        placed.add(g.deal_id);
        rows.push(...extraRows(g));
      }
    }
  }
  // 맞는 확정 견적서 줄이 없는 추가 금액은 실측 견적서 뒤에 둔다
  for (const g of docs.extras) if (!placed.has(g.deal_id)) rows.push(...extraRows(g));
  const extras = docs.extras.some((g) => g.items.length);

  planRow("final", finalPlanSub(trades, deals));

  if (!count) return <p className="mj-sub">아직 서류가 없어요.</p>;
  return (
    <>
      <div className={`mj-table-box ${s.box}`} role="region" tabIndex={0} aria-label="이 공사의 서류, 옆으로 넘겨 볼 수 있어요">
        <table className={`mj-table mj-num ${s.tbl}`}>
          <caption className="mj-sr">이 공사의 서류 {count}개와 날짜, 금액</caption>
          <thead>
            <tr>
              <th scope="col">서류</th>
              <th scope="col">날짜</th>
              <th scope="col" className={s.amt}>금액</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      {extras ? <p className={s.note}>추가 금액은 업체가 공사 중에 알린 금액이에요. 견적서 금액에 더하지 않고 따로 적어요.</p> : null}
    </>
  );
}
