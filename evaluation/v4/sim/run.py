"""시나리오(sets/scenarios)를 대본 사용자로 돌려 끝 상태를 정답과 견줘요: pass^1 · pass^3.

    cd backend && uv run python ../evaluation/v4/sim/run.py --tag sim-free --trials 3
    cd backend && LLM_LIVE=true uv run python ../evaluation/v4/sim/run.py --live --max-usd 7 --tag sim-live1   # 허락 뒤

- 기본은 무료 모드(LLM_LIVE=false, 키 환경변수 비움, 유료 호출 0회).
- --live(LLM 모드): 환경변수 LLM_LIVE=true · ANTHROPIC_API_KEY와 --max-usd가 있어야 돌아요(apienv.live_mode).
  판마다 reset 전에 장부(llm_usage)를 읽어 비용 · 호출 수 · 턴 비용(turn_id) · 지연을 적어요. 누적 + 다음 판 어림
  (drive.next_estimate: 같은 시나리오 지난 판 최댓값 × 1.25, 처음이면 시나리오 checks.max_cost_usd와
  대본 턴 수 × 지금까지 본 턴당 비용 중 큰 값)이 --max-usd를 넘으면 시작하지 않고 멈춰요.
- 판마다 시험 DB(기본 mitjip_eval_sim, Redis 12번)를 비우고 world를 다시 심어요(sim/world.py).
  날짜는 7의 배수 날만큼 옮겨요(요일 그대로, check.week_shift). 대본 글의 'M월 D일'도 같이 옮겨요.
- 사용자: script.turns 대본(say = 비서 턴, screen = 화면 열기, press = 카드 단추 누르기). LLM 사용자 시뮬레이터는
  나중에 이 자리에 붙여요. 단추는 앞서 받은 카드의 이름표로 context.choice 계약 꼴을 보내요(sim/press.py).
  같은 종류 승인 카드가 이미 있으면 누르지 않고, 카드가 없으면 press.ask 글을 먼저 보내요.
- 사람 승인: script.decide 규칙(첫 번째로 맞는 규칙, 없으면 누르지 않음). 승인은 /actions/{id}/approve(seen = 카드 판).
- events: at_start · after_turn · after_event · after_action(그 종류 행동이 그 상태가 되면)으로 업체 · 고객 쪽 일을 일으켜요.
  clock_tick은 정한 시각으로 비서 시간 트리거 · 정리를 돌려요(먼저 말 건 줄의 거짓 경보 확인, sim/world.py).
  after_turn · 승인 규칙의 턴 번호는 대본 글 턴만 세요(단추 · ask 턴은 빼요). max_turns는 모든 턴을 세요.
- worker: 걸음마다 한 차례 돌려요(기억 뽑기 일 assistant_memory + 비서 정리 · 먼저 말 걸기). --no-worker ·
  --no-nudges로 끌 수 있어요. 행동마다 출처(button · turn · screen · nudge)를 적어요.
- 통과: 끝 상태(expected_end) + checks + 1계층 코드 불변식(sim/invariants.py) 모두. pass^k = 시나리오마다
  C(c, k) / C(n, k) 평균(τ-bench). 불변식을 위해 턴마다 카드 값(card_data) · 승인 카드 요약(action_data) · 턴 앞 열린
  승인 카드(open_before)를, 걸음마다 업무 상태 바뀜(timeline: 일어난 일 · 승인 · 거절 · 턴 · 화면 · worker)을 남겨요.
- pending(기능이 아직 통합에 없음) 시나리오는 건너뛰고 meta.pending에 까닭을 남겨요.
- 저장(runs/<tag>/): sim.jsonl(판마다 한 줄) · summary.json · meta.json
"""

import argparse
import json
import sys
import time
import traceback
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
V4 = HERE.parent
sys.path.insert(0, str(V4))

import apienv
from kit import RUNS, SCENARIOS, Budget, append_jsonl, jsonl, utf8_stdout

from sim import check, drive, invariants, press
from sim.world import SeedError, World

SETTLE = 6  # 한 걸음 뒤 사건 · 승인을 더 바뀌지 않을 때까지 도는 횟수 상한


def load(ids: list[str] | None, split: str, skipped: list[str] | None = None) -> list[dict]:
    """시나리오 고르기. pending(기능이 아직 통합에 없음)은 건너뛰고 skipped에 'id: 까닭'을 남겨요."""
    out = []
    for p in sorted(SCENARIOS.glob("*.json")):
        if p.stem == "scenario.schema":
            continue
        sc = json.loads(p.read_text(encoding="utf-8"))
        if ids and sc["id"] not in ids:
            continue
        if split != "all" and sc["split"] != split:
            continue
        if sc.get("pending"):
            if skipped is not None:
                skipped.append(f"{sc['id']}: {sc['pending']}")
            continue
        out.append(sc)
    return out


