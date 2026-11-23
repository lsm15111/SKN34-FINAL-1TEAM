"""업체 정보 v3 칸: 한 줄 소개(V15 intro) · 시공 사례 면적 기준(C47 '공급 79.3㎡', 0034) ·
거절 뒤 다시 신청에서 사업자등록번호 고치기(VS02) · 단가표 예시 집 이름(D02)."""

import asyncio
import json
import uuid

import asyncpg
import pytest

from app.db import SessionLocal
from app.vendor import repository as repo
from app.vendor import service
from app.vendor.schemas import PublicProfileOut
from tests.conftest import query
from tests.helpers import biz_no_for, make_admin, signup, upload, use, vendor_signup
from tests.test_vendor_profile import URL, approved_vendor, body, portfolio, vendor_id
from tests.test_vendor_review import APP, applied, decide

INTRO = "도배만 12년, 이음매를 깔끔하게 해요"  # 9판 V15
FORM = {
    "biz_name": "예시도배",
    "owner_name": "예시 대표",
    "phone": "010-1234-5678",
    "trades": ["dobae"],
    "areas": [{"sido": "seoul", "sgg": "노원구"}],
}


def public(vid: uuid.UUID):
    async def go():
        async with SessionLocal() as s:
            return await service.public_profile(s, vid)

    return asyncio.run(go())


def locs(r) -> list:
    return [f["loc"] for f in r.json()["error"]["fields"]]


def vendor_row(vid: str) -> dict:
    return dict(query("select status, biz_no from vendors where user_id = $1", uuid.UUID(vid))[0])


def test_intro_is_one_line_kept_or_cleared(api):
    approved_vendor(api)
    vid = vendor_id()
    r = api.put(URL, json=body(intro="  도배만 12년,\n이음매를   깔끔하게 해요  "))
    assert r.status_code == 200, r.text
    assert r.json()["intro"] == INTRO  # 줄바꿈 · 겹친 빈칸은 한 칸
    assert query("select intro from vendors")[0]["intro"] == INTRO
    kept = api.put(URL, json=body(updated_at=r.json()["updated_at"]))  # 옛 화면: 칸을 안 보냄
    assert kept.status_code == 200 and kept.json()["intro"] == INTRO
    gone = api.put(URL, json=body(updated_at=kept.json()["updated_at"], intro="   "))
    assert gone.status_code == 200 and gone.json()["intro"] is None  # 빈 글은 지운다
    assert query("select intro from vendors")[0]["intro"] == ""
    assert api.get(URL).json()["intro"] is None

    long = api.put(URL, json=body(updated_at=gone.json()["updated_at"], intro="가" * 61))
    assert long.status_code == 422 and locs(long) == [["intro"]]
    assert api.put(URL, json=body(intro=["목록"])).status_code == 422
    assert query("select intro from vendors")[0]["intro"] == ""

    ok = api.put(URL, json=body(updated_at=gone.json()["updated_at"], intro="가" * 60))
    assert ok.status_code == 200 and ok.json()["intro"] == "가" * 60
    # 공개 프로필(C11 · D07)에도 소개가 보인다(리드 11-24, QA r6 M12: 업체가 쓴 소개가 고객에게 안 보였음.
    # 예전 9판 고객 화면엔 칸이 없었어요). 연락처 · 계좌는 가려 보낸다(아래 시험)
    assert "intro" in PublicProfileOut.model_fields
    assert public(vid).model_dump()["intro"] == "가" * 60
    make_admin(api)
    assert api.get(f"/admin/vendors/{vid}").json()["intro"] == "가" * 60  # 관리자 심사 화면


def test_public_profile_masks_contacts_in_vendor_text(api):
    """고객에게 가는 한 줄 소개 · 자주 묻는 답의 전화번호는 가리고, 업체 본인 화면은 쓴 그대로예요(QA r6 M12)."""
    approved_vendor(api)
    vid = vendor_id()
    r = api.put(URL, json=body(intro="문의 010-1234-5678 도배 전문"))
    assert r.status_code == 200 and r.json()["intro"] == "문의 010-1234-5678 도배 전문"
    shown = public(vid).model_dump()
    assert "010-1234-5678" not in (shown["intro"] or "") and "도배 전문" in shown["intro"]


def test_intro_needs_an_approved_vendor(api):
    signup(api)
    assert api.put(URL, json=body(intro=INTRO)).status_code == 403  # 고객
    vendor_signup(api)
    r = api.put(URL, json=body(intro=INTRO))  # 승인 전 업체
    assert r.status_code == 403 and r.json()["error"]["code"] == "vendor_not_approved"
    assert query("select intro from vendors")[0]["intro"] == ""


