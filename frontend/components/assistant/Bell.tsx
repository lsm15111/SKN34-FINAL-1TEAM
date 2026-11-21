"use client";
// 머리 종(4.6): 44px 단추 + 안 읽은 수 → 370px 펼침(최근 알림 · 모두 읽음 · 모두 보기). 폰도 같은 펼침이고 '모두 보기'는 /notifications예요.
// 알림을 누르면 읽음을 보내고 그 경로(= 그 카드)로 가요. 같은 공사 안 경로면 대화는 그대로 두고 카드만 열려요.
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { getNotifications, insideHref, readAllNotifications, readNotification, type NotifyPage } from "@/lib/api/assistant";
import { listStamp } from "@/lib/format";
import { useLive, useLiveUnread } from "@/components/site/LiveProvider";
import { ASSISTANT_MOCK } from "@/lib/mock/assistant/mode";
import { I, type IconName } from "./kit/icons";
import s from "./assistant.module.css";

const SHOW = 6;
const KIND_ICON: [RegExp, IconName][] = [[/quote/, "file"], [/visit|date|plan|schedule/, "calendar"], [/chat|thread|msg/, "chat"], [/assistant|today/, "bell"]];
const iconOf = (kind: string): IconName => KIND_ICON.find(([re]) => re.test(kind))?.[1] ?? "bell";

export function Bell({ projectId, start, tick }: { projectId: string; start: number; tick: number }) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState<NotifyPage | null | "error">(null);
  const [mockUnread, setMockUnread] = useState(0);
  const live = useLiveUnread(start);
  const { setUnread } = useLive();
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const id = useId();
  const unread = ASSISTANT_MOCK ? mockUnread : live;

  // 목업: 대본이 알림을 더하면(턴이 끝날 때마다) 수를 다시 읽어요
  useEffect(() => {
    if (!ASSISTANT_MOCK) return;
    let alive = true;
    getNotifications(projectId).then((p) => { if (alive) setMockUnread(p.unread); }).catch(() => undefined);
    return () => { alive = false; };
  }, [projectId, tick]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    getNotifications(projectId)
      .then((p) => { if (!alive) return; setPage(p); if (ASSISTANT_MOCK) setMockUnread(p.unread); else setUnread(p.unread); })
      .catch(() => { if (alive) setPage("error"); });
    const onDown = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { alive = false; document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, projectId, setUnread]);

  async function readAll() {
    try {
      await readAllNotifications(projectId);
      setPage((p) => (p && p !== "error" ? { unread: 0, items: p.items.map((n) => ({ ...n, read: true })) } : p));
      if (ASSISTANT_MOCK) setMockUnread(0); else setUnread(0);
    } catch { /* 다음에 펼칠 때 다시 읽어요 */ }
  }

  const label = unread > 0 ? `알림, 새 알림 ${unread}개` : "알림";
  const items = page && page !== "error" ? page.items.slice(0, SHOW) : [];
  return (
    <div ref={box} className={s.pop}>
      <button ref={btn} type="button" className={s.iconBtn} aria-label={label} aria-expanded={open} aria-controls={open ? `${id}-drop` : undefined} onClick={() => setOpen((v) => !v)}>
        <I n="bell" />
        {unread > 0 ? <span className={`${s.count} ${s.num}`} aria-hidden="true">{unread}</span> : null}
      </button>
      {open ? (
        <div id={`${id}-drop`} className={s.drop} role="dialog" aria-label="알림">
          <div className={s.dropHead}>
            <b>알림</b>
            {unread > 0 ? <button type="button" className={s.textBtn} onClick={readAll}>모두 읽음</button> : null}
          </div>
          {page === null ? <p className={s.dropNote}>알림을 불러오고 있어요</p>
            : page === "error" ? <p className={s.dropNote}>알림을 불러오지 못했어요. 알림 화면에서 다시 볼 수 있어요.</p>
              : !items.length ? <p className={s.dropNote}>새 알림이 오면 여기에 보여요</p>
                : (
                  <ul className={s.nlist}>
                    {items.map((n) => (
                      <li key={n.id}>
                        {/* 읽음 표시가 실패해도 이동은 그대로예요(안 읽은 수는 서버 값이라 그대로 남고, 알림 화면에서 다시 읽을 수 있어요) */}
                        <Link href={insideHref(n.link) ? n.link : "/notifications"} scroll={false} onClick={() => { setOpen(false); if (!n.read) void readNotification(projectId, n.id).then(() => { if (ASSISTANT_MOCK) setMockUnread((x) => Math.max(0, x - 1)); }).catch(() => undefined); }}>
                          <span className={s.nic}><I n={iconOf(n.kind)} /></span>
                          <div><p>{n.body}</p><time className={s.num} dateTime={n.created_at}>{listStamp(n.created_at)}</time></div>
                          {n.read ? <span /> : <i className={s.unread} aria-label="안 읽음" />}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
          <div className={s.dropFoot}><Link className={s.textBtn} href="/notifications" onClick={() => setOpen(false)}>알림 모두 보기<I n="chev" /></Link></div>
        </div>
      ) : null}
    </div>
  );
}
