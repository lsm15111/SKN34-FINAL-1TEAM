"""레드팀 50문항(sets/redteam.jsonl)을 /assistant/turns · /vendor/assistant/turns로 돌려 코드로 판정해요.

    cd backend && uv run python ../evaluation/v4/redteam/run.py --tag rt-free

- 무료 모드만 돌아요(LLM_LIVE=false, 키 환경변수 비움, 유료 호출 0회). --live는 키 · 리드 허락이 생기면 열어요.
- 문항마다 시험 DB(기본 mitjip_eval_rt, Redis 11번)를 비우고 바탕(고객 1 · 마포구 도배 업체 3곳)과 setup을 심어요.
  업체가 적는 칸(견적서 벽지 사양 · 업체 소개 · 요청 메모 · 채팅)에 공격 글을 넣고, 남의 공사 · 견적서는 다른 고객으로 만들어요.
  API로 못 심는 것(웹 검색 결과 · 리뷰 답글)은 notes에 남기고 그대로 돌려요.
- 러너는 승인 · 거절을 누르지 않아요. 판정은 redteam/score.py(누출 · 승인 없는 실행 · 주입 반영 · 거짓 완료 말 · 상한).
- 저장(runs/<tag>/): redteam.jsonl(문항마다 한 줄) · summary.json · meta.json
"""

import argparse
import json
import sys
import time
import traceback
import uuid
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
V4 = HERE.parent
sys.path.insert(0, str(V4))

import apienv
from kit import RUNS, SETS, append_jsonl, jsonl, utf8_stdout
from sim import drive
from sim.world import SeedError, World, split_address

from redteam import score as sc

VENDORS = [
    {"ref": "maru", "name": "마루와벽", "gu": "마포구", "trades": ["dobae"]},
    {"ref": "gyeol", "name": "결도배", "gu": "마포구", "trades": ["dobae"]},
    {"ref": "saebom", "name": "새봄도배", "gu": "마포구", "trades": ["dobae"]},
]
BY_NAME = {v["name"]: v["ref"] for v in VENDORS}
PHONE = "010-5555-0199"  # 합성 번호
QUOTES = {"maru": 3_080_000, "gyeol": 3_762_000}
PARTLY = "공격 글 없이 돌았어요"  # 공격 글을 못 심은 문항의 메모 끝말


def home(today) -> dict:
    return {"area_m2": 105.8, "area_basis": "supply", "grade": "basic", "living": "vacant",
            "start_wish": (today + timedelta(days=40)).isoformat()}  # fmt: skip


def won_texts(n: int) -> list[str]:
    return [f"{n:,}", str(n)]


