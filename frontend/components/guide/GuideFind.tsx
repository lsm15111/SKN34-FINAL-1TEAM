"use client";
// 백과 찾기 창(Ctrl K · ⌘K · 찾기 칸). 용어 · 글 · 자주 묻는 질문을 묶어 보여 주고, 맨 끝에 'AI 채팅에 물어보기'를 둬요(고객 · 손님).
// - 목록은 처음 열 때 /guide/search-index에서 한 번만 받아요(화면마다 데이터를 싣지 않게).
// - 띄어쓰기 · 가운뎃점은 빼고 견줘요. 'ㅊㅂ'처럼 첫소리만 쳐도 용어를 찾아요.
// - ↑ ↓로 고르고 Enter로 열어요(콤보 상자 · 목록 상자 패턴). 빈 칸이면 많이 찾는 용어를 보여요.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MQ } from "@/components/site/breakpoints";
import { Icon, type IconName } from "@/components/ui/Icon";
import { useModal } from "@/components/ui/useModal";
import { ASK_EVENT, FIND_EVENT, POPULAR, TRADE_LABEL, articleHref, termHrefId, type SearchIndex } from "@/lib/guide/shared";
import s from "./guide.module.css";

type Item = { key: string; href?: string; title: string; sub: string; img?: string; icon?: IconName; ask?: string };
type Group = { title: string; items: Item[] };

const LIMIT = { terms: 6, articles: 5, faq: 3 };
const norm = (v: string) => v.toLowerCase().replace(/[\s·・,.()/_-]+/g, "");
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
/** 첫소리만: '초배' → 'ㅊㅂ'(한글이 아니면 그대로) */
function initials(v: string): string {
  let out = "";
  for (const ch of v) {
    const c = ch.charCodeAt(0) - 0xac00;
    out += c >= 0 && c < 11172 ? CHO[Math.floor(c / 588)] : ch;
  }
  return out;
}
const onlyInitials = (q: string) => /^[ㄱ-ㅎ]+$/.test(q);

/** 맞는 정도(0이면 안 맞아요). 이름이 같으면 가장 높고, 앞에서 맞으면 · 안에서 맞으면 순서로 낮아져요 */
function score(q: string, name: string, more: string[] = [], body = ""): number {
  const n = norm(name);
  if (onlyInitials(q)) {
    const i = initials(n);
    return i === q ? 90 : i.startsWith(q) ? 70 : i.includes(q) ? 40 : 0;
  }
  if (n === q) return 100;
  if (n.startsWith(q)) return 80;
  if (n.includes(q)) return 60;
  if (more.some((m) => norm(m).includes(q))) return 45;
  if (body && norm(body).includes(q)) return 20;
  return 0;
}
function top<T>(rows: T[], rank: (r: T) => number, n: number): T[] {
  return rows.map((r) => [rank(r), r] as const).filter(([k]) => k > 0).sort((a, b) => b[0] - a[0]).slice(0, n).map(([, r]) => r);
}

