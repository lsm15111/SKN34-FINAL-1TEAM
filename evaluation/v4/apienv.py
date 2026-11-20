"""v4 평가 러너(시뮬레이터 · 레드팀)가 같이 쓰는 앱 준비: 시험 DB · Redis · ASGI 클라이언트 · 무료 모드.

- DB · Redis 접속값만 .env에서 읽어요(POSTGRES_USER · POSTGRES_PASSWORD · DB_HOST_PORT · REDIS_HOST_PORT).
  LLM 키 · LLM_LIVE는 읽지 않아요. 무료 모드는 키 환경변수를 이 프로세스에서 비우고 LLM_LIVE=false로 둬요.
- 시험 DB는 따로 써요(기본 mitjip_eval_sim · Redis 12번). 백엔드 pytest(mitjip_test · 15번)와 섞이지 않아요.
- 앱은 backend/tests/conftest.py와 같은 방법으로 올려요: DB 새로 만들기 → Alembic head → 판마다 표 비우기.
- 시험 DB에는 지식 자료가 없어서, 백엔드 시험처럼 저장소 CSV 색인(tests/v3_kb.repo_index)을 넘겨요.
- ToolTap: 비서 도구 입력(args)을 턴마다 모아요(누출 확인용). 운영 코드는 바꾸지 않고 이 프로세스에서만 감싸요.
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"

KEY_ENVS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY")
DB_KEYS = ("POSTGRES_USER", "POSTGRES_PASSWORD", "DB_HOST_PORT", "REDIS_HOST_PORT")


def env_files() -> list[Path]:
    """DB 접속값을 찾을 .env 후보: 이 체크아웃 → 메인 체크아웃(worktree에는 .env가 없어요)."""
    return [ROOT / ".env", ROOT.parent / "SKN34-FINAL-1TEAM" / ".env"]


def load_db_env(path: Path | None = None) -> Path | None:
    """DB · Redis 접속값만 환경변수로 올려요(이미 있으면 그대로). 읽은 파일을 돌려줘요(값은 찍지 않아요)."""
    for p in [path] if path else env_files():
        if p is None or not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = (x.strip() for x in line.split("=", 1))
            if k in DB_KEYS and v and not os.environ.get(k):
                os.environ[k] = v
        return p
    return None


def free_mode() -> None:
    """유료 호출 0회: LLM_LIVE=false, 키 환경변수 비움(설정은 환경변수만 읽어요)."""
    os.environ["LLM_LIVE"] = "false"
    for k in KEY_ENVS:
        os.environ[k] = ""


class ToolTap:
    """비서 도구 호출 입력을 모아요. take(turn_id)로 그 턴 것만 가져가요."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def install(self) -> None:
        from app.assistant import tools as tools_mod

        real = tools_mod.run

        async def run(t, tc, args):
            self.rows.append(
                {
                    "turn_id": str(getattr(tc, "turn_id", "") or ""),
                    "name": getattr(t, "name", str(t)),
                    "args": args if isinstance(args, dict) else {},
                }
            )
            return await real(t, tc, args)

        tools_mod.run = run

    def take(self, turn_id: str | None = None) -> list[dict]:
        got = [r for r in self.rows if turn_id is None or r["turn_id"] == turn_id]
        self.rows = [r for r in self.rows if r not in got]
        return got


class App:
    """시험 DB를 만들고 앱을 ASGI(TestClient)로 올려요. reset()은 판마다 표 · Redis를 비워요."""

    def __init__(self, db_name: str, redis_db: int) -> None:
        if not db_name.startswith("mitjip_eval"):  # 개발 · 시험 DB를 지우지 않게
            raise SystemExit("평가 DB 이름은 mitjip_eval로 시작해야 해요.")
        self.db_name, self.redis_db = db_name, redis_db
        self.api = None
        self.tap = ToolTap()

    def boot(self) -> "App":
        port = os.environ.get("REDIS_HOST_PORT") or "6379"
        os.environ["TEST_DB_NAME"] = self.db_name
        os.environ["TEST_REDIS_URL"] = f"redis://127.0.0.1:{port}/{self.redis_db}"
        for p in (str(TESTS), str(BACKEND)):
            if p not in sys.path:
                sys.path.insert(0, p)
        import tests.conftest as cf  # 불러오면 APP_ENV=test · DATABASE_URL · REDIS_URL · FILES_DIR를 둬요

        self.cf = cf
        asyncio.run(cf._recreate_db())
        from alembic import command
        from alembic.config import Config

        cfg = (
            Config()
        )  # ini 없이: 마이그레이션 INFO 로그를 찍지 않아요(URL은 env.py가 설정에서 읽어요)
        cfg.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(cfg, "head")
        from fastapi.testclient import TestClient

        from app.main import app

        self._tc = TestClient(app)
        self.api = self._tc.__enter__()  # 이벤트 루프 하나로 모든 요청을 돌려요(백엔드 시험과 같음)
        self._patch_knowledge()
        self.tap.install()
        return self

    def _patch_knowledge(self) -> None:
        from v3_kb import repo_index

        from app.knowledge import service as knowledge

        ix = repo_index()

        async def index(_s):
            return ix

        knowledge.index = index

    def reset(self) -> None:
        import redis

        from app.agent import llm

        asyncio.run(self.cf._truncate())
        redis.Redis.from_url(os.environ["TEST_REDIS_URL"]).flushdb()
        llm.clear_stubs()
        self.api.cookies.clear()
        self.tap.rows.clear()

    def query(self, sql: str, *args):
        return self.cf.query(sql, *args)

    def close(self) -> None:
        if self.api is not None:
            try:
                self._tc.__exit__(None, None, None)
            except (
                RuntimeError
            ):  # 다른 이벤트 루프(asyncio.run)에서 쓴 Redis 연결은 닫을 때 이렇게 나요
                pass
            self.api = None
        shutil.rmtree(self.cf.FILES_DIR, ignore_errors=True)


def settings_mode() -> dict:
    """지금 앱 설정의 LLM 모드(값만, 키 없음)."""
    from app.agent import llm
    from app.config import settings

    return {
        "llm_live": bool(settings.llm_live),
        "provider": settings.llm_provider,
        "available": llm.available(),
    }
