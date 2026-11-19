"""POST · PATCH /projects v3 몸통(HomeInfoIn, contract 3.2 · api.md 3장): 지금 화면 몸통(ProjectCreate)도 그대로,
422 fields.loc도 그대로. Idempotency-Key로 손님 답을 한 번만 옮기고(같은 키 200, 처리 중 409 in_progress),
첫 실측 요청 뒤 고치기는 409 locked. v3 표준견적서 칸(범위 · 공간 · 면 · 판 · 예산)."""

import asyncio
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import asyncpg

from app.project.schemas import ProjectOut
from app.quote.service import calc_trades
from app.shared.clock import today_seoul
from tests.conftest import TEST_DSN, query
from tests.helpers import signup, use, vendor_signup
from tests.test_project import body as v2_body

START = (today_seoul() + timedelta(days=40)).isoformat()
HOME = {"sido": "seoul", "sgg": "노원구", "emd": "상계동", "area_m2": "69.4",
        "area_basis": "supply", "occupied": False, "grade": "basic",
        "budget_won": 3_000_000, "start_date": START}  # fmt: skip
PART = {**HOME, "scope": "partial", "spaces": ["living", "kitchen"], "faces": ["wall"]}


def create(api, data: dict, key: str | None = None):
    headers = {"Idempotency-Key": key} if key else {}
    return api.post("/projects", json=data, headers=headers)


def test_v3_body_creates_a_member_project_with_home(api):
    signup(api)
    r = create(api, HOME)
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["source"], p["emd"], p["budget_won"]) == ("member", "상계동", 3_000_000)
    assert p["home"] == {
        "trade": "dobae",
        "scope": "full",
        "spaces": [],
        "faces": ["wall", "ceiling"],
        "rooms": None,  # 안 넣으면 비워 두고 계산 엔진이 평형 기본값(21평 → 2개)으로 센다
        "housing": "apt",
        "sido": "seoul",
        "sgg": "노원구",
        "emd": "상계동",
        "area_m2": "69.4",
        "area_basis": "supply",
        "occupied": False,
        "grade": "basic",
        "budget_won": 3_000_000,
        "start_date": START,
    }
    assert p["size"] == {"band": None, "basis": "supply", "m2": "69.4"}
    assert p["when"] == {"kind": "date", "start": START, "end": None}
    assert p["trades"]["dobae"] == {"spaces": [], "grade": "basic"} and p["budget"] is None
    assert api.get(f"/projects/{p['id']}").json() == p
    (row,) = query("select source, client_key, emd, budget_won, start_kind from projects")
    assert (row["source"], row["client_key"], row["start_kind"]) == ("member", None, "date")

    st = api.get(f"/projects/{p['id']}/standard").json()
    # 9판 C07 집, 시장 평균 실크. 판 2026H2-rooms: 69.4 × 1.55 + 방 2 × 20.4 (2.5배 판 2,060,625)
    assert st["total"] == 1_802_374 and st["price_ver"] == "2026H2-rooms"
    assert (st["scope"], st["spaces"], st["faces"], st["share_ver"]) == (
        "full",
        [],
        ["wall", "ceiling"],
        None,
    )
    assert (st["market_ver"], st["budget_fit"], st["formula_ver"]) == (
        "paper-market-2026.11",
        "within",
        "2026.11.2",
    )
    paper = next(ln for ln in st["trades"][0]["lines"] if ln["key"] == "paper")
    assert (paper["unit"], paper["basis"], paper["qty"]) == ("벽지 평", "market", "53.9")
    assert st["days"] == "2.0"  # C07 '예상 2일'


def test_standard_days_are_the_guest_days(api):
    """저장한 공사의 표준견적서와 손님 계산(POST /guest/standard)이 같은 계산 엔진 일수를 보인다."""
    signup(api)
    cases = (
        (HOME, "2.0"),
        ({**HOME, "occupied": True}, "2.5"),  # 짐 정리 · 보양 반나절
        ({**PART, "start_date": None}, "1.0"),  # C60 '예상 1일'
    )
    for home, days in cases:
        p = create(api, home)
        assert p.status_code == 201, p.text
        st = api.get(f"/projects/{p.json()['id']}/standard").json()
        guest = api.post("/guest/standard", json=home)
        assert guest.status_code == 200, guest.text
        assert (st["days"], st["total"]) == (guest.json()["days"], guest.json()["total"])
        assert st["days"] == days


def test_standard_days_add_up_trades_for_old_projects(api):
    """옛 몸통(목공 + 도배)이면 공정별 계산 엔진 일수의 합"""
    signup(api)
    p = create(api, v2_body())
    assert p.status_code == 201, p.text
    st = api.get(f"/projects/{p.json()['id']}/standard").json()
    per_trade = {c.trade: c.days for c in calc_trades(ProjectOut.model_validate(p.json()))}
    assert set(per_trade) == {"mokgong", "dobae"} and all(per_trade.values())
    assert Decimal(st["days"]) == per_trade["mokgong"] + per_trade["dobae"]


