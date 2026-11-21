"""업체 심사: 승인 · 보완 요청 · 거절, 보완해서 다시 보냄 · 거절 뒤 다시 신청, 처리 기록 · 알림 · 동시 결정."""

import asyncio
import json
import uuid

import asyncpg
import pytest

from app.auth.models import User
from app.config import settings
from app.db import SessionLocal
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from app.vendor import service
from app.vendor.schemas import ReviewIn
from tests.conftest import query
from tests.helpers import JPEG, make_admin, no_surprises, signup, upload, use, vendor_signup

APP = "/vendor/application"
ROW = (
    "insert into vendor_reviews (id, vendor_id, action, code, changes)"
    " select gen_random_uuid(), user_id, {action}, {code}, {changes} from vendors"
)


def applied(api, email: str = "vendor@mitjip.test", **over) -> tuple[str, str]:
    """업체 가입 신청. (세션 토큰, 업체 id)"""
    r = vendor_signup(api, email=email, **over)
    assert r.status_code == 201, r.text
    return api.cookies.get(settings.session_cookie), r.json()["id"]


def decide(api, vid: str, action: str, **body):
    return api.post(f"/admin/vendors/{vid}/review", json={"action": action, **body})


def notes(vid: str) -> list[dict]:
    rows = query("select kind, body, link from notifications where user_id = $1", uuid.UUID(vid))
    return [dict(r) for r in rows]


def test_apply_shows_application_and_history(api):
    applied(api)
    got = api.get(APP)
    assert got.status_code == 200, got.text
    a = got.json()
    assert a["status"] == "pending" and a["applied_at"] and a["approved_at"] is None
    assert (a["biz_name"], a["owner_name"], a["trades"]) == ("예시도배", "예시 대표", ["dobae"])
    assert [x["label"] for x in a["areas"]] == ["서울 노원구", "서울 도봉구"]
    assert a["license"]["filename"] == "사업자등록증.pdf"
    assert a["decision"] is None and a["open_fields"] == []

    make_admin(api)
    vid = query("select user_id from vendors")[0]["user_id"]
    assert api.get("/admin/vendors/summary").json() == {"pending": 1, "needs_info": 0, "done": 0}
    (item,) = api.get("/admin/vendors", params={"status": "pending"}).json()
    assert item["waiting_days"] == 0 and item["resubmitted"] is False and item["changes"] is None
    detail = api.get(f"/admin/vendors/{vid}").json()
    assert [(r["action"], r["by_name"]) for r in detail["reviews"]] == [("apply", "예시 담당자")]


def test_approve_opens_vendor_features_once(api):
    token, vid = applied(api)
    assert api.get("/vendor/profile").status_code == 403  # 심사 중에는 잠겨 있다
    make_admin(api)
    r = decide(api, vid, "approve", opened_on="2014-03-02")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "approved" and d["approved_at"] and d["opened_on"] == "2014-03-02"
    assert [x["action"] for x in d["reviews"]] == ["approve", "apply"]
    again = decide(api, vid, "approve")
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"
    assert "다른 관리자가 먼저" in again.json()["error"]["message"]
    assert notes(vid) == [
        {
            "kind": "vendor_approve",
            "body": "가입 심사가 끝났어요. 이제 고객 요청을 받을 수 있어요.",
            "link": "/vendor",
        }
    ]
    assert api.get("/admin/vendors/summary").json()["done"] == 1

    use(api, token)
    assert api.get("/vendor/profile").status_code == 200  # 승인 효과: 업체 기능이 열린다
    a = api.get(APP).json()
    assert a["status"] == "approved" and a["decision"]["action"] == "approve"
    assert api.get("/me").json()["vendor_status"] == "approved"


