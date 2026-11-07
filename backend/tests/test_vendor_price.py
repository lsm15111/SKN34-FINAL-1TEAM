"""가견적 단가: 근거 파일 붙이기 · 단가 직접 넣기 · 확인 · 다시 고치기, 동시 확인 409, 고객용 확인 묶음."""

import asyncio
import uuid

import asyncpg
import pytest

from app.auth.models import User
from app.db import SessionLocal
from app.shared.errors import AppError
from app.vendor import service
from tests.conftest import query
from tests.helpers import PDF, no_surprises, signup, upload, vendor_signup
from tests.test_vendor_profile import URL as PROFILE
from tests.test_vendor_profile import approved_vendor, body, vendor_id

PRICES = "/vendor/prices"
NEW_SET = (
    "insert into vendor_price_sets (id, vendor_id, trade, version)"
    " select gen_random_uuid(), vendor_id, trade, {version} from s"
)


def ready_vendor(api, email: str = "vendor@mitjip.test", **profile) -> str:
    """승인된 도배 업체 + 근거 파일 하나. 파일 id를 돌려준다."""
    approved_vendor(api, email)
    assert api.put(PROFILE, json=body(**profile)).status_code == 200
    fid = upload(api, kind="price_doc", content=PDF, name="견적서_2026-09.pdf").json()["id"]
    r = api.post("/vendor/price-files", json={"file_id": fid, "trade": "dobae"})
    assert r.status_code == 201, r.text
    return fid


def maru(fid: str | None = None, wall: int = 6650) -> dict:
    return {
        "lines": [
            {"key": "wall", "unit_price": wall, "source_file_id": fid},
            {"key": "ceiling", "unit_price": 6800, "source_file_id": fid},
            {"key": "paper_basic", "unit_price": 3400},
            {"key": "primer", "included_in": "paper_basic", "source_file_id": fid},
        ]
    }


def _run(fn, *args):
    async def go():
        async with SessionLocal() as s:
            return await fn(s, *args)

    return asyncio.run(go())


def test_save_confirm_and_edit_again(api):
    first = api.get(PRICES, params={"trade": "dobae"})
    assert first.status_code == 401
    fid = ready_vendor(api)
    vid = vendor_id()
    empty = api.get(PRICES, params={"trade": "dobae"}).json()
    assert [r["key"] for r in empty["rows"]] == [
        "wall",
        "ceiling",
        "paper_basic",
        "paper_economy",
        "primer",
    ]
    assert empty["draft"] is None and empty["confirmed"] is None
    assert [f["filename"] for f in empty["files"]] == ["견적서_2026-09.pdf"]

    saved = api.put(f"{PRICES}/dobae", json=maru(fid))
    assert saved.status_code == 200, saved.text
    draft = saved.json()["draft"]
    assert (
        draft["version"] == 1 and draft["status"] == "draft" and saved.json()["confirmed"] is None
    )
    ex = draft["example"]  # 32평 아파트 예 · r2 단가
    assert (ex["supply"], ex["vat"], ex["total"]) == (2_621_695, 262_170, 2_883_865)
    primer = next(x for x in ex["lines"] if x["key"] == "primer")
    assert primer["amount"] == 0 and primer["included_in_name"] == "도배지 (실크)"
    assert next(x for x in ex["lines"] if x["key"] == "wall")["source"] == "견적서_2026-09.pdf"
    assert _run(service.confirmed_prices, [vid], "dobae") == {}  # 확인 전: 가견적 없음

    ok = api.post(f"{PRICES}/dobae/confirm")
    assert ok.status_code == 200, ok.text
    v1 = ok.json()["confirmed"]
    assert ok.json()["draft"] is None and v1["version"] == 1 and v1["confirmed_at"]
    cp = _run(service.confirmed_prices, [vid], "dobae")[vid]
    assert cp.set_id == uuid.UUID(v1["id"]) and cp.prices["wall"].unit_price == 6650
    assert cp.prices["primer"].included_in == "paper_basic" and cp.files == ["견적서_2026-09.pdf"]

    again = api.put(f"{PRICES}/dobae", json=maru(fid, wall=7000)).json()  # 다시 고치기
    assert again["draft"]["version"] == 2 and again["confirmed"]["id"] == v1["id"]
    cp = _run(service.confirmed_prices, [vid], "dobae")[vid]
    assert cp.set_id == uuid.UUID(v1["id"]) and cp.prices["wall"].unit_price == 6650
    v2 = api.post(f"{PRICES}/dobae/confirm").json()["confirmed"]
    assert v2["version"] == 2 and v2["lines"][0] == {
        "key": "wall",
        "unit_price": 7000,
        "included_in": None,
        "source_file_id": fid,
    }
    rows = query("select version, status from vendor_price_sets order by version")
    assert [(r["version"], r["status"]) for r in rows] == [(1, "retired"), (2, "confirmed")]
    assert query("select count(*) n from vendor_price_lines")[0]["n"] == 8  # 예전 묶음도 남는다
    twice = api.post(f"{PRICES}/dobae/confirm")
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "invalid_state"


