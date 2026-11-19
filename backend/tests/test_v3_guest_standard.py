"""손님 표준견적서(POST /guest/standard, dev-03 · C57)와 읍면동 목록(GET /regions/{sido}/{sgg}).
로그인 없이 계산만 하고 DB에 아무것도 쓰지 않는다. 지역 밖 · 모르는 칸은 422."""

from datetime import timedelta

from app.shared.clock import today_seoul
from tests.conftest import query
from tests.helpers import signup

URL = "/guest/standard"
HOME = {"sido": "seoul", "sgg": "노원구", "emd": "상계동", "area_m2": "69.4",
        "area_basis": "supply", "occupied": False, "grade": "basic"}  # fmt: skip


def rows_in_db() -> int:
    """모든 표의 행 수 합 (alembic_version 빼고)"""
    names = [
        r["tablename"]
        for r in query(
            "select tablename from pg_tables where schemaname = 'public'"
            " and tablename <> 'alembic_version'"
        )
    ]
    sql = " + ".join(f'(select count(*) from "{n}")' for n in names)
    return query(f"select {sql} as n")[0]["n"]


def test_guest_standard_without_login_writes_nothing(api):
    signup(api)  # 다른 행이 있어도 그대로인지 보려고 회원 하나를 둔다
    api.cookies.clear()
    before = rows_in_db()
    r = api.post(URL, json=HOME)
    assert r.status_code == 200, r.text
    g = r.json()
    # C07 공급 69.4㎡ · 방 2개(21평 기본값): 도배 면적 69.4 × 1.55 + 2 × 20.4 = 148.4㎡ (2.5배 판 2,060,625)
    assert (g["supply"], g["vat"], g["total"]) == (1_638_522, 163_852, 1_802_374)
    assert (g["scope"], g["area_m2"], g["area_basis"], g["pyeong"]) == (
        "full",
        "69.4",
        "supply",
        "21.0",
    )
    assert (g["market_ver"], g["share_ver"], g["price_ver"]) == (
        "paper-market-2026.11",
        None,
        "2026H2-rooms",
    )
    assert g["rooms"] == 2
    assert g["formula_ver"] == "2026.11.2" and g["budget_fit"] is None
    assert (g["man_day"], g["days"]) == ("4.5", "2.0")
    paper = next(ln for ln in g["lines"] if ln["key"] == "paper")
    assert (paper["qty"], paper["unit"], paper["unit_price"], paper["amount"], paper["basis"]) == (
        "53.9",
        "벽지 평",
        10_749,
        579_371,
        "market",
    )
    removal = next(ln for ln in g["lines"] if ln["key"] == "removal")
    assert removal["state"] == "after_visit"  # 합계 밖
    assert any("시장 평균" in a for a in g["assumptions"])
    assert "no-store" in r.headers["cache-control"]
    assert rows_in_db() == before


def test_budget_fit_and_partial_scope(api):
    over = api.post(URL, json={**HOME, "budget_won": 1_800_000}).json()
    within = api.post(URL, json={**HOME, "budget_won": 1_810_000}).json()
    assert (over["budget_fit"], within["budget_fit"]) == ("over", "within")
    part = {**HOME, "scope": "partial", "spaces": ["living", "kitchen"], "faces": ["wall"]}
    p = api.post(URL, json=part)
    assert p.status_code == 200, p.text
    g = p.json()
    # 2방 표: 거실 0.20 + 주방 0.11 = 0.31 몫 × 벽 96.5㎡ = 29.9㎡
    assert (g["scope"], g["share_ver"], g["total"]) == ("partial", "space-rooms-2026.11", 335_547)
    ceiling = next(ln for ln in g["lines"] if ln["key"] == "ceiling")
    assert (ceiling["state"], ceiling["qty"], ceiling["amount"]) == ("excluded", None, None)
    hapji = api.post(URL, json={**HOME, "grade": "economy"}).json()
    assert hapji["total"] == 1_436_436


