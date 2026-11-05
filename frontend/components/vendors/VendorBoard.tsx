"use client";
// 업체 고르기 목록 + 실측 요청에 담기 (시안 WVendors · WVendorsPanel). 담은 업체 · 남길 말은 이 기기 sessionStorage에 프로젝트 · 공정마다 둔다.
// 업체 이름을 누르면 같은 주소(/vendors/[vid])가 오른쪽 창으로 열린다. 창에서 담아도 이 목록에 바로 보인다(pick.ts).
// 금액 · 퍼센트는 API 값을 그대로 보인다. 금액은 부가세 포함이라 따로 적지 않는다. 담을 수 있는 수(slotsLeft)는 서버가 정한다(공정마다 3곳까지).
// 이 공정을 확정했으면(locked) 담기 · 요청 칸을 두지 않는다. 확정 · 다시 고르는 중 안내는 목록 위(head)에 화면이 그린다.
// 닫힌 줄은 shutKind로 나눈다: 확정이 살아 있을 때 다른 업체 확정은 '다른 업체로 정했어요', 그 밖은 '지난 실측 닫힘'(확정이 없으면 '다시 담기').
import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { CONTACT_LABEL, tradeLabel } from "@/lib/labels";
import { won } from "@/lib/format";
import { Check, Close, Picked, Plus, VisitState } from "./icons";
import { PICK_EVENT, SEND_EVENT, markFromList, readPick, writePick } from "./pick";
import { RequestDialog } from "./RequestDialog";
import { FAILED_TEXT, areasText, asMethod, declineText, feeText, isLive, shutKind, vsText, when, type Created, type VendorRow, type VTrade } from "./text";
import s from "./VendorBoard.module.css";

type Props = {
  /** 목록 위: 공정 탭 · 표준견적서 합계 (서버가 그린다) */
  head: ReactNode;
  projectId: string;
  trade: VTrade;
  areaName: string;
  slotsLeft: number;
  consentVer: string;
  vendors: VendorRow[];
  /** 닫힌 요청이 닫힌 때 (visit id → 시각, 실측 요청 목록에서) */
  closedAt: Record<string, string>;
  /** 이 공정을 이미 확정함: 담기 · 실측 요청을 막는다 */
  locked?: boolean;
};

/** 방금 보낸 결과. shared: 내 연락처를 보낸 업체가 있음(업체가 먼저 연락할 수 있다) */
type Sent = { ok: string[]; shared: boolean; failed: { name: string; code: string }[] };

function Estimate({ v }: { v: VendorRow }) {
  if (v.estimate_total == null) {
    return <p className={s.none}>가견적 없음</p>;
  }
  const vs = vsText(v.vs_standard, v.vs_direction);
  return (
    <>
      <p className={`mj-num ${s.total}`}>{won(v.estimate_total)}</p>
      {vs ? <p className={`mj-num ${s.vs}`}>{vs} {v.vs_direction === "same" ? null : <span aria-hidden="true">{v.vs_direction === "less" ? "▼" : "▲"}</span>}</p> : null}
    </>
  );
}

