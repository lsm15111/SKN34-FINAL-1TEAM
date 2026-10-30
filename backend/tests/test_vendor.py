from app.config import settings
from tests.conftest import query
from tests.helpers import JPEG, PASSWORD, make_admin, signup, use, vendor_signup


def test_vendor_signs_up_with_license_only_and_waits(api):
    r = vendor_signup(api)
    assert r.status_code == 201, r.text
    me = r.json()
    assert (
        me["role"] == "vendor" and me["vendor_status"] == "pending" and me["name"] == "예시 담당자"
    )
    assert api.get("/me").json()["vendor_status"] == "pending"


def test_signup_checks_input_and_license(api):
    assert vendor_signup(api, license=None).status_code == 422  # 사업자등록증 없음
    short = vendor_signup(api, password="short")
    assert short.status_code == 422 and short.json()["error"]["fields"][0]["loc"] == ["password"]
    assert vendor_signup(api, license=("a.txt", b"not a license")).status_code == 415
    assert vendor_signup(api, license=("등록증.jpg", JPEG)).status_code == 201  # 사진도 된다
    again = vendor_signup(api)
    assert again.status_code == 409 and again.json()["error"]["code"] == "email_taken"


def test_admin_approves_then_rejects(api):
    vendor_signup(api)
    vendor_token = api.cookies.get(settings.session_cookie)
    make_admin(api)
    pending = api.get("/admin/vendors", params={"status": "pending"}).json()
    assert [(v["name"], v["biz_name"]) for v in pending] == [("예시 담당자", None)]
    vid = pending[0]["user_id"]

    ok = api.post(f"/admin/vendors/{vid}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert api.post(f"/admin/vendors/{vid}/approve").status_code == 409
    assert api.post(f"/admin/vendors/{vid}/reject", json={"reason": ""}).status_code == 422
    rej = api.post(f"/admin/vendors/{vid}/reject", json={"reason": "사업자등록증이 흐려요"})
    assert rej.json()["status"] == "rejected"

    use(api, vendor_token)
    me = api.get("/me").json()
    assert (
        me["vendor_status"] == "rejected" and me["vendor_reject_reason"] == "사업자등록증이 흐려요"
    )


def test_only_admin_sees_vendor_applications(api):
    signup(api, "c@mitjip.test")
    assert api.get("/admin/vendors").status_code == 403
    api.cookies.clear()
    assert api.get("/admin/vendors").status_code == 401


def test_license_file_is_private(api):
    vendor_signup(api)
    vendor_token = api.cookies.get(settings.session_cookie)
    make_admin(api)
    lic = api.get("/admin/vendors").json()[0]["license_file_id"]
    assert api.get(f"/files/{lic}").status_code == 200  # 관리자
    use(api, vendor_token)
    assert api.get(f"/files/{lic}").status_code == 200  # 그 업체
    signup(api, "stranger@mitjip.test")
    assert api.get(f"/files/{lic}").status_code == 404  # 다른 회원은 있는지도 모른다
    assert PASSWORD


def test_removing_the_reviewing_admin_keeps_the_approval(api):
    vendor_signup(api)
    make_admin(api)
    vid = api.get("/admin/vendors").json()[0]["user_id"]
    api.post(f"/admin/vendors/{vid}/approve")
    query("delete from users where role = 'admin'")
    (row,) = query("select status, reviewed_by from vendors")
    assert row["status"] == "approved" and row["reviewed_by"] is None
