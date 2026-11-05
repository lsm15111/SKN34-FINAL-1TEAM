"use client";
// 공사 중 추가 금액 (시안 WPlanDone '공사 중 추가 금액'). 확정 공정표 · 공사 날짜 화면이 같이 쓴다.
// 공정마다 업체가 알린 추가 금액(한 일 · 이유 · 금액 · 사진)을 보이고, 확인 기다림이면 '확인했어요' · '이야기하고 싶어요'를 확인 창 뒤
// POST /projects/{id}/deals/{deal}/extras/{extra}/ack로 한 번만 답한다. 금액 · 합계는 API(계산 엔진) 값이고, 공급가 · 부가세는 합계 칸에서만 나눈다.
// 이미 답했으면(409) 서버 문장을 보이고 화면을 새로 읽는다. 믿집은 결제를 하지 않는다.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import { Check, Close } from "@/components/vendors/icons";
import { iGa } from "@/components/vendors/text";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { dateSeoul, md, won } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import d from "@/components/vendors/dialog.module.css";
import s from "./plan.module.css";

type Group = Schemas["TradeExtrasOut"];
type Extra = Schemas["ExtraOut"];
type Ack = Schemas["AckIn"]["ack"];

/** 확정마다 확정 금액(부가세 포함) · 전화 걸기 번호(숫자만, 연락처가 보일 때) */
export type ExtraDeal = { total: number | null; tel: string | null };

type Props = {
  projectId: string;
  groups: Group[];
  deals: Record<string, ExtraDeal>;
  /** 공정 이름을 붙인다 (공정이 둘 이상인 확정 공정표) */
  multi: boolean;
};

const ACK_TEXT: Record<Extra["ack"], string> = { pending: "확인 기다림", ok: "확인했어요", talk: "업체와 이야기 중" };
const tail = (vatMode: string) => (vatMode === "exempt" ? "면세" : "부가세 포함");
const madeOn = (x: Extra) => md(dateSeoul(x.created_at));