class Watch:
    """업무 상태 시간표(불변식 '승인 없는 실행'): 걸음(바탕 · 일어난 일 · 승인 · 거절 · 턴 · 화면 · worker)마다 업무 상태
    지문(drive.biz)을 읽어 바뀐 줄을 남겨요. n은 그 걸음까지 센 비서 턴 수(불변식 턴 번호와 같아요)."""

    def __init__(self, app) -> None:
        self.app, self.rows, self.last, self.n = app, [], drive.biz(app), 0

    def mark(self, op: str, **kw) -> None:
        now = drive.biz(self.app)
        changes = drive.biz_diff(self.last, now)
        self.last = now
        if changes:
            self.rows.append({"op": op, "n": self.n, **kw, "changes": changes})


class Events:
    def __init__(self, specs: list[dict]) -> None:
        self.specs, self.fired, self.log = specs, set(), []

    def due(self, turn_no: int, actions: list[dict]) -> list[dict]:
        out = []
        for e in self.specs:
            if e["id"] in self.fired:
                continue
            w = e["when"]
            if (
                w.get("at_start")
                or "after_turn" in w
                and turn_no >= w["after_turn"]
                or "after_event" in w
                and w["after_event"] in self.fired
            ):
                out.append(e)
            elif "after_action" in w:
                aa = w["after_action"]
                k = check.db_kind(aa["kind"])
                if any(
                    a["kind"] == k
                    and a["status"] == aa["status"]
                    and (not aa.get("vendor") or a.get("vendor") == aa["vendor"])
                    for a in actions
                ):
                    out.append(e)
        return out


def actions_now(app, world: World | None = None) -> list[dict]:
    """행동 종류 · 상태 · 대상 업체(요청이 대상이면 world.vendors ref)."""
    vmap = {v["id"]: ref for ref, v in (world.vendors if world else {}).items()}
    return [
        {"kind": r["kind"], "status": r["status"], "vendor": vmap.get(r["vendor_id"] or "")}
        for r in app.query(
            "select a.kind, a.status, v.vendor_id::text as vendor_id from assistant_actions a"
            " left join visits v on a.target_kind = 'visit' and v.id = a.target_id"
        )
    ]


def open_kinds(app, surface: str) -> list[str]:
    """이 화면(고객 · 업체)에서 열려 있는 승인 카드 종류(기한 전 proposed). 턴 앞에 읽어 기록해요."""
    rows = app.query(
        "select distinct kind from assistant_actions"
        " where status = 'proposed' and surface = $1 and expires_at > now()",
        surface,
    )
    return sorted(r["kind"] for r in rows)


def fire(app, world: World, ev: Events, turn_no: int, cref: str, watch: Watch | None = None) -> int:
    n = 0
    for _ in range(len(ev.specs) + 1):
        due = ev.due(turn_no, actions_now(app, world))
        if not due:
            break
        for e in due:
            ev.fired.add(e["id"])
            row = {"id": e["id"], "do": e["do"], "after_turn": turn_no, "ok": True}
            try:
                world.event(e["do"], e.get("args") or {}, cref)
            except SeedError as x:
                row.update(ok=False, error=str(x))
            # 상대방 · 시간 흐름이 바꾼 업무 상태(승인 없이 바뀌어도 되는 걸음)
            if watch is not None:
                watch.mark("event", ref=e["id"], do=e["do"])
            ev.log.append(row)
            n += 1
    return n


def decide(app, world, sc, who, surface, pid, turn_no, decided, approved, log,
           watch: Watch | None = None) -> int:  # fmt: skip
    rules = (sc.get("script") or {}).get("decide") or []
    n = 0
    for a in drive.open_actions(app, world, who, surface, pid):
        aid = a["action_id"]
        payload = drive.payload_of(app, aid)
        extra = (
            drive.proposal_dates(app, payload.get("proposal_id"))
            if a["kind"] in ("dates_accept", "delay_accept")
            else {}
        )
        view = check.view_of(a, payload, extra)
        do, rule = check.decide(rules, a["kind"], view, turn_no)
        if do == "leave" or decided.get(aid) == do:
            continue
        got = drive.press(app, world, who, surface, a, do)
        if watch is not None:  # 사람 승인 · 거절이 바꾼 업무 상태
            watch.mark(do, ref=aid, kind=a["kind"])
        decided[aid] = do
        if do == "approve":
            approved.add(aid)
        log.append({"turn": turn_no, "action_id": aid, "kind": a["kind"], "do": do, "rule": rule,
                    **got})  # fmt: skip
        n += 1
    return n


