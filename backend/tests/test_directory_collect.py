"""외부 업체 수집기: 상가정보 CSV · KISCON 공시 (가짜 파일 · 가짜 응답, 실제 호출 없음)."""

import asyncio
import csv
import json

import httpx2
import pytest

from app.config import settings
from app.directory import client, tasks
from app.directory.repository import key_hash
from tests.conftest import query

HEAD = [
    "상가업소번호",
    "상호명",
    "지점명",
    "상권업종소분류명",
    "표준산업분류코드",
    "표준산업분류명",
    "시도명",
    "시군구명",
    "도로명주소",
    "경도",
    "위도",
]
ROWS = [
    # 인테리어 디자인업 → 모든 공정 후보
    ["FAKE0001", "가짜인테리어 1", "", "인테리어 디자인업", "M73201", "인테리어 디자인업",
     "서울특별시", "마포구", "서울특별시 마포구 가짜로 1", "126.9", "37.55"],
    # 벽지 가게, 일반구는 시 단위로
    ["FAKE0002", "가짜벽지", "2호점", "벽지/장판/마루 소매업", "", "",
     "경기도", "수원시 장안구", "경기도 수원시 장안구 가짜로 2", "", ""],
    # 음식점은 거른다
    ["FAKE0003", "가짜식당", "", "한식 일반 음식점업", "I56111", "한식 일반 음식점업",
     "서울특별시", "마포구", "서울특별시 마포구 가짜로 3", "126.9", "37.55"],
    ["FAKE0004", "가짜내장", "", "", "F42412", "도배, 실내 장식 및 내장 목공사업",
     "세종특별자치시", "", "세종특별자치시 가짜로 4", "0", "0"],
    # 개편 전 구 이름은 시 · 도만 남긴다
    ["FAKE0005", "가짜창호", "", "", "F42420", "유리 및 창호 공사업",
     "인천광역시", "중구", "인천광역시 중구 가짜로 5", "126.6", "37.47"],
]  # fmt: skip


def write_csv(path, rows=ROWS, encoding="utf-8-sig", head=HEAD):
    with path.open("w", encoding=encoding, newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)
    return str(path)


def vendors():
    return {
        r["source_id"]: r for r in query("select * from ext_vendors order by source, source_id")
    }


def test_sangga_csv_keeps_only_interior_rows(tmp_path):
    path = write_csv(tmp_path / "상가정보_가짜.csv")
    got = asyncio.run(tasks.import_sangga_csv({}, path))
    assert got == {"read": 5, "matched": 4, "saved": 4}
    v = vendors()
    assert set(v) == {"FAKE0001", "FAKE0002", "FAKE0004", "FAKE0005"}
    assert (
        v["FAKE0001"]["trades"][:2] == ["dobae", "mokgong"] and len(v["FAKE0001"]["trades"]) == 10
    )
    assert (v["FAKE0001"]["sido"], v["FAKE0001"]["sgg"]) == ("seoul", "마포구")
    assert float(v["FAKE0001"]["lat"]) == 37.55
    assert v["FAKE0002"]["name"] == "가짜벽지 2호점" and v["FAKE0002"]["sgg"] == "수원시"
    assert v["FAKE0002"]["trades"] == ["dobae", "floor"]
    assert (v["FAKE0004"]["sgg"], v["FAKE0004"]["lat"]) == ("세종시", None)  # 0,0은 버린다
    assert (v["FAKE0005"]["sido"], v["FAKE0005"]["sgg"]) == ("incheon", None)
    assert all(r["phone"] is None and r["source"] == "sangga" for r in v.values())


def test_reimport_updates_in_place_and_keeps_token(tmp_path):
    path = write_csv(tmp_path / "a.csv")
    asyncio.run(tasks.import_sangga_csv({}, path))
    token = vendors()["FAKE0001"]["optout_token"]
    rows = [ROWS[0][:1] + ["가짜인테리어 1 새이름"] + ROWS[0][2:]]
    asyncio.run(tasks.import_sangga_csv({}, write_csv(tmp_path / "b.csv", rows)))
    v = vendors()
    assert len(v) == 4 and v["FAKE0001"]["name"] == "가짜인테리어 1 새이름"
    assert v["FAKE0001"]["optout_token"] == token


def test_cp949_file_is_read(tmp_path):
    path = write_csv(tmp_path / "old.csv", ROWS[:1], encoding="cp949")
    assert asyncio.run(tasks.import_sangga_csv({}, path))["saved"] == 1
    assert vendors()["FAKE0001"]["name"] == "가짜인테리어 1"


def test_wrong_file_changes_nothing(tmp_path):
    bad = write_csv(tmp_path / "bad.csv", [["x", "y"]], head=["번호", "이름"])
    assert asyncio.run(tasks.import_sangga_csv({}, bad)) == {"error": "bad_csv"}
    assert asyncio.run(tasks.import_sangga_csv({}, str(tmp_path / "없음.csv"))) == {
        "error": "no_file"
    }
    assert vendors() == {}


def test_opted_out_vendor_stays_out_when_collected_again(tmp_path):
    query(
        "insert into contact_optouts (key_hash, via) values ($1, 'link')",
        key_hash("src", "sangga:FAKE0001"),
    )
    asyncio.run(tasks.import_sangga_csv({}, write_csv(tmp_path / "a.csv")))
    v = vendors()
    assert v["FAKE0001"]["opted_out"] is True and v["FAKE0002"]["opted_out"] is False


# ── KISCON ──

REP = "가짜대표"  # 대표자 이름 칸. 어디에도 저장되면 안 된다


