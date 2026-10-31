"use client";
// 가견적 후보 업체 한 곳: 앱 · 외부 배지, 공정 · 지역, 왜 이 업체(도우미 설명, 있을 때만), 비용 · 출처 · 모은 날, 받는 길 하나.
// 받는 길: 앱 업체는 화면 안 확인 뒤 요청 · 견적 창구는 새 탭 + 요청문 복사 · 전화는 번호 + 통화 체크리스트
// · 참고는 링크만 · 대신 연락은 동의 뒤 요청. 비용은 API 글을 그대로 보이고 화면에서 계산하지 않는다.
import { useEffect, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { TRADE_LABEL, type TradeKey } from "@/lib/types";
import { dateSeoul, ymd } from "@/lib/format";
import { CopyButton } from "./CopyButton";
import s from "./CandidateCard.module.css";

type Candidate = Schemas["CandidateOut"];
type Props = {
  c: Candidate;
  trade: string;
  projectId: string;
  facts: string[];
  /** 이 화면에서 방금 보낸 요청의 상태 글 (지금 공정) */
  sent?: string;
  onSent: (label: string) => void;
};

const tradeName = (t: string) => TRADE_LABEL[t as TradeKey] ?? t;
const COST_BADGE: Record<Candidate["cost"]["kind"], string> = { free: "mj-b-ok", vendor_fee: "mj-b-sep", unknown: "mj-b-wait" };

/** 업체가 공개한 주소 중 http · https만 연다 */
function safeHref(u?: string | null) {
  if (!u) return null;
  try {
    const x = new URL(u);
    return x.protocol === "https:" || x.protocol === "http:" ? x.href : null;
  } catch {
    return null;
  }
}

export function CandidateCard({ c, trade, projectId, facts, sent, onSent }: Props) {
  const done = sent ?? c.requests.find((r) => r.trade === trade)?.label;
  // 지금 공정의 요청 상태는 받는 길 칸이 보여서, 배지에는 다른 공정 것만 둔다
  const inRoute = c.route === "app_request" || c.route === "proxy";
  const chips = c.requests.filter((r) => !(inRoute && r.trade === trade));
  const day = c.source.fetched_at ? ymd(dateSeoul(c.source.fetched_at)) : null;

  return (
    <li className={s.card}>
      <div className={s.head}>
        <h3 className={s.name}>{c.name}</h3>
        <span className={`mj-badge ${c.kind === "app" ? "mj-b-ok" : "mj-b-wait"}`}>{c.kind === "app" ? "믿집 업체" : "외부 업체"}</span>
      </div>
      <p className={s.meta}>
        {c.trades.map(tradeName).join(" · ")} · {c.region}
        {c.near ? <span className="mj-badge mj-b-in">같은 지역</span> : null}
      </p>
      {c.why ? <p className={s.why}><span className="mj-src">도우미 설명</span>{c.why}</p> : null}

      <dl className={s.info}>
        <div><dt>가견적 비용</dt><dd><span className={`mj-badge ${COST_BADGE[c.cost.kind]}`}>{c.cost.label}</span></dd></div>
        {c.registration ? <div><dt>등록 정보</dt><dd>{c.registration}</dd></div> : null}
        {c.biz_status ? <div><dt>사업자 상태</dt><dd>{c.biz_status}</dd></div> : null}
        <div><dt>출처</dt><dd>{c.source.label}{day ? ` · ${c.kind === "app" ? "승인한 날" : "모은 날"} ${day}` : ""}</dd></div>
      </dl>
      {chips.length ? (
        <ul className={s.states} aria-label="보낸 요청">
          {chips.map((r) => <li key={r.trade} className="mj-badge mj-b-dark">{tradeName(r.trade)} · {r.label}</li>)}
        </ul>
      ) : null}

      <div className={s.route}>
        <p className={s.routeH}><span className="mj-small">받는 길</span> <b>{c.route_label}</b></p>
        {c.route === "app_request" ? <AppRequest c={c} trade={trade} projectId={projectId} done={done} onSent={onSent} /> : null}
        {c.route === "proxy" ? <ProxyRequest c={c} trade={trade} projectId={projectId} facts={facts} done={done} onSent={onSent} /> : null}
        {c.route === "link" ? <LinkRoute c={c} facts={facts} /> : null}
        {c.route === "phone" ? <PhoneRoute c={c} /> : null}
        {c.route === "reference" ? <Links c={c} empty="등록 정보만 있어요. 이 업체에 물어볼 길은 아직 없어요." /> : null}
      </div>
      {c.proxy_off ? <p className={`mj-notice ${s.off}`}><span>이 업체는 믿집이 대신 연락할 수 있지만, 대신 연락은 법 검토가 끝나면 열려요.</span></p> : null}
      {c.route !== "reference" ? <Links c={c} /> : null}
    </li>
  );
}

/** 포트폴리오 · 홈페이지 · 카카오맵 (새 탭) */
function Links({ c, empty }: { c: Candidate; empty?: string }) {
  const many = c.links.portfolio.length > 1;
  const items = [
    ...c.links.portfolio.map((u, i) => ({ href: safeHref(u), label: many ? `포트폴리오 ${i + 1}` : "포트폴리오" })),
    { href: safeHref(c.links.homepage), label: "홈페이지" },
    { href: safeHref(c.links.place), label: "카카오맵" },
  ].filter((x): x is { href: string; label: string } => !!x.href);
  if (!items.length) return empty ? <p className="mj-small">{empty}</p> : null;
  return (
    <ul className={s.links}>
      {items.map((x) => (
        <li key={x.label}><a href={x.href} target="_blank" rel="noopener noreferrer">{x.label}<span className="mj-sr"> · {c.name} (새 탭)</span></a></li>
      ))}
    </ul>
  );
}

/** 앱 업체: 화면 안에서 한 번 더 확인하고 보낸다 */
function AppRequest({ c, trade, projectId, done, onSent }: { c: Candidate; trade: string; projectId: string; done?: string; onSent: (label: string) => void }) {
  const router = useRouter();
  const uid = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const msg = useRef<HTMLTextAreaElement>(null);
  const ask = useRef<HTMLParagraphElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const result = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (open) (done ? result : ask).current?.focus(); }, [open, done]); // 보낸 뒤에는 결과 글로

  if (done) return <p ref={result} tabIndex={-1} className={s.done} role="status"><span className="mj-badge mj-b-ok">{done}</span> 이 업체에 {tradeName(trade)} 가견적을 요청했어요.</p>;

  async function send() {
    setBusy(true);
    setErr("");
    try {
      await call("POST", `/projects/${projectId}/quote-requests`, { trade, vendor_id: c.id, message: msg.current?.value.trim() ?? "" });
      onSent("요청했어요");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) onSent("이미 요청했어요");
      else setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  function cancel() {
    setOpen(false);
    setErr("");
    setTimeout(() => opener.current?.focus(), 0);
  }

  if (!open) {
    return (
      <div className={s.actions}>
        <button ref={opener} type="button" className="mj-btn mj-btn-pri" onClick={() => setOpen(true)}>가견적 요청 보내기<span className="mj-sr"> · {c.name}</span></button>
      </div>
    );
  }
  return (
    <div className={s.confirm} role="group" aria-labelledby={`${uid}-q`}>
      <p id={`${uid}-q`} ref={ask} tabIndex={-1} className={s.confirmQ}>{c.name}에 {tradeName(trade)} 가견적을 요청할까요?</p>
      <p className="mj-small">업체에는 이 공정의 집 정보(지역 · 평수 · 시기 · 거주)와 남긴 말만 가요. 이름 · 연락처 · 동 · 호수는 보내지 않아요.</p>
      <div className="mj-field">
        <label className="mj-label" htmlFor={`${uid}-m`}>업체에 남길 말 <span className="mj-opt">(선택)</span></label>
        {c.draft ? <p id={`${uid}-h`} className="mj-hint">도우미가 쓴 초안이에요. 고쳐서 보내도 돼요.</p> : null}
        <textarea id={`${uid}-m`} ref={msg} className="mj-textarea" maxLength={1000} defaultValue={c.draft ?? ""} aria-describedby={c.draft ? `${uid}-h` : undefined} />
      </div>
      <div className="mj-btn-row">
        <button type="button" className="mj-btn mj-btn-pri" disabled={busy} onClick={send}>{busy ? "보내는 중…" : "요청 보내기"}</button>
        <button type="button" className="mj-btn mj-btn-sec" disabled={busy} onClick={cancel}>그만두기</button>
      </div>
      {err ? <p className="mj-error" role="alert">{err}</p> : null}
    </div>
  );
}

