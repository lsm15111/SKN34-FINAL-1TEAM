"""회원가입 · 로그인 · 세션. 비밀번호는 argon2id 해시로만 저장한다.

argon2는 일부러 느리고(수십 ms) 메모리를 많이 쓴다(64MiB). 요청 처리 흐름(이벤트 루프)을 막지 않게
작업 스레드에서 돌리고, 한 번에 4개까지만 돌려 메모리를 묶는다. 차례는 이벤트 루프에서 기다려 기다리는 요청이
작업 스레드 자리(anyio 기본 40)를 쥐지 않게 한다.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repository as repo
from app.auth.models import User, UserSession
from app.auth.schemas import LoginIn, MeOut, MePatch, SignupIn
from app.config import settings
from app.shared import ratelimit
from app.shared.clock import now_utc
from app.shared.errors import AppError

log = logging.getLogger(__name__)
_hasher = PasswordHasher()  # 기본값이 OWASP 권장 범위의 argon2id
_HASH_SLOTS = anyio.CapacityLimiter(4)
# 없는 이메일로 로그인할 때도 같은 시간을 쓰게 하는 가짜 해시 (계정 있는지 알아내기 방지)
_DUMMY_HASH = _hasher.hash("mitjip-dummy-password")

WINDOW = 15 * 60  # 초
LOGIN_PER_EMAIL_IP = (
    10  # 같은 이메일 · 같은 IP: 다른 곳에서 남의 계정을 잠그지 못하게 IP를 함께 본다
)
LOGIN_PER_IP = 50  # 한 IP가 이메일을 바꿔 가며 시도하는 것
SIGNUP_PER_IP = 10  # 한 시간에
TOO_MANY = "여러 번 시도했어요. 잠시 뒤에 다시 해 주세요."
# 로그인 · 가입 한도는 Redis가 멈춰도 열리지 않게 프로세스 안에서 대신 센다 (security.md AU-03)
CLOSED: ratelimit.Fallback = "local"


def _sid(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_sync(password: str) -> str:
    return _hasher.hash(password)


def _verify_sync(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


async def _hash(password: str) -> str:
    return await anyio.to_thread.run_sync(_hash_sync, password, limiter=_HASH_SLOTS)


async def _verify(hashed: str, password: str) -> bool:
    return await anyio.to_thread.run_sync(_verify_sync, hashed, password, limiter=_HASH_SLOTS)


async def signup_limit(ip: str) -> None:
    await ratelimit.hit(ratelimit.key("signup", ip), SIGNUP_PER_IP, 3600, TOO_MANY, fallback=CLOSED)


async def create_user(
    s: AsyncSession, *, email: str, name: str, password: str, role: str, phone: str | None = None
) -> User:
    """회원 한 명을 만든다. 일반 · 업체 회원가입이 같이 쓴다. commit은 부르는 쪽이 한다.
    같은 이메일로 동시에 두 번 눌러도 DB 고유 제약이 막고, 그때도 409로 답한다."""
    if await repo.user_by_email(s, email):
        raise AppError(409, "email_taken", "이미 가입한 이메일이에요.")
    user = User(
        email=email,
        name=name,
        phone=phone,
        password_hash=await _hash(password),
        role=role,
    )
    s.add(user)
    try:
        await s.flush()
    except IntegrityError as exc:
        await s.rollback()
        raise AppError(409, "email_taken", "이미 가입한 이메일이에요.") from exc
    return user


async def start_session(s: AsyncSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    s.add(
        UserSession(
            id=_sid(token),
            user_id=user.id,
            expires_at=now_utc() + timedelta(days=settings.session_days),
        )
    )
    await s.flush()
    return token


async def signup_customer(s: AsyncSession, data: SignupIn, ip: str) -> tuple[User, str]:
    await signup_limit(ip)
    user = await create_user(
        s,
        email=data.email,
        name=data.name,
        password=data.password,
        role="customer",
        phone=data.phone,
    )
    token = await start_session(s, user)
    await s.commit()
    return user, token


async def _check_password(email: str, hashed: str | None, password: str, ip: str) -> bool:
    """시도 횟수를 먼저 센 뒤 비밀번호를 본다 (동시에 몰려도 한도를 넘지 못함)."""
    await ratelimit.hit(
        ratelimit.key("login-ip", ip), LOGIN_PER_IP, WINDOW, TOO_MANY, fallback=CLOSED
    )
    k = ratelimit.key("login", email, ip)
    await ratelimit.hit(k, LOGIN_PER_EMAIL_IP, WINDOW, TOO_MANY, fallback=CLOSED)
    ok = await _verify(hashed or _DUMMY_HASH, password)
    if ok and hashed:
        await ratelimit.reset(k)
    return ok and hashed is not None


async def login(s: AsyncSession, data: LoginIn, ip: str) -> tuple[User, str]:
    user = await repo.user_by_email(s, data.email)
    ok = await _check_password(data.email, user.password_hash if user else None, data.password, ip)
    if not ok or user is None:
        raise AppError(401, "bad_login", "이메일이나 비밀번호가 맞지 않아요.")
    if user.status != "active":
        raise AppError(403, "suspended", "사용이 정지된 계정이에요. 고객센터에 문의해 주세요.")
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = await _hash(data.password)
    token = await start_session(s, user)
    await s.commit()
    return user, token


async def confirm_password(user: User, password: str, ip: str) -> None:
    """탈퇴처럼 되돌릴 수 없는 일 전에 비밀번호를 다시 확인한다. 로그인과 같은 시도 제한을 쓴다."""
    if not await _check_password(user.email, user.password_hash, password, ip):
        raise AppError(403, "bad_password", "비밀번호가 맞지 않아요.")


async def delete_user(s: AsyncSession, user: User) -> None:
    """회원 행을 지운다. 세션 · 프로젝트 · 파일 정보 · 업체 정보는 DB가 함께 지운다(ON DELETE CASCADE).
    commit은 부르는 쪽이 한다."""
    await repo.delete_user(s, user.id)


async def logout(s: AsyncSession, token: str | None) -> None:
    if token:
        await repo.delete_session(s, _sid(token))
        await s.commit()


async def user_from_token(s: AsyncSession, token: str) -> User | None:
    found = await repo.session_with_user(s, _sid(token))
    if not found:
        return None
    sess, user = found
    now = now_utc()
    if sess.expires_at <= now or user.status != "active":
        return None
    if now - sess.last_seen_at > timedelta(hours=1):  # 마지막 사용 시각은 한 시간에 한 번만 쓴다
        await repo.touch_session(s, sess.id, now)
        await s.commit()
    return user


async def me(s: AsyncSession, user: User) -> MeOut:
    status = code = note = None
    if user.role == "vendor":
        from app.vendor.repository import (
            review_of,  # 업체 기능이 auth를 쓰므로 여기서만 늦게 읽는다 (D7 예외)
        )

        got = await review_of(s, user.id)
        if got:
            status, code, note = got
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        phone=user.phone,
        role=user.role,
        created_at=user.created_at,
        vendor_status=status,
        vendor_review_code=code,
        vendor_review_note=note,
        vendor_reject_reason=note if status == "rejected" else None,
    )


async def update_me(s: AsyncSession, user: User, data: MePatch) -> MeOut:
    if data.name is not None:
        user.name = data.name
    if data.phone is not None:
        user.phone = data.phone
    await s.commit()
    return await me(s, user)
