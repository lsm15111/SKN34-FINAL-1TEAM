"""이 집 업체 고르기 · 업체 자세히: 거르기(승인 · 공정 · 지역), 가견적(계산 엔진 · 없음 · 정렬), 권한, 시공 사진."""

import uuid
from datetime import date

from app.calc.schedule import years_since
from app.shared.clock import today_seoul
from tests.conftest import query
from tests.helpers import JPEG, PASSWORD, PDF, make_admin, signup, upload, use, vendor_signup
from tests.test_project import ALL, SIX
from tests.test_project import body as project_body
from tests.test_vendor_price import maru, ready_vendor
from tests.test_vendor_profile import URL as PROFILE
from tests.test_vendor_profile import approved_vendor, vendor_id
from tests.test_vendor_profile import body as profile_body

NOWON_32 = {  # 노원구 32평(공급 105.8㎡) 빈 집 · 도배 기본형 · 기본 공간 6곳(집 전체): 시안 예시와 같은 집
    "sgg": "노원구",
    "size": {"basis": "supply", "m2": "105.8"},
    "occupied": False,
    "balcony_ext": False,
    "spaces": SIX,
    "trades": {"dobae": {"spaces": ALL, "grade": "basic"}},
}


def priced(api, email: str, name: str, wall: int | None = 6650, **profile) -> str:
    """승인 · 업체 정보 · 근거 파일 · (wall이 있으면) 확인한 도배 단가까지 만든 업체 id"""
    fid = ready_vendor(api, email, **profile)
    if wall is not None:
        assert api.put("/vendor/prices/dobae", json=maru(fid, wall=wall)).status_code == 200
        assert api.post("/vendor/prices/dobae/confirm").status_code == 200
    query("update vendors set biz_name = $1 where user_id = $2", name, vendor_id(email))
    return str(vendor_id(email))


def world(api) -> dict:
    """업체 여러 곳 + 고객 프로젝트. 이름 → id, 'customer' → 토큰, 'project' → id"""
    w = {
        "maru": priced(api, "maru@mitjip.test", "마루와벽"),
        "gyeol": priced(api, "gyeol@mitjip.test", "결도배", wall=7000),
        "hangyeol": priced(api, "hangyeol@mitjip.test", "한결인테리어", wall=None),
        "gangnam": priced(
            api, "gangnam@mitjip.test", "강남도배", areas=[{"sido": "seoul", "sgg": "강남구"}]
        ),
        "closed": priced(api, "closed@mitjip.test", "닫힌도배"),
    }
    # 천장 단가를 안 넣은 업체: 이 집은 천장도 하니 가견적 없음
    fid = ready_vendor(api, "gana@mitjip.test")
    lines = [ln for ln in maru(fid)["lines"] if ln["key"] != "ceiling"]
    api.put("/vendor/prices/dobae", json={"lines": lines})
    api.post("/vendor/prices/dobae/confirm")
    query(
        "update vendors set biz_name = '가나도배' where user_id = $1", vendor_id("gana@mitjip.test")
    )
    w["gana"] = str(vendor_id("gana@mitjip.test"))
    # 목공만 하는 업체
    approved_vendor(api, "mok@mitjip.test")
    assert api.put(PROFILE, json=profile_body(trades=["mokgong"])).status_code == 200
    w["mok"] = str(vendor_id("mok@mitjip.test"))
    query(
        "update vendors set status = 'rejected', review_code = 'closed', approved_at = null"
        " where user_id = $1",
        uuid.UUID(w["closed"]),
    )
    w["customer"] = signup(api, "home@mitjip.test")
    r = api.post("/projects", json=project_body(**NOWON_32))
    assert r.status_code == 201, r.text
    w["project"] = r.json()["id"]
    return w


