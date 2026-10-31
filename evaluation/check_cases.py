"""무료 점검(T0): 생성 사례를 계산 엔진에 다시 넣어 보고, 기대 검사 규칙끼리 모순이 없는지 본다. LLM 호출 없음.

1. 형식: 키 · 값 범위 · id 중복 · 같은 입력 · 범주마다 dev:held-out 2:1 · 두 나눔의 문장 조각 겹침
2. 계산: 계산 엔진이 오류 없이 돌고, 저장한 단계 키 · '실측 후' 줄이 지금 계산과 같다
   (계산 엔진이나 기준 단가가 바뀌면 여기서 잡힌다. 그때는 생성기를 다시 돌린다)
3. 기대 검사: 지금 규칙으로 다시 만든 것과 같고, 규칙 id가 채점표에 있으며, 꼭 언급과 언급하면 안 됨이 겹치지 않는다
4. 모범 답: 규칙을 모두 지키는 답(scorers/witness.py)을 채점하면 모든 검사를 통과한다 (규칙끼리 모순이 없다는 증거)
5. 입력 글: 공정 에이전트가 받을 글을 만들 수 있고 단계 키가 다 들어 있다

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/check_cases.py [--agent wallpaper] [--cases 경로]
기본은 두 에이전트의 cases_5k.jsonl(없으면 sample_100.jsonl). 문제가 있으면 1로 끝난다.
"""

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, trades
from evaluation.scorers import trade_plan, witness
from evaluation.scorers.expect import expect

KEYS = ("id", "agent", "split", "category", "strata", "input", "expect")


def _input_errors(agent: str, inp: dict) -> list[str]:
    errs = []
    c = inp["common"]
    try:
        area = Decimal(c["area_m2"])
        if not (0 < area <= 1000 and area == area.quantize(Decimal("0.1"))):
            errs.append("면적은 0~1000㎡, 소수 한 자리")
    except (InvalidOperation, TypeError):
        errs.append("면적 값")
    if c["area_basis"] not in ("supply", "exclusive"):
        errs.append("면적 기준 값")
    if not (isinstance(c["occupied"], bool) and isinstance(c["balcony_ext"], bool)):
        errs.append("거주 · 발코니는 참거짓")
    if c.get("built_year") is not None and not 1900 <= c["built_year"] <= 2100:
        errs.append("준공 연도 범위")
    if not set(inp.get("other_trades", [])) <= {trades.OTHER[agent]}:
        errs.append("같이 하는 공정 값")
    to_check = inp.get("to_check", [])
    if not set(to_check) <= set(trades.CHECK_FIELDS[agent]) or len(set(to_check)) != len(to_check):
        errs.append("to_check 칸")
    if "area_basis" in to_check and c["area_basis"] != trades.DEFAULTS["area_basis"]:
        errs.append("모르는 면적 기준은 기본값이어야 해요")
    if agent == "wallpaper":
        t = inp["trades"]["dobae"]
        if t["grade"] not in ("economy", "basic") or not isinstance(t["include_ceiling"], bool):
            errs.append("도배 칸 값")
        for f in ("grade", "include_ceiling"):
            if f in to_check and t[f] != trades.DEFAULTS[f]:
                errs.append(f"모르는 {f}는 기본값이어야 해요")
        return errs
    t = inp["trades"]["mokgong"]
    items = t["items"]
    if not items or list(items) != [i for i in trades.ITEMS if i in items]:
        errs.append("목공 항목은 하나 이상, 정해진 순서로 한 번씩")
    if "door" in items:
        if not (isinstance(t["doors"], int) and 1 <= t["doors"] <= 10):
            errs.append("방문 개수 1~10")
        if not isinstance(t["door_frame"], bool):
            errs.append("문틀 교체는 참거짓")
        for f in ("doors", "door_frame"):
            if f in to_check and t[f] != trades.DEFAULTS[f]:
                errs.append(f"모르는 {f}는 기본값이어야 해요")
    elif (
        t["doors"] is not None
        or t["door_frame"] is not None
        or {"doors", "door_frame"} & set(to_check)
    ):
        errs.append("방문이 없으면 방문 칸은 비워요")
    if len(t["spaces"]) > 30 or any(not s or len(s) > 20 for s in t["spaces"]):
        errs.append("공간 이름은 1~20자, 30개까지")
    return errs