def test_unknown_fields_and_bad_shapes_are_422(api):
    for extra in ({"name": "고객"}, {"phone": "01012345678"}):
        r = api.post(URL, json={**HOME, **extra})
        assert r.status_code == 422, extra
        e = r.json()["error"]
        assert e["code"] == "invalid" and e["fields"][0]["loc"] == list(extra)
        assert "01012345678" not in r.text and "고객" not in r.text  # 입력값을 돌려보내지 않는다
    full_with_space = api.post(URL, json={**HOME, "spaces": ["living"]})
    assert full_with_space.status_code == 422
    partial_without = api.post(URL, json={**HOME, "scope": "partial", "faces": ["wall"]})
    assert partial_without.status_code == 422
    for bad in ({"area_m2": "10"}, {"area_m2": "69.45"}, {"budget_won": 1_234_567}):
        assert api.post(URL, json={**HOME, **bad}).status_code == 422, bad


def test_every_district_gets_a_standard_quote(api):
    # 표준견적서는 모든 시 · 군 · 구에서 나와요(업체는 업체 고르기에서 시공 지역으로 걸러요). 동은 안 받아도 돼요
    home = {k: v for k, v in HOME.items() if k != "emd"}
    for over in ({}, {"sgg": "강남구"}, {"sido": "busan", "sgg": "해운대구"}, {"emd": "역삼동"}):
        r = api.post(URL, json={**home, **over})
        assert r.status_code == 200, (over, r.text)
        assert r.json()["total"] > 0


def test_bad_region_or_date_is_422(api):
    cases = [
        ({"sgg": "없는구"}, "sgg"),
        ({"sido": "busan", "sgg": "노원구"}, "sgg"),  # 그 시 · 도에 없는 구
        ({"start_date": (today_seoul() - timedelta(days=1)).isoformat()}, "start_date"),
        ({"start_date": (today_seoul() + timedelta(days=800)).isoformat()}, "start_date"),
    ]
    for over, loc in cases:
        r = api.post(URL, json={**HOME, **over})
        assert r.status_code == 422, over
        assert r.json()["error"]["fields"] == [
            {"loc": [loc], "msg": r.json()["error"]["message"]}
        ], over
    ok = api.post(
        URL, json={**HOME, "start_date": (today_seoul() + timedelta(days=30)).isoformat()}
    )
    assert ok.status_code == 200


def test_region_emds(api):
    r = api.get("/regions/seoul/노원구")
    assert r.status_code == 200, r.text
    names = [x["name"] for x in r.json()]
    assert "상계동" in names and all(x["code"] for x in r.json())
    for path in ("/regions/seoul/강남구", "/regions/nowhere/노원구"):  # 자료가 없는 구 · 없는 시도
        miss = api.get(path)
        assert miss.status_code == 404 and miss.json()["error"]["code"] == "not_found"


def test_rooms_field_changes_total_and_checks_range(api):
    """방 개수 칸: 바꾸면 방 하나에 20.4㎡씩, 0 · 6은 422, 방 개수보다 많은 방 칩도 422"""
    two = api.post(URL, json={**HOME, "rooms": 2}).json()
    four = api.post(URL, json={**HOME, "rooms": 4}).json()
    assert two["total"] == 1_802_374 and two["rooms"] == 2  # 기본값(2)과 같다
    assert four["rooms"] == 4 and four["total"] > two["total"]
    removal = {g["rooms"]: next(ln["qty"] for ln in g["lines"] if ln["key"] == "removal")
               for g in (two, four)}  # fmt: skip
    assert removal == {2: "148.4", 4: "189.2"}  # 40.8㎡ 차이
    for bad in (0, 6):
        assert api.post(URL, json={**HOME, "rooms": bad}).status_code == 422, bad
    too_many = {**HOME, "rooms": 2, "scope": "partial", "spaces": ["room2"]}
    assert api.post(URL, json=too_many).status_code == 422
    ok = api.post(URL, json={**HOME, "rooms": 5, "scope": "partial", "spaces": ["room4"]})
    assert ok.status_code == 200, ok.text
    all_off = api.post(URL, json={**HOME, "rooms": 3, "scope": "partial", "spaces": []})
    assert all_off.status_code == 422


def test_room_rule_table(api):
    r = api.get("/guest/room-rule")
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["min"], g["max"], g["fallback"], g["price_ver"]) == (1, 5, 3, "2026H2-rooms")
    supply = [(b["min_m2"], b["rooms"]) for b in g["bands"] if b["area_basis"] == "supply"]
    assert supply == [("0.0", 2), ("72.8", 3), ("132.3", 4)]
    assert g["room_kinds"] == ["master", "room1", "room2", "room3", "room4"]