def test_partial_project_keeps_spaces_and_share_version(api):
    signup(api)
    r = create(api, {**PART, "budget_won": 300_000, "start_date": None})
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["home"]["scope"], p["home"]["spaces"], p["home"]["faces"]) == (
        "partial",
        ["living", "kitchen"],
        ["wall"],
    )
    assert [s["name"] for s in p["spaces"]] == ["거실", "주방"]
    assert len(p["trades"]["dobae"]["spaces"]) == 2 and p["when"]["kind"] == "unknown"
    kinds = query("select kind from project_spaces order by sort")
    assert [k["kind"] for k in kinds] == ["living", "kitchen"]
    st = api.get(f"/projects/{p['id']}/standard").json()
    assert (st["scope"], st["spaces"], st["faces"]) == ("partial", ["living", "kitchen"], ["wall"])
    assert (st["share_ver"], st["total"], st["budget_fit"]) == (
        "space-rooms-2026.11",
        335_547,  # 2방 표 거실 0.20 + 주방 0.11 (옛 한 장 표 0.32 · 466,065)
        "over",
    )
    (row,) = query("select scope, faces, space_keys, share_ver, market_ver from standard_quotes")
    assert (row["scope"], row["faces"], row["space_keys"]) == (
        "partial",
        ["wall"],
        ["living", "kitchen"],
    )
    assert (row["share_ver"], row["market_ver"]) == ("space-rooms-2026.11", "paper-market-2026.11")


def test_same_idempotency_key_returns_the_same_project(api):
    signup(api)
    key = str(uuid.uuid4())
    first = create(api, HOME, key)
    assert first.status_code == 201, first.text
    again = create(api, HOME, key)
    assert again.status_code == 200 and again.json() == first.json()
    assert first.json()["source"] == "guest"
    assert query("select count(*) n from projects")[0]["n"] == 1
    assert str(query("select client_key from projects")[0]["client_key"]) == key
    other = create(api, HOME, str(uuid.uuid4()))
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    signup(api, "other@mitjip.test")  # 키는 사람마다 따로
    mine = create(api, HOME, key)
    assert mine.status_code == 201 and mine.json()["id"] != first.json()["id"]
    bad = api.post("/projects", json=HOME, headers={"Idempotency-Key": "not-a-uuid"})
    assert bad.status_code == 422


def _hold(name: str, ready: threading.Event, done: threading.Event) -> None:
    async def run():
        conn = await asyncpg.connect(TEST_DSN)
        try:
            await conn.execute("select pg_advisory_lock(hashtextextended($1, 0))", name)
            ready.set()
            while not done.is_set():
                await asyncio.sleep(0.05)
        finally:
            await conn.close()

    asyncio.run(run())


def test_same_key_still_in_progress_is_409(api):
    signup(api)
    owner = query("select id from users where email = 'customer@mitjip.test'")[0]["id"]
    key = str(uuid.uuid4())
    ready, done = threading.Event(), threading.Event()
    t = threading.Thread(target=_hold, args=(f"project:{owner}:{key}", ready, done))
    t.start()
    try:
        assert ready.wait(10)
        busy = create(api, HOME, key)  # 같은 키 요청이 아직 처리 중(잠금을 쥐고 있음)
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "in_progress"
    finally:
        done.set()
        t.join(10)
    assert query("select count(*) n from projects")[0]["n"] == 0
    assert create(api, HOME, key).status_code == 201


def test_v2_body_still_works_and_422_loc_is_the_same(api):
    signup(api)
    r = create(api, v2_body())
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["source"], p["emd"], p["budget_won"], p["home"]) == ("v2", None, None, None)
    cases = [
        ({k: v for k, v in v2_body().items() if k != "sido"}, ["sido"]),
        (v2_body(size={"basis": "supply", "m2": "5"}), ["size", "m2"]),
        (v2_body(trades={"dobae": {"spaces": ["a"]}}), ["trades", "dobae", "grade"]),
        (v2_body(when={"kind": "soon"}), ["when", "kind"]),
    ]
    for data, loc in cases:
        bad = create(api, data)
        assert bad.status_code == 422, loc
        assert loc in [f["loc"] for f in bad.json()["error"]["fields"]], bad.json()
    edited = api.patch(f"/projects/{p['id']}", json=v2_body(occupied=False))
    assert edited.status_code == 200 and edited.json()["rev"] == 2


