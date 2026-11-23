"""QA 6차 고침 갈래 FB(계산 · 보드). 유료 호출 0회(무료 모드 · Claude 대본).

- c2 고칠 것 1: 전용 → 공급 환산 한 값(1.315, ADR 0007). 내 집 평 · 도배 '공급 평' 수량 · 목공 · 시세 범위가 같은 값이고,
  새 판(집 크기 2026.11 · 도배 2026.11c-* · 목공 2026.11)으로 쌓아요. 이미 만든 견적은 옛 판 그대로예요.
- 화면 M9 전체 철거 철거 줄.
"""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.calc import dobae, market_band, mokgong, quick_budget
from app.calc.common import SUPPLY_PER_EXCLUSIVE
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.calc.standard_quote import house_pyeong
from app.refprice.book import (
    DOBAE_MARKET_2026_11B,
    DOBAE_PROFILES,
    DOBAE_REMODEL_2026_11B,
    MOKGONG_2026H2,
    MOKGONG_DEFAULT,
)
from app.refprice.house import HOUSE_2026H2, HOUSE_DEFAULT
from app.refprice.market import MARKET_2026_11
from app.refprice.wallpaper_market import paper_market
from tests.conftest import query
from tests.helpers import signup
from tests.test_v3_project_home import HOME, create

D = Decimal
d = date.fromisoformat
ONLY = DOBAE_PROFILES["paper_only"]


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def tool_result(log, call: int) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


def std(h: dobae.HomeV3, p=ONLY, house=HOUSE_DEFAULT, own=False, why=()) -> dobae.StandardV3:
    return dobae.standard_v3(
        h, p, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, house, why, own_paper=own
    )


def board(api, pid: str) -> dict:
    r = api.get("/assistant/board", params={"project_id": pid})
    assert r.status_code == 200, r.text
    return r.json()


def standard(api, pid: str) -> dict:
    r = api.get(f"/projects/{pid}/standard")
    assert r.status_code == 200, r.text
    return r.json()


# ---- 1. 전용 → 공급 환산 한 값 (ADR 0007) ----


def test_one_supply_per_exclusive_for_every_current_version():
    assert SUPPLY_PER_EXCLUSIVE == D("1.315")
    assert HOUSE_DEFAULT.supply_per_exclusive == SUPPLY_PER_EXCLUSIVE
    assert MOKGONG_DEFAULT.supply_per_exclusive == SUPPLY_PER_EXCLUSIVE
    assert {p.supply_per_exclusive for p in DOBAE_PROFILES.values()} == {SUPPLY_PER_EXCLUSIVE}
    assert (HOUSE_DEFAULT.version, MOKGONG_DEFAULT.version) == ("2026.11", "2026.11")
    # 옛 판은 기록이라 옛 값(1.2) 그대로예요
    assert HOUSE_2026H2.supply_per_exclusive == MOKGONG_2026H2.supply_per_exclusive == D("1.2")
    assert (
        replace(MOKGONG_DEFAULT, version="2026H2", supply_per_exclusive=D("1.2")) == MOKGONG_2026H2
    )
    assert HOUSE_DEFAULT.band_pyeong == HOUSE_2026H2.band_pyeong
    assert "1.315" in HOUSE_DEFAULT.source and "1.2" not in HOUSE_DEFAULT.source


def test_exclusive_84_is_33_4_pyeong_and_the_floor_quantity_follows():
    """계약서 전용 84㎡: 앞 판은 '30.5평'(× 1.2)인데 도배 면적은 × 1.315였어요(QA r6 c2). 지금은 둘 다 33.4평."""
    assert house_pyeong(None, D("84.0"), "exclusive", HOUSE_DEFAULT) == D("33.4")
    assert house_pyeong(None, D("84.0"), "exclusive", HOUSE_2026H2) == D("30.5")
    assert house_pyeong(None, D("112.4"), "supply", HOUSE_DEFAULT) == D("34.0")  # 공급은 그대로
    h = dobae.HomeV3(D("84.0"), "exclusive", "basic", False)
    new, old = std(h), std(h, DOBAE_MARKET_2026_11B, HOUSE_2026H2)
    assert (new.pyeong, new.qty.floor_py) == (D("33.4"), D("33.4"))
    assert (old.pyeong, old.qty.floor_py) == (D("30.5"), D("30.5"))
    # 도배 면적 · 벽지 · 품은 그대로이고 부자재 줄(공급 평 × 6,900원)만 따라가요. QA 기록 값: 3,027,474 · 1,990,518
    assert (old.quote.total, new.quote.total) == (3_027_474, 3_049_485)
    assert (
        std(h, DOBAE_MARKET_2026_11B, HOUSE_2026H2, own=True).quote.total,
        std(h, own=True).quote.total,
    ) == (
        1_990_518,
        2_012_529,
    )
    assert (new.qty.paper_py, new.quote.man_days) == (old.qty.paper_py, old.quote.man_days)
    mat = {
        s: next(ln for ln in x.quote.lines if ln.key == "material")
        for s, x in (("o", old), ("n", new))
    }
    assert (mat["o"].qty, mat["n"].qty, mat["n"].unit_price) == (D("30.5"), D("33.4"), 6_900)
    # 공급 34평(112.4㎡)으로 넣으면 판이 바뀌어도 같은 금액
    s34 = dobae.HomeV3(D("112.4"), "supply", "basic", False)
    assert (
        std(s34).quote.total
        == std(s34, DOBAE_MARKET_2026_11B, HOUSE_2026H2).quote.total
        == 3_091_076
    )
    # 근거 글도 한 값으로(앞 판은 '환산 1.2배'와 '(전용 × 1.315)'가 한 글에 같이 나왔어요)
    how = "\n".join(dobae.count_basis(h, ONLY, HOUSE_DEFAULT, new))
    assert "전용 → 공급 환산 1.315배를 곱해 공급 33.4평" in how and "(전용 × 1.315)" in how
    assert "1.2배" not in how


