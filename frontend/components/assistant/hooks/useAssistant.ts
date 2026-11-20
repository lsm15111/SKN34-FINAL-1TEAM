"use client";
// 비서 대화 상태 한 곳: feed 읽기 · 턴(SSE) 이어 붙이기 · 승인(멱등 키 · 본 판 · 409 · 만료) · 먼저 말 걸기 · 보드.
// 대화 원본은 서버 feed예요. 새로 고치면 feed로 다시 그리고, 카드 값은 서버가 바꿔 보내요(화면은 계산하지 않아요).
import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyTurnEvent, approveAction, dismissNudge as dismissApi, forgetMemory, getBoard, getFeed, newClientKey, rejectAction, replaceAction,
  replaceCard, resetMock, searchAddress, seqFilter, streamTurn, subscribeTurns,
  type ActionOut, type BoardOut, type FeedItem, type TurnEvent, type TurnIn,
} from "@/lib/api/assistant";
import { ApiError, errorText } from "@/lib/backend/client";
import { useStream } from "@/lib/backend/stream";
import { ASSISTANT_MOCK } from "@/lib/mock/assistant/mode";

export type Assistant = ReturnType<typeof useAssistant>;

export function useAssistant(projectId: string) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [chips, setChips] = useState<string[]>([]);
  const [now, setNow] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [board, setBoard] = useState<BoardOut | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [flash, setFlash] = useState(0);
  const nowRef = useRef("");
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  nowRef.current = now;

  const boardKey = useRef("");
  const refreshBoard = useCallback(async () => {
    try {
      const b = await getBoard(projectId);
      const key = JSON.stringify(b);
      // 값이 바뀌면 보드를 0.5초 반짝여요(처음 읽을 때는 빼고)
      if (boardKey.current && boardKey.current !== key) setFlash((n) => n + 1);
      boardKey.current = key;
      setBoard(b);
    } catch { /* 보드는 다음 소식 때 다시 읽어요 */ }
  }, [projectId]);

  const load = useCallback(async () => {
    try {
      const page = await getFeed(projectId);
      setItems(page.items);
      setChips(page.chips);
      setNow(page.now);
      setLoadError(null);
    } catch (e) {
      setLoadError(errorText(e));
    } finally {
      setLoaded(true);
    }
    void refreshBoard();
  }, [projectId, refreshBoard]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  /** 이벤트 하나 반영(사용자 턴 · 서버가 먼저 보낸 턴 같은 길) */
  const apply = useCallback((turnId: string, ev: TurnEvent) => {
    if (ev.type === "ack" && ev.data.at) setNow(ev.data.at);
    setItems((cur) => applyTurnEvent(cur, turnId, ev, nowRef.current || new Date().toISOString()));
    if (ev.type === "done") {
      if (ev.data.chips) setChips(ev.data.chips);
      void refreshBoard();
    }
  }, [refreshBoard]);

  // 목업: 서버가 먼저 보내는 턴(승인 뒤 이어지는 일 · 먼저 말 걸기). 턴마다 seq를 따로 걸러요
  useEffect(() => {
    const filters = new Map<string, (e: TurnEvent) => void>();
    return subscribeTurns(projectId, (turnId, e) => {
      let f = filters.get(turnId);
      if (!f) { f = seqFilter((x) => apply(turnId, x)); filters.set(turnId, f); }
      f(e);
    });
  }, [projectId, apply]);

  // 실제: 실시간 한 줄기(/stream)의 상태 소식이 오면 feed · 보드를 다시 읽어요(턴이 도는 중이면 끝난 뒤)
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useStream(["state", "notif", "resync"], () => {
    if (ASSISTANT_MOCK) return;
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
    reloadTimer.current = setTimeout(() => { if (!runningRef.current) void load(); }, 400);
  });

  const send = useCallback(async (text: string, context?: TurnIn["context"]) => {
    const t = text.trim();
    if (!t || runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    const key = newClientKey();
    setItems((cur) => [...cur, { id: `u-${key}`, role: "user", at: nowRef.current || new Date().toISOString(), text: t }]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    let turnId = "";
    try {
      await streamTurn({ project_id: projectId, client_key: key, text: t, context: context ?? null }, (ev) => {
        if (ev.type === "ack") turnId = ev.data.turn_id;
        if (turnId) apply(turnId, ev);
      }, ctl.signal);
    } catch (e) {
      // 스트림을 열기 전 오류(409 turn_running · 429 · 404)는 대화에 실패 말로 남겨요
      const msg = e instanceof ApiError && e.code === "turn_running" ? "앞 답을 만드는 중이에요. 끝나면 다시 보내 주세요." : errorText(e);
      setItems((cur) => [...cur, { id: `a-fail-${key}`, role: "assistant", at: nowRef.current, turn_id: null, parts: [], done: true, error: { code: "send", message: msg } }]);
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }, [projectId, apply]);

  const approve = useCallback(async (a: ActionOut | string) => {
    const id = typeof a === "string" ? a : a.action_id;
    const ver = typeof a === "string" ? null : a.target_ver ?? null;
    setPending((p) => ({ ...p, [id]: true }));
    setErrors((x) => { const { [id]: _, ...rest } = x; return rest; });
    try {
      const done = await approveAction(projectId, id, { client_key: newClientKey(), seen: ver });
      setItems((cur) => replaceAction(cur, done));
      void refreshBoard();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && /changed|stale|version/.test(e.code)) {
        // 판이 바뀌었어요: 서버가 새 판 + 차액으로 만든 행동을 다시 읽어 그 자리에 그려요
        await load();
      } else {
        setErrors((x) => ({ ...x, [id]: errorText(e) }));
      }
    } finally {
      setPending((p) => { const { [id]: _, ...rest } = p; return rest; });
    }
  }, [projectId, load, refreshBoard]);

  const reject = useCallback(async (a: ActionOut) => {
    setPending((p) => ({ ...p, [a.action_id]: true }));
    try {
      const done = await rejectAction(projectId, a.action_id);
      setItems((cur) => replaceAction(cur, done));
    } catch (e) {
      setErrors((x) => ({ ...x, [a.action_id]: errorText(e) }));
    } finally {
      setPending((p) => { const { [a.action_id]: _, ...rest } = p; return rest; });
    }
  }, [projectId]);

  /** [오늘은 그만]: 서버가 바뀐 카드를 주면 그 카드만, 아니면 feed를 다시 읽어요 */
  const dismissNudge = useCallback(async (_cardId: string, nudgeId: string) => {
    try {
      const card = await dismissApi(projectId, nudgeId);
      if (card) setItems((cur) => replaceCard(cur, card));
      else await load();
      void refreshBoard();
    } catch { /* 닫기 실패는 다음에 다시 보여요 */ }
  }, [projectId, load, refreshBoard]);

  const forget = useCallback(async (memoryId: string) => {
    try { await forgetMemory(projectId, memoryId); } finally { void refreshBoard(); }
  }, [projectId, refreshBoard]);

  const reset = useCallback(async (script: "f1" | "today") => {
    abortRef.current?.abort();
    await resetMock(projectId, script);
    await load();
  }, [projectId, load]);

  const actionOf = useCallback((id: string): ActionOut | null => {
    for (const it of items) {
      if (it.role !== "assistant") continue;
      for (const p of it.parts) if (p.t === "action" && p.action.action_id === id) return p.action;
    }
    return null;
  }, [items]);

  return {
    projectId, items, chips, now, loaded, loadError, running, board, pending, errors, flash,
    send, approve, reject, dismissNudge, forget, reset, reload: load, actionOf, searchAddress,
  };
}
