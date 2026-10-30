"""테스트 준비. 로컬 Docker의 PostgreSQL · Redis를 쓴다 (`docker compose up -d db redis`).

- 테스트 전용 DB(mitjip_test)를 매번 새로 만들고 Alembic으로 올린다. 개발 DB(mitjip)는 건드리지 않는다.
- 테스트마다 모든 표를 비우고(표 목록을 손으로 적지 않는다) Redis 15번 DB를 비운다.
- 접속 정보는 환경변수 또는 저장소 루트의 .env에서 읽는다 (화면에 찍지 않는다).
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def _dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


_env = _dotenv()


def _get(k: str, default: str = "") -> str:
    return os.environ.get(k) or _env.get(k, default)


_user, _pw = _get("POSTGRES_USER", "mitjip"), _get("POSTGRES_PASSWORD")
# Windows에서 localhost는 IPv6(::1)를 먼저 시도해 연결마다 2초씩 늦어진다. Docker 포트는 127.0.0.1에만 열려 있다
_host, _port = os.environ.get("TEST_DB_HOST", "127.0.0.1"), _get("DB_HOST_PORT", "5433")
TEST_DB = "mitjip_test"
ADMIN_DSN = f"postgresql://{_user}:{_pw}@{_host}:{_port}/postgres"
TEST_DSN = f"postgresql://{_user}:{_pw}@{_host}:{_port}/{TEST_DB}"
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
FILES_DIR = tempfile.mkdtemp(prefix="mitjip-files-")

# app을 불러오기 전에 설정을 테스트용으로 바꾼다
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"postgresql+asyncpg://{_user}:{_pw}@{_host}:{_port}/{TEST_DB}",
        "REDIS_URL": REDIS_URL,
        "FILES_DIR": FILES_DIR,
    }
)


async def _recreate_db() -> None:
    import asyncpg

    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        await conn.close()


async def _truncate() -> None:
    import asyncpg

    conn = await asyncpg.connect(TEST_DSN)
    try:
        rows = await conn.fetch(
            "select tablename from pg_tables"
            " where schemaname = 'public' and tablename <> 'alembic_version'"
        )
        if rows:
            names = ", ".join(f'"{r["tablename"]}"' for r in rows)
            await conn.execute(f"TRUNCATE {names} CASCADE")
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _database():
    from alembic import command
    from alembic.config import Config

    asyncio.run(_recreate_db())
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")  # 되돌리기도 되는지 본다
    command.upgrade(cfg, "head")
    yield
    shutil.rmtree(FILES_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean():
    import redis

    asyncio.run(_truncate())
    redis.Redis.from_url(REDIS_URL).flushdb()
    yield


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    # 이벤트 루프 하나로 모든 요청을 돌린다 (Redis 연결을 루프 사이에 섞지 않게)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def api(client):
    client.cookies.clear()
    return client


def query(sql: str, *args):
    """테스트에서 DB를 직접 들여다본다."""
    import asyncpg

    async def run():
        conn = await asyncpg.connect(TEST_DSN)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())
