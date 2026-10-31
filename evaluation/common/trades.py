"""공정 스펙(app.consult.trades.REGISTRY)으로 사례를 계산하고, 상담 코드와 같은 에이전트 입력 글을 만든다.

- 사례 입력의 card는 상담 카드(ConsultCard) JSON 그대로다: 공통 칸 + 공정 칸 값(values) + 공간 + 모르는 칸
- 견적은 spec.build, 공정 의견 입력 글은 consult.service.plan_text, 전문가 입력 글은 consult.service.facts
- 에이전트는 spec.agent (plan · answer · sources). 지식 글은 경로로 찾지 않고 app.agent.trade.skill(이름)로 읽는다
backend 폴더가 sys.path에 있어야 한다 (실행 스크립트 · tests/conftest.py가 넣는다).
"""

import itertools
import random
from collections.abc import Iterable
from decimal import Decimal
from functools import cache

from app.agent import trade as agent_trade
from app.calc.common import Quote
from app.consult import service
from app.consult.schemas import ConsultCard
from app.consult.trades import ORDER, REGISTRY
from app.consult.trades.base import Common, FieldSpec, TradeSpec, Value

MAX_SUBSETS = 31  # 여러 개 고르는 칸의 조합이 이보다 많으면 하나씩 · 모두 · 둘씩 일부만 쓴다


def registered() -> tuple[str, ...]:
    """등록된 공정 키 (공정 순서)"""
    return ORDER


def spec(trade: str) -> TradeSpec:
    if trade not in REGISTRY:
        raise KeyError(f"등록되지 않은 공정이에요: {trade} (등록된 공정: {', '.join(ORDER)})")
    return REGISTRY[trade]


def label(trade: str) -> str:
    return spec(trade).label


def card(inp: dict) -> ConsultCard:
    """사례 입력 → 상담 카드 (스펙으로 검사하고, 조건이 꺼진 칸 · 같이 쓰는 칸을 상담과 같게 맞춘다)"""
    return service.normalize(ConsultCard.model_validate(inp["card"]))


def common(c: ConsultCard) -> Common:
    return Common(
        area_m2=c.area_m2,
        area_basis=c.area_basis,
        occupied=c.occupied,
        balcony_ext=c.balcony_ext,
        built_year=c.built_year,
    )


def quote(trade: str, inp: dict) -> Quote:
    c = card(inp)
    return spec(trade).build(common(c), c.values.get(trade, {}))


def plan_text(trade: str, inp: dict) -> str:
    """공정 의견 에이전트가 받는 집 정보 (consult.service.plan_text 그대로)"""
    c = card(inp)
    return service.plan_text(c, spec(trade), common(c))


def render(trade: str, inp: dict, q: Quote | None = None) -> str:
    """공정 의견 에이전트가 받는 사용자 글 그대로 (app.agent.trade.render)"""
    return agent_trade.render(plan_text(trade, inp), q if q is not None else quote(trade, inp))


def facts(q: Quote) -> dict[str, list[str]]:
    """견적에서 기대 검사에 쓰는 것: 공정표 단계 키, '실측 후' 줄 키, '안 함' 줄 키"""
    return {
        "step_keys": [s.key for s in q.steps],
        "after_visit": [ln.key for ln in q.lines if ln.state == "after_visit"],
        "excluded": [ln.key for ln in q.lines if ln.state == "excluded"],
    }


def expert_text(c: ConsultCard, trade: str) -> str:
    """공정 전문가가 받는 집 정보 (consult.service.turn과 같은 글: 공통 칸 + 그 공정 칸, 덜 찼어도 된다)"""
    return "\n".join(f"{f.label}: {f.text}" for f in service.facts(c) if f.trade in (None, trade))


def agent(trade: str) -> agent_trade.TradeAgent:
    return spec(trade).agent


def sources(trade: str) -> dict[str, str]:
    """그 공정 지식의 '출처' id → 이름"""
    return spec(trade).agent.sources


@cache
def knowledge(trade: str) -> str:
    """그 공정 지식 글 (SKILL.md)"""
    return agent_trade.skill(spec(trade).agent.name)


@cache
def knowledge_body(trade: str) -> str:
    """지식 글에서 '쓰는 법' · '출처' 절과 머리말을 뺀 본문 (공정 내용만)"""
    keep, out = False, []
    for line in knowledge(trade).splitlines():
        if line.startswith("## "):
            keep = line[3:].strip() not in ("쓰는 법", "출처")
            continue
        if keep:
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- 칸 값 펼치기
def subsets(f: FieldSpec) -> list[list[str]]:
    """여러 개 고르는 칸(multi)에서 고를 수 있는 조합 (선택지 순서대로)"""
    vals = list(f.values)
    hi = min(f.max, len(vals))
    out = [list(c) for k in range(max(f.min, 1), hi + 1) for c in itertools.combinations(vals, k)]
    if len(out) <= MAX_SUBSETS:
        return out
    ones = [[v] for v in vals]
    pairs = [list(c) for c in itertools.combinations(vals, 2)]
    return (ones + [vals[:hi]] + pairs)[:MAX_SUBSETS]


def options(f: FieldSpec) -> list[Value]:
    """칸 하나에 넣을 수 있는 값 (숫자 칸은 최소 · 가운데 · 최대)"""
    if f.kind == "choice":
        return list(f.values)
    if f.kind == "multi":
        return subsets(f)
    return sorted({f.min, (f.min + f.max) // 2, f.max})


def random_values(
    r: random.Random, sp: TradeSpec, *, skip_shares: Iterable[str] = (), keep: float = 1.0
) -> dict[str, Value]:
    """스펙 칸에 맞는 값을 무작위로 채운다 (조건 when을 지킨다).

    skip_shares의 같이 쓰는 칸은 비워 둔다 (상담 normalize가 다른 공정 값으로 채운다).
    keep < 1이면 칸마다 그 확률로만 채운다 (폼이 덜 찬 카드). 숫자 칸은 최소부터 다섯 칸 안에서 고른다.
    """
    skip = set(skip_shares)
    vals: dict[str, Value] = {}
    for f in sp.fields:
        if not f.asks(vals) or (f.share and f.share in skip) or r.random() >= keep:
            continue
        if f.kind == "choice":
            v: Value = r.choice(f.values)
        elif f.kind == "multi":
            v = r.choice(subsets(f))
        else:
            v = r.randint(f.min, min(f.max, f.min + 5))
        vals[f.key] = f.norm(v)
    return vals


def combos(sp: TradeSpec, limit: int = 2000) -> list[dict[str, Value]]:
    """조건(when)을 지키며 칸 값을 모두 조합한다 (너무 많으면 limit개까지)"""
    out: list[dict[str, Value]] = [{}]
    for f in sp.fields:
        nxt = []
        for v in out:
            nxt += [{**v, f.key: o} for o in options(f)] if f.asks(v) else [v]
        out = nxt[:limit]
    return out


@cache
def after_lines(trade: str) -> dict[str, str]:
    """이 공정 견적에 나올 수 있는 '실측 후' 줄: 키 → 이름 (칸 조합 × 사는 집 · 빈집으로 계산해 모은다)"""
    sp, out = spec(trade), {}
    for vals in combos(sp):
        for occupied in (True, False):
            q = sp.build(Common(Decimal("84.0"), "supply", occupied, True, None), vals)
            for ln in q.lines:
                if ln.state == "after_visit":
                    out.setdefault(ln.key, ln.name)
    return out
