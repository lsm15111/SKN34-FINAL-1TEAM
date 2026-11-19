"""질문 세트 커버리지 점검: 모든 질문을 입구 관문(gate.gate)과 무료 모드 한 턴(run_turn, LLM_LIVE=false)에 넣어 센다.

    cd backend && LLM_LIVE=false OPENAI_API_KEY= uv run python ../evaluation/v3/coverage_check.py [--dense]

- 지식: 저장소 CSV + v3 지식 요지로 만든 색인(tests/v3_kb.repo_kb, DB 없음)과 카드 파일
- 유료 호출 0회: settings.llm_live가 켜져 있으면 멈추고, llm.structured · jev_choice · embed는 부르면 오류
- 세는 것: 담당 분포 · 되묻기 · 범위 밖 · 예외 · 출력 검사에서 빠진 문장 · 답 출처(카드 · 조각 · 정해 둔 글 · 모름)
  · 정답 라벨이 있으면 정확도 · 틀린 예시
- --dense: 질문마다 의미 검색 순위(KB.dense)를 넣는다. 순위는 dense_prep.py가 만든 .cache/q_dense.json(유료 호출 없음)
"""

import argparse
import asyncio
import dataclasses
import json
import sys
import traceback
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "backend", ROOT / "backend/tests", ROOT / "evaluation", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.agent import llm
from app.agent.v3 import gate as gate_mod
from app.agent.v3 import templates
from app.agent.v3.schemas import (
    EstimateFacts,
    PlanFacts,
    ProjectFacts,
    StandardFacts,
    StandardLineFact,
    TurnContext,
    VisitDraftFacts,
)
from app.agent.v3.turn import run_turn
from app.config import settings

TODAY = date(2026, 11, 19)
KO_TRADE = {"도배": "dobae", "목공": "mokgong", "공통": "common"}
FACTS = ProjectFacts(
    stage="standard", area_m2=69.4, area_basis="supply", trades=["dobae", "mokgong"], grade="basic",
    standard=StandardFacts(total=1974069, supply=1794608, vat=179461, lines=[
        StandardLineFact(key="wall", name="벽 도배 시공 풀 포함", state="included", qty=130.1,
                         unit="㎡", unit_price=5993, amount=779689),
        StandardLineFact(key="demolish", name="기존 벽지 철거", state="after_visit", qty=173.5,
                         unit="㎡", unit_price=1727, amount=299635),
    ]),
    plan=PlanFacts(start=date(2027, 1, 4), end=date(2027, 1, 5), work_days=2),
    visit_draft=VisitDraftFacts(
        wish_start=date(2026, 12, 7), wish_end=date(2026, 12, 21), basis_start=date(2027, 1, 4),
        formula="공사 시작 희망일 − 28일 ~ − 14일", vendors=["마루와벽", "결도배"],
    ),
    estimates=[EstimateFacts(vendor="마루와벽", total=2100000, vs_standard=6)],
)  # fmt: skip


def _no_paid(*_a, **_k):
    raise RuntimeError("유료 호출 막음")


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


