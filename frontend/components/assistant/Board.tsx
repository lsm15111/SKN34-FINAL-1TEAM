"use client";
// 내 공사 보드(웹 오른쪽 340 · 1024 아래는 아래 시트 84%): 우리 집 · 금액(표준견적서 → 확정 금액) · 업체 · 공사 기간 · 서류.
// 이 공사가 어디까지 왔는지만 봐요. 정할 일 수는 대화 위 '오늘 정할 일 n'(웹) · 입력 칸 위 '보드 · 정할 일 n'(폰)에만,
// 비서가 기억한 것은 내 정보 '비서가 기억한 것'에만 둬요(2026-11-23 사용자). 값은 서버가 준 그대로예요(금액 범위도 두 값을 받아 모양만).
// 칸을 누르면 그 칸의 자세히가 대화 안 카드 자리로 열려요(2026-11-23 사용자): '우리 집' 줄 → '우리 집 정보' 창(그 칸에 초점,
// 철거 범위 · 직접 할 일도. 실측 요청 뒤 잠기면 직접 할 일만 고치고 나머지는 보기만) · 금액 → 표준견적서(업체를 확정했으면 실측
// 견적서) · 업체 금액 범위 → 견적서 비교 · 업체 줄 → 그 업체 내역(실측 · 견적서 · 공사, 서버 href) · 기간 → 공정표 · 서류 → 서류 모음.
import Link from "next/link";
import { Fragment, useEffect, useRef, type ReactNode } from "react";
import type { BoardOut } from "@/lib/api/assistant";
import { won } from "@/lib/format";
import { StatusTag } from "./kit/StatusTag";
import { I } from "./kit/icons";
import s from "./assistant.module.css";

export function Board({ board, failed = false, onRetry, open, flash, base, onClose }: {
  board: BoardOut | null;
  /** 보드를 읽지 못했어요(읽어 둔 보드가 없을 때만 실패 줄 · 다시 불러오기) */
  failed?: boolean;
  onRetry?: () => void;
  open: boolean;
  flash: number;
  /** 이 공사 주소(/projects/{id}). 칸의 자세히는 그 아래 카드 자리 경로예요 */
  base: string;
  onClose: () => void;
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
        {!board ? (
          failed ? (
            <p className={s.fail} role="alert"><I n="alert" />보드를 불러오지 못했어요{onRetry ? <button type="button" className={s.textBtn} onClick={onRetry}>다시 불러오기</button> : null}</p>
          ) : <p className={s.muted}>보드를 불러오고 있어요</p>
        ) : (
          // 폰에서 보드(아래 시트)를 연 채 자세히로 가면 보드는 닫아요
          <Sections b={board} base={base} onOpen={open ? onClose : undefined} />
        )}
      </aside>
    </>
  );
}

/** 보드 '우리 집' 줄 → 고치기 창에서 처음 초점을 줄 칸. 줄 꼴은 서버 tools/cards.home(첫 줄 지역 · 면적 · 평 · 사는 중 ·
 *  도배 · 방 · 시작 희망 · 철거(calc.dobae.DEMOLITION 말) · 직접 할 일) */
export function factField(fact: string, i: number): string | null {
  if (i === 0) return "region";
  if (/㎡|평$/.test(fact)) return "area";
  if (/살면서|빈 집/.test(fact)) return "occupied";
  if (fact.startsWith("도배 ·")) return "grade";
  if (/^방 \d+개/.test(fact)) return "rooms";
  if (fact.startsWith("공사 시작 희망")) return "start";
  if (/^(전체 철거|부분 철거|철거 안 함)$/.test(fact)) return "demolition";
  if (fact.startsWith("직접 할 일")) return "diy";
  return null;
}