def test_district_only_body_makes_a_v3_project_anywhere(api):
    # 시 · 군 · 구까지만 넣어도(동 없음) v3 공사가 되고, 서비스 지역 밖이어도 표준견적서가 나와요
    signup(api)
    home = {k: v for k, v in HOME.items() if k != "emd"}
    r = create(api, {**home, "sgg": "강남구"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["source"], p["emd"], p["home"]["sgg"], p["home"]["emd"]) == (
        "member",
        None,
        "강남구",
        None,
    )
    st = api.get(f"/projects/{p['id']}/standard")
    assert st.status_code == 200 and st.json()["total"] > 0


def test_v3_body_errors(api):
    signup(api)
    outside = create(api, {**HOME, "sgg": "없는구"})
    assert outside.status_code == 422
    assert outside.json()["error"]["fields"][0]["loc"] == ["sgg"]
    extra = create(api, {**HOME, "phone": "01012345678"})
    assert extra.status_code == 422 and extra.json()["error"]["fields"][0]["loc"] == ["phone"]
    past = create(api, {**HOME, "start_date": (today_seoul() - timedelta(days=1)).isoformat()})
    assert past.status_code == 422 and past.json()["error"]["fields"][0]["loc"] == ["start_date"]
    mixed = create(api, {**v2_body(), "emd": "상계동"})  # v3 칸이 있으면 v3로 본다
    assert mixed.status_code == 422
    assert ["size"] in [f["loc"] for f in mixed.json()["error"]["fields"]]
    assert query("select count(*) n from projects")[0]["n"] == 0


def test_patch_v3_until_first_request_then_locked(api):
    me = signup(api)
    p = create(api, HOME).json()
    first = api.get(f"/projects/{p['id']}/standard").json()
    r = api.patch(f"/projects/{p['id']}", json={**HOME, "grade": "economy", "budget_won": None})
    assert r.status_code == 200, r.text
    e = r.json()
    assert (e["rev"], e["home"]["grade"], e["budget_won"], e["source"]) == (
        2,
        "economy",
        None,
        "member",
    )
    st = api.get(f"/projects/{p['id']}/standard").json()
    assert (st["project_rev"], st["trades"][0]["version"]) == (2, 2)
    assert st["total"] < first["total"] and st["budget_fit"] is None
    back = api.patch(f"/projects/{p['id']}", json=v2_body())  # 지금 화면 몸통으로도 고친다
    assert back.status_code == 200 and back.json()["home"] is None

    signup(api, "other@mitjip.test")
    assert api.patch(f"/projects/{p['id']}", json=HOME).status_code == 404
    assert api.get(f"/projects/{p['id']}").status_code == 404
    assert vendor_signup(api).status_code == 201
    assert create(api, HOME).status_code == 403
    assert api.patch(f"/projects/{p['id']}", json=HOME).status_code == 403

    use(api, me)
    query("update projects set locked_at = now() where id = $1", uuid.UUID(p["id"]))
    locked = api.patch(f"/projects/{p['id']}", json=HOME)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "locked"


def test_rooms_are_saved_and_change_the_standard(api):
    """방 개수를 넣으면 저장하고, 고치면 표준견적서가 새 버전으로 바뀐다. 방 5개면 작은방 4 칩도 저장된다."""
    signup(api)
    r = create(api, {**HOME, "rooms": 3})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["home"]["rooms"] == 3
    assert query("select rooms from projects")[0]["rooms"] == 3
    three = api.get(f"/projects/{p['id']}/standard").json()
    five = {
        **HOME,
        "rooms": 5,
        "scope": "partial",
        "spaces": ["living", "room4"],
        "faces": ["wall"],
    }
    assert api.patch(f"/projects/{p['id']}", json=five).status_code == 200
    after = api.get(f"/projects/{p['id']}/standard").json()
    assert after["trades"][0]["version"] == 2 and after["spaces"] == ["living", "room4"]
    assert after["share_ver"] == "space-rooms-2026.11" and after["total"] < three["total"]
    assert [k["kind"] for k in query("select kind from project_spaces order by sort")] == [
        "living",
        "room4",
    ]
    bad = {**HOME, "rooms": 2, "scope": "partial", "spaces": ["room3"], "faces": ["wall"]}
    assert api.patch(f"/projects/{p['id']}", json=bad).status_code == 422


def test_old_project_without_rooms_uses_default_rooms(api):
    """옛 공사(rooms가 비어 있음): 평형 기본값으로 세고, 고른 방 칩이 더 많으면 그만큼 센다"""
    signup(api)
    full = create(api, HOME).json()
    query("update projects set rooms = null")
    st = api.get(f"/projects/{full['id']}/standard").json()
    guest = api.post("/guest/standard", json={**HOME, "rooms": 2}).json()
    assert st["total"] == guest["total"] == 1_802_374
    part = create(api, {**PART, "spaces": ["living", "room2"]})
    assert part.status_code == 201, part.text
    st2 = api.get(f"/projects/{part.json()['id']}/standard").json()
    want = api.post("/guest/standard", json={**PART, "spaces": ["living", "room2"], "rooms": 3})
    assert st2["total"] == want.json()["total"]