/** 외부 업체 대신 연락 (켜져 있을 때만 이 길이 온다): 보낼 글과 받는 업체에 동의해야 보낸다 */
function ProxyRequest({ c, trade, projectId, facts, done, onSent }: { c: Candidate; trade: string; projectId: string; facts: string[]; done?: string; onSent: (label: string) => void }) {
  const router = useRouter();
  const uid = useId();
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const body = useRef<HTMLTextAreaElement>(null);

  if (done) return <p className={s.done} role="status"><span className="mj-badge mj-b-ok">{done}</span> {notice}</p>;

  async function send() {
    const text = body.current?.value.trim() ?? "";
    if (text.length < 10) { setErr("업체에 보낼 글을 10자 이상 적어 주세요."); return; }
    setBusy(true);
    setErr("");
    try {
      const r = await call<Schemas["ContactRequestOut"]>("POST", "/contact-requests", { project_id: projectId, trade, vendor_id: c.id, body: text, consent: true });
      setNotice(r.notice);
      onSent("대신 요청했어요");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) onSent("이미 대신 요청했어요");
      else setErr(e instanceof ApiError && e.fields?.length ? e.fields[0].msg : errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={s.confirm}>
      <div className="mj-field">
        <label className="mj-label" htmlFor={`${uid}-b`}>믿집이 업체에 보낼 글</label>
        <p id={`${uid}-h`} className="mj-hint">10자 이상 800자까지 써요. 링크는 넣을 수 없어요. 업체가 동의해 준 연락처로만 보내요.</p>
        <textarea id={`${uid}-b`} ref={body} className="mj-textarea" maxLength={800} defaultValue={c.draft ?? facts.join("\n")} aria-describedby={`${uid}-h`} />
      </div>
      <label className="mj-choice">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span className="mj-choice-main"><span className="mj-choice-title">{c.name}에 위 글을 믿집이 대신 보내는 데 동의해요</span><span className="mj-choice-desc">이름 · 연락처는 보내지 않아요</span></span>
      </label>
      <div className="mj-btn-row">
        <button type="button" className="mj-btn mj-btn-pri" disabled={!agree || busy} onClick={send}>{busy ? "보내는 중…" : "대신 요청하기"}</button>
      </div>
      {err ? <p className="mj-error" role="alert">{err}</p> : null}
    </div>
  );
}

/** 공개 견적 창구: 새 탭으로 열고 요청문을 복사해 붙여 넣는다 */
function LinkRoute({ c, facts }: { c: Candidate; facts: string[] }) {
  const uid = useId();
  const [open, setOpen] = useState(false);
  const href = safeHref(c.links.quote);
  const text = c.draft ?? facts.join("\n");
  return (
    <>
      <div className={s.actions}>
        {href ? <a className="mj-btn mj-btn-pri" href={href} target="_blank" rel="noopener noreferrer">견적 문의 열기<span className="mj-sr"> · {c.name} (새 탭)</span></a> : null}
        <CopyButton text={text} label="요청문 복사" targetId={`${uid}-t`} onFail={() => setOpen(true)} />
      </div>
      <details className={`mj-fold ${s.text}`} open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>복사할 요청문 보기</summary>
        {c.draft ? null : <p className="mj-hint">도우미 초안이 없어서 집 정보만 복사해요.</p>}
        <textarea id={`${uid}-t`} className="mj-textarea" readOnly rows={6} value={text} aria-label="복사할 요청문" />
      </details>
      <p className="mj-tiny">업체 견적 창구가 새 탭에서 열려요. 복사한 요청문을 붙여 넣어 보내 주세요.</p>
    </>
  );
}

/** 공개 대표 전화: 번호는 글자로 보이고, 통화할 때 물어볼 것을 체크한다 */
function PhoneRoute({ c }: { c: Candidate }) {
  const uid = useId();
  return (
    <>
      <p className={s.phone}><span className="mj-small">사무실 번호</span> <b id={`${uid}-p`} className="mj-num">{c.phone}</b></p>
      <div className={s.actions}>
        <CopyButton text={c.phone ?? ""} label="번호 복사" targetId={`${uid}-p`} />
      </div>
      <p className="mj-tiny">공공 등록 정보에 나온 사무실 번호예요.</p>
      {c.draft ? (
        <div className={s.say}>
          <p className="mj-small"><span className="mj-src">도우미 초안</span>전화로 이렇게 말해 보세요</p>
          <p>{c.draft}</p>
        </div>
      ) : null}
      {c.checklist.length ? (
        <fieldset className={s.check}>
          <legend className={s.checkH}>통화할 때 물어볼 것</legend>
          {c.checklist.map((t) => (
            <label key={t} className={s.checkI}><input type="checkbox" /><span>{t}</span></label>
          ))}
        </fieldset>
      ) : null}
    </>
  );
}
