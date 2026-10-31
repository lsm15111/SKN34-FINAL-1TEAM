"""사례 카드 + 계산 엔진 결과 → 기대 검사 (단계 키 · '실측 후' 줄 · 꼭 언급 · 언급하면 안 됨).

생성기가 사례마다 붙이고, 무료 점검(check_cases.py)이 지금 규칙으로 다시 만들어 같은지 본다.
규칙 id의 뜻과 키워드는 trade_plan.rules(공정)에 있다.
"""

from app.consult.schemas import ConsultCard
from evaluation.common import trades
from evaluation.plan import config
from evaluation.scorers.trade_plan import rules, scope_table


def neighbours(trade: str, picked: list[str]) -> list[str]:
    """같이 하는 공정 중 공정 순서에서 바로 앞 · 바로 뒤 공정"""
    seq = [k for k in trades.registered() if k in picked]
    i = seq.index(trade)
    return seq[max(i - 1, 0) : i] + seq[i + 1 : i + 2]


def expect(trade: str, card: ConsultCard, facts: dict) -> dict:
    """facts: trades.facts(견적) — step_keys · after_visit"""
    sp, cfg, table = trades.spec(trade), config.get(trade), rules(trade)
    vals = card.values.get(trade, {})
    must, must_not = [], []
    for f in sp.asked(vals):
        if f.kind == "count":
            continue
        chosen = vals[f.key] if isinstance(vals[f.key], list) else [vals[f.key]]
        must += [f"sum.{f.key}.{v}" for v in chosen if f"sum.{f.key}.{v}" in table]
        if f.kind == "multi":
            must_not += [f"not_chosen.{f.key}.{v}" for v in f.values if v not in chosen]
    must.append(f"sum.occupied.{'yes' if card.occupied else 'no'}")
    if card.occupied:
        must.append("prep.mention")
    else:
        must_not.append("empty.moving")
    must += [f"after.{k}" for k in facts["after_visit"]]
    must += [f"order.{k}" for k in neighbours(trade, card.trades)]
    must += [
        "check." + name.split(".", 1)[-1]
        for name in card.to_check
        if name == "area_basis" or name.startswith(f"{trade}.")
    ]
    must_not += [
        f"scope.{k}" for k in scope_table() if k not in card.trades and f"scope.{k}" in table
    ]
    if "scope.etc" in table:
        must_not.append("scope.etc")
    # 꼭 언급할 말(예문)에 든 낱말은 언급하면 안 됨으로 보지 않는다
    # (예: 도장 '벽 전체' 퍼티와 칠할 곳 '벽', 전기 '늘릴 콘센트 자리'와 '콘센트 · 스위치 교체')
    said = [table[r].example for r in must if table[r].example]
    must_not = [r for r in must_not if not any(table[r].any.search(x) for x in said)]
    if cfg.extra:
        more, less = cfg.extra(card.model_dump(mode="json"), dict(vals))
        must += more
        must_not += less
    return {
        "step_keys": list(facts["step_keys"]),
        "after_visit": list(facts["after_visit"]),
        "must": must,
        "must_not": must_not,
    }
