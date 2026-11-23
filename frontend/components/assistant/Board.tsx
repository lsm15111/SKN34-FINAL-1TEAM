"use client";
// 내 공사 보드(웹 오른쪽 340 · 1024 아래는 아래 시트 84%): 우리 집 · 지금(정할 일 · 기다리는 일) · 낼 금액 · 업체 · 공사 기간 · 서류 · 비서가 기억하는 것.
// 값은 서버가 준 그대로예요(금액 범위도 두 값을 받아 모양만). 기억은 고객 말에서만 오고 × 로 지워요.
// 기억 칩은 GET /assistant/memory(다른 담당) 값이에요. API가 아직 없으면(404) 그 칸을 숨겨요. 칩을 누르고 있으면 내가 한 말이 보여요.
// '우리 집' 줄 · '고치기' · 예상 공사를 누르면 대화 안 '우리 집 정보' 창(editHref)이 열리고 그 칸에 초점이 가요(2026-11-23 사용자).
// 철거 범위 · 직접 할 일은 그 창 밖(대화)에서 정해서, 실측 요청 뒤(잠김)에는 고칠 수 없어서 누르지 않아요.
import Link from "next/link";
import { useEffect, useRef } from "react";
import type { BoardOut, MemoryOut } from "@/lib/api/assistant";
import { won } from "@/lib/format";
import { StatusTag } from "./kit/StatusTag";
import { I } from "./kit/icons";
import s from "./assistant.module.css";

export function Board({ board, memory, open, flash, editHref, onClose, onForget }: {
  board: BoardOut | null;
  /** 기억(undefined 읽는 중 · null API 없음) */
  memory: MemoryOut[] | null | undefined;
  open: boolean;
  flash: number;
  /** 우리 집 정보 고치기 창(/projects/{id}/home). ?field=로 처음 초점 칸을 알려요 */
  editHref: string;
  onClose: () => void;
  onForget: (id: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!flash || !ref.current) return;
    const el = ref.current;
    el.classList.remove(s.boardFlash);
    void el.offsetWidth;
    el.classList.add(s.boardFlash);
  }, [flash]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("h2")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {open ? <div className={s.scrim} onClick={onClose} aria-hidden="true" /> : null}
      <aside ref={ref} className={open ? `${s.board} ${s.boardOpen}` : s.board} aria-labelledby="board-t" {...(open ? { role: "dialog", "aria-modal": true } : {})}>
        <div className={s.boardHead}>
          <h2 id="board-t" tabIndex={-1}>내 공사 보드</h2>
          <button type="button" className={`${s.x} ${s.boardX}`} aria-label="보드 닫기" onClick={onClose}><I n="x" /></button>
        </div>
        {!board ? <p className={s.muted}>보드를 불러오고 있어요</p> : (
          // 폰에서 보드(아래 시트)를 연 채 창으로 가면 보드는 닫아요
          <Sections b={board} memory={memory === undefined ? board.memory : memory} editHref={editHref} onEdit={open ? onClose : undefined} onForget={onForget} />
        )}
      </aside>
    </>
  );
}

/** 보드 '우리 집' 줄 → 고치기 창에서 처음 초점을 줄 칸. 줄 꼴은 서버 tools/cards.home(첫 줄 지역 · 면적 · 평 · 사는 중 ·
 *  도배 · 방 · 시작 희망 · 철거 · 직접 할 일). 철거 범위 · 직접 할 일은 그 창에서 고치지 않아 null */
export function factField(fact: string, i: number): string | null {
  if (i === 0) return "region";
  if (/㎡|평$/.test(fact)) return "area";
  if (/살면서|빈 집/.test(fact)) return "occupied";
  if (fact.startsWith("도배 ·")) return "grade";
  if (/^방 \d+개/.test(fact)) return "rooms";
  if (fact.startsWith("공사 시작 희망")) return "start";
  return null;
}