function Photos({ x, src }: { x: Extra; src: (fileId: string) => string }) {
  if (!x.photos.length) return null;
  return (
    <ul className={s.exPhotos} aria-label={`${x.title} 사진 ${x.photos.length}장`}>
      {x.photos.map((p, i) => (
        <li key={p.file_id}>
          <a href={src(p.file_id)} target="_blank" rel="noopener">
            <img className={s.pic} src={src(p.file_id)} alt={`${x.title} 사진 ${i + 1}`} loading="lazy" width={96} height={96} />
            <span className="mj-sr">, 새 창</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

/** 합계 칸: 확인했어요 · 확인 기다림 · 업체와 이야기 중 (공급가 · 부가세를 나눠 보이는 곳은 여기 하나) */
function Totals({ g }: { g: Group }) {
  // 0원인 칸은 숨기고, 낼 금액만 보인다
  const rows = ([["확인했어요", g.ok], ["확인 기다림", g.pending], ["업체와 이야기 중", g.talk]] as [string, Schemas["MoneyOut"]][]).filter(([, m]) => m.total > 0);
  if (!rows.length) return null;
  return (
    <dl className={`mj-num ${s.exSum}`} aria-label={`${tradeLabel(g.trade)} 추가 금액 합계`}>
      {rows.map(([t, m]) => (
        <div key={t}>
          <dt>{t}</dt>
          <dd><b className={s.exBig}>{won(m.total)}</b></dd>
        </div>
      ))}
    </dl>
  );
}

export function PlanExtras({ projectId, groups, deals, multi }: Props) {
  const router = useRouter();
  const dlg = useRef<HTMLDialogElement>(null);
  const noRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const doneRef = useRef<HTMLParagraphElement>(null);
  const [seen, setSeen] = useState(groups);
  const [local, setLocal] = useState<Record<string, Group>>({}); // 답한 뒤 응답 값 (화면을 새로 읽을 때까지)
  const [asking, setAsking] = useState<{ g: Group; x: Extra; ack: Ack } | null>(null);
  const [busy, setBusy] = useState("");
  const [done, setDone] = useState<{ deal: string; text: string } | null>(null);
  const [err, setErr] = useState<{ deal: string; text: string; warn: boolean } | null>(null);

  // 화면을 새로 그리면(router.refresh) 새 값으로 바꾼다
  if (seen !== groups) {
    setSeen(groups);
    setLocal({});
  }

  useEffect(() => { if (done) doneRef.current?.focus(); }, [done]);

  // 확인 창은 내용이 그려진 뒤 연다('아니요'에 초점)
  useEffect(() => {
    if (!asking) return;
    dlg.current?.showModal();
    noRef.current?.focus();
  }, [asking]);

  const shown = groups.map((g) => local[g.deal_id] ?? g).filter((g) => g.items.length);
  if (!shown.length) return null;

  function ask(g: Group, x: Extra, ack: Ack, btn: HTMLButtonElement) {
    if (busy) return;
    opener.current = btn;
    setErr(null);
    setAsking({ g, x, ack });
  }

  async function answer(g: Group, x: Extra, ack: Ack) {
    if (busy) return;
    setBusy(`${x.id}|${ack}`);
    setErr(null);
    setDone(null);
    try {
      const out = await call<Group>("POST", `/projects/${projectId}/deals/${g.deal_id}/extras/${x.id}/ack`, { ack });
      setLocal((m) => ({ ...m, [g.deal_id]: out }));
      setDone({
        deal: g.deal_id,
        text: ack === "ok"
          ? `‘${x.title}’ 추가 금액을 확인했다고 ${g.vendor_name}에 알렸어요.`
          : `‘${x.title}’ 추가 금액을 이야기하고 싶다고 ${g.vendor_name}에 알렸어요. 금액은 업체와 직접 정해요.`,
      });
      router.refresh();
    } catch (e) {
      // 이미 답함(409) · 다시 고른 공사(404): 서버 문장을 보이고 새로 읽는다
      setErr({ deal: g.deal_id, text: errorText(e), warn: e instanceof ApiError && e.status === 409 });
      if (!(e instanceof ApiError) || e.status !== 0) router.refresh();
    }
    setBusy("");
  }

  return (
    <section id="extras" aria-labelledby="ex-t" className={s.extras}>
      <div className={s.exHead}>
        <h2 id="ex-t" className="mj-h2">공사 중 추가 금액</h2>
        <p className="mj-small">업체가 알린 추가 금액이에요. 낼지는 업체와 직접 정해요.</p>
      </div>

      {shown.map((g) => {
        const deal = deals[g.deal_id] ?? { total: null, tel: null };
        const src = (x: Extra) => (fileId: string) => `/api/projects/${projectId}/deals/${g.deal_id}/extras/${x.id}/files/${fileId}`;
        const waiting = g.items.filter((x) => x.ack === "pending");
        const answered = g.items.filter((x) => x.ack !== "pending");
        const gid = `ex-g-${g.trade}`;
        return (
          <div key={g.deal_id} className={s.exGroup} role={multi ? "group" : undefined} aria-labelledby={multi ? gid : undefined}>
            {multi ? <h3 id={gid} className="mj-h3">{tradeLabel(g.trade)} · {g.vendor_name}</h3> : null}
            {done?.deal === g.deal_id ? (
              <p ref={doneRef} tabIndex={-1} role="status" className={`mj-st mj-st-ok ${s.stBig} ${s.focusT}`}><Check size={16} />{done.text}</p>
            ) : null}
            {err?.deal === g.deal_id ? (
              err.warn ? <p role="alert" className="mj-notice mj-notice-warn"><span><b>{err.text}</b> 다시 읽은 목록을 확인해 주세요.</span></p>
                : <FieldError id={`ex-e-${g.trade}`} alert>{err.text}</FieldError>
            ) : null}

            {waiting.map((x) => {
              const hid = `ex-${x.id}`;
              return (
                <div key={x.id} className={s.box} role="group" aria-labelledby={hid}>
                  <p id={hid} className={`mj-num ${s.boxH}`}>{iGa(g.vendor_name)} 추가 금액을 알렸어요 <span className={s.exWhen}>· {madeOn(x)}</span></p>
                  <dl className={`mj-num ${s.exDl}`}>
                    <dt>무엇</dt><dd>{x.title}</dd>
                    <dt>이유</dt><dd><span className={s.exText}>{x.reason}</span> <span className="mj-small">{iGa(g.vendor_name)} 적은 글</span></dd>
                    <dt>금액</dt><dd><b>{won(x.total)}</b> <span className="mj-small">{tail(x.vat_mode)}</span></dd>
                    {x.photos.length ? <><dt>사진</dt><dd><Photos x={x} src={src(x)} /></dd></> : null}
                  </dl>
                  <p className="mj-small mj-num">{deal.total != null ? `확정 금액 ${won(deal.total)}은 그대로이고, ` : ""}추가 금액은 확정 금액에 넣지 않아요.</p>
                  <div className={s.acts}>
                    <button type="button" className={`mj-btn mj-btn-pri ${busy === `${x.id}|ok` ? s.busy : ""}`} aria-disabled={busy ? true : undefined} aria-haspopup="dialog"
                      aria-label={`${x.title} 추가 금액 확인했어요`} onClick={(e) => ask(g, x, "ok", e.currentTarget)}>
                      {busy === `${x.id}|ok` ? "보내는 중이에요…" : "확인했어요"}
                    </button>
                    <button type="button" className={`mj-btn mj-btn-sec ${busy === `${x.id}|talk` ? s.busy : ""}`} aria-disabled={busy ? true : undefined} aria-haspopup="dialog"
                      aria-label={`${x.title} 추가 금액 이야기하고 싶어요`} onClick={(e) => ask(g, x, "talk", e.currentTarget)}>
                      {busy === `${x.id}|talk` ? "보내는 중이에요…" : "이야기하고 싶어요"}
                    </button>
                  </div>
                </div>
              );
            })}

            {answered.length ? (
              <ul className={s.exDone} aria-label={`${tradeLabel(g.trade)} 답한 추가 금액 ${answered.length}건`}>
                {answered.map((x) => (
                  <li key={x.id}>
                    <div className={s.exTop}>
                      <p className={s.exTitle}><b>{x.title}</b></p>
                      <p className={`mj-st ${x.ack === "ok" ? "mj-st-ok" : "mj-st-now"}`}>{x.ack === "ok" ? <Check /> : null}{ACK_TEXT[x.ack]}</p>
                    </div>
                    <p className="mj-num"><b>{won(x.total)}</b> · {madeOn(x)}</p>
                    <p className={`mj-small ${s.exText}`}>{x.reason}</p>
                    <Photos x={x} src={src(x)} />
                  </li>
                ))}
              </ul>
            ) : null}

            <Totals g={g} />
          </div>
        );
      })}
      <p className="mj-sr" role="status">{busy ? "보내는 중이에요" : ""}</p>

      <dialog ref={dlg} className={d.dlg} aria-labelledby="ex-q" onClose={() => { setAsking(null); opener.current?.focus(); }}>
        <button type="button" className={d.x} aria-label="닫기" onClick={() => dlg.current?.close()}><Close /></button>
        {asking ? (
          <>
            <h2 id="ex-q" className="mj-h3">{asking.ack === "ok" ? `‘${asking.x.title}’ 추가 금액을 확인했다고 알릴까요?` : `‘${asking.x.title}’ 추가 금액을 이야기하고 싶다고 알릴까요?`}</h2>
            <p className="mj-num">{won(asking.x.total)} · {tail(asking.x.vat_mode)}</p>
            <p>{asking.ack === "ok"
              ? `${asking.g.vendor_name}에 알림이 가요. 한 번 답하면 바꿀 수 없어요. 믿집은 결제를 하지 않아요.`
              : `${asking.g.vendor_name}에 알림이 가고, 이 줄은 ‘업체와 이야기 중’으로 바뀌어요. 한 번 답하면 바꿀 수 없어요. 금액은 업체와 직접 정해요.`}</p>
            <div className={d.btns}>
              <button type="button" className="mj-btn mj-btn-pri" onClick={() => { const a = asking; dlg.current?.close(); void answer(a.g, a.x, a.ack); }}>
                {asking.ack === "ok" ? "네, 확인했어요" : "네, 알릴게요"}
              </button>
              <button ref={noRef} type="button" className="mj-btn mj-btn-sec" onClick={() => dlg.current?.close()}>아니요</button>
            </div>
          </>
        ) : <h2 id="ex-q" className="mj-sr">추가 금액에 답하기</h2>}
      </dialog>
    </section>
  );
}