function Sections({ b, base, onOpen }: { b: BoardOut; base: string; onOpen?: () => void }) {
  const homeHref = `${base}/home`;
  // 실측 요청 뒤(잠김)에도 창은 열려요: 직접 할 일만 고치고 나머지는 보기만(잠긴 화면). 초점 칸은 고칠 수 있을 때만.
  // 따로 '고치기' 단추는 두지 않아요
  const locked = !!b.home?.locked;
  const editable = (field: string) => !locked || field === "diy";
  const to = (field: string) => (editable(field) ? `${homeHref}?field=${field}` : homeHref);
  const go = { scroll: false, onClick: onOpen } as const;
  // 금액 칸 이름은 서버 말 앞쪽(확정 전 '표준견적서', 확정 뒤 '확정 금액' · 추가 금액이 있으면 '공사 금액'), 뒤쪽은 '부가세 포함'
  const [moneyTitle, ...moneyTail] = b.money ? b.money.label.split(" · ") : [""];
  return (
    <>
      <section className={s.bsec}>
        <h3 className={s.bsecT}>우리 집{b.confirmed ? "" : " · 확인 전"}</h3>
        {b.facts.length ? (
          <ul className={`${s.facts} ${s.factsEdit}`}>
            {b.facts.map((f, i) => {
              const field = factField(f, i);
              return field ? (
                <li key={f}><Link href={to(field)} {...go} aria-label={`${f} · ${editable(field) ? "고치기" : "보기"}`}><span>{f}</span></Link></li>
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
      {b.money ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>{moneyTitle}</h3>
          {/* 금액은 표준견적서(업체를 확정했으면 확정 · 공사 금액). 확정 전 업체 금액이 두 곳 이상이면 무엇의 범위인지 이름을 달아
              아래 줄로 보여요(서버 값 그대로). 승인한 추가 금액은 공사 금액에 들어가요 */}
          <Box href={b.money.href} go={go} label={`${b.money.label} ${b.money.won != null ? won(b.money.won) : ""} · 자세히`}>
            <b className={s.num}>{b.money.won != null ? won(b.money.won) : "—"}</b>
            {moneyTail.length ? <small>{moneyTail.join(" · ")}</small> : null}
            {b.money.extra_won ? <small className={s.num}>승인한 추가 금액 {won(b.money.extra_won)} 포함</small> : null}
          </Box>
          {b.money.range ? (
            b.money.range_href ? (
              <Link className={s.rangeLine} href={b.money.range_href} {...go}>
                <span>업체 {b.money.range_label ?? "금액"}</span>
                <span className={s.num}>{won(b.money.range[0])} ~ {won(b.money.range[1])}</span>
              </Link>
            ) : (
              <p className={s.rangeLine}>
                <span>업체 {b.money.range_label ?? "금액"}</span>
                <span className={s.num}>{won(b.money.range[0])} ~ {won(b.money.range[1])}</span>
              </p>
            )
          ) : null}
        </section>
      ) : null}
      {b.vendors?.rows.length ? (
        <section className={s.bsec}>
          <div className={s.bsecHead}>
            <h3 className={s.bsecT}>{b.vendors.title}</h3>
            <Link className={s.bsecEdit} href={`${base}/vendors`} {...go}>모두 보기</Link>
          </div>
          <ul className={s.vmini}>
            {/* 상태(공사 단계 · 닫힌 까닭 · 다음 할 일)와 금액(확정한 업체는 지금 공사 금액). 누르면 그 업체 내역(서버 href) */}
            {b.vendors.rows.map((r) => {
              const body = (
                <>
                  <b>{r.name}</b>
                  <span className={s.vstate}>
                    <StatusTag tone={r.state}>{r.text}</StatusTag>
                    {r.won != null ? <span className={`${s.num} ${s.muted}`}>{won(r.won)}</span> : null}
                  </span>
                </>
              );
              return <li key={r.name}>{r.href ? <Link href={r.href} {...go}>{body}</Link> : body}</li>;
            })}
          </ul>
        </section>
      ) : b.money ? (
        // 아직 실측을 요청한 업체가 없으면 빈 줄 하나 + 제목 옆 '모두 보기'로 업체 목록(가견적 · 담기)에 가요.
        // 업체가 생긴 뒤 · 서류 칸과 같은 자리라 칸 모양이 바뀌지 않아요(2026-11-24 사용자)
        <section className={s.bsec}>
          <div className={s.bsecHead}>
            <h3 className={s.bsecT}>업체</h3>
            <Link className={s.bsecEdit} href={`${base}/vendors`} {...go}>모두 보기</Link>
          </div>
          <p className={s.muted}>아직 실측을 요청한 업체가 없어요</p>
        </section>
      ) : null}
      {b.period ? (
        <section className={s.bsec}>
          <h3 className={s.bsecT}>{b.period.label}</h3>
          {/* 예상 공사(확정 전)는 예상 공정표, 공사 날짜를 수락했으면 확정 공정표. 시작 희망일은 '우리 집' 줄에서 고쳐요 */}
          <Box href={`${base}/plan`} go={go} label={`${b.period.label} ${b.period.value} · 공정표 보기`}>
            <b className={s.num}>{tildeBreak(b.period.value)}</b>{b.period.sub ? <small>{b.period.sub}</small> : null}
          </Box>
        </section>
      ) : null}
      {b.docs.length ? (
        // 서류 하나하나(표준견적서 · 공정표 · 견적서)는 위 칸에서 열려서 여기는 서류 모음 하나만
        <section className={s.bsec}>
          <div className={s.bsecHead}>
            <h3 className={s.bsecT}>서류</h3>
            <Link className={s.bsecEdit} href={`${base}/docs`} {...go}>모두 보기</Link>
          </div>
        </section>
      ) : null}
    </>
  );
}

/** '2027.1.6(수)~2027.1.10(일)'은 '~' 뒤에서만 줄을 바꿔요('(일'과 ')'로 갈라지지 않게, CSS keep-all과 같이) */
function tildeBreak(v: string): ReactNode {
  return v.split("~").map((x, i) => (i ? <Fragment key={i}>~<wbr />{x}</Fragment> : x));
}

/** 금액 · 기간 상자. href가 있으면 눌러 그 칸의 자세히를 열어요(오른쪽 ›) */
function Box({ href, go, label, children }: {
  href?: string | null; go: { scroll: false; onClick?: () => void }; label: string; children: ReactNode;
}) {
  if (!href) return <div className={s.money}>{children}</div>;
  return (
    <Link className={`${s.money} ${s.boxLink}`} href={href} {...go} aria-label={label}>
      {children}
      <I n="chev" className={s.boxChev} />
    </Link>
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
