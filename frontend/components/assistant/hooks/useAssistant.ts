"use client";
// 비서 대화 상태 한 곳: 다시 열기(threads/latest · feed · board · today) · 턴(SSE) 이어 붙이기 · 끊기면 같은 client_key로 다시 잇기 ·
// 승인(멱등 키 · 본 판 · 409 · 만료) · 먼저 말 걸기(nudges) · 무료 모드 · 전체 화면 카드 안 v3 단추 뒤 다시 읽기.
// 대화 원본은 서버 feed예요. 카드 값은 서버가 바꿔 보내요(화면은 계산하지 않아요).
// 실시간: 이 공사 상태 소식(state) · 다시 이음(resync)이 오면 대화 기록을 다시 읽어요. 먼저 말 걸기를 보내거나 닫아도 대화 번호표(rev)는
// 그대로라 번호표만 보면 문장 · 카드를 놓쳐요. 턴이 도는 중에 온 소식은 턴이 끝난 뒤 읽어요.
// 턴을 시작하면 그 전에 시작한 기록 읽기 결과는 버리고 턴이 끝난 뒤 다시 읽어요(보낸 말 · 흘러오는 답을 덮지 않게).
// 화면이 만든 말(오늘 정할 일 · 기록 밖 열린 승인 카드)은 처음 열 때 마지막 말 뒤에 두고, 새 말은 그 아래에 붙어요.
// 그 자리에 보인 오늘 정할 일 · 첫 인사는 첫 말을 보낸 뒤에도 그 자리에 그대로 둬요(같은 날 카드가 턴으로 와도 값만 바꿔요).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  actionsIn, anchorIndex, applyTurnEvent, approveAction, dismissNudge as dismissApi, foldCards, getBoard, getFeed, getHealth,
  getLatestThread, getToday, handledByTarget, handledByWrite, keepOlder, kindsForWrite, listActions, newClientKey, openNudge as openApi,
  rejectAction, replaceAction, resetMock, resetTurn, sayable, seqFilter, settledNudges, streamTurn, subscribeTurns, takeToday, targetOfWrite,
  turnErrorText, BUSY_TEXT, TURN_RETRY_MS, TurnBusy,
  type ActionOut, type AssistantItem, type BoardOut, type FeedItem, type HealthOut, type TodayData, type TurnEvent, type TurnIn,
} from "@/lib/api/assistant";
import { API_WRITE_EVENT, ApiError, errorText, type ApiWrite } from "@/lib/backend/client";
import { useStream } from "@/lib/backend/stream";
import { dateSeoul } from "@/lib/format";
import { ASSISTANT_MOCK } from "@/lib/mock/assistant/mode";
import { useToast } from "@/components/ui/Toast";

export type Assistant = ReturnType<typeof useAssistant>;

/** 처음 대화(기록 없음)일 때 빠른 답 칩: 업체 추천 + 도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기(QA r7 첫 인사) */
const FIRST_CHIPS = ["업체 추천해 줘", "공사는 어떤 순서로 해요?", "직접 할 수 있는 일 있어요?", "집 정보 바꾸고 싶어요"];
const LOST = "연결이 끊겼어요. 대화를 다시 불러올게요.";
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const handledKey = (pid: string) => `mj_v4_handled:${pid}`;

class Dropped extends Error {}

