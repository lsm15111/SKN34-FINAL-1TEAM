"""QA 6차 고침 갈래 FB(계산 · 보드). 유료 호출 0회(무료 모드 · Claude 대본).

- c2 고칠 것 1: 전용 → 공급 환산 한 값(1.315, ADR 0007). 내 집 평 · 도배 '공급 평' 수량 · 목공 · 시세 범위가 같은 값이고,
  새 판(집 크기 2026.11 · 도배 2026.11c-* · 목공 2026.11)으로 쌓아요. 이미 만든 견적은 옛 판 그대로예요.
- c2 고칠 것 2: 벽지 직접 구매면 보드 금액 칸 '표준견적서 · 벽지 빼고', 업체 범위 '가견적(벽지 포함)', 실측 요청 승인
  카드 '가견적' 줄에 안내 한 줄(틀).
- c2 고칠 것 6: 집 정보를 바꾼 직후 첫 보드에도 새 평(계산 엔진, 저장본을 기다리지 않음).
- c2 고칠 것 7 · 8: 집 정보 승인 카드 메모는 표준견적서 금액이 실제로 바뀔 때만 '새로 계산해요', 바뀌면 차액(계산 엔진)을
  카드에 보여요(살면서 ↔ 빈 집도).
- c2 페인트 날짜 창: 공정표에 목공 날짜가 없으면 시작은 '목공이 끝난 뒤'(calc.diy diy_v4).
- c4 고칠 것 3: '하루만 당겨'가 주말을 넘으면 앞 일하는 날(금요일), 없으면 실제 까닭.
- 화면 M9 전체 철거 철거 줄 · M6 기한 · M8 보드 공사 기간 · H2 가입 뒤 첫 보드 500.
"""

import json
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.calc import deadline, dobae, market_band, mokgong, quick_budget
from app.calc.common import SUPPLY_PER_EXCLUSIVE
from app.calc.schedule import no_earlier_why, start_choices_before
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.calc.standard_quote import house_pyeong
from app.refprice.book import (
    DOBAE_MARKET_2026_11B,
    DOBAE_PROFILES,
    DOBAE_REMODEL_2026_11B,
    MOKGONG_2026H2,
    MOKGONG_DEFAULT,
)
from app.refprice.holidays import days_off
from app.refprice.house import HOUSE_2026H2, HOUSE_DEFAULT
from app.refprice.market import MARKET_2026_11
from app.refprice.wallpaper_market import paper_market
from app.shared.clock import SEOUL
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


def tool_result(log, call: int) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


def std(h: dobae.HomeV3, p=ONLY, house=HOUSE_DEFAULT, own=False, why=()) -> dobae.StandardV3:
    return dobae.standard_v3(
        h, p, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, house, why, own_paper=own
    )


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


# ---- 3. 벽지 직접 구매: 보드 금액 칸 기준 · 실측 요청 승인 카드 (c2 고칠 것 2) ----


# ---- 4. 집 정보 승인 카드: 메모 · 차액 (c2 고칠 것 7 · 8) ----


# ---- 5. 페인트 날짜 창: 목공 날짜가 없으면 '목공이 끝난 뒤' (calc.diy diy_v4) ----


# ---- 6. 날짜 당기기 (c4 고칠 것 3) ----

MON, TUE = d("2026-12-21"), d("2026-12-22")
OFF = days_off(d("2026-11-01"), d("2027-03-01"))


def _sch(*deals) -> SimpleNamespace:
    trades = [
        SimpleNamespace(
            deal=x, request=None, requests_left=2, proposal=None, dates_state="scheduled"
        )
        for x in deals
    ]
    return SimpleNamespace(trades=trades, weekend_work=False)


def _deal(trade: str, start: date, end: date) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), trade=trade, status="scheduled", start_date=start, end_date=end
    )


def test_start_choices_before_and_why():
    fri = d("2026-12-18")
    assert start_choices_before(d("2026-12-20"), 2, 2, MON, d("2026-11-24"), OFF) == [
        (fri, MON),
        (d("2026-12-17"), fri),
    ]
    # 바라는 날부터 앞으로 먼저(지금 시작일 전까지), 모자라면 거슬러요
    assert start_choices_before(d("2026-12-17"), 1, 3, MON, d("2026-11-24"), OFF) == [
        (d("2026-12-17"), d("2026-12-17")),
        (fri, fri),
        (d("2026-12-16"), d("2026-12-16")),
    ]
    assert start_choices_before(d("2026-12-20"), 1, 3, MON, d("2026-12-19"), OFF) == []
    assert no_earlier_why(MON, d("2026-12-19"), d("2026-12-19"), None) == "off"
    assert no_earlier_why(MON, MON, MON, None) == "soon"
    assert no_earlier_why(MON, MON, d("2026-11-24"), MON) == "prev"
    assert no_earlier_why(MON, MON, d("2026-11-24"), None, wish=MON) == "wish"


# ---- 7. 기한 (화면 M6) ----


def test_pick_and_accept_deadlines_do_not_pass_the_schedule():
    at = datetime(2026, 11, 23, 22, 6, tzinfo=SEOUL)
    # 고르기: 업체 답 + 7일(11.30)이지만 기간 마지막 날(11.28)이 오기 전까지
    assert deadline.pick_due(at) == at + timedelta(days=7)
    assert deadline.pick_due(at, d("2026-11-28")) == datetime(2026, 11, 28, 0, 0, tzinfo=SEOUL)
    assert deadline.pick_due(at, d("2026-12-31")) == at + timedelta(days=7)
    # 수락: 고른 때 + 48시간(11.25 22:06)이지만 고른 반나절(11.25 오후 13시)이 시작하기 전까지
    assert deadline.accept_due(at, d("2026-11-25"), "pm") == datetime(
        2026, 11, 25, 13, 0, tzinfo=SEOUL
    )
    assert deadline.accept_due(at, d("2026-11-30"), "am") == at + timedelta(hours=48)
    assert deadline.accept_due(at) == at + timedelta(hours=48)


# ---- 8. 보드 공사 기간 = 공정표 '공사' (화면 M8) ----


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


# ---- 10. 가입 뒤 첫 보드 500(화면 H2) ----
