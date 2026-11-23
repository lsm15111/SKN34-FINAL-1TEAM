"""비서 턴 · 화면 · 승인 버튼을 ASGI로 부르고 SSE를 읽어요(시뮬레이터 · 레드팀이 같이 써요).

- 턴: 고객 POST /assistant/turns(project_id), 업체 POST /vendor/assistant/turns(visit_id는 있으면).
- 보인 글(shown): token 글 + card data + action 요약 + status 글 + error 문장. 누출 · 금지 말 확인은 이 글로 해요.
- 턴 흔적: assistant_turns(status · mode · tool_calls · trace.tools 이름 · trace.llm · trace.ms)과 ToolTap의 도구 입력.
- 비용: llm_usage(장부) 줄. 판마다 DB를 비우니(app.reset) 그 전에 읽은 줄이 곧 그 판 것이에요.
  턴 비용은 turn_id로 묶어요(턴 밖 = 기억 뽑기 · 먼저 말 걸기 · 브리핑 문장). 지연은 호출마다 latency_ms예요.
- worker 한 차례(tick): 기억 뽑기 일(jobs kind=assistant_memory)과 비서 정리(만료 · 먼저 말 걸기)를 앱과 같은
  이벤트 루프에서 돌려요. 운영 worker는 1분 · 2분마다 도는데, 시뮬레이터는 걸음마다 한 번 돌려요.
"""

import json
import math
import uuid
from collections import Counter

TEXT_KEEP = 800  # 기록에 남길 답 글 길이(채점은 전체 글로 해요)


def sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in (body or "").strip().split("\n\n"):
        f: dict[str, str] = {}
        for line in block.splitlines():
            k, _, v = line.partition(": ")
            f[k] = v
        if "event" in f and "data" in f:
            try:
                out.append((f["event"], json.loads(f["data"])))
            except ValueError:
                continue
    return out


def shown_of(ev: list[tuple[str, dict]]) -> str:
    parts = []
    for name, d in ev:
        if name == "token":
            parts.append(d.get("text") or "")
        elif name == "card":
            parts.append(json.dumps(d.get("data"), ensure_ascii=False))
        elif name == "action":
            parts.append(json.dumps(d.get("summary"), ensure_ascii=False))
        elif name in ("status", "error"):
            parts.append(d.get("text") or d.get("message") or "")
    return "\n".join(p for p in parts if p)


def _err(r) -> str:
    try:
        return (r.json().get("error") or {}).get("code") or ""
    except ValueError:
        return ""


