"""라우터 사례 무료 점검 (T0). check_cases.py가 부른다.

- 카드가 스펙 검사를 지나고 상담 규칙(normalize)으로 맞춘 것과 같다. 고객 말 · 앞 대화가 API 한도 안이다
- 기대 바뀐 칸이 모범 출력을 지금 상담 코드에 넣은 결과와 같다 (상담 코드 · 스펙이 바뀌면 여기서 잡힌다)
- 모범 출력이 채점을 모두 통과한다 (기대끼리 모순이 없다는 증거)
"""

from pathlib import Path

from pydantic import ValidationError

from app.agent.schemas import RouterOut
from app.consult.schemas import ConsultIn
from evaluation.common import gen, trades
from evaluation.router.score import apply, effect, score

HERE = Path(__file__).resolve().parent
KEYS = ("id", "split", "category", "strata", "input", "expect")


def default_cases() -> Path:
    full = HERE / "cases_5k.jsonl"
    return full if full.exists() else HERE / "sample_100.jsonl"


def check_case(case: dict) -> list[str]:
    if missing := [k for k in KEYS if k not in case]:
        return [f"키 없음: {missing}"]
    inp, exp = case["input"], case["expect"]
    try:
        c = trades.card(inp)
        ConsultIn(card=c, history=inp["history"], message=inp["message"])
    except (ValidationError, KeyError, TypeError) as e:
        return [f"입력이 상담 API 모양에 맞지 않아요: {type(e).__name__}"]
    errs = []
    if c.model_dump(mode="json") != inp["card"]:
        errs.append("카드가 상담 규칙(normalize)으로 맞춘 것과 달라요")
    ideal = RouterOut.model_validate(exp["ideal"])
    if effect(c, apply(c, ideal, exp["ideal"])) != exp["effect"]:
        errs.append("기대 바뀐 칸이 지금 상담 코드 결과와 달라요")
    if sorted({q.trade for q in ideal.questions}) != exp["questions"]:
        errs.append("기대 질문 공정이 모범 출력과 달라요")
    if ideal.out_of_scope != exp["out_of_scope"]:
        errs.append("범위 밖 기대가 모범 출력과 달라요")
    if set(exp["ideal"].get("trades_add") or []) & set(c.trades):
        errs.append("모범 출력이 이미 있는 공정을 더해요")
    s = score(case, exp["ideal"])
    if failed := [k for k, ok in s["checks"].items() if not ok]:
        errs.append(
            "모범 출력이 통과 못 함: " + "; ".join(f"{k} {s['detail'].get(k, '')}" for k in failed)
        )
    return errs


def check_set(cases: list[dict]) -> dict:
    problems = {}
    for c in cases:
        if errs := check_case(c):
            problems[c.get("id", "?")] = errs
    return gen.split_report(cases) | {"problems": problems}
