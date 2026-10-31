"""카카오 장소 ID 맞추기 (가짜 응답, 실제 호출 없음). 장소 ID 말고는 아무것도 남지 않아야 한다."""

import asyncio
import uuid
from decimal import Decimal

import httpx2
import pytest

from app.config import settings
from app.directory import client, tasks
from app.directory.sources import kakao_place_id
from tests.conftest import query
from tests.sourcing_helpers import customer_project, ext_vendor


def doc(pid, name, address="서울 마포구 서교동 1", road=""):
    """카카오 검색 결과 한 건 모양 (가짜 값)"""
    return {
        "id": pid,
        "place_name": name,
        "address_name": address,
        "road_address_name": road,
        "phone": "02-999-9999",
        "category_name": "가정,생활 > 인테리어",
        "x": "126.9",
        "y": "37.55",
        "place_url": f"http://place.map.kakao.com/{pid}",
    }


def test_place_is_picked_only_when_name_and_district_match_once():
    ok = doc("1001", "(주)가짜 인테리어")
    assert kakao_place_id("가짜인테리어", "seoul", "마포구", [ok]) == "1001"
    assert kakao_place_id("가짜인테리어", "seoul", "마포구", [ok, ok]) == "1001"
    misses = [
        [doc("1002", "가짜인테리어 마포점")],  # 지점 이름이 붙으면 다른 곳으로 본다
        [doc("1003", "가짜인테리어", "서울 서대문구 창천동 1")],  # 다른 구
        [ok, doc("1004", "가짜인테리어", "서울 마포구 합정동 2")],  # 같은 구에 둘이면 고르지 않는다
        [doc("abc", "가짜인테리어")],  # ID가 숫자가 아니면 버린다
        [],
    ]
    for docs in misses:
        assert kakao_place_id("가짜인테리어", "seoul", "마포구", docs) is None
    # 같은 구 이름이라도 시 · 도가 다르면 아니다
    assert (
        kakao_place_id("가짜", "seoul", "중구", [doc("1005", "가짜", "부산 중구 중앙동 1")]) is None
    )
    # 지번 주소가 없으면 도로명 주소로, 일반구는 시 단위로 본다
    road = doc("1006", "가짜벽지", address="", road="경기 수원시 장안구 가짜로 2")
    assert kakao_place_id("가짜벽지", "gyeonggi", "수원시", [road]) == "1006"
    assert kakao_place_id("(주)", "seoul", "마포구", [doc("1007", "")]) is None


def fake_kakao(answers, seen):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if isinstance(answers, int):
            return httpx2.Response(answers)
        docs = answers.get(request.url.params["query"], [])
        return httpx2.Response(200, json={"documents": docs, "meta": {"total_count": len(docs)}})

    return handler


def run(answers, seen=None):
    seen = [] if seen is None else seen

    async def go():
        transport = httpx2.MockTransport(fake_kakao(answers, seen))
        async with client.http_client(transport=transport) as h:
            return await tasks.match_kakao_places({"http": h})

    return asyncio.run(go())


def row(vendor_id):
    return dict(query("select * from ext_vendors where id = $1", uuid.UUID(vendor_id))[0])


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(settings, "kakao_rest_key", "fake-kakao")


def test_only_the_place_id_is_stored(api, key):
    a = ext_vendor(
        "n-a", name="가짜인테리어 1", phone="0212345678", lat=Decimal("37.55"), lng=Decimal("126.9")
    )
    b = ext_vendor("n-b", name="가짜목공", trades=["mokgong"])
    ext_vendor("n-out", name="가짜수신거부", opted_out=True)
    ext_vendor("n-nosgg", name="가짜지역모름", sgg=None)
    before = row(a)
    answers = {
        "가짜인테리어 1": [doc("1001", "가짜인테리어 1"), doc("1002", "가짜인테리어 2")],
        "마포구 가짜목공": [doc("1003", "가짜목공 2호점")],
    }
    seen: list = []
    assert run(answers, seen) == {"asked": 2, "matched": 1, "saved": 2}

    after = row(a)
    assert after["place_ref"] == "1001" and after["place_checked_at"] is not None
    skip = {"place_ref", "place_checked_at", "updated_at"}
    assert {k: v for k, v in after.items() if k not in skip} == {
        k: v for k, v in before.items() if k not in skip
    }  # 카카오의 전화 · 주소 · 분류는 어디에도 남지 않는다
    assert row(b)["place_ref"] is None and row(b)["place_checked_at"] is not None
    left = query("select count(*) n from ext_vendors where place_checked_at is null")
    assert left[0]["n"] == 2  # 수신거부 · 지역 모름은 묻지 않는다

    by_q = {r.url.params["query"]: r for r in seen}
    assert set(by_q) == {"가짜인테리어 1", "마포구 가짜목공"}
    near = by_q["가짜인테리어 1"].url.params
    assert (near["x"], near["y"], near["radius"]) == ("126.900000", "37.550000", "2000")
    assert "x" not in by_q["마포구 가짜목공"].url.params
    assert all(r.headers["authorization"] == "KakaoAK fake-kakao" for r in seen)
    assert all(r.headers["user-agent"].startswith("MitjipBot/") for r in seen)

    assert run(answers, seen) == {
        "asked": 0,
        "matched": 0,
        "saved": 0,
    }  # 30일 안에는 다시 묻지 않는다
    assert len(seen) == 2

    _, pid = customer_project(api)
    out = api.get(f"/projects/{pid}/sourcing").json()
    places = {c["name"]: c["links"]["place"] for c in out["candidates"]}
    assert places["가짜인테리어 1"] == "https://place.map.kakao.com/1001"
    assert places["가짜목공"] is None


def test_kakao_failure_changes_nothing(key):
    ext_vendor("n-a", name="가짜인테리어 1")
    assert run(401) == {"error": "http_401"}
    assert (
        query("select count(*) n from ext_vendors where place_checked_at is not null")[0]["n"] == 0
    )


def test_without_key_kakao_is_never_called():
    assert settings.kakao_rest_key == ""
    ext_vendor("n-a", name="가짜인테리어 1")
    seen: list = []
    assert run({}, seen) == {"skipped": "no_key"} and seen == []