def test_two_confirms_at_the_same_time_only_one_wins(api):
    fid = ready_vendor(api)
    api.put(f"{PRICES}/dobae", json=maru(fid))
    vid = vendor_id()

    async def confirm():
        async with SessionLocal() as s:
            user = await s.get(User, vid)
            return await service.confirm_prices(s, user, "dobae")

    async def both():
        return await asyncio.gather(confirm(), confirm(), return_exceptions=True)

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert query("select count(*) n from vendor_price_sets where status = 'confirmed'")[0]["n"] == 1


def test_exempt_vendor_example_has_no_vat(api):
    fid = ready_vendor(api, tax_kind="exempt")
    r = api.put(f"{PRICES}/dobae", json=maru(fid)).json()
    assert (r["draft"]["example"]["vat"], r["draft"]["example"]["total"]) == (0, 2_621_695)


def test_only_approved_vendor_for_its_trades(api):
    calls = (
        lambda: api.get(PRICES, params={"trade": "dobae"}),
        lambda: api.put(f"{PRICES}/dobae", json=maru()),
        lambda: api.post(f"{PRICES}/dobae/confirm"),
        lambda: api.post(
            "/vendor/price-files", json={"file_id": str(uuid.uuid4()), "trade": "dobae"}
        ),
        lambda: api.delete(f"/vendor/price-files/{uuid.uuid4()}"),
    )
    signup(api)
    assert all(c().status_code == 403 for c in calls)  # 고객
    vendor_signup(api)
    assert all(c().json()["error"]["code"] == "vendor_not_approved" for c in calls)

    fid = ready_vendor(api, "dobae@mitjip.test")  # 도배만 하는 업체
    for r in (
        api.put(f"{PRICES}/mokgong", json={"lines": []}),
        api.post(f"{PRICES}/mokgong/confirm"),
        api.post("/vendor/price-files", json={"file_id": fid, "trade": "mokgong"}),
    ):
        assert r.status_code == 409 and r.json()["error"]["code"] == "trade_not_mine"
    assert api.put(f"{PRICES}/floor", json={"lines": []}).status_code == 422
    assert api.get(PRICES, params={"trade": "mokgong"}).json()["draft"] is None


def test_price_input_is_checked(api):
    fid = ready_vendor(api)

    def put(*lines) -> tuple[int, str | None]:
        r = api.put(f"{PRICES}/dobae", json={"lines": list(lines)})
        return r.status_code, r.json().get("error", {}).get("code")

    assert put({"key": "molding", "unit_price": 1}) == (422, "price_key")  # 목공 행
    assert put({"key": "paper", "unit_price": 1}) == (422, "price_key")  # 등급별로 받는다
    assert put({"key": "wall", "unit_price": 1, "included_in": "ceiling"})[0] == 422
    assert put({"key": "wall"})[0] == 422  # 단가도 포함도 없음
    assert put({"key": "wall", "unit_price": -1})[0] == 422
    assert put({"key": "wall", "unit_price": 1}, {"key": "wall", "unit_price": 2})[0] == 422
    assert put({"key": "primer", "included_in": "paper_basic"}) == (422, "included_in")
    assert put(
        {"key": "paper_basic", "included_in": "wall"},
        {"key": "primer", "included_in": "paper_basic"},
        {"key": "wall", "unit_price": 1},
    ) == (422, "included_in")  # 포함한 줄이 또 포함 줄
    stranger = str(uuid.uuid4())
    assert put({"key": "wall", "unit_price": 1, "source_file_id": stranger}) == (
        422,
        "source_file",
    )

    assert put() == (200, None)  # 빈 묶음은 저장은 되지만 확인은 안 된다
    r = api.post(f"{PRICES}/dobae/confirm")
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_price"
    assert api.delete(f"/vendor/price-files/{fid}").status_code == 204
    api.put(f"{PRICES}/dobae", json=maru())
    r = api.post(f"{PRICES}/dobae/confirm")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_file"