export function useAssistant(projectId: string) {
  const toast = useToast();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [olderBusy, setOlderBusy] = useState(false);
  /** 처음 열 때 대화가 비어 첫 인사를 보였어요. 이 화면에서는 첫 말을 보낸 뒤에도 그대로 둬요(인사 줄이 사라지며 튀지 않게, QA r3 v1 L2) */
  const [greet, setGreet] = useState(false);
  const [chips, setChips] = useState<string[]>([]);
  const [now, setNow] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [board, setBoard] = useState<BoardOut | null>(null);
  /** 마지막 보드 읽기가 실패했어요(읽어 둔 보드가 없으면 보드 자리에 '다시 불러오기') */
  const [boardFailed, setBoardFailed] = useState(false);
  const [today, setToday] = useState<TodayData | null>(null);
  const [open, setOpen] = useState<ActionOut[]>([]);
  /** 기록 밖(열린 승인 카드 묶음)에서 승인 · 거절한 행동의 지금 모습: 열린 목록에서 빠져도 결과 카드로 남겨요 */
  const [kept, setKept] = useState<Record<string, ActionOut>>({});
  const [handled, setHandled] = useState<Record<string, true>>({});
  const [health, setHealth] = useState<HealthOut | null>(null);
  const [gone, setGone] = useState<Record<string, true>>({});
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [flash, setFlash] = useState(0);
  const nowRef = useRef("");
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const revRef = useRef<number | null>(null);
  /** 화면이 만든 말 자리: 처음 열었을 때 마지막 말(비었으면 null = 맨 앞). 한 번 정하면 그대로 둬요 */
  const [anchor, setAnchor] = useState<{ id: string; at: string } | null>(null);
  /** 처음 열었을 때 오늘 말이 없었어요: 오늘 정할 일을 그 자리(그날 첫 비서 말)에 보여요 */
  const [todayFirst, setTodayFirst] = useState(false);
  /** 그 자리에 오늘 정할 일을 보인 날짜: 그날 오늘 정할 일 카드가 턴으로 다시 와도 그 자리에 두고 값만 바꿔요(takeToday, QA r3 v1 L2) */
  const [pin, setPin] = useState<string | null>(null);
  const anchored = useRef(false);
  /** '앞 대화 더 보기'로 앞 쪽을 붙였어요(첫 쪽을 다시 읽을 때 그대로 둬요) */
  const olderRef = useRef(false);
  /** 턴이 도는 중에 온 다시 읽기(끝난 뒤 한 번). true면 번호표와 상관없이 기록을 다시 읽어요 */
  const syncLater = useRef<boolean | null>(null);
  /** 턴을 시작할 때마다 올려요. 읽기를 시작한 뒤 바뀌었으면 그 읽기 결과는 버려요 */
  const genRef = useRef(0);
  const itemsRef = useRef<FeedItem[]>([]);
  const openRef = useRef<ActionOut[]>([]);
  nowRef.current = now;
  itemsRef.current = items;
  openRef.current = open;

  const fail = (id: string, msg: string | null) => setErrors((x) => { const { [id]: _, ...rest } = x; return msg ? { ...rest, [id]: msg } : rest; });

  // 화면(v3 단추)에서 처리한 행동 id: 이 탭에만 둬요(서버 행은 그대로라 새 탭에서는 다시 열린 카드로 보여요)
  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(handledKey(projectId));
      const ids: unknown = raw ? JSON.parse(raw) : [];
      if (Array.isArray(ids)) setHandled(Object.fromEntries(ids.filter((x): x is string => typeof x === "string").map((x) => [x, true as const])));
    } catch { /* 편의 기능이라 넘어가요 */ }
  }, [projectId]);
  const markHandled = useCallback((ids: string[]) => {
    if (!ids.length) return;
    setHandled((cur) => {
      const next = { ...cur, ...Object.fromEntries(ids.map((x) => [x, true as const])) };
      try { window.sessionStorage.setItem(handledKey(projectId), JSON.stringify(Object.keys(next).slice(-50))); } catch { /* 편의 */ }
      return next;
    });
  }, [projectId]);

  const boardKey = useRef("");
  const refreshBoard = useCallback(async () => {
    try {
      const b = await getBoard(projectId);
      const key = JSON.stringify(b);
      // 값이 바뀌면 보드를 0.5초 반짝여요(처음 읽을 때는 빼고)
      if (boardKey.current && boardKey.current !== key) setFlash((n) => n + 1);
      boardKey.current = key;
      setBoard(b);
      setBoardFailed(false);
    } catch {
      // 읽어 둔 보드가 있으면 그대로 두고 다음 소식 때 다시 읽어요. 처음 읽기가 실패하면 보드가 '다시 불러오기'를 보여요(QA r6 H2)
      setBoardFailed(true);
    }
  }, [projectId]);
  /** 보드 '다시 불러오기': 다시 읽는 동안은 '불러오고 있어요'로 돌아가요 */
  const retryBoard = useCallback(() => {
    setBoardFailed(false);
    void refreshBoard();
  }, [refreshBoard]);

  /** 보드 · 오늘 정할 일 · 열린 대기 행동 · 무료 모드(대화 옆 값들) */
  const refreshSide = useCallback(async () => {
    await Promise.all([
      refreshBoard(),
      getToday(projectId).then(setToday).catch(() => undefined),
      listActions(projectId, "proposed").then(setOpen).catch(() => undefined),
      getHealth().then(setHealth),
    ]);
  }, [projectId, refreshBoard]);

  /** 버린 읽기를 다시 할 때(턴이 이미 끝났으면) 부를 later. later가 loadFeed 뒤에 만들어져서 ref로 이어요 */
  const laterRef = useRef<(force: boolean, ms?: number) => void>(() => undefined);

  /** 대화 기록 첫 쪽. 대화가 없으면(처음) 비우고 처음 칩을 보여요. 앞 쪽을 읽어 뒀으면 그 앞에 그대로 이어 붙여요.
   *  읽는 사이 턴이 시작됐으면 결과를 버리고(보낸 말 · 흘러오는 답을 지우지 않게) 턴이 끝난 뒤 다시 읽어요 */
  const loadFeed = useCallback(async () => {
    const gen = genRef.current;
    const [thread, page] = await Promise.all([getLatestThread(projectId), getFeed(projectId)]);
    if (gen !== genRef.current || runningRef.current) {
      if (runningRef.current) syncLater.current = true;
      else laterRef.current(true, 300);
      return;
    }
    if (olderRef.current) {
      setItems((cur) => foldCards(keepOlder(cur, page.items)));
    } else {
      setItems(foldCards(page.items));
      setBefore(page.before);
    }
    setNow(page.now);
    setChips(page.items.length ? page.chips : FIRST_CHIPS);
    revRef.current = thread ? thread.rev : 0;
    if (!anchored.current) {
      anchored.current = true;
      setGreet(!thread && !page.items.length);
      const last = page.items[page.items.length - 1];
      setAnchor(last ? { id: last.id, at: last.at } : null);
      const day = dateSeoul(page.now);
      setTodayFirst(!page.items.some((it) => dateSeoul(it.at) === day));
    }
  }, [projectId]);

  const load = useCallback(async () => {
    olderRef.current = false;
    try {
      await loadFeed();
      setLoadError(null);
    } catch (e) {
      setLoadError(errorText(e));
    } finally {
      setLoaded(true);
    }
    void refreshSide();
  }, [loadFeed, refreshSide]);

  useEffect(() => {
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  /** 서버 쪽이 바뀌었을 수 있을 때(실시간 소식 · v3 단추 뒤): 대화가 바뀌었으면(rev · force) 기록을 다시 읽고 옆 값들을 새로 읽어요.
   *  턴이 도는 중이면 버리지 않고 턴이 끝난 뒤로 미뤄요 */
  const resync = useCallback(async (force = false) => {
    if (runningRef.current) { syncLater.current = !!syncLater.current || force; return; }
    try {
      const t = await getLatestThread(projectId);
      if (force || (t?.rev ?? 0) !== (revRef.current ?? 0)) await loadFeed();
    } catch { /* 다음 소식 때 다시 해요 */ }
    void refreshSide();
  }, [projectId, loadFeed, refreshSide]);

  /** 이벤트 하나 반영(사용자 턴 · 서버가 먼저 보낸 턴 같은 길) */
  const apply = useCallback((turnId: string, ev: TurnEvent) => {
    if (ev.type === "ack") {
      genRef.current += 1; // 서버가 먼저 보낸 턴(목업)도 그 전에 시작한 읽기 결과로 덮지 않아요
      if (ev.data.at) setNow(ev.data.at);
    }
    setItems((cur) => applyTurnEvent(cur, turnId, ev, nowRef.current || new Date().toISOString()));
    if (ev.type === "done") {
      if (ev.data.chips?.length) setChips(ev.data.chips);
      if (typeof ev.data.rev === "number") revRef.current = ev.data.rev;
      void refreshSide();
    }
  }, [refreshSide]);

  // 목업: 서버가 먼저 보내는 턴(승인 뒤 이어지는 일 · 먼저 말 걸기). 턴마다 seq를 따로 걸러요
  useEffect(() => {
    const filters = new Map<string, (e: TurnEvent) => void>();
    return subscribeTurns(projectId, (turnId, e) => {
      let f = filters.get(turnId);
      if (!f) { f = seqFilter((x) => apply(turnId, x)); filters.set(turnId, f); }
      f(e);
    });
  }, [projectId, apply]);

  // 실제: 실시간 한 줄기(/stream). 이 공사 상태 소식(state, 업체 답 · 먼저 말 걸기 보냄 · 할 일이 끝나 닫음)과 다시 이음(resync)은
  // 대화 기록을 다시 읽어요(먼저 말 걸기는 rev를 올리지 않아요). 알림 수(notif)는 바뀌었을 때만(rev). 턴이 도는 중이면 끝난 뒤.
  // 잇따라 오면 마지막 것 하나로 모으되, 기록을 다시 읽을 일(force)은 잃지 않아요
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reloadForce = useRef(false);
  const later = useCallback((force: boolean, ms = 400) => {
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
    reloadForce.current = reloadForce.current || force;
    reloadTimer.current = setTimeout(() => {
      const f = reloadForce.current;
      reloadForce.current = false;
      void resync(f);
    }, ms);
  }, [resync]);
  laterRef.current = later;
  useStream(["state", "notif", "resync"], (e) => {
    if (ASSISTANT_MOCK) return;
    if (e.type === "notif") { later(false); return; }
    if (e.type === "state" && e.data.project_id && e.data.project_id !== projectId) return;
    later(true);
  });

  // 전체 화면 카드 안 v3 단추(사람이 누른 확정 · 수락)가 쓰기를 마치면: 같은 일을 하던 열린 승인 카드는 '처리됨'(어느 카드인지 알 때만),
  // 그리고 대화 · 보드 · 열린 대기 행동을 다시 읽어요
  useEffect(() => {
    const on = (e: Event) => {
      const { method, path } = (e as CustomEvent<ApiWrite>).detail ?? { method: "", path: "" };
      if (!path.startsWith(`/projects/${projectId}`)) return;
      const kinds = kindsForWrite(method, path, projectId);
      if (kinds.length) markHandled(handledByWrite(kinds, [...actionsIn(itemsRef.current), ...openRef.current], targetOfWrite(method, path)));
      later(true, 300);
    };
    window.addEventListener(API_WRITE_EVENT, on);
    return () => window.removeEventListener(API_WRITE_EVENT, on);
  }, [projectId, markHandled, later]);

  /** 한 턴 보내기. 넘쳐서(503 busy · unavailable) Retry-After만큼 기다렸다 같은 client_key로 한 번 다시 보내도 넘치면
   *  보낸 말을 빼고 안내한 뒤 "busy"를 돌려줘요(입력 칸이 쓴 글을 되살려요) */
  const send = useCallback(async (text: string, context?: TurnIn["context"]): Promise<"busy" | void> => {
    const t = text.trim();
    if (!sayable(t) || runningRef.current) return; // 보이지 않는 글자만 있는 글은 보내지 않아요
    runningRef.current = true;
    genRef.current += 1; // 이 턴 전에 시작한 기록 읽기 결과는 버려요
    setRunning(true);
    const key = newClientKey();
    const userId = `u-${key}`;
    setItems((cur) => [...cur, { id: userId, role: "user", at: nowRef.current || new Date().toISOString(), text: t }]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    const body: TurnIn = { project_id: projectId, client_key: key, text: t, context: context ?? null };
    let turnId = "";
    let tries = 0;
    let busyTried = false;
    const failMsg = (message: string, code = "send") =>
      setItems((cur) => [...cur, { id: `a-fail-${key}-${Date.now()}`, role: "assistant", at: nowRef.current, turn_id: null, parts: [], done: true, error: { code, message } }]);
    try {
      for (;;) {
        const again = tries > 0;
        try {
          const ended = await streamTurn(body, (ev) => {
            if (ev.type === "ack") {
              turnId = ev.data.turn_id;
              // 같은 client_key로 다시 이으면 서버가 저장한 것을 처음부터 보내요: 이 턴 조각을 비우고 받아요
              if (again) setItems((cur) => resetTurn(cur, turnId));
            }
            if (turnId) apply(turnId, ev);
          }, ctl.signal);
          if (ended) break;
          throw new Dropped();
        } catch (e) {
          if (ctl.signal.aborted) return;
          // 넘침(503, 턴을 만들기 전): Retry-After만큼 기다렸다 같은 client_key로 한 번 더. 또 넘치면 서버가 받지 않은 말이라
          // 보낸 말을 빼고 안내해요(입력 칸에는 글을 되살려요)
          if (e instanceof TurnBusy) {
            if (!busyTried) {
              busyTried = true;
              await wait(e.waitMs);
              if (ctl.signal.aborted) return;
              continue;
            }
            setItems((cur) => cur.filter((x) => x.id !== userId));
            failMsg(BUSY_TEXT, "busy");
            return "busy";
          }
          // 같은 client_key로 다시 잇는 중(again)에 온 409 turn_running은 내 턴이 아직 도는 거예요(ack 전에 끊겼어도)
          const ours = e instanceof ApiError && e.code === "turn_running" && (!!turnId || again);
          const drop = e instanceof Dropped || (e instanceof ApiError && e.code === "network");
          if ((drop || ours) && tries < TURN_RETRY_MS.length) {
            if (turnId) setItems((cur) => cur.map((x) => (x.role === "assistant" && x.turn_id === turnId ? { ...x, status: "연결이 끊겨 다시 잇고 있어요" } : x)));
            await wait(TURN_RETRY_MS[tries++]);
            continue;
          }
          if (drop || ours) {
            // 끝내 잇지 못했어요: 서버는 끝까지 돌려 저장해요. 대화를 다시 읽으면 보여요
            if (turnId) setItems((cur) => cur.map((x) => (x.role === "assistant" && x.turn_id === turnId ? { ...x, done: true, status: null, error: { code: "dropped", message: LOST } } : x)));
            else if (ours) failMsg(LOST, "dropped");
            else failMsg(errorText(e), "network");
            later(true, 3000);
          } else if (e instanceof ApiError && e.code === "turn_running") {
            // 다른 탭 · 앞 질문의 답이 아직 도는 중: 끝나면 대화를 다시 읽어 보여요
            failMsg(e.message || "앞 답을 만드는 중이에요. 끝나면 다시 보내 주세요.", "turn_running");
            later(false, 5000);
          } else if (e instanceof ApiError && e.status === 429) {
            failMsg(e.message, "too_many");
          } else {
            // 422면 서버 칸 글('보낼 말을 적어 주세요.')을 그대로 보여요
            failMsg(turnErrorText(e), e instanceof ApiError ? e.code : "send");
          }
          return;
        }
      }
    } finally {
      runningRef.current = false;
      setRunning(false);
      // 턴이 도는 동안 온 실시간 소식(먼저 말 걸기 등)을 이제 읽어요
      const pend = syncLater.current;
      syncLater.current = null;
      if (pend !== null) later(pend, 300);
    }
  }, [projectId, apply, later]);

  /** 기록 밖(열린 승인 카드 묶음)의 행동이면: 열린 목록도 바꾸고 결과를 그 자리에 남겨요(기록 안 행동은 replaceAction이 바꿔요) */
  const keep = useCallback((a: ActionOut) => {
    setOpen((cur) => cur.map((x) => (x.action_id === a.action_id ? a : x)));
    if (!actionsIn(itemsRef.current).some((x) => x.action_id === a.action_id)) setKept((k) => ({ ...k, [a.action_id]: a }));
  }, []);

  /** 행동 하나의 지금 상태를 서버에서 다시 읽어 그 자리에 그려요(판이 바뀌어 새 행동이 생겼으면 그 자리에 새 행동) */
  const refreshAction = useCallback(async (id: string, msg: string | null) => {
    try {
      const all = await listActions(projectId);
      const next = all.find((x) => x.supersedes === id);
      const cur = all.find((x) => x.action_id === id);
      setItems((list) => {
        let out = cur ? replaceAction(list, cur) : list;
        if (next) out = out.map((it) => (it.role === "assistant" ? { ...it, parts: it.parts.map((p) => (p.t === "action" && p.action.action_id === id ? { t: "action" as const, action: next } : p)) } : it));
        return out;
      });
      if (next && msg) fail(next.action_id, msg);
      setOpen(all.filter((x) => x.status === "proposed"));
      // 기록 밖 행동: 남겨 둔 것은 지금 모습으로, 새 판이 생겼으면 옛 것은 빼요(새 것은 열린 목록에 와요)
      const orphan = !actionsIn(itemsRef.current).some((x) => x.action_id === id);
      setKept((k) => {
        const out: Record<string, ActionOut> = {};
        for (const [kid, a] of Object.entries(k)) out[kid] = all.find((x) => x.action_id === kid) ?? a;
        if (orphan && next) delete out[id];
        else if (orphan && cur) out[id] = cur;
        return out;
      });
    } catch { /* 다음에 다시 읽어요 */ }
    if (!runningRef.current) later(true, 200);
  }, [projectId, later]);

  const approve = useCallback(async (a: ActionOut | string) => {
    const id = typeof a === "string" ? a : a.action_id;
    const known = typeof a === "string" ? actionsIn(itemsRef.current).find((x) => x.action_id === a) ?? openRef.current.find((x) => x.action_id === a) : a;
    const ver = known?.target_ver ?? null;
    setPending((p) => ({ ...p, [id]: true }));
    fail(id, null);
    try {
      const done = await approveAction(projectId, id, { client_key: newClientKey(), seen: ver });
      setItems((cur) => replaceAction(cur, done));
      keep(done);
      // 실행됐으면 결과를 보이고 대화 · 보드를 다시 읽어요(뒤따른 상태 · 다음 카드). 처리 중이면 잠시 뒤 그 행동을 다시 읽어요
      if (done.status === "executed") later(true, 250);
      else {
        if (done.status === "approved") setTimeout(() => { void refreshAction(id, null); }, 2500);
        void refreshSide();
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // 만료 · 판 바뀜(stale · quote_changed) · 닫힘 · 실패 · 처리 중: 카드를 서버의 새 상태로 바꿔요
        fail(id, e.message);
        if (e.code === "in_progress") setTimeout(() => { void refreshAction(id, null); }, 2500);
        else await refreshAction(id, e.message);
      } else if (e instanceof ApiError && e.status === 404) {
        fail(id, e.message);
        later(true, 200);
      } else {
        fail(id, errorText(e));
      }
    } finally {
      setPending((p) => { const { [id]: _, ...rest } = p; return rest; });
    }
  }, [projectId, later, keep, refreshAction, refreshSide]);

  const reject = useCallback(async (a: ActionOut) => {
    const id = a.action_id;
    setPending((p) => ({ ...p, [id]: true }));
    fail(id, null);
    try {
      const done = await rejectAction(projectId, id);
      setItems((cur) => replaceAction(cur, done));
      keep(done);
      void refreshSide();
    } catch (e) {
      fail(id, errorText(e));
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) await refreshAction(id, null);
    } finally {
      setPending((p) => { const { [id]: _, ...rest } = p; return rest; });
    }
  }, [projectId, keep, refreshAction, refreshSide]);

  /** 먼저 말 건 제안 열기([해 볼게요] · 알림 링크). API가 없으면 숨겨요 */
  const openNudge = useCallback(async (nudgeId: string) => {
    try { if (!(await openApi(projectId, nudgeId))) setGone((g) => ({ ...g, [nudgeId]: true })); } catch { /* 열기 기록 실패는 넘어가요 */ }
  }, [projectId]);
  /** [괜찮아요] · [오늘은 그만]: 닫으면 같은 일을 3일 쉬어요(제안은 숨기고 오늘 정할 일은 접어요). API가 없으면(404) 화면에서만 닫고,
   *  서버에서 닫지 못했으면 되돌려 다시 보이고 알려요(이 탭에서만 숨으면 서버에는 열린 제안이 남아요) */
  const dismissNudge = useCallback(async (_cardId: string, nudgeId: string) => {
    const fold = (on: boolean) => (d: TodayData): TodayData => (d.nudge_id === nudgeId ? { ...d, dismissed: on } : d);
    const foldAll = (on: boolean) => {
      setToday((t) => (t ? fold(on)(t) : t));
      setItems((cur) => cur.map((it) => (it.role !== "assistant" ? it : {
        ...it, parts: it.parts.map((p) => (p.t === "card" && p.card.kind === "today" ? { ...p, card: { ...p.card, data: fold(on)(p.card.data as TodayData) } } : p)),
      })));
    };
    setGone((g) => ({ ...g, [nudgeId]: true }));
    foldAll(true);
    try {
      await dismissApi(projectId, nudgeId);
    } catch {
      setGone((g) => { const { [nudgeId]: _, ...rest } = g; return rest; });
      foldAll(false);
      toast.show("닫지 못했어요. 잠시 뒤 다시 해 주세요.", { tone: "error" });
    }
    if (ASSISTANT_MOCK) await loadFeed().catch(() => undefined);
    void refreshSide();
  }, [projectId, loadFeed, refreshSide, toast]);

  /** 앞 대화 더 보기(턴 번호 커서) */
  const loadOlder = useCallback(async () => {
    if (!before || olderBusy) return;
    setOlderBusy(true);
    try {
      const page = await getFeed(projectId, before);
      setItems((cur) => {
        const have = new Set(cur.map((x) => x.id));
        return foldCards([...page.items.filter((x) => !have.has(x.id)), ...cur]);
      });
      setBefore(page.before);
      olderRef.current = true;
    } catch { /* 다시 누르면 돼요 */ } finally {
      setOlderBusy(false);
    }
  }, [projectId, before, olderBusy]);

  const reset = useCallback(async (script: "f1" | "today") => {
    abortRef.current?.abort();
    await resetMock(projectId, script);
    anchored.current = false; // 대본이 바뀌면 화면이 만든 말 자리 · 첫 인사 · 오늘 정할 일 자리도 다시 정해요
    setPin(null);
    setKept({});
    await load();
  }, [projectId, load]);

  const actionOf = useCallback((id: string): ActionOut | null =>
    actionsIn(items).find((x) => x.action_id === id) ?? kept[id] ?? open.find((x) => x.action_id === id) ?? null, [items, kept, open]);

  /** 같은 대상이 끝난 열린 승인 카드(실측 요청을 취소함 → 그 요청의 반나절 · 확정 카드): 단추를 숨겨요(서버 정리 전에도) */
  const ended = useMemo<Record<string, true>>(
    () => Object.fromEntries(handledByTarget([...actionsIn(items), ...open, ...Object.values(kept)]).map((x) => [x, true as const])),
    [items, open, kept],
  );
  /** 처리됨으로 보일 카드: 화면 v3 단추로 한 것 + 같은 대상이 끝난 것 */
  const handledAll = useMemo<Record<string, true>>(() => ({ ...handled, ...ended }), [handled, ended]);
  /** 할 일이 끝난 먼저 말 건 줄('완료'로 그려요): 서버가 닫은 줄 + 그 줄의 승인 카드(같은 대상)를 실행 · 처리한 것(서버 정리 전에도) */
  const settled = useMemo<Record<string, true>>(
    () => Object.fromEntries(settledNudges(items, handledAll).map((x) => [x, true as const])),
    [items, handledAll],
  );
  /** 제안을 숨길 줄: 고객이 닫은 것 + 할 일이 끝난 것 */
  const shut = useMemo<Record<string, true>>(() => ({ ...gone, ...settled }), [gone, settled]);

  /** 오늘 정할 일을 그 자리에 처음 보일 때: 그날 카드가 기록에 없고 보일 줄이 있어요 */
  const todayDate = today?.date ?? null;
  const firstToday = useMemo(() => {
    if (!todayFirst || !today) return false;
    const rows = today.todo.length + today.waiting.length; // 새 알림(news)은 카드에 보이지 않아요
    const hasToday = items.some((it) => it.role === "assistant" && it.parts.some((p) => p.t === "card" && p.card.kind === "today" && (p.card.data as TodayData).date === today.date));
    return rows > 0 && !hasToday;
  }, [items, today, todayFirst]);
  useEffect(() => { if (firstToday && todayDate) setPin(todayDate); }, [firstToday, todayDate]);

  /** 보이는 대화: 기록 + 화면이 만든 말(오늘 정할 일: 그날 카드가 기록에 없을 때 · 기록에 없는 열린 승인 카드 묶음)을 처음 열 때 마지막 말 뒤에.
   *  오늘 정할 일을 그 자리에 보인 뒤 같은 날 카드가 턴으로 오면(첫 인사 등) 그 자리에서 값만 바꾸고 턴 쪽 카드는 빼요(보낸 말 위 카드가 아래로 옮겨 가지 않게) */
  const view = useMemo<FeedItem[]>(() => {
    const local: AssistantItem[] = [];
    let base = items;
    if (todayFirst && today && (firstToday || pin === today.date)) {
      const got = takeToday(items, today.date);
      base = got.items;
      local.push({ id: `today-${today.date}`, role: "assistant", at: now, turn_id: null, done: true, local: true, parts: [{ t: "card", card: { card_id: "today", kind: "today", data: got.last ?? today } }] });
    }
    const inFeed = new Set(actionsIn(items).map((a) => a.action_id));
    const shown = new Map<string, ActionOut>();
    for (const a of open) if (!inFeed.has(a.action_id)) shown.set(a.action_id, kept[a.action_id] ?? a);
    for (const a of Object.values(kept)) if (!inFeed.has(a.action_id)) shown.set(a.action_id, a);
    const orphans = [...shown.values()].filter((a) => a.kind !== "home_info");
    if (orphans.length) {
      local.push({ id: "open-actions", role: "assistant", at: now, turn_id: null, done: true, local: true, parts: orphans.map((action) => ({ t: "action" as const, action })) });
    }
    if (!local.length) return base;
    const at = anchorIndex(base, anchor);
    return [...base.slice(0, at), ...local, ...base.slice(at)];
  }, [items, open, kept, today, todayFirst, firstToday, pin, anchor, now]);

  return {
    projectId, items: view, chips, now, loaded, loadError, running, board, boardFailed, retryBoard, pending, errors, flash, handled: handledAll, ended, health,
    gone: shut, settled,
    /** 처음 열 때 대화가 비었어요(첫 인사). 이 화면에서는 첫 말을 보낸 뒤에도 그대로 보여요 */
    fresh: greet,
    /** 기록의 마지막 말(화면이 만든 말 빼고): 입력 중 표시 · 답 기다림 줄은 이 말로 정해요 */
    tail: items[items.length - 1] ?? null,
    hasOlder: !!before, olderBusy, loadOlder,
    send, approve, reject, openNudge, dismissNudge, reset, reload: load, actionOf,
  };
}