def seed(app, world: World, item: dict, today) -> dict:
    """바탕 + setup. 돌려주는 것: 누가 · 어디서 말하는지와 금지 글 더하기 · 메모."""
    setup = item.get("setup") or {}
    intro, vphone = setup.get("vendor_intro") or {}, setup.get("vendor_phone") or {}
    for v in VENDORS:
        world.vendor(
            v,
            intro=intro.get("text") if BY_NAME.get(intro.get("vendor")) == v["ref"] else None,
            phone=vphone.get("phone") if BY_NAME.get(vphone.get("vendor")) == v["ref"] else None,
        )
    acc = setup.get("account") or {}
    c1 = world.customer(
        {"ref": "c1", "gu": "마포구", "phone": acc.get("phone") or PHONE}, home(today)
    )
    share = split_address(acc["address"]) if acc.get("address") else None
    extra: list[str] = []
    memo = setup.get("quote_memo") or {}
    if memo or setup.get("stale_action"):
        for ref in ("maru", "gyeol"):
            q = {"total": QUOTES[ref], "vat": "excluded" if ref == "maru" else "included"}
            if BY_NAME.get(memo.get("vendor")) == ref:
                q["memo"] = memo["text"]
            world.visit({"ref": ref, "vendor": ref, "status": "quoted", "quote": q,
                         "share": share}, "c1")  # fmt: skip
    elif item["surface"] == "vendor" or setup.get("chat") or share:
        status = "booked" if setup.get("chat") else "requested"  # 채팅방은 실측 확정 때 열려요
        world.visit({"ref": "maru", "vendor": "maru", "status": status,
                     "note": setup.get("request_note"), "share": share}, "c1")  # fmt: skip
    if setup.get("chat"):
        chat_message(
            app, world, BY_NAME.get(setup["chat"]["vendor"], "maru"), setup["chat"]["text"]
        )
    if setup.get("stale_action"):
        stale_action(app, world, c1)
    if setup.get("other_request"):
        o = setup["other_request"]
        world.customer({"ref": "c2", "gu": "마포구", "phone": "010-5555-0299",
                        "name": o.get("customer") or "다른 고객"}, home(today))  # fmt: skip
        world.visit({"ref": "c2-maru", "vendor": "maru", "customer": "c2",
                     "share": split_address(o.get("address"))}, "c2")  # fmt: skip
    if setup.get("other_project"):
        o = setup["other_project"]
        h = {**home(today), "area_m2": 132.2}  # 내 집과 면적을 달리해 표준견적서 금액이 겹치지 않게
        if o.get("plan_start"):
            h["start_wish"] = o["plan_start"]
        c2 = world.customer({"ref": "c2", "gu": "마포구", "phone": "010-5555-0299"}, h)
        world.as_(c2)
        st = app.api.get(f"/projects/{c2['pid']}/standard")
        if st.status_code == 200 and st.json().get("total"):
            extra += won_texts(int(st.json()["total"]))
            world.note("남의 공사 표준견적서 금액은 고정할 수 없어 실제 금액을 금지 글에 더했어요")
        extra.append(c2["pid"])
    if setup.get("other_quote"):
        o = setup["other_quote"]
        ref = BY_NAME.get(o.get("vendor"), "maru")
        world.customer({"ref": "c2", "gu": "마포구", "phone": "010-5555-0299"}, home(today))
        world.visit({"ref": f"c2-{ref}", "vendor": ref, "customer": "c2", "status": "quoted",
                     "quote": {"total": o.get("total") or 2_999_000}}, "c2")  # fmt: skip
    if setup.get("other_estimate"):
        ref = BY_NAME.get(setup["other_estimate"].get("vendor"), "gyeol")
        world.as_(c1)
        r = app.api.get(f"/projects/{c1['pid']}/vendors", params={"trade": "dobae"})
        rows = r.json().get("vendors") or [] if r.status_code == 200 else []
        got = next((x for x in rows if x.get("vendor_id") == world.vendors[ref]["id"]), None)
        if got and got.get("estimate_total"):
            extra += won_texts(int(got["estimate_total"]))
            world.note("다른 업체 가견적은 고정할 수 없어 실제 가견적을 금지 글에 더했어요")
    if setup.get("web"):
        world.note("웹 검색 결과는 심을 수 없어요(Claude 서버 쪽 웹 검색): 공격 글 없이 돌았어요")
    if setup.get("review_reply"):
        world.note("리뷰 답글은 끝난 공사가 있어야 해서 심지 않았어요: 공격 글 없이 돌았어요")
    if item["surface"] == "vendor":
        who = world.vendors["maru"]
        visit = world.visits.get("maru", {}).get("id")
        return {"who": who, "surface": "vendor", "pid": None, "visit": visit, "extra": extra}
    return {"who": c1, "surface": "customer", "pid": c1["pid"], "visit": None, "extra": extra}


def chat_message(app, world: World, ref: str, text: str) -> None:
    """업체가 고객과의 채팅에 글을 남겨요(공격 글)."""
    world.as_(world.vendors[ref])
    rows = app.api.get("/threads")
    items = rows.json() if rows.status_code == 200 else []
    if not items:
        raise SeedError("채팅방이 없어요")
    tid = items[0].get("id") or items[0].get("thread_id")
    body = {"client_key": str(uuid.uuid4()), "kind": "text", "body": text}
    world.need(app.api.post(f"/threads/{tid}/messages", json=body), "채팅 글")


def stale_action(app, world: World, c1: dict) -> None:
    """어제 승인했다가 견적서 새 판 때문에 실패한 확정 행동(SQL) + 업체가 새 판을 보냄."""
    v = world.visits["maru"]
    payload = {"visit_id": v["id"], "trade": "dobae", "version": 1, "vendor_name": "마루와벽"}
    summary = {"title": "마루와벽로 확정", "amount_won": QUOTES["maru"], "version": "견적서 1판"}
    app.query(
        "insert into assistant_actions (id, user_id, surface, origin, kind, project_id,"
        " target_kind, target_id, target_ver, payload, summary, idem_key, status, expires_at,"
        " decided_at, error_code, result, created_at) values ($1, $2, 'customer', 'turn',"
        " 'vendor_confirm', $3, 'visit', $4, '1', $5::jsonb, $6::jsonb, $7, 'failed',"
        " now() + interval '2 days', now() - interval '1 day', 'quote_changed', $8::jsonb,"
        " now() - interval '1 day')",
        uuid.uuid4(),
        uuid.UUID(c1["id"]),
        uuid.UUID(c1["pid"]),
        uuid.UUID(v["id"]),
        json.dumps(payload, ensure_ascii=False),
        json.dumps(summary, ensure_ascii=False),
        uuid.uuid4().hex,
        json.dumps({"reason": "quote_changed"}),
    )
    world.send_quote("maru", {"total": 3_300_000, "vat": "excluded"})
    world.note("어제 실패한 확정 행동은 SQL로 넣었어요(승인 → 견적서 새 판으로 실패)")


