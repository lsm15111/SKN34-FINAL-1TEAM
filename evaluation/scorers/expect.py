"""사례 입력 + 계산 엔진 결과 → 기대 검사 (단계 키 · 꼭 언급 · 언급하면 안 됨).

생성기가 사례마다 붙이고, 무료 점검(check_cases.py)이 지금 규칙으로 다시 만들어 같은지 본다.
규칙 id의 뜻과 키워드는 trade_plan.RULES에 있다.
"""

from evaluation.common.trades import CHECK_FIELDS, ITEMS, OTHER


def expect(agent: str, inp: dict, facts: dict) -> dict:
    """facts: trades.facts(견적) — step_keys · after_visit"""
    c = inp["common"]
    other, to_check = inp.get("other_trades", []), inp.get("to_check", [])
    must = [f"sum.occupied.{'yes' if c['occupied'] else 'no'}"]
    must_not = ["scope"]
    if agent == "wallpaper":
        t = inp["trades"]["dobae"]
        must = [f"sum.grade.{t['grade']}", "sum.ceiling", *must]
        if not t["include_ceiling"]:
            must_not.append("not_chosen.ceiling")
        if c["balcony_ext"]:
            must.append("balcony.check")
        else:
            must_not.append("balcony.none")
    else:
        t = inp["trades"]["mokgong"]
        must = [f"sum.item.{i}" for i in t["items"]] + must
        if "door" in t["items"]:
            must.append(f"sum.door_frame.{'yes' if t['door_frame'] else 'no'}")
        must_not += [f"not_chosen.{i}" for i in ITEMS if i not in t["items"]]
        must_not.append("balcony.any")
    if c["occupied"]:
        must.append("prep.mention")
    else:
        must_not.append("empty.moving")
    must += [f"after.{k}" for k in facts["after_visit"]]
    if OTHER[agent] in other:
        must.append("order.other")
    else:
        must_not.append("other.trade")
    must += [f"check.{f}" for f in to_check if f in CHECK_FIELDS[agent]]
    return {
        "step_keys": list(facts["step_keys"]),
        "after_visit": list(facts["after_visit"]),
        "must": must,
        "must_not": must_not,
    }