def test_market_range_and_carpentry_use_the_same_conversion():
    assert market_band._supply(D("84.0"), "exclusive") == D("84.0") * SUPPLY_PER_EXCLUSIVE
    r = quick_budget.quick(quick_budget.QuickIn(D("84.0"), "exclusive"), MARKET_2026_11)
    assert "공급 33.4평으로 어림한 면적 · 길이" in r.assumed
    inp = mokgong.MokgongInput(D("84.0"), "exclusive", ("molding", "base"), False)
    new, old = mokgong.quote(inp, MOKGONG_DEFAULT), mokgong.quote(inp, MOKGONG_2026H2)
    assert "공급면적은 전용면적 × 1.315로 환산했어요." in new.assumptions
    assert (old.total, new.total) == (1_275_843, 1_398_150)


def test_standard_stacks_a_new_version_and_keeps_the_old_record(api):
    signup(api)
    pid = create(api, {**HOME, "area_m2": "84.0", "area_basis": "exclusive"}).json()["id"]
    st = standard(api, pid)
    dob = next(t for t in st["trades"] if t["trade"] == "dobae")
    assert (st["pyeong"], st["price_ver"], dob["total"]) == ("33.4", "2026.11c-market", 3_049_485)
    # 앞 판으로 만든 기록(전용 × 1.2)이 있던 공사: 다음에 열면 새 버전을 쌓고 옛 버전은 그대로 둬요
    query(
        "update standard_quotes set price_ver = '2026.11b-market', pyeong = 30.5 where project_id = $1::uuid",
        pid,
    )
    again = standard(api, pid)
    assert (again["pyeong"], again["price_ver"]) == ("33.4", "2026.11c-market")
    rows = query(
        "select version, price_ver, pyeong from standard_quotes where project_id = $1::uuid order by version",
        pid,
    )
    assert [(r["version"], r["price_ver"], r["pyeong"]) for r in rows] == [
        (1, "2026.11b-market", D("30.5")),
        (2, "2026.11c-market", D("33.4")),
    ]


# ---- 9. 전체 철거면 기존 벽지 철거 줄 '안 함' (화면 M9) ----


def test_full_demolition_moves_removal_to_the_demolition_work():
    h = dobae.HomeV3(D("105.8"), "supply", "basic", False)
    remodel = DOBAE_PROFILES["remodel"]

    def removal(v: dobae.StandardV3):
        return next(ln for ln in v.quote.lines if ln.key == "removal")

    full = std(h, remodel, why=(dobae.FULL_DEMOLITION,))
    assert removal(full).state == "excluded"
    assert removal(full).source.startswith(dobae.DEMOLISHED_REMOVAL)
    # 다른 리모델링 신호(문틀 교체) · 앞 판은 그대로 '실측 후', 합계는 같아요(어느 쪽도 합계 밖)
    door = std(h, remodel, why=("문틀 교체",))
    old = std(h, DOBAE_REMODEL_2026_11B, why=(dobae.FULL_DEMOLITION,))
    assert removal(door).state == removal(old).state == "after_visit"
    assert full.quote.total == door.quote.total == old.quote.total


def test_full_demolition_on_the_saved_standard(api):
    signup(api)
    pid = create(api, {**HOME, "demolition": "full"}).json()["id"]
    dob = next(t for t in standard(api, pid)["trades"] if t["trade"] == "dobae")
    line = next(ln for ln in dob["lines"] if ln["key"] == "removal")
    assert (dob["profile"], line["state"]) == ("remodel", "excluded")
    pid2 = create(api, {**HOME, "demolition": "partial"}).json()["id"]
    dob2 = next(t for t in standard(api, pid2)["trades"] if t["trade"] == "dobae")
    assert next(ln for ln in dob2["lines"] if ln["key"] == "removal")["state"] == "after_visit"