CARD_ID_MAX = 40  # TurnContextIn.card_id 길이 상한(backend schemas)


def _shift_step(t: dict, shift: int, base: date) -> dict:
    """대본 글('M월 D일')을 날짜 옮김에 맞춰요. 단추 걸음의 ask · say도 같이 옮겨요."""
    t = dict(t)
    if "say" in t:
        t["say"] = check.shift_ko(t["say"], shift, base)
    if "press" in t:
        p = dict(t["press"])
        for k in ("ask", "say"):
            if p.get(k):
                p[k] = check.shift_ko(p[k], shift, base)
        t["press"] = p
    return t


def live_kinds(app, world: World, spec: dict) -> dict[str, set[str]]:
    """상태별 행동 종류 {status: {kind}}. 같은 종류가 열려 있거나 실행됐으면 단추를 누르지 않아요.
    요청이 대상인 단추(press.PER_VISIT)에 vendor를 주면 그 업체 요청의 행동만 봐요."""
    vid = (world.vendors.get(spec.get("vendor") or "") or {}).get("id")
    mine = bool(vid) and spec["kind"] in press.PER_VISIT
    out: dict[str, set[str]] = {}
    for a in actions_now(app, world):
        if a["status"] not in press.LIVE:
            continue
        if mine and a["kind"] in press.PER_VISIT and a.get("vendor") != spec.get("vendor"):
            continue  # 다른 업체 요청의 카드
        out.setdefault(a["status"], set()).add(a["kind"])
    return out


def source_of(a: dict, turns: list[dict]) -> str:
    """행동을 만든 곳: nudge(먼저 말 걸기) · button(카드 단추 턴) · turn(글 턴) · screen(화면) ·
    server(턴 · 화면 밖에서 서버가 만든 카드, 예: 승인 때 견적서가 새 판이면 새 판으로 다시 만든 확정 카드)."""
    if a.get("origin") == "nudge":
        return "nudge"
    for t in turns:
        if a["id"] in {x.get("id") for x in t.get("actions") or []}:
            if t.get("press"):
                return "button"
            return "screen" if t.get("kind") == "screen" else "turn"
    return "server"


