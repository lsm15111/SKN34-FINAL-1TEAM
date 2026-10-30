from pathlib import Path

from app.config import settings
from tests.conftest import query
from tests.helpers import PASSWORD, make_admin, signup, upload, use, vendor_signup
from tests.test_project import body


def stored(storage_key: str) -> Path:
    return Path(settings.files_dir) / storage_key


def test_customer_withdraws_even_with_a_project(api):
    signup(api)
    photo = upload(api).json()["id"]
    assert api.post("/projects", json=body([photo])).status_code == 201
    (f,) = query("select storage_key from files")
    assert stored(f["storage_key"]).exists()

    r = api.post("/me/withdraw", json={"password": PASSWORD})
    assert r.status_code == 204
    assert api.get("/me").status_code == 401  # 쿠키가 지워졌고 세션도 없다
    counts = query(
        "select (select count(*) from users) u, (select count(*) from projects) p,"
        " (select count(*) from files) f, (select count(*) from user_sessions) s"
    )[0]
    assert dict(counts) == {"u": 0, "p": 0, "f": 0, "s": 0}
    assert not stored(f["storage_key"]).exists()  # 디스크의 사진도 지웠다


def test_wrong_password_keeps_everything(api):
    signup(api)
    r = api.post("/me/withdraw", json={"password": "wrong-password-0"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_password"
    assert api.get("/me").status_code == 200
    assert query("select count(*) n from users")[0]["n"] == 1


def test_vendor_withdraws_and_license_is_removed(api):
    vendor_signup(api)
    (f,) = query("select storage_key from files")
    assert api.post("/me/withdraw", json={"password": PASSWORD}).status_code == 204
    assert query("select count(*) n from vendors")[0]["n"] == 0
    assert not stored(f["storage_key"]).exists()


def test_admin_cannot_withdraw_here_and_login_is_needed(api):
    token = make_admin(api)
    assert (
        api.post("/me/withdraw", json={"password": PASSWORD}).json()["error"]["code"]
        == "admin_withdraw"
    )
    api.cookies.clear()
    assert api.post("/me/withdraw", json={"password": PASSWORD}).status_code == 401
    use(api, token)
    assert api.get("/me").status_code == 200