def test_needs_info_then_resubmit_only_open_fields(api):
    token, vid = applied(api)
    make_admin(api)
    note = "등록증에는 상호가 '다온인테리어'로 적혀 있어요."
    assert decide(api, vid, "needs_info", code="name_mismatch", note=note).status_code == 200
    assert notes(vid)[0]["body"] == "관리자가 보완을 요청했어요."

    use(api, token)
    me = api.get("/me").json()
    assert (me["vendor_status"], me["vendor_review_code"], me["vendor_review_note"]) == (
        "needs_info",
        "name_mismatch",
        note,
    )
    assert api.get("/vendor/profile").status_code == 403  # 보완 요청도 승인 전과 같이 잠긴다
    a = api.get(APP).json()
    assert a["open_fields"] == [
        {"field": "biz_name", "required": True},
        {"field": "license_file_id", "required": False},
    ]
    assert (a["decision"]["code"], a["decision"]["note"]) == ("name_mismatch", note)

    def send(**body):
        return api.post(f"{APP}/resubmit", json=body)

    assert send(owner_name="다른 대표").json()["error"]["code"] == "not_open"
    assert send(biz_name="다온인테리어", biz_no="1234567890").status_code == 422
    assert send().json()["error"]["code"] == "required"
    ok = send(biz_name="다온인테리어")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "pending" and ok.json()["biz_name"] == "다온인테리어"
    assert ok.json()["open_fields"] == []
    assert send(biz_name="또").status_code == 409

    make_admin(api, "admin2@mitjip.test")
    (item,) = api.get("/admin/vendors", params={"status": "pending"}).json()
    assert item["resubmitted"] is True and item["changes"] == {"biz_name": "예시도배"}
    assert item["review_code"] is None and item["review_note"] is None
    history = api.get(f"/admin/vendors/{vid}").json()["reviews"]
    assert [x["action"] for x in history] == ["resubmit", "needs_info", "apply"]
    assert history[0]["by_id"] == vid and history[0]["changes"] == {"biz_name": "예시도배"}


def test_blurry_needs_a_new_license_and_old_one_is_removed(api):
    token, vid = applied(api)
    old = query("select license_file_id from vendors")[0]["license_file_id"]
    make_admin(api)
    decide(api, vid, "needs_info", code="blurry")
    other_token, _ = applied(api, "other@mitjip.test")
    stranger_file = upload(api, kind="license", content=JPEG, name="남의 등록증.jpg").json()["id"]

    use(api, token)
    resubmit = f"{APP}/resubmit"
    assert api.post(resubmit, json={}).json()["error"]["code"] == "required"
    assert api.post(resubmit, json={"biz_name": "x"}).json()["error"]["code"] == "not_open"
    assert api.post(resubmit, json={"license_file_id": str(old)}).status_code == 422  # 지금 파일
    assert api.post(resubmit, json={"license_file_id": stranger_file}).status_code == 422
    # 승인 전 업체는 업체 종류 파일을 못 올려요(sec M5). 다른 종류 파일은 등록증 행의 종류를 바꿔 만들어요
    assert upload(api, kind="portfolio").status_code == 403
    photo = upload(api, kind="license", content=JPEG, name="시공 사진.jpg").json()["id"]
    query("update files set kind = 'portfolio' where id = $1", uuid.UUID(photo))
    assert api.post(resubmit, json={"license_file_id": photo}).status_code == 422  # 종류가 다름
    new = upload(api, kind="license", content=JPEG, name="새 등록증.jpg").json()["id"]
    r = api.post(resubmit, json={"license_file_id": new})
    assert r.status_code == 200, r.text
    assert r.json()["license"]["filename"] == "새 등록증.jpg"
    assert api.get(f"/files/{old}").status_code == 404  # 예전 등록증은 지웠다
    assert query("select count(*) n from files where id = $1", old)[0]["n"] == 0
    (h,) = query("select changes from vendor_reviews where action = 'resubmit'")
    assert json.loads(h["changes"]) == {"file": "사업자등록증.pdf"}
    assert other_token


def test_reject_then_reapply_with_same_number(api):
    token, vid = applied(api)
    biz_no = query("select biz_no from vendors")[0]["biz_no"]
    make_admin(api)
    assert decide(api, vid, "reject", code="closed").status_code == 200
    assert notes(vid)[0]["body"] == "관리자가 이번 신청을 거절했어요."

    use(api, token)
    me = api.get("/me").json()
    assert me["vendor_status"] == "rejected" and me["vendor_review_code"] == "closed"
    assert me["vendor_reject_reason"] is None  # 보낼 말 없이 거절
    assert api.post(f"{APP}/resubmit", json={"license_file_id": None}).status_code == 409
    form = {
        "biz_name": "다온인테리어",
        "owner_name": "예시 대표",
        "phone": "010-1234-5678",
        "trades": ["dobae", "mokgong"],
        "areas": [{"sido": "seoul", "sgg": "노원구"}, {"sido": "seoul", "sgg": "도봉구"}],
    }
    # v3(VS02): 다시 신청에서 번호를 고칠 수 있어 10자리는 받는다. 형식이 틀린 번호만 422
    assert api.post(f"{APP}/reapply", json={**form, "biz_no": "111-222"}).status_code == 422
    bad = api.post(f"{APP}/reapply", json={**form, "areas": [{"sido": "seoul", "sgg": "없는구"}]})
    assert bad.json()["error"]["code"] == "region"
    r = api.post(f"{APP}/reapply", json=form)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["trades"] == ["dobae", "mokgong"]
    assert r.json()["biz_no"] == biz_no  # 같은 번호
    assert api.post(f"{APP}/reapply", json=form).status_code == 409
    (h,) = query("select changes from vendor_reviews where action = 'reapply'")
    assert json.loads(h["changes"]) == {"biz_name": "예시도배", "trades": ["dobae"]}