def run_one(app, sc: dict, trial: int, worker: bool = True, nudges: bool = True) -> dict:
    """한 판. worker: 걸음마다 기억 뽑기 일을 돌려요. nudges: 비서 정리(먼저 말 걸기)도 같이 돌려요."""
    real_today = _today()
    base = date.fromisoformat(sc["world"]["today"])
    shift = check.week_shift(base, real_today)
    s = check.shift_obj(sc, shift)
    script = s.get("script") or {}
    steps = [_shift_step(t, shift, base) for t in script.get("turns") or []]
    surface = s["surface"]
    world = World(app.api, app.query, real_today, app.call)
    cref = (s["world"].get("customer") or {}).get("ref") or "c1"
    row: dict = {
        "scenario": s["id"],
        "trial": trial,
        "split": s["split"],
        "surface": surface,
        "shift_days": shift,
        "today": real_today.isoformat(),
        "worker": {"memory": worker, "nudges": worker and nudges},
    }
    t0 = time.monotonic()
    try:
        world.seed(s["world"])
    except SeedError as x:
        row.update(seed_error=str(x), notes=world.notes, passed=False, end=[], checks=[])
        return row
    if surface == "customer":
        who, pid = world.customers[cref], world.customers[cref]["pid"]
    else:
        who, pid = world.vendors[script.get("as") or s["world"]["vendors"][0]["ref"]], None
    watch = Watch(app)  # 바탕(world 심기) 뒤부터 업무 상태 바뀜을 걸음마다 남겨요
    ev = Events(s.get("events") or [])
    decided: dict[str, str] = {}
    approved: set[str] = set()
    dlog: list[dict] = []
    turns: list[dict] = []
    presses: list[dict] = []
    ticks: list[dict] = []
    said = 0  # 비서 턴 수(단추 · ask 턴 포함). max_turns 상한
    script_no = 0  # 대본 글 턴 수. events · 승인 규칙의 after_turn은 이것으로 세요(단추 턴은 빼요)

    def settle() -> None:
        for _ in range(SETTLE):
            moved = fire(app, world, ev, script_no, cref, watch)
            if worker:
                got = drive.tick(app, nudges=nudges)
                if got:
                    ticks.append({"after_turn": script_no, **got})
                    watch.mark("tick")
                    moved += 1
            moved += decide(app, world, s, who, surface, pid, script_no, decided, approved, dlog,
                            watch)  # fmt: skip
            if not moved:
                break

    def send(text: str, visit: str | None, context: dict | None, step: int, **extra) -> dict:
        nonlocal said
        said += 1
        # 턴 앞에 열린 승인 카드 종류(불변식 '없는 카드' · SentenceGate opened와 같은 기준: 이 화면 · 기한 전)
        extra["open_before"] = open_kinds(app, surface)
        rec = drive.turn(app, world, who, surface, text, project_id=pid, visit_id=visit,
                         context=context)  # fmt: skip
        if rec.get("http") == 422 and context and len(context.get("card_id") or "") > CARD_ID_MAX:
            # 화면처럼 card_id를 그대로 보냈더니 길이 상한(40)에 걸렸어요. 기록하고 card_id 없이 다시 보내요
            extra["card_id_422"] = context["card_id"]
            context = {k: v for k, v in context.items() if k != "card_id"}
            rec = drive.turn(app, world, who, surface, text, project_id=pid, visit_id=visit,
                             context=context)  # fmt: skip
        rec.update(step=step, **extra)
        turns.append(rec)
        watch.n = said
        watch.mark("turn", step=step)  # 비서 턴 안에서 바뀐 업무 상태는 승인 없는 실행이에요
        return rec

    def plan(spec: dict, visit: str | None) -> press.Press:
        chat = next((t.get("chat_id") for t in reversed(turns) if t.get("chat_id")), None)
        return press.plan(spec, turns, world, live_kinds(app, world, spec), app.refs(chat), visit)

    settle()
    for i, st in enumerate(steps, 1):
        visit = world.visits.get(st["visit"], {}).get("id") if st.get("visit") else None
        if "press" in st:
            spec = st["press"]
            pr = plan(spec, visit)
            if pr.status == "need_card" and spec.get("ask") and said < s["max_turns"]:
                send(spec["ask"], visit, None, i, ask_for=spec["kind"])
                settle()
                pr = plan(spec, visit)
            if pr.status == "need_card":
                pr.status = "missed"
            if pr.status == "pressed" and said >= s["max_turns"]:
                pr.status, pr.why = "missed", "턴 상한"
            if pr.status == "pressed":
                ctx = {"choice": pr.choice, **({"card_id": pr.card_id} if pr.card_id else {})}
                rec = send(spec.get("say") or pr.text or "", visit, ctx, i)
                got = pr.record()
                got["made"] = [a.get("kind") for a in rec.get("actions") or []
                               if a.get("status") == "proposed"]  # fmt: skip
                got["reply"] = (rec.get("text") or "")[:160]
                if rec.get("card_id_422"):
                    got["card_id_422"] = True
                rec["press"] = got
            else:
                got = pr.record()
                turns.append({"kind": "press", "step": i, "press": got, "shown": ""})
            presses.append({"step": i, "after_turn": script_no, **got})
        elif "say" in st:
            if said >= s["max_turns"]:
                break
            script_no += 1
            send(st["say"], visit, st.get("context"), i)
        else:
            rec = drive.screen(app, world, who, st["screen"], project_id=pid, visit_id=visit)
            rec["step"] = i
            turns.append(rec)
            watch.mark("screen", step=i)
        settle()
    state = world.collect()
    for a in state["actions"]:
        a["approved_by_runner"] = a["id"] in approved
        a["source"] = source_of(a, turns)
    mem_jobs = {k: sum(t.get(k, 0) for t in ticks) for k in ("memory_done", "memory_skipped")}
    if worker and state.get("memory") == [] and drive.llm_off():
        jobs_run = sum(mem_jobs.values())
        state["memory_why"] = (
            f"무료 모드: 기억 뽑기 일 {jobs_run}건을 돌렸지만 Haiku가 꺼져 0줄"
            if jobs_run
            else "무료 모드: 기억할 낱말이 든 고객 말이 없어 기억 뽑기 일 0건"
        )
    use = drive.usage(app)
    drive.add_turn_costs(turns, use)
    run = {
        "turns": turns,
        "shown": "\n".join(t.get("shown") or "" for t in turns),
        "tool_args": [x for t in turns for x in t.get("tool_args") or []],
        "cost_usd": use["cost_usd"],
    }
    end = check.check_end(s["expected_end"], state)
    proc = check.check_process(s.get("checks") or {}, run)
    row.update(
        notes=world.notes,
        turns=[{k: v for k, v in t.items() if k != "shown"} for t in turns],
        presses=presses,
        ticks=ticks,
        memory_jobs=mem_jobs,
        decisions=dlog,
        events=ev.log,
        state=state,
        timeline=watch.rows,
    )
    # 1계층 코드 불변식(sim/invariants.py): 끝 상태 · 대화 확인 옆 세 번째 묶음. 통과는 셋 모두예요
    inv = invariants.check_all(row, sc)
    row.update(
        end=end,
        checks=proc,
        invariants=inv,
        inv_summary=invariants.summary(inv),
        end_ok=check.passed(end),
        checks_ok=check.passed(proc),
        inv_ok=check.passed(inv),
        passed=check.passed(end + proc + inv),
        usage=use,
        modes=sorted({t.get("mode") for t in turns if t.get("mode")}),
        secs=round(time.monotonic() - t0, 1),
    )
    return row


