"""요청 입구 보호 · 오류 모양 · 동시 요청 · 요청 제한 (API 점검에서 나온 항목)"""

from pathlib import Path

from sqlalchemy.exc import OperationalError

from app.auth import repository as auth_repo
from app.config import settings
from app.project import service as project_service
from tests.conftest import query
from tests.helpers import PASSWORD, make_admin, signup, upload, vendor_signup
from tests.test_project import body


def test_big_body_is_refused_before_reading(api):
    big = api.post(
        "/auth/login",
        content=b"{" + b" " * (1024 * 1024 + 10) + b"}",
        headers={"content-type": "application/json"},
    )
    assert big.status_code == 413 and big.json()["error"]["code"] == "too_large"
    signup(api)
    huge = upload(api, content=b"\xff\xd8\xff" + b"\x00" * (22 * 1024 * 1024))
    assert huge.status_code == 413 and huge.json()["error"]["code"] == "too_large"


def test_framework_errors_use_the_same_shape(api):
    nf = api.get("/no-such-path")
    assert nf.status_code == 404 and nf.json()["error"]["code"] == "not_found"
    signup(api)
    na = api.delete("/me")
    assert na.status_code == 405 and na.json()["error"]["code"] == "method_not_allowed"


def test_unexpected_errors_are_500_and_db_down_is_503(api, monkeypatch):
    signup(api)

    async def boom(*_a, **_k):
        raise RuntimeError("내부 값 customer@mitjip.test")

    monkeypatch.setattr(project_service, "list_mine", boom)
    r = api.get("/projects")
    assert r.status_code == 500 and r.json() == {
        "error": {"code": "server_error", "message": "잠시 문제가 생겼어요. 다시 해 주세요."}
    }

    async def db_down(*_a, **_k):
        raise OperationalError("select 1", {}, ConnectionRefusedError())

    monkeypatch.setattr(project_service, "list_mine", db_down)
    assert api.get("/projects").json()["error"]["code"] == "unavailable"


def test_same_email_at_the_same_time_is_409_not_500(api, monkeypatch):
    signup(api, "twice@mitjip.test")

    async def not_found(*_a, **_k):  # 먼저 확인할 때는 없었던 것처럼 (동시에 두 번 누른 경우)
        return None

    monkeypatch.setattr(auth_repo, "user_by_email", not_found)
    api.cookies.clear()
    r = api.post(
        "/auth/signup", json={"name": "고객", "email": "twice@mitjip.test", "password": PASSWORD}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_signups_from_one_place_are_limited(api):
    for i in range(10):
        signup(api, f"many{i}@mitjip.test")
    api.cookies.clear()
    r = api.post(
        "/auth/signup", json={"name": "고객", "email": "many10@mitjip.test", "password": PASSWORD}
    )
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_failed_vendor_signup_leaves_no_license_file(api):
    vendor_signup(api)
    again = vendor_signup(api)  # 같은 이메일 → 409, 두 번째 등록증은 남기지 않는다
    assert again.status_code == 409
    assert query("select count(*) n from files")[0]["n"] == 1
    on_disk = [p for p in Path(settings.files_dir).rglob("*") if p.is_file()]
    stored = {r["storage_key"] for r in query("select storage_key from files")}
    assert {str(p.relative_to(settings.files_dir)).replace("\\", "/") for p in on_disk} >= stored


def test_blank_reject_reason_is_refused(api):
    vendor_signup(api)
    make_admin(api)
    vid = api.get("/admin/vendors").json()[0]["user_id"]
    r = api.post(f"/admin/vendors/{vid}/reject", json={"reason": "   "})
    assert r.status_code == 422


def test_file_missing_on_disk_is_404(api):
    signup(api)
    fid = upload(api).json()["id"]
    (row,) = query("select storage_key from files")
    (Path(settings.files_dir) / row["storage_key"]).unlink()
    r = api.get(f"/files/{fid}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_unknown_kind_and_far_dates(api):
    signup(api)
    assert upload(api, kind="selfie").json()["error"]["code"] == "file_kind"
    far = api.post("/projects", json=body(when={"kind": "date", "start": "2999-01-01"}))
    assert far.status_code == 422 and far.json()["error"]["code"] == "far_date"


def test_other_site_cannot_change_state(api):
    r = api.post("/auth/login", headers={"origin": "https://evil.example"}, json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
    assert "https://evil.example" not in settings.origins


def test_real_db_and_redis_are_ready(api):
    r = api.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"db": "ok", "redis": "ok"}
    assert len(query("select version_num from alembic_version")) == 1  # migration이 올라가 있다
