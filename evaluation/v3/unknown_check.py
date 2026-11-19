"""'모름'으로 끝나는 답의 원인 나누기 + 전후 비교 숫자 (무료 모드, 유료 호출 0회).

    cd backend && LLM_LIVE=false OPENAI_API_KEY= uv run python ../evaluation/v3/unknown_check.py [--split dev|heldout|all] [--tag 이름] [--dense]

- 질문 세트 · 한 턴은 coverage_check와 같다(load_sets · one). 질문마다 dev · held-out(split 칸)을 붙인다.
- answer.knowledge를 감싸서 부를 때마다 카드 점수 · 맞물림 · 검색 덮음(enough) · 조각 문장 점수 · 출력 검사를 남긴다.
- 원인(모름으로 끝난 knowledge 호출마다 하나): 아래 순서로 처음 맞는 것
  policy_no_extract(정책 질문이라 조각 뽑기 안 함) · check_drop(출력 검사가 뺌) · card_near(카드 점수가 문턱 바로 아래)
  · trade_filter(공종을 거르지 않으면 문턱 넘는 카드가 있음) · not_enough(검색 덮음 부족) · extract_low(조각 문장 점수 미달)
  · display_none(위 조각이 모두 보이지 않는 출처) · no_material(카드 · 조각 모두 멀다: 맞는 자료 없음 추정)
- gold: rag 세트(gold 조각 있음)에서 답에 쓴 조각이 gold에 드는 비율.
- 기본은 dev만 보인다. held-out은 마지막에 한 번만(--split heldout).
- --dense: 질문마다 의미 검색 순위를 넣는다(coverage_check --dense와 같음, dense_prep.py가 만든 캐시).
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "backend", ROOT / "backend/tests", ROOT / "evaluation", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import coverage_check as cc

from app.agent import llm
from app.agent.v3 import answer, guide, quote_explain, schedule_agent, trade_agent
from app.config import settings
from app.knowledge import cards, extract

NEAR_LOW = 0.45  # 이 점수 이상이면 '문턱 바로 아래'로 본다
CALLS: list[dict] = []


def diagnose(kb, q: str, trade, intents, policy, allow_extract: bool) -> dict:
    hits = answer.search(kb, q, trade)
    top = [h.ref for h in hits.hits[:8]]
    want = [trade] if trade and trade != "common" else None
    m = cards.find(kb.cards, q, trades=want, intents=intents, k=4)
    ranked = []
    for x in m:
        locked = bool(set(x.card.cites()) & set(top))
        ranked.append((x.score, locked, x.card.id))
    ranked.sort(key=lambda p: -p[0])
    free = cards.find(kb.cards, q, k=1)
    quotes = extract.pick(kb.ix, q, hits.hits, k=1, min_score=-9) if hits.hits else []
    disp = [
        extract.display_of(kb.ix.by_ref[h.ref].doc.kind)
        for h in hits.hits[:6]
        if h.ref in kb.ix.by_ref
    ]
    return {
        "card": ranked[0] if ranked else None,
        "free": (free[0].score, free[0].card.id, free[0].card.trade) if free else None,
        "enough": hits.enough,
        "ext": quotes[0].score if quotes else None,
        "ext_text": quotes[0].text[:60] if quotes else "",
        "disp_none": bool(disp) and all(d == "none" for d in disp),
        "no_extract": bool(answer.NO_EXTRACT & set(policy)) or not allow_extract,
        "top": top[:5],
    }


def cause(d: dict, dropped: bool) -> str:
    if dropped:
        return "check_drop"
    c = d["card"]
    if c and c[0] >= NEAR_LOW:
        return "card_near"
    f = d["free"]
    if f and f[0] >= answer.T_HIGH and (not c or f[1] != c[2]):
        return "trade_filter"
    if d["no_extract"]:
        return "policy_no_extract"
    if not d["enough"]:
        return "not_enough"
    if d["disp_none"]:
        return "display_none"
    if d["ext"] is not None and d["ext"] < extract.MIN_SCORE:
        return "extract_low"
    return "no_material"


def wrap(orig):
    def knowledge(part, kb, q, **kw):
        before, used0, sec0 = len(part.dropped), len(part.used_chunks), len(part.sections)
        how = orig(part, kb, q, **kw)
        used = [r for r in part.used_chunks[used0:] if not r.startswith("doc:")]
        said = [x.text for sec in part.sections[sec0:] for x in sec.sentences][:4]
        rec = {"q": q, "trade": kw.get("trade"), "route": kw.get("route"), "how": how, "used": used,
               "said": said, "card_id": part.used_cards[-1] if how == "card" else ""}  # fmt: skip
        if how == "card":  # 받은 카드의 맞물림 · 의미 검색 순위(규칙 고르기용)
            cites = set(part.used_chunks[used0:])  # 받은 카드의 근거 조각
            top = [h.ref for h in answer.search(kb, q, kw.get("trade")).hits[:8]]
            ref_of = {x.chunk.ref: rid for rid, x in kb.ix.by_rid.items()}
            ranks = [i for i, rid in enumerate(kb.dense) if rid in {ref_of.get(c) for c in cites}]
            rec |= {"card_score": part.scores.get(rec["card_id"]), "locked": bool(cites & set(top)),
                    "top_pos": min((top.index(c) for c in cites if c in top), default=None),
                    "dense_pos": ranks[0] if ranks else None, "has_dense": bool(kb.dense)}  # fmt: skip
        if how == "unknown":
            d = diagnose(kb, q, kw.get("trade"), kw.get("intents"), kw.get("policy") or (),
                         kw.get("allow_extract", True))  # fmt: skip
            rec |= d
            rec["cause"] = cause(d, len(part.dropped) > before)
        CALLS.append(rec)
        return how

    return knowledge


def splits() -> dict[tuple[str, str], str]:
    """(세트, id) → split. intent · ask_back은 id 앞머리, 나머지는 파일 split 칸."""
    out: dict[tuple[str, str], str] = {}
    qdir = ROOT / "data/v3/questions"
    for f in sorted(qdir.glob("*.jsonl")):
        for q in cc.jsonl(f):
            out[("bank", q["id"])] = q["split"]
    for q in cc.jsonl(qdir / "beginner_web/questions.jsonl"):
        out[("beginner", q["id"])] = q["split"]
    for name, f in (
        ("rag90", "rag/questions.jsonl"), ("rag300", "rag/questions_300.jsonl"),
        ("rag_sigong", "rag/questions_sigong.jsonl"), ("answer30", "answer/set30.jsonl"),
        ("trade18", "trade/dobae.jsonl"), ("trade18", "trade/mokgong.jsonl"),
    ):  # fmt: skip
        for q in cc.jsonl(ROOT / "evaluation" / f):
            out[(name, q["id"])] = q.get("split", "none")
    return out


def golds() -> dict[tuple[str, str], set[str]]:
    out = {}
    for name, f in (("rag90", "questions.jsonl"), ("rag300", "questions_300.jsonl"),
                    ("rag_sigong", "questions_sigong.jsonl")):  # fmt: skip
        for q in cc.jsonl(ROOT / "evaluation/rag" / f):
            g = {x["ref"] for x in q.get("gold") or [] if x.get("ref")}
            if g:
                out[(name, q["id"])] = g
    return out


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    kind = Counter(r.get("kind") for r in rows)
    unk = sum(kind[k] for k in ("unknown", "template+unknown"))
    judged = [(r, cc.correct(r)) for r in rows]
    judged = [c for _, c in judged if c is not None]
    g = [r for r in rows if r.get("gold")]
    used = [r for r in g if r.get("chunks")]
    hit = [r for r in used if set(r["chunks"]) & set(r["gold"])]
    ch_all = sum(len(r["chunks"]) for r in used)
    ch_in = sum(len(set(r["chunks"]) & set(r["gold"])) for r in used)
    says = sum(1 for r in rows if r.get("says_unknown"))
    return {
        "n": n,
        "unknown_end": f"{unk} ({unk / n:.1%})" if n else "0",
        "says_unknown": f"{says} ({says / n:.1%})" if n else "0",
        "unknown_only": kind["unknown"],
        "card": f"{kind['card']} ({kind['card'] / n:.1%})" if n else "0",
        "extract": f"{kind['extract']} ({kind['extract'] / n:.1%})" if n else "0",
        "kind": dict(kind.most_common()),
        "acc": f"{sum(judged)}/{len(judged)} ({sum(judged) / max(len(judged), 1):.1%})",
        "gold_q": len(g),
        "gold_used": len(used),
        "gold_hit": f"{len(hit)}/{len(used)} ({len(hit) / max(len(used), 1):.1%})",
        "gold_chunk_prec": f"{ch_in}/{ch_all} ({ch_in / max(ch_all, 1):.1%})",
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "heldout", "all"])
    ap.add_argument("--tag", default="now")
    ap.add_argument("--dense", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if settings.llm_live:
        sys.exit("LLM_LIVE=true 라서 멈춰요(유료 호출 막기)")
    llm.structured = cc._no_paid  # type: ignore[assignment]
    llm.jev_choice = cc._no_paid  # type: ignore[assignment]
    llm.embed_query = cc._no_paid  # type: ignore[assignment]
    k = wrap(answer.knowledge)
    for mod in (answer, guide, trade_agent, quote_explain, schedule_agent):
        mod.knowledge = k  # type: ignore[attr-defined]
    from v3_kb import repo_kb

    kb = repo_kb()
    ranks = None
    if a.dense:
        from dense_prep import load

        ranks = load()
    sp, gd = splits(), golds()
    rows = []
    for q in cc.load_sets():
        CALLS.clear()
        r = await cc.one(q, kb, ranks)
        if "ok_routes" in q:
            r["ok_routes"] = q["ok_routes"]
        sid = q["id"]
        if q["set"] in ("intent", "ask_back21"):
            r["split"] = sid.split("-")[0]
        else:
            r["split"] = sp.get((q["set"], sid), "none")
        if (q["set"], sid) in gd:
            r["gold"] = sorted(gd[(q["set"], sid)])
        r["calls"] = list(CALLS)
        r["chunks"] = [c for c in dict.fromkeys(x for c in CALLS for x in c.get("used", []))]
        rows.append(r)
    out = HERE / ".cache"
    out.mkdir(exist_ok=True)
    with (out / f"unknown_rows_{a.tag}.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    show = rows if a.split == "all" else [r for r in rows if r["split"] == a.split]
    rep = {"split": a.split, "metrics": metrics(show)}
    calls = [c for r in show for c in r["calls"] if c["how"] == "unknown"]
    rep["unknown_calls"] = len(calls)
    rep["cause"] = dict(Counter(c["cause"] for c in calls).most_common())
    rep["by_set"] = {
        s: metrics([r for r in show if r["set"] == s])
        for s in dict.fromkeys(r["set"] for r in show)
    }
    (out / f"unknown_report_{a.tag}_{a.split}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in rep.items() if k != "by_set"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