def _today() -> date:
    from app.shared.clock import today_seoul

    return today_seoul()


def _items(rs: list[dict], prefix: str = "") -> tuple[int, int]:
    """(맞은 항목 수, 잰 항목 수). na는 빼요. prefix로 '필수 도구'처럼 한 갈래만 셀 수 있어요."""
    its = [
        i
        for r in rs
        for i in (r.get("end") or []) + (r.get("checks") or [])
        if not i["na"] and i["what"].startswith(prefix)
    ]
    return sum(bool(i["ok"]) for i in its), len(its)


def press_stats(rs: list[dict]) -> dict:
    """단추 걸음: 누름(pressed) · 건너뜀(skip, 승인 카드가 이미 있음) · 못 누름(missed)과 까닭."""
    ps = [p for r in rs for p in r.get("presses") or []]
    done = [p for p in ps if p.get("status") == "pressed"]
    return {
        "steps": len(ps),
        "pressed": len(done),
        "skip": sum(p.get("status") == "skip" for p in ps),
        "missed": sum(p.get("status") == "missed" for p in ps),
        "made": sum(len(p.get("made") or []) for p in done),
        "from_refs": sum(p.get("ref_from") == "refs" for p in done),
        "card_id_422": sum(bool(p.get("card_id_422")) for p in done),
        "missed_why": sorted(
            {f"{p['kind']}: {p.get('why')}" for p in ps if p.get("status") == "missed"}
        ),
    }


def source_stats(rs: list[dict]) -> dict[str, int]:
    """행동 출처 · 상태별 수(예: 'button:executed'). 출처: button · turn · screen · nudge · server."""
    got: dict[str, int] = {}
    for r in rs:
        for a in (r.get("state") or {}).get("actions") or []:
            k = f"{a.get('source', 'other')}:{a['status']}"
            got[k] = got.get(k, 0) + 1
    return dict(sorted(got.items()))


