// 내 공사 카드(C42 폰 · D09 웹 2열): 공사 이름 · 작은 줄 · 6단계 · 지금 할 일 · [할 일 단추] + 업체 상태 꼬리표.
// 단계 · 할 일 · 기한은 API 값 그대로예요. 꼬리표는 같은 상태 업체를 묶어 '업체 답 기다림 2곳' · '업체 확정 · 마루와벽'처럼 짧게 보여요.
// 업체별 날짜 · 금액은 단추 화면(실측 일정 · 공정표)에서 봐요. 웹은 카드 높이가 같고 단추 줄은 카드 바닥에 붙어요.
import Link from "next/link";
import type { ApiMyProject } from "@/lib/api/schedule";
import type { BoardRow } from "@/lib/api/visit";
import { dateSeoul, dateShort, dueText } from "@/lib/format";
import { stepIndex } from "@/lib/guest/info";
import { gradeLabel, sizeLabel, visitState, type StateTone } from "@/lib/labels";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { StateTag } from "@/components/ui/StateTag";
import { Steps } from "@/components/ui/Steps";
import { Group, Small } from "@/components/project/Kit";
import { boardState } from "@/components/visit/text";
import s from "./cards.module.css";

/** rows: 실측 일정 상태판 줄(실측 시각이 지난 업체를 가릴 때만 읽어요) */
export type MyCard = { p: ApiMyProject; name: string; rows: BoardRow[] | null };
type Vendor = ApiMyProject["vendors"][number];
type Tag = { label: string; tone: StateTone; names: string[]; due: string | null };

/** 이 사이트 안 경로만 단추로 이어요(할 일 link는 API 값) */
const inSite = (v: string) => v.startsWith("/") && !v.startsWith("//") && !v.startsWith("/\\");

/** 꼬리표 순서: 기한 지남 · 내 차례 → 기다림 → 정해짐 → 끝남 */
const TONE_ORDER: StateTone[] = ["late", "todo", "wait", "ok", "done"];

/** 업체 하나의 상태 말. 업체 줄 밖에서도 읽히게 누구 답인지 · 무엇이 확정인지는 이름표(lib/labels)에 붙어 있어요 */
function tagState(v: Vendor, row: BoardRow | undefined): { label: string; tone: StateTone } {
  return row ? boardState(row) : visitState(v.status, "customer");
}

/** 같은 상태 업체를 한 꼬리표로 묶어요. 내가 날짜를 고를 차례(기간 옴 · 다른 날 제안)면 가장 이른 기한을 붙여요 */
function vendorTags(c: MyCard): Tag[] {
  const rows = new Map((c.rows ?? []).map((r) => [r.visit_id, r]));
  const tags = new Map<string, Tag>();
  for (const v of c.p.vendors) {
    const st = tagState(v, rows.get(v.visit_id));
    const key = `${st.tone}:${st.label}`;
    const t = tags.get(key) ?? { ...st, names: [], due: null };
    t.names.push(v.vendor_name);
    const due = v.status === "offered" || v.status === "proposed" ? v.next.due_at : null;
    if (due && (!t.due || Date.parse(due) < Date.parse(t.due))) t.due = due;
    tags.set(key, t);
  }
  return [...tags.values()].sort((a, b) => TONE_ORDER.indexOf(a.tone) - TONE_ORDER.indexOf(b.tone));
}

function Tags({ items }: { items: Tag[] }) {
  return (
    <ul className={s.tags} aria-label="업체 상태">
      {items.map((t) => (
        <li key={`${t.tone}:${t.label}`}>
          <StateTag tone={t.tone} className={s.tag}>
            <span>
              {t.label}{t.names.length > 1 ? ` ${t.names.length}곳` : ` · ${t.names[0]}`}
              {t.due ? <span className={s.due}> · {dueText(t.due)}</span> : null}
            </span>
          </StateTag>
        </li>
      ))}
    </ul>
  );
}

function Card({ c }: { c: MyCard }) {
  const { p } = c;
  const base = `/projects/${encodeURIComponent(p.id)}`;
  // API 단계 번호는 1부터(1~6, MyProjectOut.current) → 단계 띠 칸(0부터). 홈 · 공사 머리와 같은 바꾸기예요
  const current = stepIndex(p.current);
  const small = [sizeLabel(p.size), p.trades.includes("dobae") ? gradeLabel(p.grades.dobae) : null, `마지막 소식 ${dateShort(dateSeoul(p.updated_at))}`].filter(Boolean).join(" · ");
  const todo = p.todo && p.todo.text ? p.todo : null;
  const todoHref = todo && inSite(todo.link) ? todo.link : null;
  const picked = p.vendors.length > 0;
  const tags = vendorTags(c);
  const text = todo?.text || (picked ? null : "업체를 담을 차례예요");
  // 할 일 단추가 없으면 업체 줄이 하던 길(실측 일정)을 남겨요
  const button = picked
    ? todo?.action && todoHref
      ? <Button size="sm" href={todoHref}>{todo.action}</Button>
      : <Button variant="text" arrow href={`${base}/visits`}>실측 일정 보기</Button>
    : <Button variant="text" arrow href={todoHref ?? `${base}/vendors`}>{todo?.action || "업체 보기"}</Button>;
  return (
    <li className={s.item}>
      <Group as="article" className={s.card}>
        <div className={s.head}>
          <h2 className={s.title}><Link className={s.name} href={base}>{c.name}<Icon name="chevron-right" size={18} /></Link></h2>
          <Small>{small}</Small>
        </div>
        <Steps current={current} />
        {text ? <p className={s.todoText}>{text}</p> : null}
        <div className={s.foot}>
          {button}
          {tags.length ? <Tags items={tags} /> : null}
        </div>
      </Group>
    </li>
  );
}

export function ProjectCards({ items }: { items: MyCard[] }) {
  return (
    <ul className={s.grid} aria-label="내 공사 목록">
      {items.map((c) => <Card key={c.p.id} c={c} />)}
    </ul>
  );
}
