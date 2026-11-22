"use client";
// 업체 작업함 '비서 소식'(GET /vendor/assistant/feed · /vendor/assistant/actions?status=proposed):
// 비서가 만든 제안(기간 답하기 · 못 받아요 · 공사 날짜)의 승인 카드와 짧은 소식. 둘 다 비었으면 그리지 않아요.
// - 승인 · 거절은 /vendor/assistant/actions/{id}/approve · reject(멱등 키 · 본 판). 409(만료 · 판 바뀜 · 실패)면 서버의 새 상태로 다시 그려요.
// - 실행되면 작업함(서버 화면)을 다시 읽어요. 요청 화면의 v3 단추로 같은 일을 했으면 그 카드는 '처리됨'으로 보여요.
// - 고객 이름 · 연락처 · 동 · 호는 없어요(서버가 넣지 않아요). 카드 글은 서버 값 그대로예요.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  approveVendorAction, getVendorFeed, handledByWrite, listVendorActions, newClientKey, rejectVendorAction, targetOfWrite, VENDOR_ASSISTANT_EVENT,
  vendorKindsForWrite, type ActionOut, type AssistantItem, type FeedPart,
} from "@/lib/api/assistant";
import { API_WRITE_EVENT, ApiError, errorText, type ApiWrite } from "@/lib/backend/client";
import { ApprovalCard } from "@/components/assistant/kit/ApprovalCard";
import { SourceTag } from "@/components/assistant/kit/StatusTag";
import { I } from "@/components/assistant/kit/icons";
import k from "@/components/assistant/kit/kit.module.css";
import p from "./pro.module.css";

const SHOW = 3;

export function VendorFeed({ now }: { now: string }) {
  const router = useRouter();
  const [items, setItems] = useState<AssistantItem[]>([]);
  const [open, setOpen] = useState<ActionOut[]>([]);
  const [all, setAll] = useState<Record<string, ActionOut>>({});
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [handled, setHandled] = useState<Record<string, true>>({});
  const openRef = useRef<ActionOut[]>([]);
  openRef.current = open;

  const load = useCallback(async () => {
    const [f, a] = await Promise.all([getVendorFeed().catch(() => null), listVendorActions("proposed").catch(() => [] as ActionOut[])]);
    setItems(f ? f.items.filter((x): x is AssistantItem => x.role === "assistant" && x.parts.length > 0).slice(-SHOW) : []);
    setOpen(a);
  }, []);
  useEffect(() => { void load(); }, [load]);
  // 오늘 할 일 단추로 비서에게 고르기를 보낸 뒤(공사 날짜 승인 카드): 다시 읽어요
  useEffect(() => {
    const on = () => { void load(); };
    window.addEventListener(VENDOR_ASSISTANT_EVENT, on);
    return () => window.removeEventListener(VENDOR_ASSISTANT_EVENT, on);
  }, [load]);

  // 요청 화면의 v3 단추(기간 답하기 · 못 받아요 · 공사 날짜)를 누른 뒤: 같은 일을 하던 열린 카드는 '처리됨'(요청 · 공사마다 따로라
  // 쓰기 주소의 대상 id와 같은 카드만, 대상 id가 없는 옛 행동은 그 종류 열린 카드가 하나뿐일 때만, handledByWrite), 그리고 다시 읽어요
  useEffect(() => {
    const on = (e: Event) => {
      const { method, path } = (e as CustomEvent<ApiWrite>).detail ?? { method: "", path: "" };
      const kinds = vendorKindsForWrite(method, path);
      if (!kinds.length) return;
      const ids = handledByWrite(kinds, openRef.current, targetOfWrite(method, path));
      if (ids.length) setHandled((h) => ({ ...h, ...Object.fromEntries(ids.map((x) => [x, true as const])) }));
      void load();
    };
    window.addEventListener(API_WRITE_EVENT, on);
    return () => window.removeEventListener(API_WRITE_EVENT, on);
  }, [load]);

  const put = (a: ActionOut) => setAll((m) => ({ ...m, [a.action_id]: a }));
  const fail = (id: string, msg: string | null) => setErrors((x) => { const { [id]: _, ...rest } = x; return msg ? { ...rest, [id]: msg } : rest; });

  async function approve(a: ActionOut) {
    setPending((x) => ({ ...x, [a.action_id]: true }));
    fail(a.action_id, null);
    try {
      const done = await approveVendorAction(a.action_id, newClientKey(), a.target_ver ?? null);
      put(done);
      if (done.status === "executed") router.refresh();
    } catch (e) {
      fail(a.action_id, errorText(e));
      if (e instanceof ApiError && e.status === 409) {
        const fresh = await listVendorActions().catch(() => [] as ActionOut[]);
        const cur = fresh.find((x) => x.action_id === a.action_id);
        if (cur) put(cur);
      }
    } finally {
      setPending((x) => { const { [a.action_id]: _, ...rest } = x; return rest; });
      void load();
    }
  }
  async function reject(a: ActionOut) {
    setPending((x) => ({ ...x, [a.action_id]: true }));
    try { put(await rejectVendorAction(a.action_id)); } catch (e) { fail(a.action_id, errorText(e)); } finally {
      setPending((x) => { const { [a.action_id]: _, ...rest } = x; return rest; });
    }
  }

  const inFeed = new Set(items.flatMap((it) => it.parts.flatMap((x) => (x.t === "action" ? [x.action.action_id] : []))));
  const orphans = open.filter((a) => !inFeed.has(a.action_id));
  if (!items.length && !orphans.length) return null;

  const card = (a0: ActionOut) => {
    const a = all[a0.action_id] ?? a0;
    return (
      <ApprovalCard key={a.action_id} action={a} now={now} busy={!!pending[a.action_id]} handled={!!handled[a.action_id]} error={errors[a.action_id] ?? null}
        onApprove={() => { void approve(a); }} onReject={() => { void reject(a); }} />
    );
  };
  const part = (x: FeedPart, i: number) => {
    if (x.t === "action") return card(x.action);
    if (x.t === "text") return <p key={i} className={p.say}>{x.src === "ai" ? <I n="sparkle" /> : null}{x.text}</p>;
    if (x.t === "card" && x.card.kind === "vendor_brief") {
      const vid = (x.card.data as { visit_id: string }).visit_id;
      return <Link key={i} className={k.text} href={`/vendor/requests/${encodeURIComponent(vid)}`}>요청 브리핑 보기<I n="chev" /></Link>;
    }
    if (x.t === "card" && x.card.kind === "quote_checklist") {
      const vid = (x.card.data as { visit_id: string }).visit_id;
      return <Link key={i} className={k.text} href={`/vendor/requests/${encodeURIComponent(vid)}/quote`}>견적서 체크리스트 보기<I n="chev" /></Link>;
    }
    return null;
  };

  return (
    <section className={`${k.card} ${p.feed}`} aria-labelledby="vfeed-t">
      <div className={k.top}>
        <h3 id="vfeed-t">비서 소식</h3>
        <SourceTag src="guide" />
      </div>
      {orphans.map(card)}
      {items.map((it) => <div key={it.id} className={p.feedItem}>{it.parts.map(part)}</div>)}
    </section>
  );
}