def summarize(rows: list[dict], trials: int) -> dict:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["scenario"], []).append(r)
    out = []
    for sid, rs in sorted(by.items()):
        fails: dict[str, int] = {}
        for r in rs:
            for it in (r.get("end") or []) + (r.get("checks") or []) + (r.get("invariants") or []):
                if not it["ok"] and not it["na"]:
                    fails[it["what"]] = fails.get(it["what"], 0) + 1
        ok, n = _items(rs)
        out.append(
            {
                "id": sid,
                "split": rs[0]["split"],
                "surface": rs[0]["surface"],
                "trials": len(rs),
                "passed": sum(bool(r.get("passed")) for r in rs),
                "end_ok": sum(bool(r.get("end_ok")) for r in rs),
                "checks_ok": sum(bool(r.get("checks_ok")) for r in rs),
                "inv_ok": sum(bool(r.get("inv_ok", True)) for r in rs),
                "inv": inv_stats(rs),
                "seed_error": next((r["seed_error"] for r in rs if r.get("seed_error")), None),
                "event_errors": sorted(
                    {e["error"] for r in rs for e in r.get("events") or [] if not e["ok"]}
                ),
                "fails": sorted(fails, key=lambda k: -fails[k]),
                "items_ok": ok,
                "items": n,
                "notes": rs[0].get("notes") or [],
                "modes": sorted({m for r in rs for m in r.get("modes") or []}),
                "presses": press_stats(rs),
                "sources": source_stats(rs),
                "memory_jobs": {
                    k: sum((r.get("memory_jobs") or {}).get(k, 0) for r in rs)
                    for k in ("memory_done", "memory_skipped")
                },
                "cost_usd": round(sum((r.get("usage") or {}).get("cost_usd", 0) for r in rs), 6),
            }
        )
    full = [x for x in out if x["trials"] == trials]
    counts = [x["passed"] for x in full]
    all_ok, all_n = _items(rows)
    tool_ok, tool_n = _items(rows, "필수 도구")
    forb_ok, forb_n = _items(rows, "금지 도구")

    def hat(xs: list[dict], key: str, k: int):
        v = check.pass_hat([x[key] for x in xs], trials, k)
        return None if v is None else round(v, 4)

    return {
        "trials": trials,
        "scenarios": out,
        "pass^1": hat(full, "passed", 1),
        f"pass^{trials}": hat(full, "passed", trials),
        "end_only_pass^1": hat(full, "end_ok", 1),
        "checks_only_pass^1": hat(full, "checks_ok", 1),
        "inv_only_pass^1": hat(full, "inv_ok", 1),
        "invariants": inv_stats(rows),
        "by_split": {
            sp: {
                "n": len([x for x in full if x["split"] == sp]),
                "pass^1": hat([x for x in full if x["split"] == sp], "passed", 1),
                f"pass^{trials}": hat([x for x in full if x["split"] == sp], "passed", trials),
            }
            for sp in ("dev", "heldout")
        },
        "passed_runs": sum(counts),
        "runs": len(full) * trials,
        "item_rate": round(all_ok / all_n, 4) if all_n else None,
        "required_tools_recall": round(tool_ok / tool_n, 4) if tool_n else None,
        "forbidden_tools": {"items": forb_n, "used": forb_n - forb_ok},
        "paid_calls": sum(r.get("usage", {}).get("calls", 0) for r in rows),
        "cost_usd": round(sum(r.get("usage", {}).get("cost_usd", 0) for r in rows), 6),
        "presses": press_stats(rows),
        "sources": source_stats(rows),
        "nudges": nudge_stats(rows),
        "worker": rows[0].get("worker") if rows else None,
    }


def inv_stats(rs: list[dict]) -> dict:
    """불변식 합: 불변식마다 (잰 것, 위반, 잴 수 없음)과 위반한 판 · 턴 번호."""
    tot = {k: {"checked": 0, "bad": 0, "na": 0} for k in invariants.NAMES}
    where = []
    for r in rs:
        s = r.get("inv_summary") or {}
        for k, v in (s.get("by") or {}).items():
            for f in ("checked", "bad", "na"):
                tot[k][f] += v.get(f, 0)
            if v.get("bad"):
                where.append(
                    {
                        "key": f"{r['scenario']}#{r.get('trial', 0)}",
                        "inv": k,
                        "turns": v.get("turns"),
                    }
                )
    return {"by": tot, "violations": sum(v["bad"] for v in tot.values()), "where": where}


def nudge_stats(rs: list[dict]) -> dict:
    """먼저 말 건 줄: 보낸 줄(보낸 뒤 닫힌 줄 포함) 수와 거짓 경보(사람이 그 일을 끝낸 뒤 보낸 줄) 수."""
    ns = [n for r in rs for n in (r.get("state") or {}).get("nudges") or []]
    return {
        "shown": sum(check.nudge_sent(n) for n in ns),
        "false_alarms": sum(bool(n.get("late")) for n in ns),
    }