# ---- 세트 읽기: 각 줄 {set, id, text, has_project, gold_route|None, ok_routes|None, gold_trade|None, gold_ask|None}
def load_sets() -> list[dict]:
    from e1_gate import v3_gold
    from intent_metrics import load_examples

    out: list[dict] = []
    for split in ("dev", "heldout"):
        for i, e in enumerate(load_examples(ROOT / "evaluation/intent" / f"{split}.jsonl")):
            out.append({"set": "intent", "id": f"{split}-{i}", "text": e.text, "has_project": True,
                        "gold_route": v3_gold(e), "gold_trade": None})  # fmt: skip

    def bank_rows(name: str, rows: list[dict]) -> None:
        for q in rows:
            gr = (
                "out_of_scope"
                if q["expect"] == "out_of_scope"
                else ("guide" if q["trade"] == "common" else "trade")
            )
            out.append({"set": name, "id": q["id"], "text": q["text"], "has_project": False,
                        "gold_route": gr, "gold_trade": q["trade"], "expect": q["expect"]})  # fmt: skip

    qdir = ROOT / "data/v3/questions"
    bank_rows("bank", [q for f in sorted(qdir.glob("*.jsonl")) for q in jsonl(f)])
    bank_rows("beginner", jsonl(qdir / "beginner_web/questions.jsonl"))

    for name, f in (
        ("rag90", "rag/questions.jsonl"),
        ("rag300", "rag/questions_300.jsonl"),
        ("rag_sigong", "rag/questions_sigong.jsonl"),
        ("answer30", "answer/set30.jsonl"),
        ("trade18", "trade/dobae.jsonl"),
        ("trade18", "trade/mokgong.jsonl"),
    ):
        for q in jsonl(ROOT / "evaluation" / f):
            tr = KO_TRADE.get(q.get("trade", ""))
            gr = None if tr is None else ("guide" if tr == "common" else "trade")
            if q.get("expect") == "engine":
                gr = None  # 계산 엔진 질문: 담당 정답을 정하지 않음(가이드 · 공종 · 견적 설명 모두 될 수 있음)
            out.append({"set": name, "id": q["id"], "text": q["text"], "has_project": False,
                        "gold_route": gr, "gold_trade": tr, "expect": q.get("expect")})  # fmt: skip
    for split in ("dev", "heldout"):
        for i, q in enumerate(jsonl(ROOT / "evaluation/ask_back" / f"{split}.jsonl")):
            out.append({"set": "ask_back21", "id": f"{split}-{i}", "text": q["text"], "has_project": False,
                        "gold_route": None, "gold_trade": None, "gold_ask": bool(q["ask"])})  # fmt: skip
    cov = HERE / "coverage_questions.jsonl"
    if cov.exists():
        for q in jsonl(cov):
            out.append({"set": "coverage", "id": q["id"], "text": q["text"], "cat": q["cat"],
                        "has_project": q["has_project"], "gold_route": None, "ok_routes": q["ok"],
                        "gold_trade": q["trade"]})  # fmt: skip
    return out


def answer_kind(ans) -> str:
    srcs = {s.source for s in ans.sections}
    if "card" in srcs:
        return "card"
    if "extract" in srcs:
        return "extract"
    if ans.calc and not srcs - {"template"}:
        return "template+calc" if srcs else "calc"
    if srcs == {"template"}:
        return "template_only" if not ans.unknown else "template+unknown"
    if ans.unknown:
        return "unknown"
    if ans.cards:
        return "cards_only"
    return "empty"


def with_dense(kb, text: str, ranks: dict | None):
    """질문 하나의 KB: 서비스처럼 이 턴 질문의 의미 검색 순위를 채운다(ranks가 없으면 키워드만)."""
    if not ranks:
        return kb
    from app.agent.v3 import check

    return dataclasses.replace(kb, dense=ranks.get(check.mask(text)[:300], ()))


async def one(q: dict, kb, ranks: dict | None = None) -> dict:
    kb = with_dense(kb, q["text"], ranks)
    r = {k: q.get(k) for k in ("set", "id", "text", "gold_route", "gold_trade", "cat", "expect")}
    facts = FACTS if q["has_project"] else None
    try:
        g = gate_mod.gate(q["text"], has_project=facts is not None)
        r |= {"gate_route": g.route, "gate_trades": g.trades, "gate_source": g.source,
              "conf": g.confidence, "label": g.label, "policy": g.policy}  # fmt: skip
    except Exception as e:  # noqa: BLE001
        r["gate_error"] = f"{type(e).__name__}: {e}"
        r["gate_tb"] = traceback.format_exc(limit=3)
    try:
        ctx = TurnContext(user_id=uuid.UUID(int=0), today=TODAY, mode="free")
        res = await run_turn(q["text"], ctx, kb=kb, facts=facts)
        a = res.answer
        r |= {
            "route": a.trace.route, "trades": a.trace.trades, "ask": a.ask.slot if a.ask else None,
            "failed": a.failed, "dropped": a.trace.dropped, "kind": answer_kind(a),
            "has_sources": any(s.sources for s in a.sections),
            "has_cites": any(c for s in a.sections for x in s.sentences for c in x.cites),
            "parts": a.trace.parts, "failed_parts": a.trace.failed_parts,
            "first": next((x.text for s in a.sections for x in s.sentences), (a.unknown or [""])[0])[:80],
            "says_unknown": templates.UNKNOWN in a.unknown,  # 화면에 '확인하지 못했어요'가 실제로 나오는가
        }  # fmt: skip
    except Exception as e:  # noqa: BLE001
        r["turn_error"] = f"{type(e).__name__}: {e}"
        r["turn_tb"] = traceback.format_exc(limit=4)
    return r


