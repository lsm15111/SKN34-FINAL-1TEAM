"""전문가 답 사례 무료 점검 (T0). check_cases.py가 부른다.

- 카드가 스펙 검사를 지나고 상담 규칙(normalize)으로 맞춘 것과 같다
- 집 정보 글이 지금 상담 코드(consult.service.facts)로 만든 것과 같다
- 거리(무엇을 묻는지)가 지금 스펙 · 지식에 있고 핵심 말이 지금 만든 것과 같다 (지식 · 용어 · 스펙이 바뀌면 잡힌다)
- 모범 답이 채점을 모두 통과한다 (기대끼리 모순이 없다는 증거)
"""

from pathlib import Path

from pydantic import ValidationError

from evaluation.common import gen, trades
from evaluation.expert import make_cases
from evaluation.expert.score import score

HERE = Path(__file__).resolve().parent
KEYS = ("id", "trade", "split", "category", "topic", "strata", "input", "expect")


def default_cases() -> Path:
    full = HERE / "cases_5k.jsonl"
    return full if full.exists() else HERE / "sample_100.jsonl"


def check_case(case: dict) -> list[str]:
    if missing := [k for k in KEYS if k not in case]:
        return [f"키 없음: {missing}"]
    trade, topic, inp = case["trade"], case["topic"], case["input"]
    if trade not in trades.registered():
        return [f"등록되지 않은 공정: {trade}"]
    errs = []
    if case["category"] != f"{trade}.{topic}" or case["split"] not in gen.SPLITS:
        errs.append("category · split 값")
    try:
        c = trades.card(inp)
    except (ValidationError, KeyError, TypeError) as e:
        return errs + [f"카드가 스펙에 맞지 않아요: {type(e).__name__}"]
    if c.model_dump(mode="json") != inp["card"]:
        errs.append("카드가 상담 규칙(normalize)으로 맞춘 것과 달라요")
    if trades.expert_text(c, trade) != inp.get("context"):
        errs.append("집 정보 글이 지금 상담 코드로 만든 것과 달라요")
    q = inp.get("question") or ""
    if not q.strip() or len(q) > 500:
        errs.append("질문이 비었거나 너무 길어요")
    subj = make_cases.subjects(trade, topic).get(case["strata"].get("subject"))
    if subj is None:
        return errs + ["거리가 지금 스펙 · 지식에 없어요"]
    if list(subj.groups) != case["expect"]["groups"]:
        errs.append("핵심 말이 지금 만든 것과 달라요")
    s = score(case, case["expect"]["ideal"])
    if failed := [k for k, ok in s["checks"].items() if not ok]:
        errs.append(
            "모범 답이 통과 못 함: " + "; ".join(f"{k} {s['detail'].get(k, '')}" for k in failed)
        )
    return errs


def check_set(cases: list[dict]) -> dict:
    problems = {}
    for c in cases:
        if errs := check_case(c):
            problems[c.get("id", "?")] = errs
    return gen.split_report(cases) | {"problems": problems}
