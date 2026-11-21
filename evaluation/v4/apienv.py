"""v4 평가 러너(시뮬레이터 · 레드팀)가 같이 쓰는 앱 준비: 시험 DB · Redis · ASGI 클라이언트 · 무료 · LLM 모드.

- DB · Redis 접속값만 .env에서 읽어요(POSTGRES_USER · POSTGRES_PASSWORD · DB_HOST_PORT · REDIS_HOST_PORT).
  LLM 키 · LLM_LIVE는 읽지 않아요. 무료 모드는 키 환경변수를 이 프로세스에서 비우고 LLM_LIVE=false로 둬요.
- LLM 모드(--live)는 부르는 쪽 환경변수(LLM_LIVE=true · ANTHROPIC_API_KEY)를 그대로 쓰고, 다른 유료 키는 비우고
  Jev는 꺼요(live_mode). 비용은 판마다 장부(llm_usage)로 세요(sim/drive.usage).
- 판마다 새로 가입하니 두 모드 모두 새 계정 몫(LLM_NEW_USER_DAYS=0)을 꺼요. 상한 동작은 백엔드 시험이 지켜요.
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
NEW_USER_DAYS = "0"  # 새 계정 몫(usage, 가입 7일 안 고객) 끔: 판마다 새로 가입해요


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
    os.environ["LLM_NEW_USER_DAYS"] = NEW_USER_DAYS
    for k in KEY_ENVS:
        os.environ[k] = ""


LIVE_OFF = ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "VOYAGE_API_KEY")  # LLM 모드에서도 비우는 키


def live_mode() -> None:
    """LLM 모드(유료): 환경변수에 LLM_LIVE=true와 ANTHROPIC_API_KEY가 있어야 해요(키 값은 찍지 않아요).
    Claude 말고 다른 유료 키(OpenAI · OpenRouter · Voyage)는 비우고 Jev는 꺼요. 앱을 불러오기 전에 불러요."""
    if os.environ.get("LLM_LIVE", "").strip().lower() != "true":
        raise SystemExit("LLM 모드에는 환경변수 LLM_LIVE=true가 필요해요.")
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit("LLM 모드에는 환경변수 ANTHROPIC_API_KEY가 필요해요.")
    for k in LIVE_OFF:
        os.environ[k] = ""
    os.environ["JEV_ENABLED"] = "false"
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ["LLM_NEW_USER_DAYS"] = NEW_USER_DAYS


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
        """시험 DB에는 지식이 없어 저장소 색인을 넘겨요. index뿐 아니라 _index(search · 인용 확인 · 이어 묻기)도
        바꿔요(전에는 index만 바꿔 LLM 모드 search_knowledge가 늘 0건이었어요). 임베딩은 부르지 않아요."""
        from v3_kb import repo_index

        from app.agent import llm
        from app.knowledge import service as knowledge

        ix = repo_index()

        async def index(_s):
            return ix

        async def _index(_s):
            return ix, []

        async def no_embed(_texts):
            return None

        knowledge.index = index
        knowledge._index = _index
        llm.embed_texts = no_embed

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

    def call(self, fn, *args, **kw):
        """앱과 같은 이벤트 루프에서 async 함수를 돌려요(worker 일 · 정리). 백엔드 시험의 api.portal.call과 같아요."""
        from functools import partial

        return self._tc.portal.call(partial(fn, *args, **kw))

    def refs(self, chat_id: str | None) -> dict:
        """대화 이름표 표(Redis assistant:refs:{chat_id}, runtime.RefTable). 없으면 {}."""
        import json

        import redis

        if not chat_id:
            return {}
        raw = redis.Redis.from_url(os.environ["TEST_REDIS_URL"]).get(f"assistant:refs:{chat_id}")
        try:
            got = json.loads(raw) if raw else {}
        except ValueError:
            return {}
        return got if isinstance(got, dict) else {}

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


def live_settings() -> dict:
    """LLM 모드 meta에 남길 설정(모델 · effort · 상한 · Jev, 키 없음)."""
    from app.config import settings

    return {
        "model": settings.llm_claude_model,
        "effort": settings.llm_claude_effort,
        "light_model": settings.llm_claude_light_model,
        "light_effort": settings.llm_claude_light_effort,
        "cap_turn_usd": settings.llm_cap_turn_usd,
        "cap_user_day_usd": settings.llm_cap_user_day_usd,
        "cap_new_user_day_usd": settings.llm_cap_new_user_day_usd,
        "cap_new_pool_day_usd": settings.llm_cap_new_pool_day_usd,
        "new_user_days": settings.llm_new_user_days,
        "cap_service_day_usd": settings.llm_cap_service_day_usd,
        "jev_enabled": settings.jev_enabled,
    }
