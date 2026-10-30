"""요청 입구 보호 · 오류 모양 · 연결 확인 (기능이 없어도 지켜야 하는 것)"""

from app import main
from app.config import settings
from tests.conftest import query


def test_big_body_is_refused_before_reading(api):
    r = api.post(
        "/anything",
        content=b"{" + b" " * (1024 * 1024 + 10) + b"}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_framework_errors_use_the_same_shape(api):
    nf = api.get("/no-such-path")
    assert nf.status_code == 404 and nf.json()["error"]["code"] == "not_found"
    na = api.post("/health/live")
    assert na.status_code == 405 and na.json()["error"]["code"] == "method_not_allowed"


def test_other_site_cannot_change_state(api):
    r = api.post("/health/live", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"
    assert "https://evil.example" not in settings.origins


def test_unexpected_errors_are_500_with_the_same_shape(api, monkeypatch):
    async def boom() -> None:
        raise RuntimeError("내부 값")

    monkeypatch.setattr(main.db, "ping", boom)
    r = api.get("/health/ready")
    assert r.status_code == 500 and r.json() == {
        "error": {"code": "server_error", "message": "잠시 문제가 생겼어요. 다시 해 주세요."}
    }


def test_real_db_and_redis_are_ready(api):
    r = api.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"db": "ok", "redis": "ok"}
    assert len(query("select version_num from alembic_version")) == 1  # migration이 올라가 있다