def check_case(agent: str, case: dict, sources: set[str]) -> list[str]:
    missing = [k for k in KEYS if k not in case]
    if missing:
        return [f"키 없음: {missing}"]
    errs = []
    if case["agent"] != agent:
        errs.append("agent 값")
    if case["split"] not in gen.SPLITS:
        errs.append("split 값")
    inp, exp = case["input"], case["expect"]
    errs += _input_errors(agent, inp)
    if errs:
        return errs
    try:
        q = trades.quote(agent, inp)
    except (ValueError, KeyError, TypeError, InvalidOperation) as e:
        return [f"계산 오류: {e}"]
    facts = trades.facts(q)
    if facts["step_keys"] != exp["step_keys"]:
        errs.append("단계 키가 지금 계산과 달라요")
    if facts["after_visit"] != exp["after_visit"]:
        errs.append("'실측 후' 줄이 지금 계산과 달라요")
    if expect(agent, inp, facts) != exp:
        errs.append("기대 검사가 지금 규칙과 달라요")
    rules = trade_plan.RULES[agent]
    unknown = [r for r in exp["must"] + exp["must_not"] if r not in rules]
    if unknown:
        errs.append(f"채점표에 없는 규칙: {unknown}")
    both = set(exp["must"]) & set(exp["must_not"])
    if both:
        errs.append(f"꼭 언급과 언급하면 안 됨에 같이 있음: {sorted(both)}")
    if unknown:
        return errs
    s = trade_plan.score(agent, witness.ideal_plan(agent, case), exp, sources)
    failed = [k for k, ok in s["checks"].items() if not ok]
    if failed:
        errs.append(
            "모범 답이 통과 못 함: " + "; ".join(f"{k} {s['detail'].get(k, '')}" for k in failed)
        )
    text = trades.render(agent, inp, q)
    if any(f"- {k} | " not in text for k in exp["step_keys"]) or "{" in text:
        errs.append("입력 글에 단계 키가 빠졌거나 채우지 못한 자리가 있어요")
    return errs


def check_set(agent: str, cases: list[dict]) -> dict:
    sources = trade_plan.skill_sources(agent)
    problems = {}
    for c in cases:
        errs = check_case(agent, c, sources)
        if errs:
            problems[c.get("id", "?")] = errs
    ids = [c.get("id") for c in cases]
    dup_ids = len(ids) - len(set(ids))
    inputs = [json.dumps(c.get("input"), sort_keys=True) for c in cases]
    dup_inputs = len(inputs) - len(set(inputs))
    cnt = Counter((c.get("category"), c.get("split")) for c in cases)
    uneven = sorted(
        cat for cat in {k for k, _ in cnt} if abs(cnt[cat, "dev"] - 2 * cnt[cat, "heldout"]) > 2
    )
    tpl = {
        s: {x for c in cases if c.get("split") == s for x in c.get("tpl", [])} for s in gen.SPLITS
    }
    shared = sorted(tpl["dev"] & tpl["heldout"])
    return {
        "n": len(cases),
        "problems": problems,
        "dup_ids": dup_ids,
        "dup_inputs": dup_inputs,
        "uneven": uneven,
        "shared_fragments": shared,
    }


def ok(r: dict, full: bool) -> bool:
    """full이면 범주 2:1까지 본다 (표본 파일은 범주마다 개수가 적어 2:1을 보지 않는다)."""
    return not (
        r["problems"]
        or r["dup_ids"]
        or r["dup_inputs"]
        or r["shared_fragments"]
        or (full and r["uneven"])
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="평가 사례 무료 점검 (T0)")
    ap.add_argument("--agent", choices=trades.AGENTS, action="append")
    ap.add_argument("--cases", type=Path, help="사례 jsonl (에이전트 하나일 때)")
    args = ap.parse_args()
    agents = args.agent or list(trades.AGENTS)
    if args.cases and len(agents) != 1:
        sys.exit("--cases는 --agent 하나와 같이 써요.")

    print(
        "| 에이전트 | 사례 파일 | 사례 | 사례 문제 | id 중복 | 같은 입력 | 범주 2:1 어긋남 | 조각 겹침 |"
    )
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    all_ok = True
    details = []
    for agent in agents:
        path = (args.cases or HERE / agent / "cases_5k.jsonl").resolve()
        if not path.exists():
            path = HERE / agent / "sample_100.jsonl"
        r = check_set(agent, gen.read_jsonl(path))
        full = path.name == "cases_5k.jsonl"
        all_ok &= ok(r, full)
        uneven = len(r["uneven"]) if full else "-"
        print(
            f"| {agent} | {path.relative_to(ROOT).as_posix()} | {r['n']} | {len(r['problems'])} | "
            f"{r['dup_ids']} | {r['dup_inputs']} | {uneven} | {len(r['shared_fragments'])} |"
        )
        details += [f"{agent} {cid}: {'; '.join(e)}" for cid, e in list(r["problems"].items())[:10]]
    for d in details:
        print(d)
    print("\n점검 통과" if all_ok else "\n점검 실패")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