def test_list_filters_and_sorts_by_estimate(api):
    w = world(api)
    r = api.get(f"/projects/{w['project']}/vendors", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["region"], got["area_name"], got["standard_total"]) == (
        "서울 노원구",
        "노원구",
        2_945_656,  # 도배 표준견적서 294만 5,656원 (시안의 316만 6,556원은 r1 단가)
    )
    rows = [
        (v["biz_name"], v["estimate_total"], v["vs_standard"], v["vs_direction"])
        for v in got["vendors"]
    ]
    assert rows == [
        ("마루와벽", 2_883_865, "-2.1", "less"),  # 표준견적서보다 2.1% 적어요
        ("결도배", 2_949_430, "0.1", "more"),
        ("가나도배", None, None, None),  # 천장 단가 없음 → 가견적 없음
        ("한결인테리어", None, None, None),  # 확인한 단가 없음
    ]
    first = got["vendors"][0]
    assert first["verified_on"] == today_seoul().isoformat() and first["visit_fee"] == 0
    assert first["contact_method"] == "phone" and first["trades"] == ["dobae"]
    assert [a["label"] for a in first["areas"]] == ["서울 노원구", "서울 도봉구"]
    assert {"phone", "contact_url"}.isdisjoint(first)  # 연락처는 실측 요청 뒤에만

    bad = api.get(f"/projects/{w['project']}/vendors", params={"trade": "mokgong"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "trade"  # 이 집은 도배만
    assert (
        api.get(f"/projects/{w['project']}/vendors", params={"trade": "floor"}).status_code == 422
    )


def test_bundle_target_outside_project_hides_estimate(api):
    approved_vendor(api)
    assert api.put(PROFILE, json=profile_body(trades=["mokgong"])).status_code == 200
    fid = upload(api, kind="price_doc", content=PDF, name="단가.pdf").json()["id"]
    vid = str(vendor_id())
    assert (
        api.post("/vendor/price-files", json={"file_id": fid, "trade": "mokgong"}).status_code
        == 201
    )
    prices = {
        "lines": [
            {"key": "door", "unit_price": 90_000},
            {"key": "molding", "included_in": "door"},
            {"key": "molding_mat", "included_in": "door"},
        ]
    }
    assert api.put("/vendor/prices/mokgong", json=prices).status_code == 200
    assert api.post("/vendor/prices/mokgong/confirm").status_code == 200
    signup(api, "home@mitjip.test")
    p = api.post(
        "/projects",
        json=project_body(
            sgg="노원구", trades={"mokgong": {"spaces": ["a"], "items": ["molding"]}}
        ),
    )
    assert p.status_code == 201, p.text
    url = f"/projects/{p.json()['id']}/vendors"
    result = api.get(url, params={"trade": "mokgong"})
    assert result.status_code == 200, result.text
    (vendor,) = result.json()["vendors"]
    assert vendor["estimate_total"] is None
    assert vendor["vs_standard"] is None
    detail = api.get(f"{url}/{vid}", params={"trade": "mokgong"})
    assert detail.status_code == 200, detail.text
    assert detail.json()["estimate"] is None


def test_estimate_total_matches_calc_and_detail_explains_it(api):
    w = world(api)
    query("update vendors set opened_on = '2014-03-02' where user_id = $1", uuid.UUID(w["maru"]))
    url = f"/projects/{w['project']}/vendors/{w['maru']}"
    r = api.get(url, params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    d = r.json()
    e = d["estimate"]
    assert (e["supply"], e["vat"], e["total"], e["exempt"]) == (
        2_621_695,
        262_170,
        2_883_865,
        False,
    )
    assert [(x["key"], x["unit_price"], x["qty"], x["amount"]) for x in e["lines"]] == [
        ("wall", 6650, "170.3", 1_132_495),
        ("ceiling", 6800, "73.0", 496_400),
        ("paper", 3400, "292.0", 992_800),
        ("primer", None, "262.8", 0),
    ]
    primer = e["lines"][3]
    assert (
        primer["included_in_name"] == "도배지 (실크)" and primer["source"] == "견적서_2026-09.pdf"
    )
    assert e["confirmed_on"] == today_seoul().isoformat() and e["set_id"]
    assert (e["vs_standard"], e["vs_direction"]) == ("-2.1", "less")
    assert d["not_included"] == ["기존 벽지 철거", "폐기물 처리"]
    assert d["years_open"] == years_since(date(2014, 3, 2), today_seoul())
    assert (d["in_area"], d["area_name"], d["dong"]) == (True, "노원구", None)
    p = d["profile"]
    assert p["biz_name"] == "마루와벽" and p["opened_on"] == "2014-03-02"
    assert p["address_area"] == "서울특별시 도봉구" and p["faqs"][0]["key"] == "process"
    assert {"phone", "contact_url", "address"}.isdisjoint(p)

    none = api.get(f"/projects/{w['project']}/vendors/{w['hangyeol']}", params={"trade": "dobae"})
    assert none.status_code == 200 and none.json()["estimate"] is None
    gana = api.get(f"/projects/{w['project']}/vendors/{w['gana']}", params={"trade": "dobae"})
    assert gana.json()["estimate"] is None
    for name in ("gangnam", "closed", "mok"):  # 지역 밖 · 승인 아님 · 공정 안 함
        miss = api.get(f"/projects/{w['project']}/vendors/{w[name]}", params={"trade": "dobae"})
        assert miss.status_code == 404, name
    assert (
        api.get(
            f"/projects/{w['project']}/vendors/{uuid.uuid4()}", params={"trade": "dobae"}
        ).status_code
        == 404
    )


def test_exempt_vendor_has_no_vat(api):
    vid = priced(api, "tax@mitjip.test", "면세도배", tax_kind="exempt")
    signup(api, "home@mitjip.test")
    pid = api.post("/projects", json=project_body(**NOWON_32)).json()["id"]
    e = api.get(f"/projects/{pid}/vendors/{vid}", params={"trade": "dobae"}).json()["estimate"]
    assert (e["vat"], e["total"], e["exempt"]) == (0, 2_621_695, True)
    assert (e["vs_standard"], e["vs_direction"]) == ("-11.0", "less")


def test_only_the_owner_customer(api):
    w = world(api)
    paths = (
        f"/projects/{w['project']}/vendors?trade=dobae",
        f"/projects/{w['project']}/vendors/{w['maru']}?trade=dobae",
        f"/projects/{w['project']}/vendors/{w['maru']}/photos/{uuid.uuid4()}",
    )
    signup(api, "other@mitjip.test")
    assert all(api.get(u).status_code == 404 for u in paths)  # 남의 프로젝트
    assert vendor_signup(api, email="v2@mitjip.test").status_code == 201
    assert all(api.get(u).status_code == 403 for u in paths)  # 업체
    make_admin(api)
    assert all(api.get(u).status_code == 403 for u in paths)  # 관리자
    api.cookies.clear()
    assert all(api.get(u).status_code == 401 for u in paths)


def test_portfolio_photos_only_for_listed_vendor(api):
    w = world(api)
    shots = {}
    for name in ("maru", "gangnam"):
        api.cookies.clear()
        login = api.post("/auth/login", json={"email": f"{name}@mitjip.test", "password": PASSWORD})
        assert login.status_code == 200
        fid = upload(api, kind="portfolio", content=JPEG, name="거실.jpg").json()["id"]
        assert (
            api.post("/vendor/portfolio", json={"file_id": fid, "title": "실크 벽지"}).status_code
            == 201
        )
        shots[name] = fid
    doc = upload(api, kind="price_doc", content=PDF, name="단가표.pdf").json()["id"]  # 강남도배
    maru_doc = query(
        "select file_id from vendor_price_files where vendor_id = $1", uuid.UUID(w["maru"])
    )[0]["file_id"]
    lic = query("select license_file_id from vendors where user_id = $1", uuid.UUID(w["maru"]))
    use(api, w["customer"])
    base = f"/projects/{w['project']}/vendors"
    ok = api.get(f"{base}/{w['maru']}/photos/{shots['maru']}")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert (
        api.get(f"{base}/{w['maru']}/photos/{maru_doc}").status_code == 404
    )  # 근거 파일은 안 내준다
    assert api.get(f"{base}/{w['maru']}/photos/{lic[0]['license_file_id']}").status_code == 404
    assert (
        api.get(f"{base}/{w['gyeol']}/photos/{shots['maru']}").status_code == 404
    )  # 다른 업체 사진
    assert api.get(f"{base}/{w['gangnam']}/photos/{shots['gangnam']}").status_code == 404  # 지역 밖
    assert api.get(f"{base}/{w['gangnam']}/photos/{doc}").status_code == 404
    assert api.get(f"/files/{shots['maru']}").status_code == 404  # 파일 주소로는 여전히 못 연다