def test_review_codes_and_notes_are_checked(api):
    _, vid = applied(api)
    make_admin(api)

    def code(action: str, **body) -> int:
        return decide(api, vid, action, **body).status_code

    assert code("approve", code="blurry") == 422  # 승인에는 사유가 없다
    assert code("approve", note="좋아요") == 422
    assert code("needs_info") == 422
    assert code("needs_info", code="closed") == 422  # 거절 사유
    assert code("reject", code="blurry") == 422  # 보완 사유
    assert code("reject", code="other") == 422  # 직접 쓰기는 보낼 말 필수
    assert code("reject", code="other", note="   ") == 422
    assert code("reject", code="wrong_business", note="가" * 301) == 422
    assert code("hold") == 422
    r = decide(api, vid, "approve", opened_on="2999-01-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "opened_on"
    assert decide(api, str(uuid.uuid4()), "approve").status_code == 404
    assert query("select status from vendors")[0]["status"] == "pending"  # 아무것도 안 바뀌었다
    ok = decide(api, vid, "reject", code="other", note="업종이 달라요")
    assert ok.status_code == 200 and ok.json()["review_note"] == "업종이 달라요"


def test_only_allowed_transitions(api):
    token, vid = applied(api)
    make_admin(api)
    assert decide(api, vid, "needs_info", code="blurry").status_code == 200
    for action, body in (("approve", {}), ("reject", {"code": "closed"})):
        assert decide(api, vid, action, **body).status_code == 409  # 업체가 다시 낼 차례
    use(api, token)
    assert api.post(f"{APP}/reapply", json={}).status_code == 422  # 칸 검사가 먼저
    form = {
        "biz_name": "a",
        "owner_name": "b",
        "phone": "01012345678",
        "trades": ["dobae"],
        "areas": [{"sido": "seoul", "sgg": "노원구"}],
    }
    assert api.post(f"{APP}/reapply", json=form).status_code == 409  # 거절이 아니다
    query("update vendors set status = 'pending', review_code = null, review_note = null")
    assert api.post(f"{APP}/resubmit", json={}).status_code == 409  # 심사 중
    assert api.post(f"{APP}/reapply", json=form).status_code == 409
    make_admin(api, "admin2@mitjip.test")
    assert decide(api, vid, "reject", code="wrong_business").status_code == 200
    assert decide(api, vid, "approve").status_code == 409  # 거절한 뒤에는 다시 신청해야 한다
    use(api, token)
    assert api.post(f"{APP}/reapply", json=form).status_code == 200
    make_admin(api, "admin3@mitjip.test")
    assert decide(api, vid, "approve").status_code == 200
    use(api, token)
    assert api.post(f"{APP}/reapply", json=form).status_code == 409  # 승인된 뒤
    assert api.post(f"{APP}/resubmit", json={}).status_code == 409


def test_two_admins_deciding_at_once_only_one_wins(api):
    _, vid = applied(api)
    make_admin(api, "a1@mitjip.test")
    make_admin(api, "a2@mitjip.test")
    admins = [r["id"] for r in query("select id from users where role = 'admin' order by email")]

    async def decide_as(admin_id, data: ReviewIn):
        async with SessionLocal() as s:
            admin = await s.get(User, admin_id)
            return await service.review(s, admin, uuid.UUID(vid), data, today_seoul())

    async def both():
        return await asyncio.gather(
            decide_as(admins[0], ReviewIn(action="approve")),
            decide_as(admins[1], ReviewIn(action="reject", code="closed")),
            return_exceptions=True,
        )

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    decisions = query("select action from vendor_reviews where action <> 'apply'")
    assert len(decisions) == 1 and len(notes(vid)) == 1  # 이력 · 알림도 한 번만


def test_list_order_search_and_permissions(api):
    ids = {}
    for i, (email, name) in enumerate(
        (
            ("a@mitjip.test", "그린홈인테리어"),
            ("b@mitjip.test", "한빛도배"),
            ("c@mitjip.test", "늘봄목공"),
        )
    ):
        _, ids[email] = applied(api, email, biz_name=name)
        query(
            "update vendor_reviews set at = now() - make_interval(days => $1) where vendor_id = $2",
            3 - i,
            uuid.UUID(ids[email]),
        )
    vendor_token = api.cookies.get(settings.session_cookie)
    assert api.get("/admin/vendors").status_code == 403  # 업체
    assert api.get("/admin/vendors/summary").status_code == 403
    assert decide(api, ids["a@mitjip.test"], "approve").status_code == 403
    signup(api, "customer@mitjip.test")
    assert api.get(APP).status_code == 403  # 고객
    assert api.post(f"{APP}/resubmit", json={}).status_code == 403
    assert decide(api, ids["a@mitjip.test"], "approve").status_code == 403
    api.cookies.clear()
    assert api.get(APP).status_code == 401

    make_admin(api)
    assert api.get(APP).status_code == 403  # 관리자는 업체 신청이 없다
    got = api.get("/admin/vendors", params={"status": "pending"}).json()
    assert [(v["biz_name"], v["waiting_days"]) for v in got] == [
        ("그린홈인테리어", 3),
        ("한빛도배", 2),
        ("늘봄목공", 1),
    ]
    assert [v["biz_name"] for v in api.get("/admin/vendors", params={"q": "도배"}).json()] == [
        "한빛도배"
    ]
    no = query("select biz_no from vendors where biz_name = '늘봄목공'")[0]["biz_no"]
    hyphen = f"{no[:3]}-{no[3:5]}-{no[5:]}"
    assert [v["biz_name"] for v in api.get("/admin/vendors", params={"q": hyphen}).json()] == [
        "늘봄목공"
    ]
    assert api.get("/admin/vendors", params={"q": "%"}).json() == []  # 와일드카드로 안 읽는다
    decide(api, ids["b@mitjip.test"], "approve")
    decide(api, ids["c@mitjip.test"], "reject", code="closed")
    done = api.get("/admin/vendors", params={"status": "done"}).json()
    assert [v["biz_name"] for v in done] == ["늘봄목공", "한빛도배"]  # 최근에 정한 순
    assert api.get("/admin/vendors", params={"status": "approved"}).status_code == 422
    assert api.get("/admin/vendors/summary").json() == {"pending": 1, "needs_info": 0, "done": 2}
    assert vendor_token


@pytest.mark.parametrize(
    "sql",
    [
        "update vendors set status = 'needs_info'",  # 사유 코드 없음
        "update vendors set review_code = 'blurry'",  # 심사 중인데 코드
        "update vendors set status = 'needs_info', review_code = 'closed'",
        "update vendors set status = 'rejected', review_code = 'blurry'",
        "update vendors set status = 'rejected', review_code = 'other'",  # 보낼 말 없음
        "update vendors set status = 'rejected', review_code = 'closed', review_note = '  '",
        "update vendors set status = 'approved'",  # 승인 시각 없음
        "update vendors set approved_at = now()",  # 심사 중인데 승인 시각
        ROW.format(action="'needs_info'", code="null", changes="null"),  # 보완인데 코드 없음
        ROW.format(action="'approve'", code="'blurry'", changes="null"),
        ROW.format(action="'reject'", code="'blurry'", changes="null"),
        ROW.format(action="'reject'", code="'other'", changes="null"),  # 보낼 말 없음
        ROW.format(action="'apply'", code="null", changes="'{}'"),  # 처음 신청에는 바뀐 칸이 없다
        "update vendor_reviews set action = 'hold'",
    ],
)
def test_db_checks(api, sql):
    applied(api)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query(sql)


def test_migration_down_and_up_keeps_decisions(api):
    from alembic import command
    from alembic.config import Config

    from tests.conftest import BACKEND

    _, a = applied(api, "a@mitjip.test")
    _, b = applied(api, "b@mitjip.test")
    _, c = applied(api, "c@mitjip.test")
    make_admin(api)
    decide(api, a, "needs_info", code="blurry")
    decide(api, b, "reject", code="closed")
    decide(api, c, "approve")
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    try:
        command.downgrade(cfg, "0008_v2_vendor_price")
        rows = query("select user_id, status, reject_reason from vendors")
        old = {str(r["user_id"]): (r["status"], r["reject_reason"]) for r in rows}
        assert old == {
            a: ("pending", None),  # 보완 요청은 예전 상태에 없다
            b: ("rejected", "휴업 · 폐업 상태예요"),
            c: ("approved", None),
        }
    finally:
        command.upgrade(cfg, "head")
    rows = query("select user_id, status, review_code, approved_at from vendors")
    new = {
        str(r["user_id"]): (r["status"], r["review_code"], r["approved_at"] is not None)
        for r in rows
    }
    assert new == {
        a: ("pending", None, False),
        b: ("rejected", "other", False),
        c: ("approved", None, True),
    }
    actions = query("select action from vendor_reviews order by action")
    assert [r["action"] for r in actions] == ["apply", "apply", "apply", "approve", "reject"]
