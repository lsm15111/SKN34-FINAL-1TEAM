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


def make_case(agent: str, inp: dict, cid: str = "t-d0001") -> dict:
    facts = trades.facts(trades.quote(agent, inp))
    return {
        "id": cid,
        "agent": agent,
        "split": "dev",
        "category": "test",
        "strata": {},
        "input": inp,
        "expect": expect(agent, inp, facts),
    }


def wp_input(**over) -> dict:
    """도배 사례 입력 (사는 집 · 실크 · 천장 포함 · 목공 없음)"""
    common = {
        "area_m2": "112.4",
        "area_basis": "supply",
        "area_said": "34평",
        "occupied": True,
        "balcony_ext": False,
        "built_year": None,
    }
    dobae = {"grade": "basic", "include_ceiling": True}
    common |= {k: v for k, v in over.items() if k in common}
    dobae |= {k: v for k, v in over.items() if k in dobae}
    return {
        "common": common,
        "trades": {"dobae": dobae},
        "other_trades": over.get("other_trades", []),
        "to_check": over.get("to_check", []),
    }


def cp_input(**over) -> dict:
    """목공 사례 입력 (빈집 · 몰딩 + 걸레받이 · 도배 없음)"""
    common = {
        "area_m2": "84.0",
        "area_basis": "exclusive",
        "area_said": "전용 84㎡",
        "occupied": False,
        "balcony_ext": False,
        "built_year": 2005,
    }
    mok = {"items": ["molding", "base"], "spaces": ["거실"], "doors": None, "door_frame": None}
    common |= {k: v for k, v in over.items() if k in common}
    mok |= {k: v for k, v in over.items() if k in mok}
    return {
        "common": common,
        "trades": {"mokgong": mok},
        "other_trades": over.get("other_trades", []),
        "to_check": over.get("to_check", []),
    }


@pytest.fixture
def wp_case():
    return make_case("wallpaper", wp_input())


@pytest.fixture
def cp_case():
    return make_case("carpentry", cp_input())
