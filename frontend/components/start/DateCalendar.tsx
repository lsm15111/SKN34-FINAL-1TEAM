"use client";
// 펼쳐 둔 달력. 눌러서 여는 단계 없이 바로 날짜를 고른다. 하루(single) 또는 시작~끝(range).
// DayPicker가 표 형태 달력의 접근성 규칙(화살표 키 이동, 이번 달 · 다음 달 이동, 초점 관리)을 맡는다.
// 값은 "YYYY-MM-DD" 문자열로 주고받는다. 오늘 날짜는 밖에서 받는다(시계를 직접 읽지 않음).
import { DayPicker, type DateRange } from "@daypicker/react";
import { ko } from "@daypicker/react/locale";
import "@daypicker/react/style.css";

const toDate = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const toStr = (d?: Date) => (d ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` : "");

type Common = { today: string; label: string; id?: string };
type Single = Common & { range?: false; value: string; onChange: (v: string) => void };
type Range = Common & { range: true; value: { from: string; to: string }; onChange: (v: { from: string; to: string }) => void };

export function DateCalendar(props: Single | Range) {
  const t = toDate(props.today);
  const common = {
    locale: ko,
    today: t,
    startMonth: t,
    endMonth: new Date(t.getFullYear() + 1, t.getMonth()),
    disabled: { before: t },
    weekStartsOn: 0 as const,
    modifiers: { sun: { dayOfWeek: [0] } },
    modifiersClassNames: { sun: "mj-cal-sun" },
    formatters: { formatCaption: (m: Date) => `${m.getFullYear()}년 ${m.getMonth() + 1}월` },
  };
  let picker: React.ReactNode;
  if (props.range) {
    const { from, to } = props.value;
    const sel: DateRange | undefined = from ? { from: toDate(from), to: to ? toDate(to) : undefined } : undefined;
    picker = <DayPicker {...common} mode="range" selected={sel} defaultMonth={sel?.from ?? t} onSelect={(r) => props.onChange({ from: toStr(r?.from), to: toStr(r?.to) })} />;
  } else {
    const sel = props.value ? toDate(props.value) : undefined;
    picker = <DayPicker {...common} mode="single" selected={sel} defaultMonth={sel ?? t} onSelect={(d) => props.onChange(toStr(d))} />;
  }
  return <div className="mj-cal" role="group" aria-label={props.label} id={props.id}>{picker}</div>;
}
