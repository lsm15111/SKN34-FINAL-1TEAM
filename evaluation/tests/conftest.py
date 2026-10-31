"""평가 도구 테스트 준비. DB · Redis · LLM이 필요 없다.

실행 (저장소 루트에서): cd backend && uv run pytest ../evaluation/tests
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ["LLM_LIVE"] = "false"  # 유료 호출 0회 (app.config를 불러오기 전에)

from evaluation.common import trades
from evaluation.scorers.expect import expect

_COMMON = ("area_m2", "area_basis", "occupied", "balcony_ext", "built_year")


def make_input(trade: str, values: dict, over: dict, base: dict) -> dict:
    """상담 카드 JSON (스펙 검사 · normalize를 지난 것). over의 공통 칸 · others · to_check · spaces를 반영"""
    card = base | {k: over[k] for k in _COMMON if k in over}
    others = over.get("others", [])
    card |= {
        "trades": [k for k in trades.registered() if k == trade or k in others],
        "values": {trade: values},
        "spaces": over.get("spaces", {}),
        "to_check": over.get("to_check", []),
    }
    return {"card": trades.card({"card": card}).model_dump(mode="json"), "area_said": "-"}


def make_case(trade: str, inp: dict, cid: str = "t-d0001") -> dict:
    c = trades.card(inp)
    facts = trades.facts(trades.quote(trade, inp))
    return {
        "id": cid,
        "trade": trade,
        "split": "dev",
        "category": "test",
        "strata": {},
        "input": inp,
        "expect": expect(trade, c, facts),
    }


def wp_input(**over) -> dict:
    """도배 사례 입력 (사는 집 · 실크 · 천장 포함 · 같이 하는 공정 없음)"""
    values = {"grade": "basic", "include_ceiling": "yes"}
    values |= {k: over[k] for k in values if k in over}
    base = {
        "area_m2": "112.4",
        "area_basis": "supply",
        "occupied": True,
        "balcony_ext": False,
        "built_year": None,
    }
    return make_input("dobae", values, over, base)


def cp_input(**over) -> dict:
    """목공 사례 입력 (빈집 · 몰딩 + 걸레받이 · 같이 하는 공정 없음)"""
    values = {"items": over.get("items", ["molding", "base"])}
    if "door" in values["items"]:
        values |= {"doors": over.get("doors", 3), "door_frame": over.get("door_frame", "yes")}
    base = {
        "area_m2": "84.0",
        "area_basis": "exclusive",
        "occupied": False,
        "balcony_ext": False,
        "built_year": 2005,
    }
    over = {"spaces": {"mokgong": ["거실"]}} | over
    return make_input("mokgong", values, over, base)


@pytest.fixture
def wp_case():
    return make_case("dobae", wp_input())


@pytest.fixture
def cp_case():
    return make_case("mokgong", cp_input())
