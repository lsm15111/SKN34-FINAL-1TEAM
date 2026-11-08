"""표준견적서 공간 몫 · 예상 범위: 고른 공간만 계산, 거의 다 고르면 집 전체, 공정별 · 합계 범위, 업체 목록 범위."""

from decimal import ROUND_HALF_UP, Decimal

from tests.helpers import signup
from tests.test_project import SIX_NAMES, body

SIX = list(SIX_NAMES)


def _project(api, names: list[str], **over) -> dict:
    keys = [chr(ord("a") + i) for i in range(len(names))]
    trades = over.pop("trades", {"dobae": {"spaces": keys, "grade": "basic"}})
    b = body(
        size=over.pop("size", {"basis": "supply", "m2": "105.8"}),
        occupied=False,
        balcony_ext=False,
        spaces=[{"key": k, "name": n} for k, n in zip(keys, names, strict=True)],
        trades=trades,
        **over,
    )
    r = api.post("/projects", json=b)
    assert r.status_code == 201, r.text
    return r.json()


def _std(api, pid: str) -> dict:
    r = api.get(f"/projects/{pid}/standard")
    assert r.status_code == 200, r.text
    return r.json()


def test_default_six_spaces_are_the_whole_house(api):
    signup(api)
    st = _std(api, _project(api, SIX)["id"])
    (dobae,) = st["trades"]
    assert dobae["space_share"] == "1" and dobae["range"]["whole"] is True
    assert dobae["total"] == 2_945_656  # 32평 예시 집 전체(r2 단가)
    assert not any("고른 공간" in n for n in dobae["notes"])


def test_one_room_is_a_small_share_with_a_wider_range(api):
    signup(api)
    whole = _std(api, _project(api, SIX)["id"])["trades"][0]
    signup(api, "room@mitjip.test")
    room = _std(api, _project(api, ["작은방 1"])["id"])["trades"][0]
    assert Decimal("0.05") < Decimal(room["space_share"]) < Decimal("0.2")
    assert room["total"] < whole["total"] * Decimal("0.25")
    assert "고른 공간: 작은방 1" in room["notes"]
    share = int((Decimal(room["space_share"]) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    assert any(f"{share}%" in n for n in room["notes"])  # 몫(%)은 엔진 가정 문구에 있다
    r = room["range"]
    assert r["whole"] is False and r["precision"] == "area"
    assert r["low"] <= r["mid"] <= r["high"]
    assert "share:area" in {p["driver"] for p in r["parts"]}
    # 작은 공사: 폭이 금액에 비해 넓다(몫 가정 + 최소 금액)
    w = whole["range"]
    assert (r["high"] - r["low"]) / r["mid"] > (w["high"] - w["low"]) / w["mid"]


def test_one_room_range_follows_how_vendors_price_small_jobs(api):
    # 일부 공간 도배는 롤 · 하루 품 · 부자재로 가운데를 잡고, 철거 · 폐기물은 그 금액에 든 것으로 본다
    signup(api)
    room = _std(api, _project(api, ["작은방 1"])["id"])["trades"][0]["range"]
    assert room["version"] == "2026H2-r5"
    assert any("롤" in n for n in room["notes"]) and room["fixed_add"] > 0
    assert room["extra_max"] == 0 and not any(
        p["driver"].startswith("cond:") for p in room["parts"]
    )
    assert 350_000 <= room["mid"] <= 550_000  # 실크 방 1칸 실견적 28만~50만(T10)
    signup(api, "living@mitjip.test")
    living = _std(api, _project(api, ["거실"])["id"])["trades"][0]["range"]
    assert living["mid"] > room["mid"] + 250_000  # 거실 천장은 2명이 붙어 최소 2품
    signup(api, "whole@mitjip.test")
    whole = _std(api, _project(api, SIX)["id"])["trades"][0]["range"]
    assert not any("롤" in n for n in whole["notes"]) and whole["extra_max"] > 0  # 집 전체는 그대로


def test_band_only_points_to_entering_the_area(api):
    signup(api)
    p = _project(api, SIX, size={"band": "30"})
    r = _std(api, p["id"])["trades"][0]["range"]
    assert r["precision"] == "band"
    qty = next(x for x in r["parts"] if x["driver"] == "qty:area")
    assert qty["better"] == "area" and qty["high_if"] - qty["low_if"] < r["high"] - r["low"]


def test_two_trades_have_their_own_and_a_total_range(api):
    signup(api)
    keys = list("abcdef")
    trades = {
        "dobae": {"spaces": keys, "grade": "basic"},
        "mokgong": {"spaces": keys, "items": ["molding", "base"]},
    }
    st = _std(api, _project(api, SIX, trades=trades)["id"])
    mok, dob = st["trades"]
    tot = st["range"]
    assert tot["parts"] == [] and tot["whole"] is True
    assert tot["low"] <= tot["mid"] <= tot["high"]
    assert tot["high"] - tot["low"] <= (mok["range"]["high"] - mok["range"]["low"]) + (
        dob["range"]["high"] - dob["range"]["low"]
    )
    assert abs(tot["mid"] - (mok["range"]["mid"] + dob["range"]["mid"])) <= 100_000