def test_price_files(api, monkeypatch):
    fid = ready_vendor(api)
    api.put(f"{PRICES}/dobae", json=maru(fid))
    api.post(f"{PRICES}/dobae/confirm")

    again = api.post("/vendor/price-files", json={"file_id": fid, "trade": "dobae"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "file_used"
    photo = upload(api, kind="portfolio").json()["id"]
    assert (
        api.post("/vendor/price-files", json={"file_id": photo, "trade": "dobae"}).status_code
        == 422
    )
    sheet = upload(api, kind="price_doc", content=PDF, name="단가표.pdf").json()["id"]
    monkeypatch.setattr(service, "PRICE_FILES_MAX", 1)
    full = api.post("/vendor/price-files", json={"file_id": sheet, "trade": "dobae"})
    assert full.status_code == 409 and full.json()["error"]["code"] == "too_many_files"

    assert api.delete(f"/vendor/price-files/{fid}").status_code == 204
    assert api.delete(f"/vendor/price-files/{fid}").status_code == 404
    assert api.get(f"/files/{fid}").status_code == 404
    got = api.get(PRICES, params={"trade": "dobae"}).json()
    assert got["files"] == []
    wall = next(ln for ln in got["confirmed"]["lines"] if ln["key"] == "wall")
    assert wall == {"key": "wall", "unit_price": 6650, "included_in": None, "source_file_id": None}

    approved_vendor(api, "other@mitjip.test")
    assert (
        api.post("/vendor/price-files", json={"file_id": sheet, "trade": "dobae"}).status_code
        == 422
    )


def test_confirmed_prices_only_for_approved(api):
    fid = ready_vendor(api)
    api.put(f"{PRICES}/dobae", json=maru(fid))
    api.post(f"{PRICES}/dobae/confirm")
    vid = vendor_id()
    assert list(_run(service.confirmed_prices, [vid, uuid.uuid4()], "dobae")) == [vid]
    assert _run(service.confirmed_prices, [vid], "mokgong") == {}
    query(
        "update vendors set status = 'rejected', review_code = 'other', review_note = '흐려요', approved_at = null"
    )
    assert _run(service.confirmed_prices, [vid], "dobae") == {}


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("insert into vendor_price_lines select id, 'wall', 1, 'ceiling', null from s", "check"),
        ("insert into vendor_price_lines select id, 'wall', null, null, null from s", "check"),
        ("insert into vendor_price_lines select id, 'wall', null, 'wall', null from s", "check"),
        ("insert into vendor_price_lines select id, 'wall', -1, null, null from s", "check"),
        ("update vendor_price_sets set status = 'old'", "check"),
        ("update vendor_price_sets set confirmed_at = now()", "check"),  # draft인데 확인 시각
        (NEW_SET.format(version=2), "unique"),  # draft 둘
        (NEW_SET.format(version=1), "unique"),  # 같은 버전
    ],
)
def test_db_constraints(api, sql, error):
    fid = ready_vendor(api)
    api.put(f"{PRICES}/dobae", json={"lines": []})
    assert fid
    wanted = {
        "check": asyncpg.exceptions.CheckViolationError,
        "unique": asyncpg.exceptions.UniqueViolationError,
    }[error]
    with pytest.raises(wanted):
        query(f"with s as (select * from vendor_price_sets) {sql}")


def test_only_one_confirmed_per_trade_in_db(api):
    fid = ready_vendor(api)
    api.put(f"{PRICES}/dobae", json=maru(fid))
    api.post(f"{PRICES}/dobae/confirm")
    api.put(f"{PRICES}/dobae", json=maru(fid))
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        query("update vendor_price_sets set status = 'confirmed', confirmed_at = now()")