def report(summary: dict, mode: str) -> None:
    k = summary["trials"]
    live = bool(summary.get("cost"))
    print(f"\n# 시뮬레이터 결과 ({mode} 모드, 시나리오마다 {k}번)")
    print("| 시나리오 | 나눔 | 화면 | 통과 | 끝 상태만 | 확인만 | 불변식 | 맞은 항목 | 단추 |"
          + (" 비용 |" if live else "") + " 주된 실패 |")  # fmt: skip
    print("| --- " * (11 if live else 10) + "|")
    for x in summary["scenarios"]:
        why = x["seed_error"] or " · ".join(x["fails"][:3]) or "-"
        usd = f" ${x.get('cost_usd', 0):.4f} |" if live else ""
        print(f"| {x['id']} | {x['split']} | {x['surface']} | {x['passed']}/{x['trials']} | "
              f"{x['end_ok']}/{x['trials']} | {x['checks_ok']}/{x['trials']} | "
              f"{x.get('inv_ok', x['trials'])}/{x['trials']} | "
              f"{x['items_ok']}/{x['items']} | {press_cell(x.get('presses'))} |{usd} {why} |")  # fmt: skip
    f = summary.get("forbidden_tools") or {}
    print(f"\npass^1 {summary['pass^1']} · pass^{k} {summary[f'pass^{k}']} "
          f"· 끝 상태만 pass^1 {summary['end_only_pass^1']} · 확인만 pass^1 "
          f"{summary['checks_only_pass^1']} · 불변식만 pass^1 {summary.get('inv_only_pass^1')} "
          f"· 맞은 항목 {summary['item_rate']} "
          f"· 필수 도구 재현율 {summary['required_tools_recall']} "
          f"· 금지 도구 {f.get('used', 0)}/{f.get('items', 0)}항목")  # fmt: skip
    iv = summary.get("invariants") or {}
    if iv:
        print("불변식: " + " · ".join(
            f"{invariants.NAMES[k]} 위반 {v['bad']}/잰 것 {v['checked']}(na {v['na']})"
            for k, v in (iv.get("by") or {}).items()
        ))  # fmt: skip
        for w in iv.get("where") or []:
            print(f"  위반 {w['key']} {invariants.NAMES[w['inv']]} 턴 {w['turns'] or '-'}")
    print(f"유료 호출 {summary['paid_calls']}회 · 비용 ${summary['cost_usd']}")
    if live:
        c = summary["cost"]
        print(drive.cost_line(c))
        print("목적별:", c["by_purpose"], "· 실패한 호출:", c["errors"] or "없음")
    if summary.get("stopped"):
        print("멈춤:", summary["stopped"])
    p = summary.get("presses") or {}
    print(f"단추 걸음 {p.get('steps', 0)} · 누름 {p.get('pressed', 0)} · 건너뜀 {p.get('skip', 0)} "
          f"· 못 누름 {p.get('missed', 0)} · 이름표 표에서 찾음 {p.get('from_refs', 0)} "
          f"· card_id 422 {p.get('card_id_422', 0)}")  # fmt: skip
    print("행동 출처:", summary.get("sources"))
    nd = summary.get("nudges") or {}
    print(f"먼저 말 건 줄: 보낸 줄 {nd.get('shown', 0)} · 거짓 경보 {nd.get('false_alarms', 0)}")