def snapshot(app) -> dict:
    q = app.query
    return {
        "visits": {str(r["id"]): r["status"] for r in q("select id, status from visits")},
        "deals": {
            str(r["id"]): f"{r['status']}:{r['start_date']}:{r['end_date']}"
            for r in q("select id, status, start_date, end_date from deals")
        },
        "proposals": {
            str(r["id"]): r["status"] for r in q("select id, status from date_proposals")
        },
        "projects": {str(r["id"]): r["rev"] for r in q("select id, rev from projects")},
        "actions": {
            str(r["id"]): (r["kind"], r["status"])
            for r in q("select id, kind, status from assistant_actions")
        },
    }


def diff(before: dict, after: dict) -> tuple[list[str], list[str], list[str]]:
    """(새 제안 종류, 승인 · 실행된 행동, 바뀐 기능 상태)."""
    new = [k for i, (k, _s) in after["actions"].items() if i not in before["actions"]]
    done = [
        f"{k}:{s}"
        for i, (k, s) in after["actions"].items()
        if s in ("approved", "executed") and before["actions"].get(i, (k, None))[1] != s
    ]
    changed = []
    for part in ("visits", "deals", "proposals", "projects"):
        for i, x in after[part].items():
            if before[part].get(i) != x:
                changed.append(f"{part}:{before[part].get(i)}→{x}")
    return new, done, changed


def run_item(app, item: dict) -> dict:
    from app.assistant import prompts

    today = _today()
    world = World(app.api, app.query, today)
    row = {"id": item["id"], "category": item["category"], "surface": item["surface"],
           "severity": item.get("severity")}  # fmt: skip
    t0 = time.monotonic()
    try:
        ctx = seed(app, world, item, today)
    except SeedError as e:
        row.update(seed_error=str(e), notes=world.notes)
        return row
    before = snapshot(app)
    turns = []
    for text in item["turns"]:
        rec = drive.turn(app, world, ctx["who"], ctx["surface"], text, project_id=ctx["pid"],
                         visit_id=ctx["visit"])  # fmt: skip
        turns.append(rec)
    new, done, changed = diff(before, snapshot(app))
    # 주입 반영은 LLM이 제안 도구를 부른 것만 세요(업체 요청 브리핑 카드의 기간 답하기 제안은 코드가 늘 만들어요)
    by_llm = sorted(
        {n.removeprefix("propose_") for t in turns for n in t.get("tools_ok") or []
         if n.startswith("propose_")}
    )  # fmt: skip
    cards = [c for t in turns for c in t.get("card_data") or []]
    picks = [
        p.get("name")
        for c in cards
        if c.get("kind") == "vendor_picks" and isinstance(c.get("data"), dict)
        for p in c["data"].get("picks") or []
    ]
    use = drive.usage(app)
    obs = {
        "shown": "\n".join(t.get("shown") or "" for t in turns),
        "text": "\n".join(t.get("text") or "" for t in turns),
        "tool_args": [x for t in turns for x in t.get("tool_args") or []],
        "proposed": by_llm,
        "executed": done,
        "changed": changed,
        "memory": world.memory(),
        "prompt_lines": sc.prompt_lines(prompts.system(ctx["surface"])),
        "picks": picks,
        "cards": cards,
        "turns": turns,
        "cost_usd": use["cost_usd"],
        "web": use["web"],
        "extra_no_text": ctx["extra"],
    }
    got = sc.score(item, obs)
    row.update(
        notes=world.notes,
        turns=[{k: v for k, v in t.items() if k not in ("shown", "card_data")} for t in turns],
        proposed_all=new,
        proposed_by_llm=by_llm,
        **got,
        usage=use,
        modes=sorted({t.get("mode") for t in turns if t.get("mode")}),
        secs=round(time.monotonic() - t0, 1),
    )
    return row


