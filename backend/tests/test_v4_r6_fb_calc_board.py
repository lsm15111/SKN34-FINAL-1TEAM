"""QA 6차 고침 갈래 FB(계산 · 보드). 유료 호출 0회(무료 모드 · Claude 대본).

- c2 고칠 것 1: 전용 → 공급 환산 한 값(1.315, ADR 0007). 내 집 평 · 도배 '공급 평' 수량 · 목공 · 시세 범위가 같은 값이고,
  새 판(집 크기 2026.11 · 도배 2026.11c-* · 목공 2026.11)으로 쌓아요. 이미 만든 견적은 옛 판 그대로예요.
- c2 고칠 것 2: 벽지 직접 구매면 보드 금액 칸 '표준견적서 · 벽지 빼고', 업체 범위 '가견적(벽지 포함)', 실측 요청 승인
  카드 '가견적' 줄에 안내 한 줄(틀).
- c2 고칠 것 6: 집 정보를 바꾼 직후 첫 보드에도 새 평(계산 엔진, 저장본을 기다리지 않음).
- c2 고칠 것 7 · 8: 집 정보 승인 카드 메모는 표준견적서 금액이 실제로 바뀔 때만 '새로 계산해요', 바뀌면 차액(계산 엔진)을
  카드에 보여요(살면서 ↔ 빈 집도).
- 화면 M9 전체 철거 철거 줄.
"""

import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service as assistant_service
from app.assistant.tools import propose
from app.calc import dobae, market_band, mokgong, quick_budget
from app.calc.common import SUPPLY_PER_EXCLUSIVE
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.calc.standard_quote import house_pyeong
from app.quote.service import OWN_PAPER_NOTE
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
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_diy import chips
from tests.test_v4_assistant_free import cards_of, two_vendors
from tests.test_v4_assistant_turns import ask, ok

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


# ---- 2. 집 정보를 바꾼 직후 첫 보드의 평 (c2 고칠 것 6) ----


def test_first_board_after_an_area_change_shows_the_new_pyeong(api):
    signup(api)
    pid = create(api, {**HOME, "area_m2": "105.8"}).json()["id"]
    first = board(api, pid)
    assert "32평" in first["facts"]
    # 표준견적서를 다시 열기 전(저장본은 아직 32평)에 보드를 읽어도 새 집 정보로 센 평이에요
    r = api.patch(f"/projects/{pid}", json={**HOME, "area_m2": "84.0", "area_basis": "exclusive"})
    assert r.status_code == 200, r.text
    b = board(api, pid)
    assert "전용 84.0㎡" in b["facts"] and "33.4평" in b["facts"] and "32평" not in b["facts"]
    assert D(b["home"]["area"]["pyeong"]) == D("33.4")


# ---- 3. 벽지 직접 구매: 보드 금액 칸 기준 · 실측 요청 승인 카드 (c2 고칠 것 2) ----


def test_paper_buy_names_the_basis_on_the_board_and_the_request_card(api):
    pid, _ = two_vendors(api)
    chips(api, pid, ["paper_buy"])
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    refs = ",".join(p["ref"] for p in picks["data"]["picks"])
    ev = ok(ask(api, pid, "두 곳에 요청할래요", context={"choice": f"visit_request:{refs}"}))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    row = next(r for r in a["summary"]["rows"] if r["label"] == "가견적")
    assert (row["value"], row["sub"]) == ("업체가 확인한 단가로 고정돼요", OWN_PAPER_NOTE)
    assert approve(api, a["action_id"]).json()["status"] == "executed"
    m = board(api, pid)["money"]
    # 표준견적서는 벽지를 뺀 값, 요청 때 고정한 가견적은 벽지 값이 든 값(부가세 포함 그대로)
    assert m["label"] == "표준견적서 · 벽지 빼고 · 부가세 포함"
    assert m["range_label"] == "가견적(벽지 포함)" and len(m["range"]) == 2
    fixed = sorted(r["estimate_total"] for r in query("select estimate_total from visits"))
    assert m["range"] == fixed
    dob = next(t for t in standard(api, pid)["trades"] if t["trade"] == "dobae")
    assert m["won"] == dob["total"] and dob["own_paper"]


