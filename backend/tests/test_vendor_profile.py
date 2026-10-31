"""업체 정보 관리 (GET · PUT /vendor/profile): 권한, 입력 한도, 저장 뒤 읽기, 동시 저장, 가견적 후보 반영.

합성 데이터만 쓴다 (가짜 업체 · 가짜 주소).
"""

import asyncio
import uuid

import asyncpg
import pytest

from app.auth.models import User
from app.config import settings
from app.db import SessionLocal
from app.shared.errors import AppError
from app.shared.regions import SGG
from app.vendor import service
from app.vendor.schemas import MAX_AREAS, VendorProfileIn
from tests.conftest import query
from tests.helpers import make_admin, signup, use, vendor_signup
from tests.sourcing_helpers import customer_project

URL = "/vendor/profile"
MAPO = {"sido": "seoul", "sgg": "마포구"}
# 서울 25곳 + 경기 31곳 = 56곳 (한도 50을 넘는다)
MANY = [{"sido": sido, "sgg": n} for sido in ("seoul", "gyeonggi") for n in sorted(SGG[sido])]


def approved_vendor(api, email: str = "vendor@mitjip.test") -> tuple[str, str]:
    """업체 가입 + 승인만 (공정 · 지역은 아직 없다). (세션 토큰, 업체 id)"""
    r = vendor_signup(api, email=email)
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    query(
        "update vendors set status = 'approved', reviewed_at = now() where user_id = $1",
        uuid.UUID(vid),
    )
    return api.cookies.get(settings.session_cookie), vid


def profile(**over) -> dict:
    return {
        "biz_name": "가짜도배집",
        "site_url": "https://fake-home.test",
        "trades": ["dobae", "mokgong"],
        "areas": [MAPO, {"sido": "seoul", "sgg": "서대문구"}],
        "portfolio_urls": ["https://fake-blog.test/case-1"],
        **over,
    }


def test_approved_vendor_fills_profile_and_reads_it_back(api):
    approved_vendor(api)
    empty = api.get(URL)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {
        "biz_name": None,
        "site_url": None,
        "trades": [],
        "areas": [],
        "portfolio_urls": [],
    }
    r = api.put(
        URL,
        json=profile(
            biz_name="  가짜   도배집 ",
            site_url="HTTPS://fake-home.test/about",
            trades=["mokgong", "dobae", "dobae"],
            areas=[{"sido": "seoul", "sgg": "서대문구"}, MAPO, MAPO],
            portfolio_urls=[
                "https://fake-blog.test/1",
                "https://fake-blog.test/1",
                " http://fake-sns.test/2 ",
            ],
        ),
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got == {  # 빈칸 · 겹친 값은 정리해서 저장한다
        "biz_name": "가짜 도배집",
        "site_url": "https://fake-home.test/about",
        "trades": ["dobae", "mokgong"],
        "areas": [MAPO, {"sido": "seoul", "sgg": "서대문구"}],
        "portfolio_urls": ["https://fake-blog.test/1", "http://fake-sns.test/2"],
    }
    assert api.get(URL).json() == got


def test_saving_again_changes_only_the_difference(api):
    approved_vendor(api)
    assert api.put(URL, json=profile()).status_code == 200
    before = {r["trade"]: r["x"] for r in query("select trade, xmin::text x from vendor_trades")}
    r = api.put(
        URL,
        json=profile(
            trades=["dobae", "tile"],
            areas=[MAPO, {"sido": "gyeonggi", "sgg": "고양시"}],
            site_url="",
            portfolio_urls=[],
        ),
    )
    assert r.status_code == 200, r.text
    after = {r["trade"]: r["x"] for r in query("select trade, xmin::text x from vendor_trades")}
    assert set(after) == {"dobae", "tile"}
    assert after["dobae"] == before["dobae"]  # 그대로 둔 공정은 지우고 다시 넣지 않는다
    areas = query("select sido, sgg from vendor_areas order by sido, sgg")
    assert [(a["sido"], a["sgg"]) for a in areas] == [("gyeonggi", "고양시"), ("seoul", "마포구")]
    (v,) = query("select site_url, portfolio_urls from vendors")
    assert v["site_url"] is None and v["portfolio_urls"] == []


def test_only_approved_vendors_use_profile(api):
    api.cookies.clear()
    assert api.get(URL).status_code == 401
    assert api.put(URL, json=profile()).status_code == 401
    signup(api, "c@mitjip.test")
    assert api.get(URL).status_code == 403  # 고객
    assert api.put(URL, json=profile()).json()["error"]["code"] == "forbidden"
    make_admin(api)
    assert api.get(URL).status_code == 403  # 관리자
    assert api.put(URL, json=profile()).status_code == 403
    r = vendor_signup(api, email="wait@mitjip.test")  # 승인 대기
    nope = api.get(URL)
    assert nope.status_code == 403 and nope.json()["error"]["code"] == "vendor_not_approved"
    assert api.put(URL, json=profile()).status_code == 403
    query(
        "update vendors set status = 'rejected', reject_reason = '흐려요' where user_id = $1",
        uuid.UUID(r.json()["id"]),
    )
    assert api.get(URL).status_code == 403  # 반려
    rej = api.put(URL, json=profile())
    assert rej.status_code == 403 and rej.json()["error"]["code"] == "vendor_not_approved"
    assert query("select count(*) n from vendor_trades")[0]["n"] == 0
    assert query("select count(*) n from vendors where biz_name is not null")[0]["n"] == 0


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"trades": []}, "trades"),
        ({"trades": ["sauna"]}, "trades"),
        ({"areas": []}, "areas"),
        ({"areas": [{"sido": "seoul", "sgg": "해운대구"}]}, "areas"),  # 서울에 없는 구
        ({"areas": [{"sido": "mars", "sgg": "마포구"}]}, "areas"),
        ({"areas": MANY}, "areas"),  # 한도를 넘는다
        ({"portfolio_urls": ["javascript:alert(1)"]}, "portfolio_urls"),
        ({"portfolio_urls": ["ftp://fake.test/a"]}, "portfolio_urls"),
        ({"portfolio_urls": ["fake.test/a"]}, "portfolio_urls"),
        ({"portfolio_urls": ["https://"]}, "portfolio_urls"),
        ({"portfolio_urls": ["https://fake.test/a b"]}, "portfolio_urls"),
        ({"portfolio_urls": [f"https://fake.test/{i}" for i in range(6)]}, "portfolio_urls"),
        ({"portfolio_urls": ["https://fake.test/" + "a" * 290]}, "portfolio_urls"),
        ({"site_url": "javascript:alert(1)"}, "site_url"),
        ({"biz_name": "   "}, "biz_name"),
        ({"biz_name": "가" * 101}, "biz_name"),
    ],
)
def test_profile_input_limits(api, over, field):
    approved_vendor(api)
    r = api.put(URL, json=profile(**over))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["fields"][0]["loc"][0] == field
    assert query("select count(*) n from vendor_trades")[0]["n"] == 0