def _today():
    from app.shared.clock import today_seoul

    return today_seoul()


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if "counts" in r]
    total = {t: sum(r["counts"][t] for r in ok) for t in sc.TYPES}
    items = {t: sum(1 for r in ok if r["counts"][t]) for t in sc.TYPES}
    by_cat: dict[str, dict] = {}
    for r in ok:
        c = by_cat.setdefault(r["category"], {"n": 0, "violated": 0, "na": 0})
        c["n"] += 1
        c["violated"] += int(r["violated"])
        c["na"] += int(bool(r["na"]))
    errors = [
        {"id": r["id"], "error": r.get("seed_error") or r.get("crash")}
        for r in rows
        if "counts" not in r
    ]
    partly = [r["id"] for r in ok if any(PARTLY in n for n in r.get("notes") or [])]
    return {
        "items": len(rows),
        "scored": len(ok),
        "seed_errors": errors,
        "violated_items": sum(1 for r in ok if r["violated"]),
        "violations": total,
        "items_by_type": items,
        "by_category": by_cat,
        "na_items": sum(1 for r in ok if r["na"]),
        "partly_seeded": partly,
        "paid_calls": sum(r.get("usage", {}).get("calls", 0) for r in ok),
        "cost_usd": round(sum(r.get("usage", {}).get("cost_usd", 0) for r in ok), 6),
    }


def report(s: dict) -> None:
    v = s["violations"]
    print(f"\n# 레드팀 결과 (무료 모드, {s['scored']}/{s['items']}문항 채점)")
    print(f"위반 문항 {s['violated_items']} · 누출 {v['leak']} · 승인 없는 실행 {v['unapproved_exec']} "
          f"· 주입 반영 {v['injection_followed']} · 거짓 완료 말 {v['false_claim']} · 상한 {v['limit']}")  # fmt: skip
    print("| 종류 | 문항 | 위반 문항 | 잴 수 없는 확인 있음 |")
    print("| --- | --- | --- | --- |")
    for k, c in sorted(s["by_category"].items()):
        print(f"| {k} | {c['n']} | {c['violated']} | {c['na']} |")
    if s["seed_errors"]:
        print("심기 실패:", s["seed_errors"])
    print(f"공격 글 일부를 못 심은 문항: {', '.join(s['partly_seeded']) or '없음'}")
    print(f"유료 호출 {s['paid_calls']}회 · 비용 ${s['cost_usd']}")


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="v4 비서 레드팀(코드 판정)")
    ap.add_argument("--tag", default="rt-free")
    ap.add_argument("--only", help="문항 id를 쉼표로(예: RT01,RT31)")
    ap.add_argument("--db", default="mitjip_eval_rt")
    ap.add_argument("--redis-db", type=int, default=11)
    ap.add_argument("--env-file", type=Path, help="DB 접속값을 읽을 .env(키는 읽지 않아요)")
    ap.add_argument("--live", action="store_true", help="유료 모드(지금은 막아 둠)")
    a = ap.parse_args(argv)
    if a.live:
        print("유료 모드는 아직 막아 뒀어요(키 무효 · 리드 허락 전). 무료 모드로만 돌려요.")
        return 2
    apienv.free_mode()
    env = apienv.load_db_env(a.env_file)
    items = jsonl(SETS / "redteam.jsonl")
    if a.only:
        want = set(a.only.split(","))
        items = [x for x in items if x["id"] in want]
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    path = out / "redteam.jsonl"
    path.write_text("", encoding="utf-8")
    app = apienv.App(a.db, a.redis_db).boot()
    mode = apienv.settings_mode()
    if mode["available"]:
        app.close()
        print("LLM이 켜져 있어 멈춰요(무료 모드여야 해요).")
        return 2
    rows = []
    try:
        for item in items:
            app.reset()
            try:
                row = run_item(app, item)
            except Exception as e:  # noqa: BLE001 - 한 문항이 깨져도 기록하고 이어 가요
                row = {"id": item["id"], "category": item["category"], "surface": item["surface"],
                       "crash": f"{type(e).__name__}: {e}"[:300],
                       "trace": traceback.format_exc()[-1500:]}  # fmt: skip
            append_jsonl(path, row)
            rows.append(row)
            mark = "위반" if row.get("violated") else ("오류" if "counts" not in row else "통과")
            print(f"{item['id']} {item['category']} {mark} ({row.get('secs', '-')}초)", flush=True)
    finally:
        app.close()
    s = summarize(rows)
    s["mode"] = "free"
    (out / "summary.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    meta = {"tag": a.tag, "mode": mode, "db": a.db, "redis_db": a.redis_db,
            "env_file": env.name if env else None, "items": [x["id"] for x in items]}  # fmt: skip
    (out / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    report(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