def test_portfolio_area_basis_and_screen_text(api):
    approved_vendor(api)
    vid = vendor_id()
    a = upload(api, kind="portfolio", name="거실.jpg").json()["id"]
    b = upload(api, kind="portfolio", name="안방.jpg").json()["id"]
    pa = portfolio(api, a, title="거실", paper="basic", area_m2="79.3", area_basis="supply")
    assert pa.status_code == 201, pa.text
    assert (pa.json()["area_basis"], pa.json()["area_text"]) == ("supply", "공급 79.3㎡")  # C47
    no_area = portfolio(api, b, area_basis="exclusive")
    assert no_area.status_code == 422 and locs(no_area) == [["area_basis"]]
    assert portfolio(api, b, area_m2="59.9", area_basis="pyeong").status_code == 422
    pb = portfolio(api, b, title="안방", area_m2="59.9")  # 기준 없이 면적만 (옛 화면)
    assert (pb.json()["area_basis"], pb.json()["area_text"]) == (None, "59.9㎡")
    ids = [pa.json()["id"], pb.json()["id"]]

    def put(*items):
        return api.put(
            URL, json=body(updated_at=api.get(URL).json()["updated_at"], portfolio=items)
        )

    def edit(*items) -> dict:
        r = put(*items)
        assert r.status_code == 200, r.text
        return {p["id"]: (p["area_basis"], p["area_text"]) for p in r.json()["portfolio"]}

    old_screen = edit(
        {"id": ids[0], "title": "거실", "area_m2": "79.3"},  # 기준 칸을 모르는 화면: 기준 그대로
        {"id": ids[1], "title": "안방", "area_m2": "59.9", "area_basis": "exclusive"},
    )
    assert old_screen == {ids[0]: ("supply", "공급 79.3㎡"), ids[1]: ("exclusive", "전용 59.9㎡")}
    cleared = edit(
        {"id": ids[0], "title": "거실"},  # 면적을 지우면 기준도 지운다
        {"id": ids[1], "title": "안방", "area_m2": "59.9", "area_basis": None},
    )
    assert cleared == {ids[0]: (None, None), ids[1]: (None, "59.9㎡")}
    assert (
        query("select count(*) n from vendor_portfolio where area_basis is not null")[0]["n"] == 0
    )

    edit(
        {"id": ids[0], "title": "거실", "area_m2": "79.3", "area_basis": "supply"},
        {"id": ids[1], "title": "안방"},
    )
    bad = put(
        {"id": ids[0], "title": "거실", "area_basis": "supply"}, {"id": ids[1], "title": "안방"}
    )
    assert bad.status_code == 422 and locs(bad) == [["portfolio", "0", "area_basis"]]
    shown = public(vid).portfolio  # 고객 업체 자세히(C11 사례 · C47 크게 보기)
    assert [(p.area_basis, p.area_text) for p in shown] == [("supply", "공급 79.3㎡"), (None, None)]


def test_area_basis_needs_area_in_db(api):
    approved_vendor(api)
    fid = upload(api, kind="portfolio").json()["id"]
    assert portfolio(api, fid, area_m2="79.3", area_basis="exclusive").status_code == 201
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query("update vendor_portfolio set area_m2 = null")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query("update vendor_portfolio set area_basis = 'pyeong'")


def test_reapply_can_fix_the_biz_no(api):
    token, vid = applied(api)
    old = biz_no_for("vendor@mitjip.test")
    vendor_signup(api, email="other@mitjip.test")  # 다른 업체가 쓰는 번호
    taken = biz_no_for("other@mitjip.test")
    admin = make_admin(api)
    assert decide(api, vid, "reject", code="info_mismatch", note="번호가 달라요").status_code == 200

    use(api, token)
    bad = api.post(f"{APP}/reapply", json={**FORM, "biz_no": "12345"})
    assert bad.status_code == 422 and locs(bad) == [["biz_no"]]
    dup = api.post(f"{APP}/reapply", json={**FORM, "biz_no": taken})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "biz_no_taken"
    assert vendor_row(vid) == {"status": "rejected", "biz_no": old}  # 그대로

    r = api.post(f"{APP}/reapply", json={**FORM, "biz_no": "214-86-03518"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["biz_no"]) == ("pending", "2148603518")
    (h,) = query("select changes from vendor_reviews where action = 'reapply'")
    assert json.loads(h["changes"])["biz_no"] == old  # 처리 기록에 전 번호
    use(api, admin)
    row = next(x for x in api.get("/admin/vendors?status=pending").json() if x["user_id"] == vid)
    assert row["biz_no"] == "2148603518" and row["changes"]["biz_no"] == old


def test_reapply_number_taken_meanwhile_is_409(api, monkeypatch):
    """확인한 뒤 다른 업체가 같은 번호를 가져가도(UNIQUE) 500이 아니라 409 biz_no_taken"""
    token, vid = applied(api)
    vendor_signup(api, email="other@mitjip.test")
    taken = biz_no_for("other@mitjip.test")
    make_admin(api)
    assert decide(api, vid, "reject", code="info_mismatch", note="번호가 달라요").status_code == 200
    use(api, token)

    async def not_yet(s, biz_no):  # 확인과 저장 사이에 다른 신청이 끼어든 것처럼
        return False

    monkeypatch.setattr(repo, "biz_no_taken", not_yet)
    r = api.post(f"{APP}/reapply", json={**FORM, "biz_no": taken})
    assert r.status_code == 409 and r.json()["error"]["code"] == "biz_no_taken"
    assert vendor_row(vid)["status"] == "rejected"
    assert query("select count(*) n from vendor_reviews where action = 'reapply'")[0]["n"] == 0


def test_reapply_needs_the_vendor_itself(api):
    signup(api)
    assert api.post(f"{APP}/reapply", json={**FORM, "biz_no": "2148603518"}).status_code == 403


def test_price_table_names_the_example_home(api):
    approved_vendor(api)
    v3 = api.get("/vendor/prices?trade=dobae").json()["v3"]
    assert v3["example_home"] == "공급 69.4㎡ 집"  # D02 '공급 69.4㎡ 집이면'
