"""무료 점검(T0): 만든 사례를 상담 · 계산 코드에 다시 넣어 보고, 기대 규칙끼리 모순이 없는지 본다. LLM 호출 없음.

공정 의견 (공정마다)
1. 형식: 키 · id 중복 · 같은 입력 · 범주마다 dev:held-out 2:1 · 두 나눔의 문장 조각 겹침
2. 카드: 상담 카드(ConsultCard)로 스펙 검사를 지나고, 상담과 같게 맞춘 카드(normalize)와 같다
3. 계산: 저장한 단계 키 · '실측 후' 줄이 지금 계산과 같다 (계산 엔진 · 기준 단가가 바뀌면 여기서 잡힌다)
4. 기대 검사: 지금 규칙으로 다시 만든 것과 같고, 규칙 id가 채점표에 있으며, 꼭 언급과 언급하면 안 됨이 겹치지 않는다
5. 모범 답: 규칙을 모두 지키는 답을 채점하면 모든 검사를 통과한다 (규칙끼리 모순이 없다는 증거)
6. 입력 글: 공정 에이전트가 받을 글을 만들 수 있고 단계 키가 다 들어 있다
라우터 · 전문가 답: 각 폴더의 check.py가 같은 방식으로 본다 (모범 답이 채점을 모두 통과하는지 등).

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/check_cases.py [--trade dobae] [--cases 경로]
기본은 등록된 공정마다 plan/<공정>/cases_5k.jsonl(없으면 sample_100.jsonl)과 라우터 · 전문가 사례. 문제가 있으면 1로 끝난다.
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, trades
from evaluation.expert import check as expert_check
from evaluation.router import check as router_check
from evaluation.run_agent import default_cases, ideal
from evaluation.scorers import trade_plan
from evaluation.scorers.expect import expect

KEYS = ("id", "trade", "split", "category", "strata", "input", "expect")
# 평가 이름 → (표에 쓸 이름, check 모듈: default_cases · check_set)
OTHER_SETS = {"router": ("라우터", router_check), "expert": ("전문가 답", expert_check)}


def check_case(trade: str, case: dict, sources: set[str], witness) -> list[str]:
    missing = [k for k in KEYS if k not in case]
    if missing:
        return [f"키 없음: {missing}"]
    errs = []
    if case["trade"] != trade:
        errs.append("trade 값")
    if case["split"] not in gen.SPLITS:
        errs.append("split 값")
    inp, exp = case["input"], case["expect"]
    try:
        c = trades.card(inp)
    except (ValidationError, KeyError, TypeError) as e:
        return errs + [f"카드가 스펙에 맞지 않아요: {type(e).__name__}"]
    if c.model_dump(mode="json") != inp["card"]:
        errs.append("카드가 상담 규칙(normalize)으로 맞춘 것과 달라요")
    if trade not in c.trades or c.area_m2 is None or c.occupied is None or c.area_basis is None:
        errs.append("공정 · 공통 칸이 비었어요")
    if errs:
        return errs
    sp = trades.spec(trade)
    if sp.missing(c.values.get(trade, {})):
        return ["물을 칸이 남았어요 (공정 의견은 칸이 다 찬 뒤에 만든다)"]
    try:
        q = sp.build(trades.common(c), c.values[trade])
    except (ValueError, KeyError, TypeError) as e:
        return [f"계산 오류: {e}"]
    facts = trades.facts(q)
    if facts["step_keys"] != exp["step_keys"]:
        errs.append("단계 키가 지금 계산과 달라요")
    if facts["after_visit"] != exp["after_visit"]:
        errs.append("'실측 후' 줄이 지금 계산과 달라요")
    if expect(trade, c, facts) != exp:
        errs.append("기대 검사가 지금 규칙과 달라요")
    rules = trade_plan.rules(trade)
    unknown = [r for r in exp["must"] + exp["must_not"] if r not in rules]
    if unknown:
        errs.append(f"채점표에 없는 규칙: {unknown}")
    both = set(exp["must"]) & set(exp["must_not"])
    if both:
        errs.append(f"꼭 언급과 언급하면 안 됨에 같이 있음: {sorted(both)}")
    if unknown:
        return errs
    s = trade_plan.score(trade, witness(case), exp, sources)
    failed = [k for k, ok in s["checks"].items() if not ok]
    if failed:
        errs.append(
            "모범 답이 통과 못 함: " + "; ".join(f"{k} {s['detail'].get(k, '')}" for k in failed)
        )
    text = trades.render(trade, inp, q)
    if any(f"- {k} | " not in text for k in exp["step_keys"]) or "{" in text:
        errs.append("입력 글에 단계 키가 빠졌거나 채우지 못한 자리가 있어요")
    return errs


def check_set(trade: str, cases: list[dict]) -> dict:
    sources, witness = set(trades.sources(trade)), ideal(trade)
    problems = {}
    for c in cases:
        errs = check_case(trade, c, sources, witness)
        if errs:
            problems[c.get("id", "?")] = errs
    return gen.split_report(cases) | {"problems": problems}


def ok(r: dict, full: bool) -> bool:
    """full이면 범주 2:1까지 본다 (표본 파일은 범주마다 개수가 적어 2:1을 보지 않는다)."""
    return not (
        r["problems"]
        or r["dup_ids"]
        or r["dup_inputs"]
        or r["shared_fragments"]
        or (full and r["uneven"])
    )


def row(name: str, path: Path, r: dict, full: bool) -> str:
    uneven = len(r["uneven"]) if full else "-"
    return (
        f"| {name} | {path.relative_to(ROOT).as_posix()} | {r['n']} | {len(r['problems'])} | "
        f"{r['dup_ids']} | {r['dup_inputs']} | {uneven} | {len(r['shared_fragments'])} |"
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="평가 사례 무료 점검 (T0)")
    ap.add_argument("--trade", action="append", help="공정 의견 공정 키 (없으면 등록된 공정 전부)")
    ap.add_argument("--cases", type=Path, help="사례 jsonl (--trade 하나일 때)")
    ap.add_argument("--only", choices=["plan", "router", "expert"], action="append")
    args = ap.parse_args()
    picked = args.trade or list(trades.registered())
    if args.cases and len(picked) != 1:
        sys.exit("--cases는 --trade 하나와 같이 써요.")
    only = set(args.only or ("plan", "router", "expert"))

    print(
        "| 평가 | 사례 파일 | 사례 | 사례 문제 | id 중복 | 같은 입력 | 범주 2:1 어긋남 | 조각 겹침 |"
    )
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    all_ok, details = True, []
    sets: list[tuple[str, Path, dict]] = []
    if "plan" in only:
        for trade in picked:
            path = (args.cases or default_cases(trade)).resolve()
            sets.append((f"공정 의견 {trade}", path, check_set(trade, gen.read_jsonl(path))))
    for kind, (name, mod) in OTHER_SETS.items():
        if kind in only and not args.trade:
            path = mod.default_cases().resolve()
            sets.append((name, path, mod.check_set(gen.read_jsonl(path))))
    for name, path, r in sets:
        full = path.name == "cases_5k.jsonl"
        all_ok &= ok(r, full)
        print(row(name, path, r, full))
        details += [f"{name} {cid}: {'; '.join(e)}" for cid, e in list(r["problems"].items())[:10]]
    for d in details:
        print(d)
    print("\n점검 통과" if all_ok else "\n점검 실패")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