def item(no, item_name, flag, day, name="가짜건설", tel="02-123-4567", addr=None):
    return {
        "ncrGsKname": name,
        "ncrGsMaster": REP,
        "ncrMasterNum": no,
        "ncrItemName": item_name,
        "ncrGsFlag": flag,
        "ncrGsAddr": addr or "서울특별시 마포구 가짜로 9",
        "ncrOffTel": tel,
        "ncrGsDate": day,
    }


def page(items, total):
    body = {"items": {"item": items}, "totalCount": total, "pageNo": 1, "numOfRows": 100}
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL"}, "body": body}}


def fake_api(pages, seen):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        n = int(request.url.params["pageNo"])
        got = pages[n - 1]
        if isinstance(got, int):
            return httpx2.Response(got)
        return httpx2.Response(200, json=got)

    return handler


def run_kiscon(pages, seen=None, start="20261001", end="20261031"):
    seen = [] if seen is None else seen

    async def go():
        async with client.http_client(transport=httpx2.MockTransport(fake_api(pages, seen))) as h:
            return await tasks.sync_kiscon({"http": h}, start, end)

    return asyncio.run(go())


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(settings, "data_go_kr_key", "fake-key")


def test_kiscon_replays_events_into_current_vendors(key):
    a, b, c = "1000000001", "1000000002", "1000000003"
    p1 = [
        item(a, "실내건축공사업", "신규", "20261002"),
        item(b, "토목공사업", "신규", "20261002"),  # 거르는 업종
        item(c, "실내건축공사업", "신규", "20261003", name="가짜목공", tel="010-1234-5678"),
    ]
    p2 = [
        item(a, "도장ㆍ습식ㆍ방수ㆍ석공사업", "신규", "20261005"),
        item(c, "실내건축공사업", "말소", "20261010", name="가짜목공"),
    ]
    seen: list = []
    got = run_kiscon([page(p1, 5), page(p2, 5)], seen)
    assert got == {"items": 5, "events": 4, "saved": 1, "removed": 0}
    v = vendors()
    assert set(v) == {a}  # 토목은 거르고, 말소된 c는 남지 않는다
    assert v[a]["industries"] == ["도장ㆍ습식ㆍ방수ㆍ석공사업", "실내건축공사업"]
    assert {"dobae", "mokgong", "paint", "tile", "bath"} <= set(v[a]["trades"])
    assert (v[a]["reg_kind"], v[a]["reg_no"], v[a]["phone"]) == ("construction", a, "021234567")
    assert (v[a]["sido"], v[a]["sgg"]) == ("seoul", "마포구")
    assert all(REP not in str(val) for val in v[a].values())  # 대표자 이름은 두지 않는다
    req = seen[0]
    assert req.url.params["serviceKey"] == "fake-key" and req.url.params["startDate"] == "20261001"
    assert req.headers["user-agent"].startswith("MitjipBot/")


def test_kiscon_close_and_transfer_follow_the_registration(key):
    a, d = "1000000001", "1000000004"
    run_kiscon([page([item(a, "실내건축공사업", "신규", "20261002")], 1)])
    # 양도: a의 실내건축 등록이 d로 간다. a는 남는 업종이 없어 빠진다
    moved = [
        item(a, "실내건축공사업", "양도", "20261020"),
        item(d, "실내건축공사업", "양수", "20261020", name="가짜인수", tel="010-0000-0000"),
    ]
    got = run_kiscon([page(moved, 2)])
    assert got["removed"] == 1
    v = vendors()
    assert set(v) == {d} and v[d]["name"] == "가짜인수" and v[d]["phone"] is None  # 휴대전화는 버림


def test_kiscon_failure_midway_changes_nothing(key):
    first = page([item("1000000001", "실내건축공사업", "신규", "20261002")], 300)
    assert run_kiscon([first, 500]) == {"error": "http_500"}
    assert vendors() == {}


def test_kiscon_without_key_is_skipped():
    assert settings.data_go_kr_key == ""
    assert run_kiscon([]) == {"skipped": "no_key"}
    assert asyncio.run(tasks.sync_kiscon({}, "2026", "20261031")) == {"skipped": "no_key"}


def test_kiscon_bad_period(key):
    assert run_kiscon([], start="20261031", end="20261001") == {"error": "bad_period"}


def test_portal_response_shapes():
    one = page({"ncrGsKname": "가짜"}, 1)  # 한 건이면 목록이 아니라 객체로 온다
    assert client.parse_items(json.dumps(one).encode()) == ([{"ncrGsKname": "가짜"}], 1)
    empty = {"response": {"header": {"resultCode": "00"}, "body": {"items": "", "totalCount": 0}}}
    assert client.parse_items(json.dumps(empty).encode()) == ([], 0)
    xml = (
        "<response><header><resultCode>00</resultCode></header><body><items>"
        "<item><ncrGsKname>가짜</ncrGsKname><ncrMasterNum>1000000001</ncrMasterNum></item>"
        "</items><totalCount>1</totalCount></body></response>"
    ).encode()
    assert client.parse_items(xml) == ([{"ncrGsKname": "가짜", "ncrMasterNum": "1000000001"}], 1)
    no_key = "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"
    auth = f"<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>{no_key}</returnAuthMsg>"
    cases = [
        ((auth + "</cmmMsgHeader></OpenAPI_ServiceResponse>").encode(), no_key),
        (b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', "xml_dtd"),
        (json.dumps({"response": {"header": {"resultCode": "30"}}}).encode(), "result_30"),
        (b"not data", "unknown_format"),
    ]
    for bad, reason in cases:
        with pytest.raises(client.ApiError) as err:
            client.parse_items(bad)
        assert err.value.reason == reason
