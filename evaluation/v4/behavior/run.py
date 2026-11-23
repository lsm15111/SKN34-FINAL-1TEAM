"""v4 비서 행동 평가: 2026-11-23에 바꾼 세 가지(범위 밖 막기 · 지식 근거 · 다음 단계 안내)를 여러 번 돌려 통과율을 봐요.

    cd backend && uv run python ../evaluation/v4/behavior/run.py --tag beh-free                 # 무료(LLM 0회)
    bash eval-live-openai.sh mitjip_eval_beh 9 -- uv run python ../evaluation/v4/behavior/run.py \
        --kinds next_step --live --provider openai --repeat 3 --max-usd 0.6 --tag beh-ns1      # 유료(허락 뒤)

- off_topic(48줄): 고객 말 하나 → runtime.off_topic(LLM 없이 막을지). block이 맞으면 통과. 정밀도 · 재현율도 내요.
  asked가 있으면 비서가 바로 앞에서 그 물음을 한 뒤의 말이에요.
- grounds(8줄): 도배 질문 → 지식 검색(키워드 + 공정, 말뭉치 evaluation/rag/.cache/corpus.json, 임베딩 없음). 1위 조각
  공정 갈래에 top1_scope가 있고, 앞 N위에 다른 마감이 주인인 조각(bm25.OTHER_FINISH)이 없으면 통과.
- next_step(9장면): 시나리오 world로 그 단계 공사를 심고(sim.world, 날짜는 오늘 쪽으로 옮김) 지식 질문 두 개를 보내요.
  첫 답은 안내(코드의 지금 할 일 줄 · 다음 일 카드 · 승인 카드 · 되물음 중 하나)가 있어야 하고, 둘째 답은 같은 지금 할 일
  줄을 되풀이하지 않아야 해요. 둘 다 맞아야 그 판 통과. --repeat k면 판마다 다시 심어 pass^1 · pass^k(τ-bench)를 내요.
  LLM 모드에서만 돌아요(--live, --max-usd). 모델 · effort는 OPENAI_* · LLM_CLAUDE_* 환경변수대로예요.
- 나눔: dev · held_out = 2 : 1(종류마다 고정 해시 순서, next_step은 시나리오 나눔). --split로 골라요(기본 dev).
- 저장: runs/<tag>/results.jsonl(판마다 한 줄) · summary.json · meta.json
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from math import comb
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
V4 = HERE.parent
RAG = V4.parent / "rag"
sys.path.insert(0, str(V4))

from kit import ROOT, RUNS, append_jsonl, jsonl, utf8_stdout

sys.path.insert(0, str(ROOT / "backend"))  # app.* (backend 폴더에서 돌리지 않아도)

CASES = HERE / "cases.jsonl"
KINDS = ("off_topic", "grounds", "next_step")
# 모델이 스스로 다음 단계를 말했는지(참고 칸, 통과 판단에는 안 써요)
NEXT = re.compile(
    r"(업체|실측|견적서|공사 날짜)[^.\n]{0,20}(골라|고르|요청|담아|추천|보내|비교|확정|수락)|차례예요|다음(은| 단계| 할 일)"
)
CASE_USD = 0.03  # 다음 단계 한 장면(두 턴) 처음 어림
MARGIN = 1.25


def load(kinds: list[str], split: str) -> list[dict]:
    rows = [r for r in jsonl(CASES) if r["kind"] in kinds]
    return rows if split == "all" else [r for r in rows if r["split"] == split]


def base(r: dict) -> dict:
    return {"id": r["id"], "kind": r["kind"], "split": r["split"]}


# ---- 범위 밖 막기(코드) ----


def run_off_topic(rows: list[dict]) -> list[dict]:
    from app.assistant import runtime

    out = []
    for r in rows:
        hist = [{"role": "assistant", "content": r["asked"]}] if r.get("asked") else []
        ctx = SimpleNamespace(
            surface="customer", pressed=False, choice=[], text=r["text"], history=hist
        )
        got = runtime.off_topic(ctx)  # type: ignore[arg-type]
        out.append(
            {
                **base(r),
                "text": r["text"],
                "block": r["block"],
                "got": got,
                "pass": got == r["block"],
            }
        )
    return out


# ---- 지식 근거(키워드 검색) ----


def run_grounds(rows: list[dict]) -> list[dict]:
    from app.knowledge import bm25

    sys.path.insert(0, str(RAG))
    import rank_server

    corpus = RAG / ".cache" / "corpus.json"
    if not corpus.exists():
        raise SystemExit("말뭉치가 없어요. 먼저 python evaluation/rag/corpus.py를 돌려요")
    ix = rank_server.load_index(corpus)
    out = []
    for r in rows:
        hits = bm25.search(ix, r["text"], k=6, trade=r["trade"]).hits
        # 검사는 고친 규칙(bm25.OTHER_FINISH)과 따로 줄마다 적은 낱말로 해요(규칙을 꺼도 잡히게)
        n, banned = r["no_other_finish_top"], set(r.get("banned_first") or ())
        other = [h.ref for h in hits[:n] if (ix.by_ref[h.ref].chunk.trades or ("",))[0] in banned]
        ok = bool(hits) and r["top1_scope"] in hits[0].scope and not other
        out.append({**base(r), "text": r["text"], "pass": ok, "other_finish": other,
                    "top": [[h.ref, list(h.scope), h.title[:30]] for h in hits[:3]]})  # fmt: skip
    return out


# ---- 다음 단계 안내(LLM) ----


def judge_turns(recs: list[dict]) -> dict:
    """두 턴 기록 → 안내 · 되풀이 판단."""
    from app.assistant import free, runtime

    lines = sorted((x for x in free.NOW_LINES if x), key=len, reverse=True)

    def code(text: str) -> str | None:
        return next((x for x in lines if x in text), None)

    first, second = recs[0], recs[1] if len(recs) > 1 else None
    t1 = first.get("text") or ""
    g = {
        "code": code(t1),
        "card": [c for c in first.get("cards") or [] if c in runtime.STEP_CARDS],
        "action": bool(first.get("actions")),
        "asked": t1.rstrip().endswith("?"),
        "model": bool(NEXT.search(t1)),
    }
    guided = bool(g["code"] or g["card"] or g["action"] or g["asked"])
    again = code(second.get("text") or "") if second else None
    repeat = bool(again and again == g["code"])
    ok_turns = all(r.get("http") == 200 and r.get("mode") == "llm" for r in recs)
    return {"guide": g, "guided": guided, "repeat": repeat, "ok_turns": ok_turns,
            "pass": ok_turns and guided and not repeat}  # fmt: skip


def run_next_step(rows: list[dict], a, out: Path) -> list[dict]:
    import apienv
    from sim import check, drive
    from sim.world import SeedError, World

    from app.shared.clock import today_seoul

    app = apienv.App(a.db, a.redis_db).boot()
    mode = apienv.settings_mode()
    if not mode["available"]:
        app.close()
        raise SystemExit("LLM을 부를 수 없어 멈춰요(LLM_LIVE · 키 · 공급자).")
    spent, worst, done = 0.0, CASE_USD, []
    try:
        for trial in range(1, a.repeat + 1):
            for r in rows:
                if spent + worst * MARGIN > a.max_usd:
                    print(f"상한 ${a.max_usd}: 지금까지 ${spent:.4f} + 다음 어림이 넘어 멈춰요")
                    return done
                app.reset()
                sc = json.loads(
                    (V4 / "sets" / "scenarios" / f"{r['world']}.json").read_text("utf-8")
                )
                real_today = today_seoul()
                s = check.shift_obj(
                    sc, check.week_shift(date.fromisoformat(sc["world"]["today"]), real_today)
                )
                world = World(app.api, app.query, real_today, app.call)
                row = {**base(r), "trial": trial, "world": r["world"], "stage": r["stage"]}
                t0 = time.monotonic()
                try:
                    world.seed(s["world"])
                except SeedError as x:
                    row.update(seed_error=str(x), guided=False, repeat=False)
                    row["pass"] = False
                    done.append(row)
                    append_jsonl(out / "results.jsonl", row)
                    continue
                cref = (s["world"].get("customer") or {}).get("ref") or "c1"
                who, pid = world.customers[cref], world.customers[cref]["pid"]
                recs = [
                    drive.turn(app, world, who, "customer", q, project_id=pid) for q in r["turns"]
                ]
                cost = drive.usage(app)["cost_usd"]
                spent, worst = spent + cost, max(worst, cost)
                row.update(judge_turns(recs), cost_usd=round(cost, 6), s=round(time.monotonic() - t0, 1),
                           texts=[(x.get("text") or "")[:400] for x in recs],
                           cards=[x.get("cards") for x in recs], tools=[x.get("tools_ok") for x in recs])  # fmt: skip
                done.append(row)
                append_jsonl(out / "results.jsonl", row)
                g = row["guide"]
                print(f"{r['id']} #{trial} {r['stage']} {'통과' if row['pass'] else '실패'} · 코드 줄 {bool(g['code'])} · "
                      f"카드 {g['card']} · 되물음 {g['asked']} · 되풀이 {row['repeat']} · ${cost:.4f}")  # fmt: skip
    finally:
        app.close()
    return done


# ---- 요약 ----


def pass_k(rows: list[dict], k: int) -> float | None:
    by: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by[r["id"]].append(bool(r.get("pass")))
    vals = [comb(sum(v), k) / comb(len(v), k) for v in by.values() if len(v) >= k]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize(results: dict[str, list[dict]], repeat: int) -> dict:
    out: dict = {}
    if rows := results.get("off_topic"):
        tp = sum(1 for r in rows if r["block"] and r["got"])
        fp = sum(1 for r in rows if not r["block"] and r["got"])
        fn = sum(1 for r in rows if r["block"] and not r["got"])
        out["off_topic"] = {
            "n": len(rows), "pass": round(sum(r["pass"] for r in rows) / len(rows), 4),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "wrong": [{"id": r["id"], "text": r["text"], "block": r["block"]} for r in rows if not r["pass"]],
        }  # fmt: skip
    if rows := results.get("grounds"):
        out["grounds"] = {"n": len(rows), "pass": round(sum(r["pass"] for r in rows) / len(rows), 4),
                          "wrong": [r["id"] for r in rows if not r["pass"]]}  # fmt: skip
    if rows := results.get("next_step"):
        ok = [r for r in rows if "guide" in r]
        out["next_step"] = {
            "runs": len(rows), "cases": len({r["id"] for r in rows}), "repeat": repeat,
            "pass^1": pass_k(rows, 1), f"pass^{repeat}": pass_k(rows, repeat),
            "guided": round(sum(r["guided"] for r in ok) / len(ok), 4) if ok else None,
            "code_line": round(sum(bool(r["guide"]["code"]) for r in ok) / len(ok), 4) if ok else None,
            "model_said_next": round(sum(r["guide"]["model"] for r in ok) / len(ok), 4) if ok else None,
            "repeat_line": sum(r["repeat"] for r in ok),
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 6),
        }  # fmt: skip
    return out


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="v4 비서 행동 평가(범위 밖 막기 · 지식 근거 · 다음 단계 안내)"
    )
    ap.add_argument("--tag", required=True)
    ap.add_argument(
        "--kinds", default="off_topic,grounds", help="쉼표로: off_topic · grounds · next_step"
    )
    ap.add_argument("--split", default="dev", choices=["dev", "held_out", "all"])
    ap.add_argument("--repeat", type=int, default=1, help="next_step 판 수")
    ap.add_argument(
        "--live", action="store_true", help="LLM 모드(유료, next_step에 필요). --max-usd를 꼭 줘요"
    )
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="openai")
    ap.add_argument("--max-usd", type=float)
    ap.add_argument("--db", default="mitjip_eval_beh")
    ap.add_argument("--redis-db", type=int, default=9)
    ap.add_argument("--env-file", type=Path, help="DB 접속값을 읽을 .env(키는 읽지 않아요)")
    a = ap.parse_args(argv)
    kinds = [k for k in a.kinds.split(",") if k]
    if bad := [k for k in kinds if k not in KINDS]:
        ap.error(f"모르는 종류: {bad}")
    if "next_step" in kinds and not (a.live and a.max_usd and a.max_usd > 0):
        ap.error("next_step은 --live와 --max-usd(0보다 큰 값)가 필요해요")

    import apienv

    if a.live:
        apienv.openai_mode() if a.provider == "openai" else apienv.live_mode()
    else:
        apienv.free_mode()
    apienv.load_db_env(a.env_file)
    out = RUNS / a.tag
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text("", encoding="utf-8")
    results: dict[str, list[dict]] = {}
    for kind in kinds:
        rows = load([kind], a.split)
        if kind == "off_topic":
            results[kind] = run_off_topic(rows)
        elif kind == "grounds":
            results[kind] = run_grounds(rows)
        else:
            results[kind] = run_next_step(rows, a, out)
        if kind != "next_step":
            for r in results[kind]:
                append_jsonl(out / "results.jsonl", r)
    summary = summarize(results, a.repeat)
    meta = {"tag": a.tag, "kinds": kinds, "split": a.split, "repeat": a.repeat, "live": a.live,
            "llm": apienv.live_settings() if a.live else None, "max_usd": a.max_usd}  # fmt: skip
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    (out / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), "utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