def _trace(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return raw or {}


def turn(
    app,
    world,
    who: dict,
    surface: str,
    text: str,
    *,
    project_id: str | None = None,
    visit_id: str | None = None,
    context: dict | None = None,
) -> dict:
    """비서 한 턴. 돌려주는 것: 기록 한 줄(보인 글 shown 포함)."""
    world.as_(who)
    body: dict = {"client_key": uuid.uuid4().hex, "text": text}
    if context:
        body["context"] = context
    if surface == "customer":
        body["project_id"] = project_id
        r = app.api.post("/assistant/turns", json=body)
    else:
        if visit_id:
            body["visit_id"] = visit_id
        r = app.api.post("/vendor/assistant/turns", json=body)
    rec: dict = {"kind": "say", "say": text, "http": r.status_code}
    if r.status_code != 200:
        rec.update(error=_err(r), shown="", tools=[], tool_calls=0, llm=0, actions=[], cards=[])
        return rec
    ev = sse(r.text)
    names = [n for n, _ in ev]
    tid = ev[0][1].get("turn_id") if ev and ev[0][0] == "ack" else None
    done = next((d for n, d in ev if n == "done"), {})
    err = next((d for n, d in ev if n == "error"), None)
    row = (
        app.query(
            "select status, mode, tool_calls, trace, error_code, chat_id::text as chat_id"
            " from assistant_turns where id = $1",
            uuid.UUID(tid),
        )
        if tid
        else []
    )
    t = dict(row[0]) if row else {}
    trace = _trace(t.get("trace"))
    tokens = "".join(d.get("text") or "" for n, d in ev if n == "token")
    taken = app.tap.take(tid) if tid else []
    facts = app.tap.take_facts()  # 이 턴에 비서가 받은 턴 사실(판정 에이전트 근거)
    cards = [d for n, d in ev if n == "card"]
    answer = next(
        (
            c["data"].get("text") or ""
            for c in cards
            if c.get("kind") == "answer" and isinstance(c.get("data"), dict)
        ),
        "",
    )
    rec.update(
        turn_id=tid,
        chat_id=t.get("chat_id"),
        events=names,
        mode=done.get("mode") or t.get("mode"),
        turn_status=t.get("status"),
        stopped=bool(done.get("stopped")),
        error=(err or {}).get("code") or t.get("error_code"),
        reason=trace.get("reason"),
        tool_calls=t.get("tool_calls") or 0,
        tools=[x.get("name") for x in trace.get("tools") or []],
        tools_ok=[x.get("name") for x in trace.get("tools") or [] if x.get("ok")],
        llm=trace.get("llm") or 0,
        ms=trace.get("ms"),
        cards=[c.get("kind") for c in cards],
        card_data=[
            {"card_id": c.get("card_id"), "kind": c.get("kind"), "data": c.get("data")}
            for c in cards
        ],
        actions=[
            {"id": d.get("action_id"), "kind": d.get("kind"), "status": d.get("status")}
            for n, d in ev
            if n == "action"
        ],
        text=(tokens or answer)[:TEXT_KEEP],
        shown=shown_of(ev),
        tool_args=[{k: v for k, v in x.items() if k not in ("seen", "error")} for x in taken],
        # 도구 결과는 따로(시나리오 점검 no_tool_args가 입력만 보게): 판정 에이전트의 근거
        tool_out=[
            {"name": x["name"], "seen": x.get("seen"), "error": x.get("error")} for x in taken
        ],
        facts=facts,
    )
    return rec


SCREEN_URL = {
    "vendor_brief": "/vendor/assistant/briefs/{visit_id}",
    "vendor_checklist": "/vendor/assistant/checklists/{visit_id}",
    "vendor_today": "/vendor/assistant/today",
    "customer_today": "/assistant/today",
    "customer_board": "/assistant/board",
}


def screen(app, world, who: dict, name: str, *, project_id=None, visit_id=None) -> dict:
    """화면 열기(LLM 없음). 업체 요청 브리핑은 코드가 기간 답하기 제안을 만들어요."""
    world.as_(who)
    url = SCREEN_URL[name].format(visit_id=visit_id)
    params = {"project_id": project_id} if name.startswith("customer_") else None
    r = app.api.get(url, params=params)
    rec: dict = {"kind": "screen", "screen": name, "http": r.status_code}
    if r.status_code != 200:
        rec.update(error=_err(r), shown="")
        return rec
    data = r.json()
    rec["shown"] = json.dumps(data, ensure_ascii=False)
    sug = data.get("suggest") if isinstance(data, dict) else None
    rec["actions"] = [{"id": sug.get("action_id"), "kind": "window_answer"}] if sug else []
    return rec


def prefix(surface: str) -> str:
    return "/assistant" if surface == "customer" else "/vendor/assistant"


def open_actions(app, world, who: dict, surface: str, project_id: str | None) -> list[dict]:
    world.as_(who)
    params = {"status": "proposed"}
    if surface == "customer" and project_id:
        params["project_id"] = project_id
    r = app.api.get(f"{prefix(surface)}/actions", params=params)
    return r.json() if r.status_code == 200 else []


def press(app, world, who: dict, surface: str, action: dict, do: str) -> dict:
    """승인(화면이 본 판 seen을 같이 보냄) · 거절."""
    world.as_(who)
    aid = action["action_id"]
    if do == "approve":
        body = {"client_key": uuid.uuid4().hex, "seen": action.get("target_ver")}
        r = app.api.post(f"{prefix(surface)}/actions/{aid}/approve", json=body)
    else:
        r = app.api.post(f"{prefix(surface)}/actions/{aid}/reject")
    out = {"http": r.status_code, "code": _err(r)}
    if r.status_code == 200:
        out["status"] = r.json().get("status")
    return out


def payload_of(app, action_id: str) -> dict:
    rows = app.query("select payload from assistant_actions where id = $1", uuid.UUID(action_id))
    raw = rows[0]["payload"] if rows else {}
    return _trace(raw)


def proposal_dates(app, proposal_id: str | None) -> dict:
    if not proposal_id:
        return {}
    rows = app.query(
        "select start_date, end_date from date_proposals where id = $1", uuid.UUID(proposal_id)
    )
    if not rows:
        return {}
    return {"start": rows[0]["start_date"].isoformat(), "end": rows[0]["end_date"].isoformat()}


MEMORY_KIND = "assistant_memory"


def llm_off() -> bool:
    """지금 앱이 LLM을 못 부르는지(무료 모드). 기억이 비었을 때 까닭을 적는 데 써요."""
    from app.agent import llm

    return not llm.available()


async def _memory_jobs(now) -> dict[str, int]:
    """기한이 된 기억 뽑기 일만 거둬 worker와 같은 함수(_run_one)로 처리해요. 결과 이름 → 수."""
    from app import worker
    from app.db import SessionLocal
    from app.jobs import service as jobs

    async with SessionLocal() as s:
        claimed = await jobs.claim(s, now, limit=50, kinds=[MEMORY_KIND])
        await s.commit()
    out: dict[str, int] = {}
    for job in claimed:
        got = await worker._run_one(job, now)
        out[got] = out.get(got, 0) + 1
    return out


def tick(app, nudges: bool = True) -> dict:
    """worker 한 차례: 기억 뽑기 일 → 비서 정리(만료 · 먼저 말 걸기 아웃박스 · 기한이 된 제안 평가).
    무료 모드라 기억 뽑기(Haiku) · 먼저 말 걸기 판정 · 문장(Haiku)은 꺼짐으로 끝나요(문장은 틀). 돌려주는 것: 0이 아닌 수."""
    from app.assistant import service as assistant_service
    from app.shared.clock import now_utc

    now = now_utc()
    out = {f"memory_{k}": v for k, v in app.call(_memory_jobs, now).items()}
    if nudges:
        out.update({k: v for k, v in app.call(assistant_service.sweep, now).items() if v})
    return out


LEDGER_SQL = (
    "select turn_id::text as turn_id, purpose, model, cost_micros, latency_ms, ok, error,"
    " input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, web_searches"
    " from llm_usage order by created_at, id"
)
TOKENS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")
TURN_USD = 0.06  # 처음 문항 어림의 턴당 비용(계약서 비서 턴 상한 llm_cap_turn_usd와 같음, 보수적)
MARGIN = 1.25  # 같은 시나리오 지난 판 최댓값에 곱하는 여유


def usage(app) -> dict:
    """장부(llm_usage) 그 판 합. app.reset()이 표를 비우니 reset 전에 불러요."""
    return usage_of([dict(r) for r in app.query(LEDGER_SQL)])


def usage_of(rows: list[dict]) -> dict:
    """장부 줄 → 판 합(글 없음): 호출 수 · 비용 · 웹 검색 · turn_id별 · 목적별 · 모델별 · 토큰 ·
    호출마다 지연(latency_ms) · 실패한 호출의 오류 종류 수."""
    micros = 0
    books: dict[str, dict[str, list[int]]] = {"turns": {}, "by_purpose": {}, "by_model": {}}
    errors: Counter[str] = Counter()
    for r in rows:
        c = int(r.get("cost_micros") or 0)
        micros += c
        for name, key in (("turns", "turn_id"), ("by_purpose", "purpose"), ("by_model", "model")):
            if r.get(key):
                b = books[name].setdefault(str(r[key]), [0, 0])
                b[0] += 1
                b[1] += c
        if r.get("ok") is False:
            errors[str(r.get("error") or "unknown")] += 1
    out: dict = {"calls": len(rows), "cost_usd": micros / 1e6,
                 "web": sum(int(r.get("web_searches") or 0) for r in rows)}  # fmt: skip
    for name, book in books.items():
        out[name] = {k: {"calls": n, "cost_usd": m / 1e6} for k, (n, m) in book.items()}
    out["tokens"] = {
        k.removesuffix("_tokens"): sum(int(r.get(k) or 0) for r in rows) for k in TOKENS
    }
    out["latency_ms"] = [int(r.get("latency_ms") or 0) for r in rows]
    out["errors"] = dict(errors)
    return out


def add_turn_costs(turns: list[dict], use: dict) -> None:
    """턴 기록에 장부의 그 턴 비용 · 호출 수를 적어요(turn_id가 있는 턴만)."""
    book = use.get("turns") or {}
    for t in turns:
        if t.get("turn_id"):
            got = book.get(t["turn_id"]) or {}
            t["cost_usd"] = round(got.get("cost_usd", 0.0), 6)
            t["ledger_calls"] = got.get("calls", 0)


def pctl(xs: list[float], q: float) -> float | None:
    """백분위(선형 보간, q는 0~1). 값이 없으면 None."""
    if not xs:
        return None
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(x, nd)


def cost_summary(rows: list[dict]) -> dict:
    """판(문항) 줄 → 비용 · 지연 요약. 턴 비용 = 장부의 그 turn_id 합(LLM을 안 부른 턴은 0).
    턴 밖 = 기억 뽑기 · 먼저 말 걸기 · 브리핑 문장. 호출 지연 = latency_ms, 턴 시간 = trace.ms
    (TestClient는 SSE를 다 받은 뒤 돌려줘서 첫 조각 시간은 못 재요)."""
    uses = [r.get("usage") or {} for r in rows]
    turns = [t for r in rows for t in r.get("turns") or [] if t.get("turn_id")]
    tc = [float(t.get("cost_usd") or 0.0) for t in turns]
    llm_tc = [float(t.get("cost_usd") or 0.0) for t in turns if t.get("ledger_calls")]
    lat = [x for u in uses for x in u.get("latency_ms") or []]
    ms = [t["ms"] for t in turns if isinstance(t.get("ms"), (int, float))]
    total = sum(float(u.get("cost_usd") or 0.0) for u in uses)
    by: dict[str, dict] = {}
    errors: Counter[str] = Counter()
    for u in uses:
        for k, v in (u.get("by_purpose") or {}).items():
            b = by.setdefault(k, {"calls": 0, "cost_usd": 0.0})
            b["calls"] += v["calls"]
            b["cost_usd"] += v["cost_usd"]
        errors.update(u.get("errors") or {})
    return {
        "cost_usd": round(total, 6),
        "calls": sum(int(u.get("calls") or 0) for u in uses),
        "turns": len(turns),
        "turns_with_llm": len(llm_tc),
        "turn_usd_median": _r(pctl(tc, 0.5)),
        "turn_usd_p90": _r(pctl(tc, 0.9)),
        "llm_turn_usd_median": _r(pctl(llm_tc, 0.5)),
        "llm_turn_usd_p90": _r(pctl(llm_tc, 0.9)),
        "outside_turns_usd": round(total - sum(tc), 6),
        "call_ms_median": _r(pctl(lat, 0.5), 0),
        "call_ms_p90": _r(pctl(lat, 0.9), 0),
        "turn_ms_median": _r(pctl(ms, 0.5), 0),
        "turn_ms_p90": _r(pctl(ms, 0.9), 0),
        "by_purpose": {
            k: {"calls": v["calls"], "cost_usd": round(v["cost_usd"], 6)}
            for k, v in sorted(by.items())
        },
        "errors": dict(sorted(errors.items())),
    }


def next_estimate(
    prev: list[float], turns: int, seen_turn_usd: float = 0.0, floor: float | None = None
) -> float:
    """다음 판(문항) 어림(달러). 같은 시나리오 지난 판이 있으면 그 최댓값 × MARGIN.
    처음이면 floor(시나리오 비용 상한 checks.max_cost_usd)와 턴 수 × 지금까지 본 턴당 비용 중 큰 값,
    floor가 없으면 턴 수 × max(TURN_USD, 지금까지 본 턴당 비용)."""
    if prev:
        return max(prev) * MARGIN
    if floor is not None:
        return max(floor, max(turns, 1) * seen_turn_usd)
    return max(turns, 1) * max(TURN_USD, seen_turn_usd)


def live_cost(app, row: dict, book, est: float) -> str | None:
    """LLM 모드 한 판(문항) 뒤: 장부 비용 · 호출 수를 행에 적고 누적(kit.Budget)을 바꿔요.
    깨진 판 · 심기 실패도 reset 전에 장부를 읽어 세요. 장부를 못 읽으면 어림으로 세고 멈출 까닭을 돌려줘요."""
    why = None
    if "usage" not in row:
        try:
            row["usage"] = usage(app)
        except Exception as e:  # noqa: BLE001 - 셀 수 없으면 더 돌리지 않아요
            row["usage_error"] = type(e).__name__
            why = "장부(llm_usage)를 읽지 못해 쓴 돈을 셀 수 없어 멈췄어요"
    use = row.get("usage") or {}
    row["cost_usd"] = round(use.get("cost_usd", est), 6)
    row["llm_calls"] = use.get("calls")
    book.settle(est, row["cost_usd"])
    return why


def cost_line(s: dict) -> str:
    """결과 출력 한 줄: 총비용 · 턴당 비용 · 지연."""
    return (f"LLM 비용 ${s['cost_usd']} · 호출 {s['calls']}회 · 턴 {s['turns']}(LLM 턴 {s['turns_with_llm']}) "
            f"· 턴당 중앙값 ${s['turn_usd_median']} · p90 ${s['turn_usd_p90']} · 턴 밖 ${s['outside_turns_usd']} "
            f"· 호출 지연 p90 {s['call_ms_p90']}ms · 턴 시간 p90 {s['turn_ms_p90']}ms")  # fmt: skip
