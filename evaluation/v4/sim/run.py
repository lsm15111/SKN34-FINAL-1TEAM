"""시나리오(sets/scenarios)를 대본 사용자로 돌려 끝 상태를 정답과 견줘요: pass^1 · pass^3.

    cd backend && uv run python ../evaluation/v4/sim/run.py --tag sim-free --trials 3

- 무료 모드만 돌아요(LLM_LIVE=false, 키 환경변수 비움, 유료 호출 0회). --live는 키 · 리드 허락이 생기면 열어요.
- 판마다 시험 DB(기본 mitjip_eval_sim, Redis 12번)를 비우고 world를 다시 심어요(sim/world.py).
  날짜는 7의 배수 날만큼 옮겨요(요일 그대로, check.week_shift). 대본 글의 'M월 D일'도 같이 옮겨요.
- 사용자: script.turns 대본(say = 비서 턴, screen = 화면 열기). LLM 사용자 시뮬레이터는 나중에 이 자리에 붙여요.
- 사람 승인: script.decide 규칙(첫 번째로 맞는 규칙, 없으면 누르지 않음). 승인은 /actions/{id}/approve(seen = 카드 판).
- events: at_start · after_turn · after_event · after_action(그 종류 행동이 그 상태가 되면)으로 업체 · 고객 쪽 일을 일으켜요.
- 통과: 끝 상태(expected_end) + checks 모두. pass^k = 시나리오마다 C(c, k) / C(n, k) 평균(τ-bench).
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
from kit import RUNS, SCENARIOS, append_jsonl, jsonl, utf8_stdout

from sim import check, drive
from sim.world import SeedError, World

SETTLE = 6  # 한 걸음 뒤 사건 · 승인을 더 바뀌지 않을 때까지 도는 횟수 상한


def load(ids: list[str] | None, split: str) -> list[dict]:
    out = []
    for p in sorted(SCENARIOS.glob("*.json")):
        if p.stem == "scenario.schema":
            continue
        sc = json.loads(p.read_text(encoding="utf-8"))
        if ids and sc["id"] not in ids:
            continue
        if split != "all" and sc["split"] != split:
            continue
        out.append(sc)
    return out


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
                k = check.db_kind(w["after_action"]["kind"])
                if any(
                    a["kind"] == k and a["status"] == w["after_action"]["status"] for a in actions
                ):
                    out.append(e)
        return out


def actions_now(app) -> list[dict]:
    return [
        {"kind": r["kind"], "status": r["status"]}
        for r in app.query("select kind, status from assistant_actions")
    ]


def fire(app, world: World, ev: Events, turn_no: int, cref: str) -> int:
    n = 0
    for _ in range(len(ev.specs) + 1):
        due = ev.due(turn_no, actions_now(app))
        if not due:
            break
        for e in due:
            ev.fired.add(e["id"])
            row = {"id": e["id"], "do": e["do"], "after_turn": turn_no, "ok": True}
            try:
                world.event(e["do"], e.get("args") or {}, cref)
            except SeedError as x:
                row.update(ok=False, error=str(x))
            ev.log.append(row)
            n += 1
    return n


def decide(app, world, sc, who, surface, pid, turn_no, decided, approved, log) -> int:
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
        decided[aid] = do
        if do == "approve":
            approved.add(aid)
        log.append({"turn": turn_no, "action_id": aid, "kind": a["kind"], "do": do, "rule": rule,
                    **got})  # fmt: skip
        n += 1
    return n


def run_one(app, sc: dict, trial: int) -> dict:
    real_today = _today()
    base = date.fromisoformat(sc["world"]["today"])
    shift = check.week_shift(base, real_today)
    s = check.shift_obj(sc, shift)
    script = s.get("script") or {}
    steps = [
        {**t, "say": check.shift_ko(t["say"], shift, base)} if "say" in t else t
        for t in script.get("turns") or []
    ]
    surface = s["surface"]
    world = World(app.api, app.query, real_today)
    cref = (s["world"].get("customer") or {}).get("ref") or "c1"
    row: dict = {
        "scenario": s["id"],
        "trial": trial,
        "split": s["split"],
        "surface": surface,
        "shift_days": shift,
        "today": real_today.isoformat(),
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
    ev = Events(s.get("events") or [])
    decided: dict[str, str] = {}
    approved: set[str] = set()
    dlog: list[dict] = []
    turns: list[dict] = []
    said = 0
    fire(app, world, ev, 0, cref)
    for i, st in enumerate(steps, 1):
        visit = world.visits.get(st["visit"], {}).get("id") if st.get("visit") else None
        if "say" in st:
            if said >= s["max_turns"]:
                break
            said += 1
            rec = drive.turn(app, world, who, surface, st["say"], project_id=pid,
                             visit_id=visit, context=st.get("context"))  # fmt: skip
        else:
            rec = drive.screen(app, world, who, st["screen"], project_id=pid, visit_id=visit)
        rec["step"] = i
        turns.append(rec)
        for _ in range(SETTLE):
            moved = fire(app, world, ev, said, cref)
            moved += decide(app, world, s, who, surface, pid, said, decided, approved, dlog)
            if not moved:
                break
    state = world.collect()
    for a in state["actions"]:
        a["approved_by_runner"] = a["id"] in approved
    use = drive.usage(app)
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
        turns=[{k: v for k, v in t.items() if k not in ("shown", "card_data")} for t in turns],
        decisions=dlog,
        events=ev.log,
        state=state,
        end=end,
        checks=proc,
        end_ok=check.passed(end),
        checks_ok=check.passed(proc),
        passed=check.passed(end + proc),
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


def summarize(rows: list[dict], trials: int) -> dict:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["scenario"], []).append(r)
    out = []
    for sid, rs in sorted(by.items()):
        fails: dict[str, int] = {}
        for r in rs:
            for it in (r.get("end") or []) + (r.get("checks") or []):
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
                "seed_error": next((r["seed_error"] for r in rs if r.get("seed_error")), None),
                "event_errors": sorted(
                    {e["error"] for r in rs for e in r.get("events") or [] if not e["ok"]}
                ),
                "fails": sorted(fails, key=lambda k: -fails[k]),
                "items_ok": ok,
                "items": n,
                "notes": rs[0].get("notes") or [],
                "modes": sorted({m for r in rs for m in r.get("modes") or []}),
            }
        )
    full = [x for x in out if x["trials"] == trials]
    counts = [x["passed"] for x in full]
    all_ok, all_n = _items(rows)
    tool_ok, tool_n = _items(rows, "필수 도구")

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
        "paid_calls": sum(r.get("usage", {}).get("calls", 0) for r in rows),
        "cost_usd": round(sum(r.get("usage", {}).get("cost_usd", 0) for r in rows), 6),
    }


def report(summary: dict, mode: str) -> None:
    k = summary["trials"]
    print(f"\n# 시뮬레이터 결과 ({mode} 모드, 시나리오마다 {k}번)")
    print("| 시나리오 | 나눔 | 화면 | 통과 | 끝 상태만 | 확인만 | 맞은 항목 | 주된 실패 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for x in summary["scenarios"]:
        why = x["seed_error"] or " · ".join(x["fails"][:3]) or "-"
        print(f"| {x['id']} | {x['split']} | {x['surface']} | {x['passed']}/{x['trials']} | "
              f"{x['end_ok']}/{x['trials']} | {x['checks_ok']}/{x['trials']} | "
              f"{x['items_ok']}/{x['items']} | {why} |")  # fmt: skip
    print(f"\npass^1 {summary['pass^1']} · pass^{k} {summary[f'pass^{k}']} "
          f"· 끝 상태만 pass^1 {summary['end_only_pass^1']} · 확인만 pass^1 "
          f"{summary['checks_only_pass^1']} · 맞은 항목 {summary['item_rate']} "
          f"· 필수 도구 재현율 {summary['required_tools_recall']}")  # fmt: skip
    print(f"유료 호출 {summary['paid_calls']}회 · 비용 ${summary['cost_usd']}")


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
    ap.add_argument("--live", action="store_true", help="유료 모드(지금은 막아 둠)")
    ap.add_argument("--resummarize", action="store_true", help="돌린 sim.jsonl로 요약만 다시 내요")
    a = ap.parse_args(argv)
    if a.live:
        print("유료 모드는 아직 막아 뒀어요(키 무효 · 리드 허락 전). 무료 모드로만 돌려요.")
        return 2
    if a.resummarize:
        out = RUNS / a.tag
        summary = summarize(jsonl(out / "sim.jsonl"), a.trials)
        summary["mode"] = "free"
        write_json(out / "summary.json", summary)
        report(summary, "무료")
        return 0
    apienv.free_mode()
    env = apienv.load_db_env(a.env_file)
    scen = load(a.only.split(",") if a.only else None, a.split)
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    path = out / "sim.jsonl"
    path.write_text("", encoding="utf-8")
    app = apienv.App(a.db, a.redis_db).boot()
    mode = apienv.settings_mode()
    if mode["available"]:
        app.close()
        print("LLM이 켜져 있어 멈춰요(무료 모드여야 해요).")
        return 2
    rows = []
    try:
        for sc in scen:
            for t in range(a.trials):
                app.reset()
                try:
                    row = run_one(app, sc, t)
                except Exception as e:  # noqa: BLE001 - 한 판이 깨져도 기록하고 이어 가요
                    row = {"scenario": sc["id"], "trial": t, "split": sc["split"],
                           "surface": sc["surface"], "passed": False,
                           "crash": f"{type(e).__name__}: {e}"[:300],
                           "trace": traceback.format_exc()[-1500:]}  # fmt: skip
                append_jsonl(path, row)
                rows.append(row)
                mark = "통과" if row.get("passed") else "실패"
                print(f"{sc['id']} #{t + 1} {mark} ({row.get('secs', '-')}초)", flush=True)
    finally:
        app.close()
    summary = summarize(rows, a.trials)
    summary["mode"] = "free"
    write_json(out / "summary.json", summary)
    meta = {"tag": a.tag, "mode": mode, "db": a.db, "redis_db": a.redis_db,
            "env_file": env.name if env else None, "scenarios": [s["id"] for s in scen],
            "trials": a.trials}  # fmt: skip
    write_json(out / "meta.json", meta)
    report(summary, "무료")
    return 0


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
