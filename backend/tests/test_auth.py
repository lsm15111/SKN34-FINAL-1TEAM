from app.config import settings
from tests.conftest import query
from tests.helpers import PASSWORD, signup


def test_signup_logs_in_and_stores_only_a_hash(api):
    r = api.post(
        "/auth/signup", json={"name": "  고객  ", "email": "New@Mitjip.Test", "password": PASSWORD}
    )
    assert r.status_code == 201
    assert r.json()["email"] == "new@mitjip.test"
    assert r.json()["name"] == "고객"
    cookie = r.headers["set-cookie"]
    assert settings.session_cookie in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert api.get("/me").json()["role"] == "customer"
    (row,) = query("select password_hash from users where email = $1", "new@mitjip.test")
    assert row["password_hash"].startswith("$argon2id$") and PASSWORD not in row["password_hash"]
    (sess,) = query("select id from user_sessions")
    assert sess["id"] != api.cookies.get(settings.session_cookie)  # DB에는 토큰 원문이 없다


def test_same_email_cannot_sign_up_twice(api):
    signup(api, "dup@mitjip.test")
    api.cookies.clear()
    r = api.post(
        "/auth/signup", json={"name": "또", "email": "DUP@mitjip.test", "password": PASSWORD}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_short_password_uses_the_common_error_shape(api):
    r = api.post(
        "/auth/signup", json={"name": "고객", "email": "a@mitjip.test", "password": "short"}
    )
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "invalid" and body["fields"][0]["loc"] == ["password"]
    assert "short" not in r.text  # 입력값을 되돌려 보내지 않는다


def test_login_logout(api):
    signup(api, "me@mitjip.test")
    api.cookies.clear()
    wrong = api.post("/auth/login", json={"email": "me@mitjip.test", "password": "wrong-pass"})
    nobody = api.post("/auth/login", json={"email": "nobody@mitjip.test", "password": PASSWORD})
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json() == nobody.json()  # 있는 계정인지 알려 주지 않는다
    ok = api.post("/auth/login", json={"email": "ME@mitjip.test", "password": PASSWORD})
    assert ok.status_code == 200
    assert api.get("/me").status_code == 200
    assert api.post("/auth/logout").status_code == 204
    assert api.get("/me").status_code == 401


def test_too_many_failed_logins_are_blocked(api):
    signup(api, "slow@mitjip.test")
    api.cookies.clear()
    for _ in range(10):
        api.post("/auth/login", json={"email": "slow@mitjip.test", "password": "wrong-pass"})
    r = api.post("/auth/login", json={"email": "slow@mitjip.test", "password": PASSWORD})
    assert r.status_code == 429


def test_requests_from_other_sites_are_refused(api):
    evil = api.post(
        "/auth/login",
        json={"email": "a@b.cd", "password": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert evil.status_code == 403 and evil.json()["error"]["code"] == "bad_origin"
    ours = api.post(
        "/auth/login",
        json={"email": "a@b.cd", "password": "x"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert ours.status_code == 401


def test_change_my_name(api):
    signup(api, "rename@mitjip.test")
    r = api.patch("/me", json={"name": "새 이름"})
    assert r.status_code == 200 and r.json()["name"] == "새 이름"
    assert api.patch("/me", json={"name": "   "}).status_code == 422
