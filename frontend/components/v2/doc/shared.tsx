"use client";
// 견적서 · 공정표 공통: 표시 형식(v10 fmt · wonText · approxMan · manRange) · 문서 겹창(docShell) · 입력 칸(fld) · 날짜 칸(dateField8).
// 숫자는 API 응답을 보이기만 한다. 만 원 반올림 표시는 v10과 같다.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { DateCalendar } from "@/components/start/DateCalendar";
import { md, todaySeoul } from "../dates";
import { V3 } from "../store";

export const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("ko-KR"));
export const wonText = (n: number | null | undefined) => (n == null ? "—" : n % 10000 === 0 ? `${(n / 10000).toLocaleString("ko-KR")}만 원` : `${n.toLocaleString("ko-KR")}원`);
export const STATE_KO: Record<string, string> = { included: "포함", bundled: "묶음 포함", separate: "따로 계산", optional: "선택", after_visit: "실측 후", excluded: "안 함" };
export const BASIS_KO: Record<string, string> = { public: "공공 기준", assumed: "팀 가정값", none: "업체 견적에서", market: "시장 근거", pick: "고른 자재" };
/** 요약 카드용 표시: 만 원 단위(정확한 금액은 견적서에 그대로) */
export const approxMan = (n: number | null | undefined) => (n == null ? "—" : `약 ${Math.round(n / 10000).toLocaleString("ko-KR")}만 원`);
export const manRange = (lo: number, hi: number) => `${Math.round(lo / 10000).toLocaleString("ko-KR")}만 ~ ${Math.round(hi / 10000).toLocaleString("ko-KR")}만 원`;
export const signWon = (d: number) => `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}원`;

/** 공정표 · 견적서 기록 (v10 log) */
export const log = (t: string) => V3.log.push(`${todaySeoul()} · ${t}`);

/* 공정표 표시 (v6 WD · mdw · md0 · TCOLOR). 날짜 글만 바꾼다 */
const WD = "일월화수목금토";
const wd = (d: string) => WD[new Date(d + "T00:00:00Z").getUTCDay()];
export const mdw = (d: string) => `${d.slice(5).replace("-", ".")}(${wd(d)})`;
export const md0 = (d: string) => d.slice(5).replace("-", ".");
export const wdOf = wd;
export const TCOLOR = (k: string) =>
  ({ mokgong: "#8B6B4A", dobae: "#2d6cb5", dry: "#c9c5bf", clean: "#9aa5b1" } as Record<string, string>)[k] ||
  ["#5b8a72", "#a3714f", "#6b6fa8", "#b0874a", "#4f8a9c", "#9c5f7a", "#7a8a4f", "#8a6f9c", "#5f7f9c", "#9c7a5f"][[...k].reduce((a, c) => a + c.charCodeAt(0), 0) % 10];

/** 입력 칸 + 보이는 이름 (v10 fld) */
export function Fld({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="fld">
      <span>{label}</span>
      {children}
    </label>
  );
}

/** 문서 겹창 (v10 docShell): 고객 보기 / 업체 보기, ×, Esc · 바깥 누르기로 닫기, 열면 × 에 초점 */
export function DocShell({ title, close, children }: { title: string; close: () => void; children: () => ReactNode }) {
  const [, setRole] = useState(V3.role);
  const x = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    x.current?.focus();
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [close]);
  return (
    <div
      className="sheet-bg doc-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="sheet doc" role="dialog" aria-modal="true" aria-label={title}>
        <div className="doc-head">
          <h3>{title}</h3>
          <div className="seg" role="group" aria-label="보기">
            {([["customer", "고객 보기"], ["vendor", "업체 보기"]] as const).map(([k, l]) => (
              <button
                key={k}
                type="button"
                aria-pressed={V3.role === k}
                onClick={() => {
                  V3.role = k;
                  setRole(k);
                }}
              >
                {l}
              </button>
            ))}
          </div>
          <button ref={x} type="button" className="x" aria-label="닫기" onClick={close}>×</button>
        </div>
        <div className="doc-body">{children()}</div>
      </div>
    </div>
  );
}

type DfCommon = { id: string; labelId: string; label: string; compact?: boolean; notToday?: boolean; tail?: string };
type DfOne = DfCommon & { range?: false; value: string; onChange: (v: string) => void };
type DfRange = DfCommon & { range: true; value: { from: string; to: string }; onChange: (v: { from: string; to: string }) => void };
/** 누르면 펼치는 날짜 칸 (v10 dateField8). 달력은 팀 DateCalendar */
export function DateField(o: DfOne | DfRange) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const has = o.range ? !!o.value.from : !!o.value;
  const text = !has
    ? "날짜 고르기"
    : (o.range ? (o.value.to && o.value.to !== o.value.from ? `${md(o.value.from)} ~ ${md(o.value.to)}` : md(o.value.from)) : md(o.value)) + (o.tail || "");
  const shut = () => {
    setOpen(false);
    setTimeout(() => btn.current?.focus(), 0);
  };
  return (
    <div
      className={"df8" + (o.compact ? " compact" : "")}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          e.stopPropagation();
          shut();
        }
      }}
    >
      <div className="df8-row">
        <button ref={btn} type="button" id={o.id} className="btn df8-btn" aria-expanded={open} aria-controls={o.id + "-cal"} aria-labelledby={`${o.labelId} ${o.id}`} onClick={() => setOpen(!open)}>
          <span className="df8-ic" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
              <rect x="2" y="3" width="12" height="11" rx="1.5" />
              <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
            </svg>
          </span>
          <span className="num">{text}</span>
        </button>
        <button
          type="button"
          className="btn-text df8-clear"
          hidden={!has}
          onClick={() => {
            if (o.range) o.onChange({ from: "", to: "" });
            else o.onChange("");
            shut();
          }}
        >
          지우기<span className="sr">, {o.label}</span>
        </button>
      </div>
      <div className="df8-box" id={o.id + "-cal"} hidden={!open}>
        {open ? (
          o.range ? (
            <DateCalendar
              range
              today={todaySeoul()}
              label={`${o.label} 고르기`}
              notToday={o.notToday}
              value={o.value}
              onChange={(v) => {
                o.onChange(v);
                if (v.from && v.to && v.from !== v.to) shut(); // 끝 날까지 고르면 접는다
              }}
            />
          ) : (
            <DateCalendar
              today={todaySeoul()}
              label={`${o.label} 고르기`}
              notToday={o.notToday}
              value={o.value}
              onChange={(v) => {
                o.onChange(v);
                shut();
              }}
            />
          )
        ) : null}
      </div>
    </div>
  );
}
