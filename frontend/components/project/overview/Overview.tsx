// 한 공사 화면 (시안 WProjectB). GET /projects/{id}/overview 하나로 그린다.
// 지금 할 일 문구 · 버튼 · 가는 곳, 단계 판정, 낼 금액 · 예산 견줌, 공사 기간, 연락처 기한은 모두 API(계산 엔진) 값이고 화면은 형식만 바꾼다.
// 견적 직후(phase=estimate)에는 '업체 연락처'를 두지 않는다(시안 메모).
// 수락한 공사 날짜가 있고 공사 시작 전이면 '금액과 날짜' 아래에 공사 전에 할 일(PreWorkCheck)을 둔다. 상담 묻기는 넣지 않는다.
import Link from "next/link";
import { PreWorkCheck } from "@/components/project/PreWorkCheck";
import { span } from "@/components/schedule/text";
import { budgetLabel, phoneText, projectTitle, tradeLabel } from "@/lib/labels";
import { decText, md, todaySeoul, won } from "@/lib/format";
import { Chev, State } from "./icons";
import { tradeDates, tradeState, type Overview as Ov } from "./text";
import s from "./Overview.module.css";

export function Overview({ ov }: { ov: Ov }) {
  const id = ov.project_id;
  const title = projectTitle(ov.region, ov.trades.map((t) => t.trade));
  const early = ov.phase === "estimate";
  const contacts = early ? [] : ov.contacts.filter((c) => c.contact.phone);
  const todo = ov.todo;
  const finished = todo ? todo.code === "done" : ov.phase === "done";
  const { money, period } = ov;
  const allStandard = money.by_trade.every((m) => m.source === "standard");
  const notAccepted = ov.trades.filter((t) => !t.start_date).map((t) => tradeLabel(t.trade));
  const beforeWork = period.kind === "final" && period.start > todaySeoul() && ov.checks.length > 0;

  return (
    <main id="main">
      <nav className={`mj-wrap mj-crumb ${s.crumb}`} aria-label="이동 경로">
        <ol>
          <li><Link href="/my">내 공사</Link><span aria-hidden="true">›</span></li>
          <li><span aria-current="page">{title}</span></li>
        </ol>
      </nav>
      <div className={`mj-wrap ${s.head}`}>
        <h1 className="mj-h1">{title}</h1>
        {ov.pyeong ? <p className="mj-sub mj-num">{decText(ov.pyeong)}평</p> : null}
      </div>

      {todo || finished ? (
        <section className={`mj-wrap ${s.todoSec}`} aria-labelledby="todo-t">
          <div className={s.todo}>
            <h2 id="todo-t" className={s.todoH}>지금 할 일</h2>
            <p className={`mj-num ${s.todoT}`}>{todo ? todo.text : "공사가 끝났어요"}</p>
            {finished ? (
              contacts.length ? (
                <p className={s.todoActs}>
                  <a className={s.lnkG} href="#contacts">연락처 보기</a>
                </p>
              ) : null
            ) : todo ? (
              <Link className="mj-btn mj-btn-pri" href={todo.link}>{todo.action}</Link>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className={`mj-wrap ${s.trades}`} aria-labelledby="tr-t">
        <h2 id="tr-t" className="mj-h2">공정별 상태</h2>
        <ul className={`mj-num ${s.lines}`} aria-labelledby="tr-t">
          {ov.trades.map((t) => {
            const st = tradeState(t);
            const dt = tradeDates(t);
            return (
              <li key={t.trade} className={s.ln}>
                <h3 className={`mj-h2 ${s.lnName}`}>{tradeLabel(t.trade)}</h3>
                <p className={s.lnVendor}>{t.vendor_name ? <><span className="mj-sr">업체 </span>{t.vendor_name}</> : null}</p>
                <p className={s.lnState}><State tone={st.tone} text={st.text} size={16} /></p>
                <p className={s.lnDates}>
                  {dt ? <><span className="mj-sr">{dt.accepted ? "공사 날짜 " : "수락 기다리는 날짜 "}</span>{span(dt.start, dt.end)}</> : null}
                </p>
              </li>
            );
          })}
        </ul>

      </section>

      <div className={`mj-wrap ${s.row}`}>
        <div className={s.left}>
          <section aria-labelledby="md-t">
            <h2 id="md-t" className="mj-sr">금액과 날짜</h2>
            <div className={`mj-num ${s.md}`}>
              <dl className={s.box}>
                <dt className={s.dt}>{allStandard ? "표준견적서" : "낼 금액"}</dt>
                <dd className={s.big}><span className={s.bigV}>{won(money.total)}</span></dd>
                {money.by_trade.length ? (
                  <dd className="mj-small">
                    {money.by_trade.map((m, i) => (
                      <span key={m.trade}>
                        {i ? " · " : ""}{tradeLabel(m.trade)} {won(m.total)}{m.source === "standard" && !allStandard ? " (표준견적서 기준)" : ""}
                      </span>
                    ))}
                  </dd>
                ) : null}
                {money.budget ? (
                  <>
                    <dt className={`${s.dt} ${s.dt2}`}>예산</dt>
                    <dd className={s.budget}>
                      {budgetLabel(money.budget.band)}
                      {money.budget.status === "within" ? <State tone="ok" text="예산 안이에요" /> : null}
                      {money.budget.status === "over" && money.budget.over_by != null ? <span className="mj-st mj-st-wait">예산보다 {won(money.budget.over_by)} 많아요</span> : null}
                    </dd>
                  </>
                ) : null}
              </dl>
              <dl className={s.box}>
                <dt className={s.dt}>{period.kind === "expected" ? "예상 기간" : "공사 기간"}</dt>
                <dd className={s.big}><span className={s.bigV}>{md(period.start)} ~ {md(period.end)}</span></dd>
                <dd className="mj-small">
                  일하는 날 {period.work_days}일 · 입주 청소까지
                  {period.kind === "final" && notAccepted.length ? ` · ${notAccepted.join(" · ")} 날짜는 아직 수락 전이에요` : ""}
                </dd>
              </dl>
            </div>
          </section>
          {beforeWork ? <PreWorkCheck projectId={id} checks={ov.checks} start={period.start} /> : null}
        </div>

        {contacts.length ? (
          <section id="contacts" className={s.contacts} aria-labelledby="ct-t">
            <h2 id="ct-t" className={s.dt}>업체 연락처</h2>
            <ul className={`mj-num ${s.ctList}`}>
              {contacts.map((c) => {
                const phone = phoneText(c.contact.phone ?? "");
                return (
                  <li key={c.trade}>
                    <p className={s.ctTrade}>{tradeLabel(c.trade)}</p>
                    <p className={s.ctMain}>
                      {c.vendor_name}{c.contact.owner_name ? ` · 대표 ${c.contact.owner_name}` : ""}<br />
                      <b className={s.phone}>{phone}</b>
                    </p>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
      </div>

      <div className={`mj-wrap ${s.moreNav}`}>
        <p className={s.dt}>더 보기</p>
        <nav className={s.tabs} aria-label="이 공사 더 보기">
          <Link href={`/projects/${id}/plan`}>공정표<Chev /></Link>
          <Link href={`/projects/${id}/docs`}>서류<Chev /></Link>
          <Link href={`/notifications?project=${id}`}>소식<Chev /></Link>
        </nav>
      </div>
    </main>
  );
}