export function VendorBoard({ head, projectId, trade, areaName, slotsLeft, consentVer, vendors, closedAt, locked = false }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [ids, setIds] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [onlyEst, setOnlyEst] = useState(false);
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState<Sent | null>(null);
  const sentRef = useRef<HTMLDivElement>(null);
  const tName = tradeLabel(trade);
  const base = `/projects/${projectId}`;

  useEffect(() => {
    const p = readPick(projectId, trade);
    setIds(p.ids);
    setMsg(p.msg);
  }, [projectId, trade]);
  useEffect(() => { if (sent) sentRef.current?.focus(); }, [sent]);
  // 오른쪽 창에서 담거나 뺐을 때
  useEffect(() => {
    const read = () => setIds(readPick(projectId, trade).ids);
    window.addEventListener(PICK_EVENT, read);
    return () => window.removeEventListener(PICK_EVENT, read);
  }, [projectId, trade]);
  // 오른쪽 창에서 '실측 요청 보내기'를 눌렀을 때: 담은 업체가 있으면 확인 창을 연다
  useEffect(() => {
    const ask = () => { if (readPick(projectId, trade).ids.length) { setSent(null); setOpen(true); } };
    window.addEventListener(SEND_EVENT, ask);
    return () => window.removeEventListener(SEND_EVENT, ask);
  }, [projectId, trade]);
  // 오른쪽 창으로 보고 있는 업체 (주소 /vendors/[vid]). 창을 닫으면 눌렀던 업체 이름으로 돌아간다
  const viewing = pathname.match(/\/vendors\/([^/]+)$/)?.[1] ?? null;
  const lastView = useRef<string | null>(null);
  useEffect(() => {
    if (!viewing && lastView.current) document.getElementById(`vn-${lastView.current}`)?.focus();
    lastView.current = viewing;
  }, [viewing]);

  const byId = new Map(vendors.map((v) => [v.vendor_id, v]));
  // 담은 것: 목록에 있고 아직 열린 요청이 없는 업체만, 남은 칸까지
  const picked = ids.filter((id) => { const v = byId.get(id); return v && !(v.visit && isLive(v.visit.status)); }).slice(0, Math.max(0, slotsLeft));
  const room = Math.max(0, slotsLeft - picked.length);
  const shown = onlyEst ? vendors.filter((v) => v.estimate_total != null) : vendors;

  function save(next: string[], nextMsg = msg) {
    setIds(next);
    writePick(projectId, trade, { ids: next, msg: nextMsg });
  }
  function toggle(id: string) {
    setSent(null);
    if (picked.includes(id)) save(picked.filter((x) => x !== id));
    else if (room > 0) save([...picked, id]);
  }

  function onSent(r: Created) {
    setOpen(false);
    const done = new Set([...r.created.map((c) => c.vendor_id ?? ""), ...r.failed.map((f) => f.vendor_id)]);
    const rest = picked.filter((id) => !done.has(id));
    setMsg("");
    save(rest, "");
    setSent({
      ok: r.created.map((c) => c.vendor_name),
      shared: r.created.some((c) => c.share_contact),
      failed: r.failed.map((f) => ({ name: byId.get(f.vendor_id)?.biz_name ?? "업체", code: f.code })),
    });
    router.refresh();
  }

  const roomText = slotsLeft <= 0
    ? "이미 3곳에 요청했어요. 요청을 취소하거나 업체가 못 받으면 칸이 비어요."
    : room === 0 ? "3곳까지 담았어요. 하나를 빼면 담을 수 있어요."
    : !picked.length ? (room >= 3 ? "업체를 담아 주세요 (3곳까지)" : `업체를 담아 주세요 (${room}곳 더 담을 수 있어요)`)
    : `${room}곳 더 담을 수 있어요 (3곳까지)`;
  const backTo = `${base}/vendors?trade=${trade}`;

  // 보낸 결과: 목록 위(공정 탭 아래)에 두고 그리로 초점을 옮긴다. 폰에서도 창이 닫힌 자리에서 바로 보인다
  const sentBox = sent ? (
    <div ref={sentRef} tabIndex={-1} role="status" className={s.sent}>
      {sent.ok.length ? (
        <>
          <p className={s.sentLine}><span className="mj-st mj-st-ok"><Check />보냈어요</span><b>{sent.ok.join(" · ")}에 요청했어요.</b></p>
          <p className="mj-small">{sent.shared ? "업체가 먼저 연락할 수 있어요. 먼저 전화해도 돼요." : "업체에 먼저 연락해 방문 날짜를 정해 주세요."}</p>
          <Link className={`mj-btn mj-btn-pri ${s.self}`} href={`${base}/visits?trade=${trade}`}>연락처 보기</Link>
        </>
      ) : null}
      {sent.failed.map((f) => (
        <p key={f.name + f.code} className={s.sentLine}>
          <span className="mj-st mj-st-bad"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" /></svg>못 보냈어요</span>
          <b>{f.name}</b><span className="mj-small">{FAILED_TEXT[f.code] ?? "요청하지 못했어요."}</span>
        </p>
      ))}
    </div>
  ) : null;

  return (
    <div className={s.layout}>
      <div className={s.main}>
        {head}
        {locked ? null : sentBox}
        <div role="group" aria-label="목록 거르기" className={s.filter}>
          <p className={`mj-small ${s.area}`}>{areaName}에서 일하는 업체만 보여요 · 가견적 낮은 순</p>
          <label className={s.ck}><input type="checkbox" checked={onlyEst} onChange={(e) => setOnlyEst(e.target.checked)} />가견적이 있는 업체만</label>
        </div>

        <h2 className="mj-sr">{tName} 업체 {shown.length}곳</h2>
        <div className={`${s.vr} ${s.vh}`} aria-hidden="true"><span className={s.c1}>업체</span><span className={s.c2}>확인</span><span className={s.c3}>실측 · 연락</span><span className={s.c4}>가견적</span><span className={s.c5} /></div>
        {shown.length ? (
          <ul role="list" className={s.list}>
            {shown.map((v) => {
              const name = v.biz_name ?? "업체";
              const m = asMethod(v.contact_method);
              const vis = v.visit;
              const kind = vis ? shutKind(vis, locked) : null;
              const on = picked.includes(v.vendor_id);
              const full = !on && room === 0;
              const looking = viewing === v.vendor_id;
              return (
                <li key={v.vendor_id} className={`${s.vr} ${looking ? s.on : ""}`}>
                  <div className={s.c1}>
                    <h3 className={`mj-h3 ${s.vnH}`}>
                      <Link id={`vn-${v.vendor_id}`} className={s.vn} href={`${base}/vendors/${v.vendor_id}?trade=${trade}`} scroll={false} aria-current={looking || undefined} onClick={() => markFromList(backTo)}>{name}<span className="mj-sr"> 자세히 보기</span></Link>
                      {looking ? <span className={s.seeing}>보는 중</span> : null}
                    </h3>
                    <p className="mj-small">{[...v.trades.map(tradeLabel), areasText(v.areas, areaName)].join(" · ")}</p>
                  </div>
                  <ul className={`${s.c2} ${s.facts}`} aria-label="믿집 확인">
                    <li><span className={s.okIcon}><Check /></span><span>사업자 확인함</span></li>
                  </ul>
                  <div className={s.c3}>
                    <p className={s.mlab}>실측 · 연락</p>
                    <p>{feeText(v.visit_fee)}{m ? ` · ${CONTACT_LABEL[m]}` : ""}</p>
                  </div>
                  <div className={s.c4}>
                    <p className={s.mlab}>가견적</p>
                    <Estimate v={v} />
                  </div>
                  <div className={s.c5}>
                    {vis && isLive(vis.status) ? (
                      <div className={s.state}>
                        <VisitState status={vis.status} />
                        {vis.status === "requested" ? <Link className={`mj-lnk ${s.sm}`} href={`${base}/visits?trade=${trade}`}>연락처 보기<span className="mj-sr">, {name}</span></Link> : null}
                        {vis.status === "quoted" ? <Link className={`mj-lnk ${s.sm}`} href={`${base}/quotes?trade=${trade}`}>비교하기<span className="mj-sr">, {name} 실측 견적서</span></Link> : null}
                        {vis.status === "chosen" ? <Link className={`mj-lnk ${s.sm}`} href={`${base}/visits?trade=${trade}`}>연락처 보기<span className="mj-sr">, {name}</span></Link> : null}
                      </div>
                    ) : (
                      <>
                        {vis ? (
                          <div className={s.state}>
                            <VisitState status={vis.status} past={kind === "past"} />
                            <span className="mj-small mj-num">{[kind === "other" ? "다른 업체로 정했어요" : declineText(vis.decline_code), when(closedAt[vis.id])].filter(Boolean).join(" · ")}</span>
                          </div>
                        ) : null}
                        {locked ? null : (
                          <button type="button" className={s.pick} aria-pressed={on} aria-disabled={full || undefined} aria-describedby={full ? "pk-room" : undefined} onClick={() => toggle(v.vendor_id)}>
                            {on ? <Picked /> : <Plus />}{on ? "담았어요" : kind === "past" ? "다시 담기" : "실측 요청에 담기"}<span className="mj-sr">, {name}</span>
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className={s.empty}>가견적이 있는 업체가 아직 없어요. 거르기를 풀면 모든 업체가 보여요.</p>
        )}
      </div>

      {locked ? null : <aside className={s.side} aria-labelledby="pk-t">
        <form className={s.form} onSubmit={(e) => { e.preventDefault(); if (picked.length) setOpen(true); }} noValidate>
          <h2 id="pk-t" className="mj-h3">{tName} 실측 요청할 업체{picked.length ? <> <span className="mj-num">{picked.length}<span className="mj-sr">곳</span></span></> : null}</h2>
          {picked.length ? (
            <ul role="list" className={s.basket}>
              {picked.map((id) => {
                const v = byId.get(id)!;
                const name = v.biz_name ?? "업체";
                return (
                  <li key={id}>
                    <div className={s.bName}>
                      <p className={s.strong}>{name}</p>
                      <p className="mj-small mj-num">{v.estimate_total != null ? `가견적 ${won(v.estimate_total)}` : "가견적 없음"}</p>
                    </div>
                    <button type="button" className={s.rmv} aria-label={`${name} 빼기`} onClick={() => toggle(id)}><Close /></button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          <p id="pk-room" className="mj-hint">{roomText}</p>
          {/* 담은 업체가 없으면 남길 말 · 보내기 칸을 접는다 */}
          {picked.length ? <>
          <div className="mj-field">
            <label className="mj-label" htmlFor="pk-memo">업체에 남길 말 <span className="mj-opt">(선택)</span></label>
            <textarea id="pk-memo" className="mj-textarea" rows={3} maxLength={300} value={msg} aria-describedby="pk-memo-h" placeholder="예: 평일 오후나 주말 오전이 좋아요." onChange={(e) => { setMsg(e.target.value); writePick(projectId, trade, { ids: picked, msg: e.target.value }); }} />
            <p id="pk-memo-h" className="mj-hint mj-num">{msg.length}/300자 · 담은 업체 모두에게 가요</p>
          </div>
          <button type="submit" className="mj-btn mj-btn-pri" aria-haspopup="dialog">실측 요청 보내기</button>
          </> : null}
        </form>
      </aside>}

      {/* 폰 · 좁은 화면(960px 아래)에서는 담은 업체 칸이 목록 맨 아래라, 담으면 화면 아래에 막대를 붙인다 */}
      {!locked && picked.length ? (
        <div className={s.bar} data-pick-bar="">
          <a className={s.barCount} href="#pk-t"><b className="mj-num">{picked.length}곳</b> 담음<span className="mj-sr"> · 담은 업체 보기</span></a>
          <button type="button" className="mj-btn mj-btn-pri" aria-haspopup="dialog" onClick={() => setOpen(true)}>실측 요청 보내기</button>
        </div>
      ) : null}

      {locked ? null : (
        <RequestDialog
          open={open}
          onClose={() => setOpen(false)}
          onSent={onSent}
          projectId={projectId}
          trade={trade}
          vendors={picked.map((id) => ({ id, name: byId.get(id)?.biz_name ?? "업체" }))}
          message={msg}
          consentVer={consentVer}
          backTo={backTo}
          idp="rq"
        />
      )}
    </div>
  );
}
