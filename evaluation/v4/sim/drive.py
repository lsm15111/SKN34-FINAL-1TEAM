"""비서 턴 · 화면 · 승인 버튼을 ASGI로 부르고 SSE를 읽어요(시뮬레이터 · 레드팀이 같이 써요).

- 턴: 고객 POST /assistant/turns(project_id), 업체 POST /vendor/assistant/turns(visit_id는 있으면).
- 보인 글(shown): token 글 + card data + action 요약 + status 글 + error 문장. 누출 · 금지 말 확인은 이 글로 해요.
- 턴 흔적: assistant_turns(status · mode · tool_calls · trace.tools 이름 · trace.llm)과 ToolTap의 도구 입력.
- 비용: llm_usage(장부) 합. 판마다 DB를 비우니 합이 곧 그 판 비용이에요.
"""

import json
import uuid

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
            "select status, mode, tool_calls, trace, error_code from assistant_turns where id = $1",
            uuid.UUID(tid),
        )
        if tid
        else []
    )
    t = dict(row[0]) if row else {}
    trace = _trace(t.get("trace"))
    tokens = "".join(d.get("text") or "" for n, d in ev if n == "token")
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
        cards=[c.get("kind") for c in cards],
        card_data=[{"kind": c.get("kind"), "data": c.get("data")} for c in cards],
        actions=[
            {"id": d.get("action_id"), "kind": d.get("kind"), "status": d.get("status")}
            for n, d in ev
            if n == "action"
        ],
        text=(tokens or answer)[:TEXT_KEEP],
        shown=shown_of(ev),
        tool_args=app.tap.take(tid) if tid else [],
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


def usage(app) -> dict:
    """장부(llm_usage) 합: 유료 호출 수 · 비용 · 웹 검색 수."""
    row = app.query(
        "select count(*) as n, coalesce(sum(cost_micros), 0) as micros,"
        " coalesce(sum(web_searches), 0) as web from llm_usage"
    )[0]
    return {"calls": int(row["n"]), "cost_usd": int(row["micros"]) / 1e6, "web": int(row["web"])}