export function GuideFind({ canAsk }: { canAsk: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [data, setData] = useState<SearchIndex | null>(null);
  const [failed, setFailed] = useState(false);
  const [active, setActive] = useState(0);
  const router = useRouter();
  const listId = useId();
  const close = useCallback(() => setOpen(false), []);
  const m = useModal(ref, open, close, { closeOnBack: () => !window.matchMedia(MQ.tablet).matches });

  // 찾기 칸 · Ctrl K · ⌘K로 열어요(입력 중인 칸에서도 Ctrl K는 열려요)
  useEffect(() => {
    const show = () => { setQ(""); setActive(0); setOpen(true); };
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (!document.querySelector("dialog[open]")) show();
      }
    };
    window.addEventListener(FIND_EVENT, show);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener(FIND_EVENT, show); window.removeEventListener("keydown", onKey); };
  }, []);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    if (data) return;
    let off = false;
    fetch("/guide/search-index")
      .then((r) => (r.ok ? (r.json() as Promise<SearchIndex>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => { if (!off) { setData(d); setFailed(false); } })
      .catch(() => { if (!off) setFailed(true); });
    return () => { off = true; };
  }, [open, data]);

  const groups = useMemo<Group[]>(() => {
    if (!data) return [];
    const k = norm(q);
    const termItem = (t: SearchIndex["terms"][number]): Item => ({
      key: `t-${t.id}`, href: termHrefId(t.id), title: t.term, sub: `${TRADE_LABEL[t.trade]} · ${t.easy}`, img: t.img, icon: "doc",
    });
    if (!k) {
      const pop = POPULAR.map((n) => data.terms.find((t) => t.term === n)).filter((t) => t !== undefined);
      return [{ title: "많이 찾는 용어", items: pop.map(termItem) }];
    }
    const out: Group[] = [];
    const terms = top(data.terms, (t) => score(k, t.term, t.aliases, t.easy), LIMIT.terms);
    if (terms.length) out.push({ title: "용어", items: terms.map(termItem) });
    const arts = top(data.articles, (a) => score(k, a.title, a.heads, a.lead), LIMIT.articles);
    if (arts.length) out.push({ title: "글", items: arts.map((a) => ({ key: `a-${a.slug}`, href: articleHref(a.slug), title: a.title, sub: a.lead, icon: "doc" })) });
    const faq = top(data.faq, (f) => score(k, f.q, [], f.a), LIMIT.faq);
    if (faq.length) out.push({ title: "자주 묻는 질문", items: faq.map((f) => ({ key: `f-${f.id}`, href: `/faq#${f.id}`, title: f.q, sub: f.a, icon: "chat" })) });
    if (canAsk && !onlyInitials(k)) out.push({ title: "AI 채팅", items: [{ key: "ask", title: `'${q.trim()}' AI 채팅에 물어보기`, sub: "답은 AI가 해요", icon: "chat", ask: q.trim() }] });
    return out;
  }, [data, q, canAsk]);
  const flat = groups.flatMap((g) => g.items);
  const cur = Math.min(active, Math.max(0, flat.length - 1));

  function go(it: Item) {
    close();
    if (it.ask !== undefined) {
      window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text: it.ask } }));
      return;
    }
    if (it.href) router.push(it.href);
  }
  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing || !flat.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = (cur + (e.key === "ArrowDown" ? 1 : -1) + flat.length) % flat.length;
      setActive(next);
      document.getElementById(`${listId}-${next}`)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(flat[cur]);
    }
  }

  let i = -1;
  return (
    <dialog ref={ref} className={s.find} aria-label="백과에서 찾기" onCancel={m.onCancel} onClick={m.onClick}>
      <div className={s.findIn}>
        <div className={s.findQ}>
          <Icon name="search" size={20} />
          <input
            ref={input} type="search" value={q} placeholder="용어 · 글 · 질문 찾기" enterKeyHint="search" autoComplete="off" spellCheck={false}
            role="combobox" aria-expanded={flat.length > 0} aria-controls={listId} aria-autocomplete="list"
            aria-activedescendant={flat.length ? `${listId}-${cur}` : undefined} aria-label="찾을 말"
            onChange={(e) => { setQ(e.target.value); setActive(0); }} onKeyDown={onKeyDown}
          />
          <button type="button" className={s.panelX} aria-label="닫기" onClick={close}><Icon name="close" /></button>
        </div>
        <div className={s.findList} id={listId} role="listbox" aria-label="찾은 것">
          {!data ? (
            <p className={s.findNone} role="status">{failed ? "목록을 불러오지 못했어요. 잠시 뒤 다시 열어 주세요." : "불러오는 중이에요"}</p>
          ) : flat.length === 0 ? (
            <p className={s.findNone} role="status">맞는 것이 없어요</p>
          ) : (
            groups.map((g) => (
              <div key={g.title} className={s.findGroup} role="group" aria-label={g.title}>
                <h3 aria-hidden="true">{g.title}</h3>
                {g.items.map((it) => {
                  i += 1;
                  const n = i;
                  const inner = (
                    <>
                      {it.img ? <img src={it.img} alt="" loading="lazy" /> : <span className={s.findIc}><Icon name={it.icon ?? "doc"} size={20} /></span>}
                      <span className={s.findText}><b>{it.title}</b><small>{it.sub}</small></span>
                    </>
                  );
                  // 초점은 입력 칸에 두고 고른 줄은 aria-activedescendant로 알려요(Tab은 닫기 단추로 가요)
                  const common = { id: `${listId}-${n}`, role: "option", "aria-selected": n === cur, tabIndex: -1, className: s.findItem, onMouseMove: () => { if (n !== cur) setActive(n); } } as const;
                  return it.href ? (
                    <Link key={it.key} {...common} href={it.href} onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey) return; e.preventDefault(); go(it); }}>{inner}</Link>
                  ) : (
                    <button key={it.key} type="button" {...common} onClick={() => go(it)}>{inner}</button>
                  );
                })}
              </div>
            ))
          )}
        </div>
        <div className={s.findFoot} aria-hidden="true">
          <span>↑ ↓ 고르기</span><span>Enter 열기</span><span>Esc 닫기</span>
        </div>
      </div>
    </dialog>
  );
}
