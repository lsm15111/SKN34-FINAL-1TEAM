"""공정 스펙 공통 생성기: 설정 없는 새 공정(가짜 스펙)도 칸 종류(choice · multi · count · unknown · when ·
share)에서 범주 · 격자를 만들고, 규칙 예문으로 만든 모범 답이 T0 점검을 통과한다."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

import pytest

from evaluation import check_cases
from evaluation.common import trades
from evaluation.plan import config, make_cases
from evaluation.scorers import trade_plan


@dataclass
class _Quote:
    version: str
    lines: list
    subtotal: int
    vat: int
    total: int
    man_days: Decimal
    steps: list
    days: Decimal
    assumptions: list


def _build(c, v):
    from app.calc.common import Line, Step

    lines = [Line("base", "바탕 고르기", Decimal(1), "식", 1000, 1000, "included", "s")]
    if "y" in v["parts"]:
        lines.append(
            Line("remove", "기존 바닥재 철거", None, "식", None, None, "after_visit", "s", "none")
        )
    lines.append(Line("waste", "폐기물 처리", None, "식", None, None, "after_visit", "s", "none"))
    steps = [Step("prep", "짐 정리 · 보양", 1)] if c.occupied else []
    steps += [Step("work", "본 작업", 2), Step("finish", "정리 · 청소", 1)]
    return _Quote("t", lines, 1000, 100, 1100, Decimal(1), steps, Decimal(2), [])


@pytest.fixture
def probe(monkeypatch):
    """등록되지 않은 가짜 공정 'probe'를 잠깐 레지스트리에 넣는다 (목공과 방문 개수 칸을 같이 쓴다)."""
    from app.agent.trade import TradeAgent
    from app.consult.trades import REGISTRY
    from app.consult.trades.base import Choice, FieldSpec, TradeSpec

    agent = TradeAgent(
        "probe", "시험", "probe-v1", "시스템", "답", {"field": "현장", "smp": "기준"}
    )
    spec = TradeSpec(
        key="probe",
        label="시험",
        order=55,
        fields=(
            FieldSpec(
                "finish",
                "마감 종류",
                "어떤 마감?",
                "choice",
                (Choice("matte", "무광 마감"), Choice("gloss", "유광 마감")),
                unknown="matte",
            ),
            FieldSpec(
                "parts",
                "시공 부위",
                "어디?",
                "multi",
                (Choice("x", "거실 벽"), Choice("y", "주방 벽"), Choice("z", "현관 벽")),
                max=3,
            ),
            FieldSpec(
                "doors",
                "문 개수",
                "몇 개?",
                "count",
                min=1,
                max=10,
                unknown=3,
                when=lambda v: "y" in v.get("parts", ()),
                share="doors",
            ),
        ),
        agent=agent,
        build=_build,
        card_lines=lambda c, v: [f"마감: {v['finish']}"],
    )
    monkeypatch.setitem(REGISTRY, "probe", spec)
    monkeypatch.setattr(trades, "ORDER", ("mokgong", "probe", "dobae"))
    monkeypatch.setitem(config.CONFIGS, "probe", config.PlanConfig(scope_exempt=()))
    caches = (trade_plan.rules, trade_plan.auto_exempt, trades.after_lines)
    for c in caches:
        c.cache_clear()
    yield spec
    for c in caches:
        c.cache_clear()


def test_new_trade_without_config_builds_and_passes_t0(probe):
    cases, stats = make_cases.build("probe", 420)
    cats = Counter((c["category"], c["split"]) for c in cases)
    assert len({k for k, _ in cats}) == 3 * 7  # 마감(무광 · 유광 · 모름) × 부위 조합 7
    assert all(cats[k, "dev"] == 2 * cats[k, "heldout"] for k, _ in cats)
    r = check_cases.check_set("probe", cases)
    assert r["problems"] == {} and check_cases.ok(r, full=True), list(r["problems"].items())[:3]
    assert stats["exact"] + stats["near"] < len(cases)

    # 조건(when): 주방 벽이 있을 때만 문 개수를 묻고, 모르겠어요면 기본값 3 + to_check
    for c in cases:
        card = c["input"]["card"]
        v = card["values"]["probe"]
        assert ("doors" in v) == ("y" in v["parts"])
        if "probe.doors" in card["to_check"]:
            assert v["doors"] == 3
        # 같이 쓰는 칸(share): 목공도 방문을 하면 같은 값이 들어간다 (상담 normalize)
        mok = card["values"].get("mokgong", {})
        if "doors" in v and "doors" in mok:
            assert mok["doors"] == v["doors"]
    shared = [
        c
        for c in cases
        if "doors" in c["input"]["card"]["values"].get("mokgong", {})
        and "doors" in c["input"]["card"]["values"]["probe"]
    ]
    assert shared

    rules = trade_plan.rules("probe")
    assert rules["sum.parts.x"].any.search("거실 벽") and not rules["sum.parts.x"].any.search(
        "주방 벽"
    )
    assert {"after.remove", "after.waste", "check.doors", "check.finish"} <= set(rules)
    must = Counter(r for c in cases for r in c["expect"]["must"])
    assert must["order.mokgong"] and must["order.dobae"]
