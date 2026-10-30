import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserSession


async def user_by_email(s: AsyncSession, email: str) -> User | None:
    return (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def user_by_id(s: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await s.get(User, user_id)


async def session_with_user(s: AsyncSession, sid: str) -> tuple[UserSession, User] | None:
    row = (
        await s.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.id == sid)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def delete_session(s: AsyncSession, sid: str) -> None:
    await s.execute(delete(UserSession).where(UserSession.id == sid))


async def touch_session(s: AsyncSession, sid: str, at: datetime) -> None:
    await s.execute(update(UserSession).where(UserSession.id == sid).values(last_seen_at=at))


async def delete_user(s: AsyncSession, user_id: uuid.UUID) -> None:
    await s.execute(delete(User).where(User.id == user_id))