def test_paper_basis_words():
    label, rng = assistant_service.paper_basis(
        "표준견적서 · 부가세 포함", "가견적 · 실측 견적서", True
    )
    assert (label, rng) == (
        "표준견적서 · 벽지 빼고 · 부가세 포함",
        "가견적(벽지 포함) · 실측 견적서",
    )
    assert assistant_service.paper_basis("표준견적서 · 부가세 포함", "가견적", False) == (
        "표준견적서 · 부가세 포함",
        "가견적",
    )
    money = SimpleNamespace(by_trade=[SimpleNamespace(trade="dobae", source="deal")])
    assert not assistant_service.own_paper_in(True, money)  # 확정했으면 그 견적서 금액이에요


# ---- 4. 집 정보 승인 카드: 메모 · 차액 (c2 고칠 것 7 · 8) ----


def test_home_note_says_new_standard_only_when_the_amount_moves():
    when = {"start_date": "2027-01-11"}
    assert propose.home_note(when, False, moved=False) == (
        "저장하면 예상 공정표 날짜가 바뀌어요. 표준견적서 금액은 그대로예요"
    )
    assert propose.home_note({"demolition": "partial"}, False, moved=False) == (
        "저장하면 표준견적서 금액은 그대로예요"
    )
    assert (
        propose.home_note({"occupied": True}, False, moved=True)
        == "저장하면 표준견적서를 새로 계산해요"
    )
    assert propose.home_note({"demolition": "full"}, False, moved=True) == (
        "저장하면 표준견적서를 리모델링 기준으로 새로 계산해요"
    )
    # 계산을 못 하면(None) 앞 말 그대로 · 지역 바꾸기 꼬리도 그대로
    assert propose.home_note({"sgg": "중구", "sido": "seoul"}, False) == (
        "저장하면 표준견적서를 새로 계산해요. 업체 추천도 바뀐 지역 업체로 바뀌어요"
    )


def _home_card(api, script, pid: str, fields: dict, text: str) -> tuple[dict, dict]:
    log = script(
        [
            {"tool_calls": [{"id": "p", "name": "propose_home_info", "input": {"fields": fields}}]},
            {"text": "카드를 확인해 주세요."},
        ]
    )
    ev = ok(ask(api, pid, text))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    return a, tool_result(log, 1)


def test_occupied_change_card_shows_the_engine_difference(api, script):
    signup(api)
    pid = create(api, HOME).json()["id"]
    before = standard(api, pid)["total"]
    a, model = _home_card(api, script, pid, {"occupied": True}, "살면서 공사해야 할 것 같아요")
    diff = a["summary"]["diff"]
    assert diff["label"] == "표준견적서" and diff["from_won"] == before
    assert diff["diff_won"] == diff["to_won"] - before > 0
    assert a["summary"]["note"] == "저장하면 표준견적서를 새로 계산해요"
    # 모델 값에도 카드와 같은 금액(부가세 포함): 저장 전에도 '얼마나 달라져요?'에 답해요(QA r6 c2 T4)
    rows = {r["label"]: r for r in model["summary"]["rows"]}
    assert rows["표준견적서(지금)"]["won"] == before
    assert (rows["표준견적서(승인 뒤)"]["won"], rows["표준견적서(승인 뒤)"]["diff_won"]) == (
        diff["to_won"],
        diff["diff_won"],
    )
    assert approve(api, a["action_id"], seen=a["target_ver"]).json()["status"] == "executed"
    assert standard(api, pid)["total"] == diff["to_won"]  # 저장한 표준견적서와 같은 값


def test_date_or_partial_demolition_card_keeps_the_amount(api, script):
    signup(api)
    pid = create(api, HOME).json()["id"]
    later = (d(HOME["start_date"]) + timedelta(days=7)).isoformat()
    a, _ = _home_card(api, script, pid, {"start_date": later}, "공사는 일주일 뒤로 할게요")
    assert a["summary"]["diff"] is None
    assert (
        a["summary"]["note"] == "저장하면 예상 공정표 날짜가 바뀌어요. 표준견적서 금액은 그대로예요"
    )
    b, _ = _home_card(api, script, pid, {"demolition": "partial"}, "벽지만 뜯을게요")
    assert (
        b["summary"]["diff"] is None
        and b["summary"]["note"] == "저장하면 표준견적서 금액은 그대로예요"
    )
    # 전체 철거는 리모델링 기준이라 금액이 바뀌어요(차액을 같이 보여요)
    c, _ = _home_card(api, script, pid, {"demolition": "full"}, "전체 철거할게요")
    assert c["summary"]["diff"]["diff_won"] > 0 and "리모델링 기준" in c["summary"]["note"]
    (dob,) = standard(api, pid)["trades"]
    assert dob["version"] == 1  # 카드만 만들었어요(저장 전)


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
