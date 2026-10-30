from fastapi.testclient import TestClient

from app import main


def test_live_needs_nothing():
    res = TestClient(main.app).get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_ready_reports_which_part_failed(monkeypatch):
    async def down() -> None:
        raise ConnectionError("db down")

    async def up() -> None:
        return None

    monkeypatch.setattr(main.db, "ping", down)
    monkeypatch.setattr(main.queue, "ping", up)
    res = TestClient(main.app).get("/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["checks"]["db"] == "error: ConnectionError"
    assert body["checks"]["redis"] == "ok"


def test_ready_ok_when_all_up(monkeypatch):
    async def up() -> None:
        return None

    monkeypatch.setattr(main.db, "ping", up)
    monkeypatch.setattr(main.queue, "ping", up)
    res = TestClient(main.app).get("/health/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
