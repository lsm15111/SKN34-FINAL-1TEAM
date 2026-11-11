"use client";
// 공정표 문서 · 공정표 보기 (v10 planDocEl · vendorDateCard · customerDateCard, v6 schedView · weekList · barsEl · ganttEl).
// 날짜 · 일수는 API plan 응답(blocks · days) 그대로 쓴다. 업체 날짜 점검 · 영향 미리 보기도 API가 계산한다.
import { useEffect, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { toast } from "../engine";
import { V3 } from "../store";
import { accepted, type Block, fetchPlan, fetchQuote, type Plan, type PlanTrade, props, type Quote, type Trial } from "./api";
import { DateField, Fld, log, md0, mdw, TCOLOR, wdOf } from "./shared";

/** 견적이 없으면 받아 둔다 */
export async function ensureQuote() {
  if (!V3.quote) V3.quote = await fetchQuote();
  return V3.quote as Quote;
}
/** 공정표를 다시 받는다 (v10 buildPlan). 공정 단계 · 기간은 서버가 견적을 다시 계산해서 쓴다 */
export async function loadPlan() {
  const p = await fetchPlan();
  V3.plan = p;
  return p;
}

/* ---------- 공정표 보기 ---------- */
const CAT_OF_TRADE: Record<string, string> = { mokgong: "carpentry", dobae: "wallpaper" };
const TRADE_DO: Record<string, string> = {
  window: "샷시 · 현관문을 바꿔요", carpentry: "천장 · 벽을 잡고 몰딩 · 문틀 · 방문을 달아요", bath: "변기 · 세면대 · 수전 · 욕실장을 달아요",
  tile: "욕실 · 주방 · 현관에 타일을 붙여요", film: "문 · 몰딩 · 가구 겉면에 필름을 붙여요", paint: "벽 · 천장 · 문을 칠해요", wallpaper: "벽 · 천장에 벽지를 붙여요",
  floor: "마루 · 장판을 깔아요", furniture: "주방 · 붙박이장 · 신발장을 설치해요", middoor: "현관 중문을 달아요", light: "조명 · 스위치 · 콘센트를 달아요", finish: "도어록을 달고 마무리해요",
};
function blockWhat(b: Block) {
  if (b.kind === "dry") return "창문을 닫고 벽지를 말려요";
  if (b.kind === "clean") return "공사 먼지를 치워요";
  return TRADE_DO[CAT_OF_TRADE[b.trade] || b.trade] || "";
}
const view = { sched: "list" as "list" | "bars" };

/** 주 묶음: 블록 시작일을 그 주 월요일로 묶는다 (v6 weekList, 보이기용 날짜 글. 블록 날짜는 API 그대로) */
function weeksOf(p: Plan) {
  const day = (s: string) => new Date(s + "T00:00:00Z");
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const add = (s: string, n: number) => {
    const d = day(s);
    d.setUTCDate(d.getUTCDate() + n);
    return iso(d);
  };
  const monday = (s: string) => add(s, -((day(s).getUTCDay() + 6) % 7));
  const first = monday(p.blocks[0].start), groups = new Map<string, Block[]>();
  for (const b of p.blocks) {
    const w = monday(b.start);
    if (!groups.has(w)) groups.set(w, []);
    groups.get(w)!.push(b);
  }
  return [...groups].map(([w, bs]) => ({ n: Math.round((day(w).getTime() - day(first).getTime()) / (7 * 864e5)) + 1, from: w, to: add(w, 6), bs }));
}

function WeekList({ p }: { p: Plan }) {
  const [all, setAll] = useState(false);
  const SHOW = 2, ws = p.blocks.length ? weeksOf(p) : [];
  const list = (
    <ol className="wk">
      {ws.map((w, gi) => (
        <li key={w.from} className="wk-g" hidden={!all && gi >= SHOW}>
          <h5>
            {`${w.n}주차`}
            <small>{`${mdw(w.from)} ~ ${mdw(w.to)}`}</small>
          </h5>
          <ul>
            {w.bs.map((b) => (
              <li key={b.trade + b.start} className={"wk-i" + (b.kind !== "work" ? " soft" : "")}>
                <i className="wk-dot" style={{ background: TCOLOR(b.trade || b.kind) }} aria-hidden="true" />
                <div>
                  <div className="wk-top">
                    <b>{b.ko}</b>
                    <span className="num">{b.start === b.end ? mdw(b.start) : `${mdw(b.start)} ~ ${mdw(b.end)}`}</span>
                  </div>
                  <p>{(b.kind === "work" && b.days ? `${b.days}일 · ` : "") + blockWhat(b)}</p>
                </div>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
  if (ws.length <= SHOW) return list;
  return (
    <div className="wk-box">
      {list}
      {all ? null : (
        <button type="button" className="btn btn-sm wk-more" onClick={() => setAll(true)}>
          {`나머지 ${ws.length - SHOW}주 보기`}
        </button>
      )}
    </div>
  );
}

function BarsEl({ p, mini }: { p: Plan; mini: boolean }) {
  const days = p.days, W = mini ? 30 : 36, NAME = mini ? 84 : 120;
  const tall = `1 / ${p.blocks.length + 2}`;
  return (
    <div>
      <div className="sb" role="region" tabIndex={0} aria-label="공정표 막대, 옆으로 넘겨 볼 수 있어요. 같은 내용은 주별 목록에 있어요">
        <div
          className="sb-grid num"
          aria-hidden="true"
          style={{ gridTemplateColumns: `${NAME}px repeat(${days.length}, ${W}px)`, gridTemplateRows: `40px repeat(${p.blocks.length}, 44px)`, width: `${NAME + days.length * W}px` }}
        >
          {days.map((d, i) => (d.off ? <span key={"o" + d.date} className="sb-off" style={{ gridColumn: i + 2, gridRow: tall }} title={d.holiday || "쉬는 날"} /> : null))}
          <span className="sb-name sb-corner" style={{ gridRow: 1 }}>{`${+days[0]?.date.slice(5, 7)}월~`}</span>
          {days.map((d, i) => {
            const dd = +d.date.slice(8);
            return (
              <span key={"h" + d.date} className={"sb-head" + (d.off ? " off" : "")} style={{ gridColumn: i + 2 }}>
                <b>{dd === 1 && i > 0 ? `${+d.date.slice(5, 7)}.1` : String(dd)}</b>
                {wdOf(d.date)}
              </span>
            );
          })}
          {p.blocks.map((b, r) => {
            const s = days.findIndex((d) => d.date === b.start), e = days.findIndex((d) => d.date === b.end), n = e - s + 1;
            return [
              <span key={"n" + r} className="sb-name" style={{ gridRow: r + 2 }}>
                <b>{b.ko}</b>
                <small>{b.kind === "work" && b.days ? `${b.days}일` : b.kind === "dry" ? "말리기" : ""}</small>
              </span>,
              <span
                key={"b" + r}
                className={"sb-bar g-" + b.state + (b.kind !== "work" ? " soft" : "")}
                style={{ gridRow: r + 2, gridColumn: `${s + 2} / span ${n}`, background: TCOLOR(b.trade || b.kind) }}
                title={`${b.ko} ${b.start} ~ ${b.end}`}
              >
                {n >= 3 ? `${md0(b.start)}~${md0(b.end)}` : ""}
              </span>,
            ];
          })}
        </div>
      </div>
      <ul className="sb-legend" aria-hidden="true">
        <li><i className="k-off" />쉬는 날 · 공휴일</li>
        <li><i className="k-soft" />말리기 · 청소</li>
        <li>옆으로 넘겨 보세요</li>
      </ul>
    </div>
  );
}

function SchedView({ p }: { p: Plan }) {
  const [v, setV] = useState(view.sched);
  return (
    <div className="sv-wrap">
      <div className="seg" role="group" aria-label="공정표 보기">
        {([["list", "주별 목록"], ["bars", "막대로 보기"]] as const).map(([k, l]) => (
          <button
            key={k}
            type="button"
            data-v={k}
            aria-pressed={v === k}
            onClick={() => {
              view.sched = k;
              setV(k);
            }}
          >
            {l}
          </button>
        ))}
      </div>
      <div className="sv">{v === "list" ? <WeekList p={p} /> : <BarsEl p={p} mini />}</div>
    </div>
  );
}

/** 공정표 그림 (v6 ganttEl 최종판): 대화 카드는 주별 목록 / 막대, 문서는 막대 */
export function GanttEl({ p, mini }: { p: Plan; mini: boolean }) {
  return mini ? <SchedView p={p} /> : <BarsEl p={p} mini={false} />;
}

/* ---------- 공정표 문서 ---------- */
export function PlanDocBody() {
  const [p, setP] = useState<Plan | null>((V3.plan as Plan | null) ?? null);
  const [err, setErr] = useState("");
  const reload = async () => {
    try {
      setP(await loadPlan());
      setErr("");
    } catch (e) {
      setErr(errorText(e));
    }
  };
  useEffect(() => {
    reload();
  }, []);
  if (!p) return <p className="muted">{err || "공정표를 계산하는 중이에요…"}</p>;
  return (
    <>
      {err ? <p className="warn-line">{err}</p> : null}
      <PlanDocEl p={p} reload={reload} />
    </>
  );
}

function PlanDocEl({ p, reload }: { p: Plan; reload: () => void }) {
  const vendor = V3.role === "vendor";
  return (
    <div>
      <div className="doc-opts">
        <label className="chk">
          <input
            type="checkbox"
            defaultChecked={V3.cons.weekendWork}
            onChange={(e) => {
              V3.cons.weekendWork = e.target.checked;
              reload();
            }}
          />
          주말에도 공사
        </label>
        <div className="df8-lab">
          <span id="c8-end-l">끝낼 날</span>
          <DateField
            id="c8-end"
            labelId="c8-end-l"
            label="끝낼 날"
            compact
            value={V3.cons.endBy}
            onChange={(v) => {
              V3.cons.endBy = v;
              reload();
            }}
          />
        </div>
        <div className="df8-lab">
          <span id="c8-start-l">시작 가능</span>
          <DateField
            id="c8-start"
            labelId="c8-start-l"
            label="시작 가능"
            compact
            value={V3.cons.startAfter}
            onChange={(v) => {
              V3.cons.startAfter = v;
              reload();
            }}
          />
        </div>
      </div>
      <GanttEl p={p} mini={false} />
      <p className="muted">도배 뒤 2일은 창문을 닫고 말려요.</p>
      {p.warn.length ? <p className="warn-line">{p.warn.join(" · ")}</p> : null}
      <h4 className="doc-sec">{vendor ? "업체: 공사 날짜 내기 · 바꾸기" : "공정별 날짜"}</h4>
      <div className="date-cards">
        {p.trades.map((t) => (vendor ? <VendorDateCard key={t.trade} t={t} p={p} reload={reload} /> : <CustomerDateCard key={t.trade} t={t} p={p} reload={reload} />))}
      </div>
      {V3.log.length ? (
        <details className="srcs">
          <summary>{`기록 ${V3.log.length}개`}</summary>
          <ol>
            {V3.log.map((x, i) => <li key={i}>{x}</li>)}
          </ol>
        </details>
      ) : null}
      <h4 className="doc-sec">날짜별 할 일</h4>
      <div className="tbl">
        <table>
          <thead>
            <tr>
              <th>날짜</th>
              <th>할 일</th>
            </tr>
          </thead>
          <tbody>
            {p.days.map((d) => (
              <tr key={d.date} className={d.off ? "dim" : ""}>
                <td className="num">{mdw(d.date)}</td>
                <td>
                  {d.items.length
                    ? d.items.map((it, i) => (
                        <div key={i}>
                          <b>{it.ko}</b> {it.todo.join(" · ")}
                        </div>
                      ))
                    : d.off
                      ? d.holiday
                        ? `휴일 · ${d.holiday}`
                        : "쉬는 날"
                      : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VendorDateCard({ t, p, reload }: { t: PlanTrade; p: Plan; reload: () => void }) {
  const b = p.blocks.find((x) => x.trade === t.trade);
  const rid = "vd8-" + t.trade;
  const prop = props()[t.trade], acc = accepted()[t.trade];
  const [rng, setRng] = useState({ from: prop?.start || b?.start || "", to: prop?.end || b?.end || "" });
  const [crew, setCrew] = useState(String(t.crew));
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState("");
  const send = async () => {
    const st = rng.from, en = rng.to;
    let r: Trial | null | undefined;
    try {
      r = (await fetchPlan({ trade: t.trade, start: st, end: en })).trial;
    } catch (e) {
      return setMsg(errorText(e));
    }
    if (r?.error) return setMsg(r.error);
    if (acc && !reason.trim()) return setMsg("날짜를 바꾸는 이유를 적어 주세요. 고객에게 보여요.");
    props()[t.trade] = { start: st, end: en, crew: +crew || t.crew, reason: reason.trim() || null, change: !!acc };
    log(`업체가 ${t.ko} 날짜를 ${acc ? "바꾸자고 했어요" : "냈어요"} (${st} ~ ${en})`);
    if (r?.short) toast(`필요한 기간보다 짧아요. 일하는 날 ${r.work_days}일 · 필요한 기간 ${r.need}일이에요. 낼 수는 있어요.`);
    setMsg("");
    reload();
  };
  return (
    <div className="date-card">
      <b>{t.ko}</b>
      <span className="muted">{acc ? `수락한 날짜 ${acc.start} ~ ${acc.end}` : prop ? "낸 날짜 · 고객 수락 기다림" : `확정 + 2일 18:00까지 날짜를 내요 · 필요한 기간 약 ${t.need}일`}</span>
      <div className="fld">
        <span id={rid + "-l"}>공사 날짜 (시작 ~ 끝)</span>
        <DateField id={rid} labelId={rid + "-l"} label={`${t.ko} 공사 날짜`} range notToday value={rng} onChange={setRng} />
      </div>
      <div className="form-grid">
        <Fld label="작업 인원(명)">
          <input className="inp sm" type="number" min="1" max="20" aria-label="작업 인원" value={crew} onChange={(e) => setCrew(e.target.value)} />
        </Fld>
        {acc ? (
          <Fld label="바꾸는 이유">
            <input className="inp" placeholder="바꾸는 이유(고객에게 보여요)" aria-label="바꾸는 이유" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Fld>
        ) : null}
      </div>
      <button type="button" className="btn btn-pri btn-sm" onClick={send}>
        {acc ? "날짜 바꾸기 요청" : prop ? "날짜 다시 내기" : "공사 날짜 내기"}
      </button>
      <p className="muted">{msg}</p>
    </div>
  );
}

function CustomerDateCard({ t, p, reload }: { t: PlanTrade; p: Plan; reload: () => void }) {
  const prop = props()[t.trade], acc = accepted()[t.trade];
  if (!prop || (acc && !prop.change))
    return (
      <div className="date-card">
        <b>{t.ko}</b>
        <span className="muted">{acc ? `날짜 수락함 · ${acc.start} ~ ${acc.end}` : "업체가 날짜를 정하고 있어요(예상 자리)"}</span>
      </div>
    );
  return <CustomerDateMine t={t} p={p} reload={reload} />;
}

/** 업체가 날짜를 냈을 때: 이 날짜로 하면 뒤 공정이 어떻게 밀리는지 · 겹치는지 미리 본다(API plan trial) */
function CustomerDateMine({ t, p, reload }: { t: PlanTrade; p: Plan; reload: () => void }) {
  const prop = props()[t.trade];
  const [trial, setTrial] = useState<Trial | null>(null);
  useEffect(() => {
    let live = true;
    fetchPlan({ trade: t.trade, start: prop.start, end: prop.end })
      .then((x) => live && setTrial(x.trial ?? null))
      .catch(() => live && setTrial(null));
    return () => {
      live = false;
    };
  }, [p, t.trade, prop.start, prop.end]);
  const moved = trial?.moved ?? [];
  const clash = !!trial?.clash;
  return (
    <div className="date-card mine">
      <b>{t.ko}</b>
      <span>{`${prop.change ? "바꿀 날짜 옴" : "날짜 옴"} · ${prop.start} ~ ${prop.end} · ${prop.crew}명`}</span>
      {prop.reason ? <span className="muted">{`업체가 적은 이유: ${prop.reason}`}</span> : null}
      {moved.length ? <span className="warn-line">{`이 날짜로 하면 ${moved.map((b) => `${b.ko} ${b.start}부터`).join(" · ")}로 밀려요 · 해당 업체 재확인이 필요해요`}</span> : null}
      <div className="row">
        <button
          type="button"
          className="btn btn-pri btn-sm"
          disabled={!trial}
          onClick={() => {
            if (clash) return toast("겹치는 날이 있어 수락할 수 없어요.");
            accepted()[t.trade] = { start: prop.start, end: prop.end };
            delete props()[t.trade];
            log(`고객이 ${t.ko} ${prop.change ? "새 " : ""}날짜를 수락했어요 (${prop.start} ~ ${prop.end})`);
            for (const b of moved)
              if (accepted()[b.trade]) {
                log(`${b.ko} 업체에 날짜 재확인을 요청했어요`);
                delete accepted()[b.trade];
              }
            reload();
          }}
        >
          {prop.change ? "새 날짜 수락하기" : "이 날짜로 수락하기"}
        </button>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => {
            log(`고객이 ${t.ko} 다른 날짜를 요청했어요 · 업체 답 기한 ${p.due_next ?? "다음 날 18:00"}`);
            delete props()[t.trade];
            reload();
            toast("다른 날짜를 요청했어요 · 업체가 다음 날 18:00까지 답해요");
          }}
        >
          다른 날짜 요청
        </button>
      </div>
    </div>
  );
}