def correct(r: dict) -> bool | None:
    route = r.get("route")
    if route is None:
        return False
    if r.get("ok_routes"):
        ok = route in r["ok_routes"]
        if ok and r.get("gold_trade") and route in ("trade", "multi"):
            ok = r["gold_trade"] in (r.get("trades") or [])
        return ok
    gr = r.get("gold_route")
    if gr is None:
        return None
    if gr == "trade" and route == "multi" and r.get("gold_trade") in (r.get("trades") or []):
        return True  # 공종 질문이 multi로 가도 정답 공종이 들어 있으면 공종 길(e1_gate와 같은 규칙)
    return route == gr


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    routes = Counter(r.get("route", "ERROR") for r in rows)
    gate_routes = Counter(r.get("gate_route", "ERROR") for r in rows)
    drop_turns = [r for r in rows if r.get("dropped")]
    reasons = Counter(x for r in rows for x in r.get("dropped") or [])
    judged = [(r, correct(r)) for r in rows]
    judged = [(r, c) for r, c in judged if c is not None]
    k = sum(c for _, c in judged)
    tr_rows = [
        r
        for r in rows
        if r.get("gold_trade") not in (None, "common") and r.get("route") in ("trade", "multi")
    ]
    tr_ok = sum((r.get("trades") or [None])[0] == r["gold_trade"] for r in tr_rows)
    ask_rows = [r for r in rows if "gold_ask" in r or r.get("set") == "ask_back21"]
    out = {
        "n": n,
        "route": dict(routes.most_common()),
        "gate_route": dict(gate_routes.most_common()),
        "ask_back": routes.get("ask_back", 0),
        "out_of_scope": routes.get("out_of_scope", 0),
        "slot_ask": sum(1 for r in rows if r.get("ask")),
        "gate_errors": sum(1 for r in rows if "gate_error" in r),
        "turn_errors": sum(1 for r in rows if "turn_error" in r),
        "failed": sum(1 for r in rows if r.get("failed")),
        "dropped_turns": len(drop_turns),
        "dropped_reasons": dict(reasons.most_common()),
        "kind": dict(Counter(r.get("kind", "ERROR") for r in rows).most_common()),
        "with_sources": sum(1 for r in rows if r.get("has_sources")),
        "judged": len(judged),
        "correct": k,
        "trade_first": f"{tr_ok}/{len(tr_rows)}",
    }
    if ask_rows:
        out["ask_agree"] = sum(
            (r.get("route") == "ask_back" or bool(r.get("ask"))) == r["gold_ask"]
            for r in ask_rows
            if "gold_ask" in r
        )
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if settings.llm_live:
        sys.exit("LLM_LIVE=true 라서 멈춰요(유료 호출 막기)")
    llm.structured = _no_paid  # type: ignore[assignment]
    llm.jev_choice = _no_paid  # type: ignore[assignment]
    llm.embed_query = _no_paid  # type: ignore[assignment]
    from v3_kb import repo_kb

    kb = repo_kb()
    ranks = None
    if a.dense:
        from dense_prep import load

        ranks = load()
    qs = load_sets()
    rows = []
    for q in qs:
        r = await one(q, kb, ranks)
        if "gold_ask" in q:
            r["gold_ask"] = q["gold_ask"]
        if "ok_routes" in q:
            r["ok_routes"] = q["ok_routes"]
        rows.append(r)
    sets = list(dict.fromkeys(r["set"] for r in rows))
    report = {"kb": {"chunks": kb.ix.n, "cards": len(kb.cards.cards), "card_set": kb.cards.version,
                     "dense": a.dense}}  # fmt: skip
    report["sets"] = {s: summarize([r for r in rows if r["set"] == s]) for s in sets}
    report["all"] = summarize(rows)
    cov = [r for r in rows if r["set"] == "coverage"]
    report["coverage_by_cat"] = {
        c: {"n": len(x), "ok": sum(bool(correct(r)) for r in x),
            "routes": dict(Counter(r.get("route", "ERROR") for r in x))}
        for c in dict.fromkeys(r["cat"] for r in cov)
        for x in [[r for r in cov if r["cat"] == c]]
    }  # fmt: skip
    wrong = [r for r in rows if correct(r) is False]
    report["wrong_by_pair"] = dict(
        Counter(
            f"{r['set']}: {r.get('gold_route') or r.get('ok_routes')} → {r.get('route')}"
            for r in wrong
        ).most_common(30)
    )
    out = HERE / ".cache"  # git 밖
    out.mkdir(exist_ok=True)
    (out / "coverage_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with (out / "coverage_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