def press_cell(p: dict | None) -> str:
    """결과표 '단추' 칸: 누름 · 건너뜀 · 못 누름(판 합)."""
    if not p or not p.get("steps"):
        return "-"
    return f"누름 {p['pressed']} · 건너뜀 {p['skip']} · 못 누름 {p['missed']}"


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="v4 비서 시뮬레이터(대본 사용자)")
    ap.add_argument("--tag", default="sim-free")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--only", help="시나리오 id를 쉼표로(예: F1,S04)")
    ap.add_argument("--split", default="all", choices=["all", "dev", "heldout"])
    ap.add_argument("--db", default="mitjip_eval_sim")
    ap.add_argument("--redis-db", type=int, default=12)
    ap.add_argument("--env-file", type=Path, help="DB 접속값을 읽을 .env(키는 읽지 않아요)")
    ap.add_argument(
        "--live",
        action="store_true",
        help="LLM 모드(유료). 환경변수 LLM_LIVE=true · ANTHROPIC_API_KEY와 --max-usd가 있어야 해요",
    )
    ap.add_argument(
        "--max-usd", type=float, help="--live 상한(달러). 누적 + 다음 판 어림이 넘으면 멈춰요"
    )
    ap.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default="anthropic",
        help="--live 공급자. openai는 OPENAI_API_KEY를 써요(모델 · effort는 OPENAI_* 환경변수)",
    )
    ap.add_argument("--resummarize", action="store_true", help="돌린 sim.jsonl로 요약만 다시 내요")
    ap.add_argument(
        "--no-worker", action="store_true", help="worker(기억 뽑기 · 먼저 말 걸기)를 돌리지 않아요"
    )
    ap.add_argument(
        "--no-nudges", action="store_true", help="기억 뽑기만 돌리고 먼저 말 걸기는 빼요"
    )
    a = ap.parse_args(argv)
    if a.resummarize:
        out = RUNS / a.tag
        old = (
            json.loads((out / "meta.json").read_text("utf-8"))
            if (out / "meta.json").exists()
            else {}
        )
        live = a.live or old.get("run_mode") == "live"
        rows = jsonl(out / "sim.jsonl")
        summary = summarize(rows, a.trials)
        summary["mode"] = "live" if live else "free"
        if live:
            summary.update(cost=drive.cost_summary(rows), max_usd=old.get("max_usd"),
                           stopped=old.get("stopped"))  # fmt: skip
        write_json(out / "summary.json", summary)
        report(summary, "LLM" if live else "무료")
        return 0
    if a.live and (a.max_usd is None or a.max_usd <= 0):
        ap.error("--live에는 --max-usd(0보다 큰 값)가 필요해요")
    if a.live:
        apienv.openai_mode() if a.provider == "openai" else apienv.live_mode()
    else:
        apienv.free_mode()
    env = apienv.load_db_env(a.env_file)
    skipped: list[str] = []
    scen = load(a.only.split(",") if a.only else None, a.split, skipped)
    for x in skipped:
        print(f"건너뜀(pending) {x}")
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    path = out / "sim.jsonl"
    path.write_text("", encoding="utf-8")
    app = apienv.App(a.db, a.redis_db).boot()
    mode = apienv.settings_mode()
    if mode["available"] != a.live:
        app.close()
        print("LLM을 부를 수 없어 멈춰요(LLM_LIVE · 키 · 공급자를 확인해 주세요)." if a.live
              else "LLM이 켜져 있어 멈춰요(무료 모드여야 해요).")  # fmt: skip
        return 2
    llm_set = apienv.live_settings() if a.live else None
    rows = []
    book = Budget(a.max_usd if a.live else None)
    prev: dict[str, list[float]] = {}  # 시나리오별 지난 판 비용
    seen = 0.0  # 지금까지 본 판의 턴당 비용 최댓값(처음 판 어림에 써요)
    stopped = None
    try:
        for sc in scen:
            for t in range(a.trials):
                est = 0.0
                if a.live:
                    steps = [
                        x for x in (sc.get("script") or {}).get("turns") or [] if "screen" not in x
                    ]
                    floor = (sc.get("checks") or {}).get("max_cost_usd")
                    est = drive.next_estimate(prev.get(sc["id"], []), len(steps), seen, floor)
                    if not book.reserve(est):
                        stopped = (f"상한 ${a.max_usd}: 지금까지 ${book.spent:.4f} + 다음 판 어림 "
                                   f"${est:.4f}({sc['id']} #{t + 1})이 넘어 시작하지 않았어요")  # fmt: skip
                        break
                app.reset()
                try:
                    row = run_one(app, sc, t, worker=not a.no_worker, nudges=not a.no_nudges)
                except Exception as e:  # noqa: BLE001 - 한 판이 깨져도 기록하고 이어 가요
                    row = {"scenario": sc["id"], "trial": t, "split": sc["split"],
                           "surface": sc["surface"], "passed": False,
                           "crash": f"{type(e).__name__}: {e}"[:300],
                           "trace": traceback.format_exc()[-1500:]}  # fmt: skip
                if a.live:
                    stopped = drive.live_cost(app, row, book, est)
                    prev.setdefault(sc["id"], []).append(row["cost_usd"])
                    n = sum(1 for x in row.get("turns") or [] if x.get("turn_id"))
                    seen = max(seen, row["cost_usd"] / max(n, 1))
                append_jsonl(path, row)
                rows.append(row)
                mark = "통과" if row.get("passed") else "실패"
                usd = f" · ${row['cost_usd']:.4f} · 누적 ${book.spent:.4f}" if a.live else ""
                print(f"{sc['id']} #{t + 1} {mark} ({row.get('secs', '-')}초{usd})", flush=True)
                if stopped:
                    break
            if stopped:
                break
    finally:
        app.close()
    summary = summarize(rows, a.trials)
    summary["mode"] = "live" if a.live else "free"
    if a.live:
        summary.update(cost=drive.cost_summary(rows), max_usd=a.max_usd, stopped=stopped)
    write_json(out / "summary.json", summary)
    meta = {"tag": a.tag, "mode": mode, "run_mode": summary["mode"], "db": a.db,
            "redis_db": a.redis_db, "env_file": env.name if env else None,
            "scenarios": [s["id"] for s in scen], "trials": a.trials, "worker": not a.no_worker,
            "nudges": not a.no_worker and not a.no_nudges, "pending": skipped}  # fmt: skip
    if a.live:
        meta.update(llm=llm_set, max_usd=a.max_usd, stopped=stopped, cost=summary["cost"])
    write_json(out / "meta.json", meta)
    report(summary, "LLM" if a.live else "무료")
    return 0


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