def test_area_limit_boundary_and_body_size(api):
    approved_vendor(api)
    ok = api.put(URL, json=profile(areas=MANY[:MAX_AREAS]))
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["areas"]) == MAX_AREAS
    big = api.put(
        URL,
        content=b"{" + b" " * (1024 * 1024 + 10) + b"}",
        headers={"content-type": "application/json"},
    )
    assert big.status_code == 413


def test_db_checks_links_and_homepage(api):
    _, vid = approved_vendor(api)
    v = uuid.UUID(vid)
    bad = [
        ["javascript:alert(1)"],
        ["https://ok.test/1", "ftp://ok.test/2"],
        ["https://a b.test"],
        [None],
        [f"https://ok.test/{i}" for i in range(6)],
    ]
    for urls in bad:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            query("update vendors set portfolio_urls = $1 where user_id = $2", urls, v)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query("update vendors set site_url = 'javascript:alert(1)' where user_id = $1", v)
    good = ["https://ok.test/1", "http://ok.test/2?a=1&b=2"]
    query("update vendors set portfolio_urls = $1 where user_id = $2", good, v)
    assert query("select portfolio_urls from vendors")[0]["portfolio_urls"] == good


def test_two_saves_at_once_do_not_mix(api):
    _, vid = approved_vendor(api)
    a = VendorProfileIn(**profile(biz_name="가짜A", trades=["dobae"], areas=[MAPO]))
    b = VendorProfileIn(
        **profile(
            biz_name="가짜B",
            trades=["tile", "bath"],
            areas=[{"sido": "busan", "sgg": "중구"}, {"sido": "busan", "sgg": "동구"}],
        )
    )
    want = {
        "가짜A": (["dobae"], [("seoul", "마포구")]),
        "가짜B": (["bath", "tile"], [("busan", "동구"), ("busan", "중구")]),
    }

    async def both():
        async def once(data):
            async with SessionLocal() as s:
                user = await s.get(User, uuid.UUID(vid))
                try:
                    await service.save_profile(s, user, data)
                    return 200
                except AppError as exc:
                    return exc.status

        return await asyncio.gather(once(a), once(b), once(a), once(b))

    for _ in range(3):
        assert set(asyncio.run(both())) <= {200, 409}  # 500이 나지 않는다
        (v,) = query("select biz_name from vendors")
        trades = sorted(r["trade"] for r in query("select trade from vendor_trades"))
        areas = sorted((r["sido"], r["sgg"]) for r in query("select sido, sgg from vendor_areas"))
        assert (trades, areas) == want[v["biz_name"]]  # 한 쪽 저장만 남고 섞이지 않는다


def test_saved_vendor_becomes_app_candidate(api):
    """저장한 공정 · 시군구의 프로젝트에 앱 업체(앱 안 가견적 요청, 무료)로 나온다."""
    v_token, vid = approved_vendor(api)
    c_token, pid = customer_project(api)  # 서울 마포구 도배 · 목공
    sourcing = f"/projects/{pid}/sourcing"
    assert api.get(sourcing).json()["candidates"] == []  # 정보를 넣기 전에는 후보가 아니다

    use(api, v_token)
    assert api.put(URL, json=profile(trades=["dobae", "tile"], areas=[MAPO])).status_code == 200
    use(api, c_token)
    (card,) = api.get(sourcing).json()["candidates"]
    assert (card["id"], card["kind"], card["route"], card["name"], card["trades"]) == (
        vid,
        "app",
        "app_request",
        "가짜도배집",
        ["dobae"],
    )
    assert card["cost"]["label"] == "무료"
    assert card["links"]["homepage"] == "https://fake-home.test"
    assert card["links"]["portfolio"] == ["https://fake-blog.test/case-1"]
    ask = api.post(f"/projects/{pid}/quote-requests", json={"trade": "dobae", "vendor_id": vid})
    assert ask.status_code == 201, ask.text

    use(api, v_token)  # 다른 구로 바꾸면 후보에서 빠진다
    assert api.put(URL, json=profile(areas=[{"sido": "seoul", "sgg": "강남구"}])).status_code == 200
    use(api, c_token)
    assert api.get(sourcing).json()["candidates"] == []
