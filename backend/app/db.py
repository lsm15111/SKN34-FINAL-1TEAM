from collections.abc import AsyncIterator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

# 제약 이름 규칙. migration에서 제약을 이름으로 다시 찾을 수 있게 첫 테이블 전에 정한다
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 테스트는 요청마다 이벤트 루프가 달라질 수 있어 연결을 재사용하지 않는다
# hide_parameters: 오류 메시지 · 로그에 SQL 값(이메일 · 이름 · 해시)을 넣지 않는다.
# 연결 수: 프로세스 하나에 최대 10개. uvicorn worker 수 × 10이 PostgreSQL max_connections(기본 100)보다 작아야 한다.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    **(
        {"poolclass": NullPool}
        if settings.app_env == "test"
        else {"pool_size": 5, "max_overflow": 5, "pool_timeout": 10}
    ),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """모든 테이블 모델의 부모. Alembic autogenerate가 이 metadata를 읽는다."""

    metadata = MetaData(naming_convention=NAMING)


async def get_session() -> AsyncIterator[AsyncSession]:
    """요청 하나에 DB 세션 하나. 같은 요청 안의 의존성은 이 세션을 같이 쓴다."""
    async with SessionLocal() as session:
        yield session


async def ping() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