function Sections({ b, memory, editHref, onEdit, onForget }: {
  b: BoardOut; memory: MemoryOut[] | null; editHref: string; onEdit?: () => void; onForget: (id: string) => void;
}) {
  const editable = !!b.facts.length && !b.home?.locked;
  const to = (field: string | null) => (field ? `${editHref}?field=${field}` : editHref);
  return (
    <>
      <section className={s.bsec}>
        <div className={s.bsecHead}>
          <h3 className={s.bsecT}>우리 집{b.confirmed ? "" : " · 확인 전"}</h3>
          {editable ? <Link className={s.bsecEdit} href={editHref} scroll={false} onClick={onEdit}>고치기</Link> : null}
        </div>
        {b.facts.length ? (
          <ul className={editable ? `${s.facts} ${s.factsEdit}` : s.facts}>
            {b.facts.map((f, i) => {
              const field = editable ? factField(f, i) : null;
              return field ? (
                <li key={f}><Link href={to(field)} scroll={false} onClick={onEdit} aria-label={`${f} · 고치기`}><span>{f}</span></Link></li>
              ) : <li key={f}><span>{f}</span></li>;
            })}
          </ul>
        ) : <p className={s.muted}>주소를 알려 주면 채워져요</p>}
      </section>
      {b.plan_example ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>대표 평면 · 예시</h3>
          <PlanExample />
        </section>
      ) : null}
      {b.step > 0 ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>지금</h3>
          <div className={s.now2}>
            <div className={b.todo ? s.need : undefined}><span>정할 일</span><b className={s.num}>{b.todo}</b></div>
            <div><span>기다리는 일</span><b className={s.num}>{b.waiting}</b></div>
          </div>
        </section>
      ) : null}
      {b.money ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>낼 금액</h3>
          <div className={s.money}>
            <small>{b.money.label}</small>
            <b className={s.num}>{b.money.range ? `${won(b.money.range[0])} ~ ${won(b.money.range[1])}` : b.money.won != null ? won(b.money.won) : "—"}</b>
            {/* 승인한 추가 금액은 공사 금액에 들어가요(서버 계산 값) */}
            {b.money.extra_won ? <small className={s.num}>승인한 추가 금액 {won(b.money.extra_won)} 포함</small> : null}
          </div>
        </section>
      ) : null}
      {b.vendors?.rows.length ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>{b.vendors.title}</h3>
          <ul className={s.vmini}>
            {/* 상태(공사 단계 · 닫힌 까닭 · 다음 할 일)와 금액(확정한 업체는 지금 공사 금액)을 같이 보여요 */}
            {b.vendors.rows.map((r) => (
              <li key={r.name}>
                <b>{r.name}</b>
                <span className={s.vstate}>
                  <StatusTag tone={r.state}>{r.text}</StatusTag>
                  {r.won != null ? <span className={`${s.num} ${s.muted}`}>{won(r.won)}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {b.period ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>{b.period.label}</h3>
          {/* 예상 공사(확정 전)는 시작 희망일로 정해져서 눌러 고쳐요. 확정한 공사 날짜는 업체와 정해요 */}
          {editable && b.period.label === "예상 공사" ? (
            <Link className={`${s.money} ${s.moneyEdit}`} href={to("start")} scroll={false} onClick={onEdit} aria-label={`${b.period.label} ${b.period.value} · 시작 희망일 고치기`}>
              <b className={s.num}>{b.period.value}</b>{b.period.sub ? <small>{b.period.sub}</small> : null}
            </Link>
          ) : (
            <div className={s.money}><b className={s.num}>{b.period.value}</b>{b.period.sub ? <small>{b.period.sub}</small> : null}</div>
          )}
        </section>
      ) : null}
      {b.docs.length ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>서류</h3>
          <div className={s.links}>{b.docs.map((d) => <Link key={d.href + d.label} href={d.href} scroll={false}>{d.label}</Link>)}</div>
        </section>
      ) : null}
      {memory ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>비서가 기억하는 것</h3>
          {memory.length ? (
            <ul className={s.mem}>
              {memory.map((m) => (
                <li key={m.id} title={`내가 한 말: ${m.evidence_quote}`}>
                  {m.value}
                  <button type="button" aria-label={`'${m.value}' 지우기`} onClick={() => onForget(m.id)}><I n="x" /></button>
                </li>
              ))}
            </ul>
          ) : <p className={s.muted}>내가 말한 것만 기억해요</p>}
          <div className={s.links}><Link href="/account">내 정보에서 모두 보기</Link></div>
        </section>
      ) : null}
    </>
  );
}

/** 30평대 3베이 대표 평면(예시 그림. 이 집 도면이 아니에요) */
function PlanExample() {
  return (
    <svg className={s.planSvg} viewBox="0 0 160 100" role="img" aria-label="30평대 3베이 대표 평면 예시">
      <rect className={s.wall} x="4" y="4" width="152" height="92" />
      <line x1="44" y1="4" x2="44" y2="54" /><line x1="112" y1="4" x2="112" y2="54" /><line x1="4" y1="54" x2="156" y2="54" /><line x1="78" y1="54" x2="78" y2="96" />
      <rect className={s.wet} x="44" y="54" width="34" height="22" /><rect className={s.wet} x="122" y="64" width="34" height="32" />
      <text x="12" y="32">방</text><text x="66" y="32">거실</text><text x="124" y="32">안방</text><text x="12" y="80">방</text><text x="49" y="69">욕실</text><text x="88" y="84">주방</text><text x="128" y="84">욕실</text>
    </svg>
  );
}
