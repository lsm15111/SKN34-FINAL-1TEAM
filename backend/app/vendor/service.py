"""업체 가입 · 관리자 승인 / 반려 · 업체 정보 관리.

가입은 기본 회원정보 + 사업자등록증만 받는다. 관리자가 등록증을 보고 승인하면 업체 기능을 쓴다.
승인된 업체는 업체 정보 관리에서 상호 · 맡는 공정 · 일하는 지역 · 포트폴리오 링크를 적는다.
"""

import uuid

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.models import User
from app.files import service as files_service
from app.shared.clock import now_utc
from app.shared.errors import AppError
from app.vendor import repository as repo
from app.vendor.models import Vendor
from app.vendor.schemas import (
    AreaIn,
    VendorAdminOut,
    VendorCard,
    VendorProfileIn,
    VendorProfileOut,
    VendorSignupIn,
)

NO_NAME = "상호 미등록 업체"  # 승인 뒤 업체 정보를 아직 안 채운 경우
NOT_APPROVED = "승인된 업체만 쓸 수 있어요."
SAVE_CONFLICT = "다른 곳에서 먼저 바꿨어요. 다시 열어 주세요."


async def signup(
    s: AsyncSession, data: VendorSignupIn, license_file: UploadFile, ip: str
) -> tuple[User, str]:
    await auth_service.signup_limit(ip)
    lic = await files_service.prepare(
        "license", license_file
    )  # 검사 · 위치 정보 지우기는 DB 밖에서
    user = await auth_service.create_user(
        s, email=data.email, name=data.name, password=data.password, role="vendor"
    )
    row = await files_service.persist(s, user.id, lic)
    try:
        s.add(Vendor(user_id=user.id, license_file_id=row.id))
        await s.flush()
        token = await auth_service.start_session(s, user)
        await s.commit()
    except Exception:
        files_service.discard(row)  # 가입이 안 됐으면 사업자등록증도 남기지 않는다
        raise
    return user, token


async def _out(s: AsyncSession, pairs: list[tuple[Vendor, User]]) -> list[VendorAdminOut]:
    trades, areas = await repo.trades_and_areas(s, [v.user_id for v, _ in pairs])
    return [
        VendorAdminOut(
            user_id=v.user_id,
            name=u.name,
            email=u.email,
            biz_name=v.biz_name,
            owner_name=v.owner_name,
            biz_no=v.biz_no,
            phone=v.phone,
            address=v.address,
            site_url=v.site_url,
            license_file_id=v.license_file_id,
            trades=sorted(trades[v.user_id]),
            areas=[AreaIn(sido=a, sgg=b) for a, b in areas[v.user_id]],
            intro=v.intro,
            status=v.status,
            reject_reason=v.reject_reason,
            created_at=v.created_at,
            reviewed_at=v.reviewed_at,
        )
        for v, u in pairs
    ]


async def list_for_admin(s: AsyncSession, status: str | None) -> list[VendorAdminOut]:
    return await _out(s, await repo.list_with_users(s, status))


async def get_for_admin(s: AsyncSession, vendor_id: uuid.UUID) -> VendorAdminOut:
    pair = await repo.get_with_user(s, vendor_id)
    if pair is None:
        raise AppError(404, "not_found", "업체를 찾을 수 없어요.")
    return (await _out(s, [pair]))[0]


async def candidates(s: AsyncSession, trades: list[str], sido: str, sgg: str) -> list[VendorCard]:
    """가견적 후보: 승인됐고 그 공정 · 시 · 군 · 구를 맡는 앱 업체"""
    return [
        VendorCard(
            user_id=v.user_id,
            name=v.biz_name or NO_NAME,
            trades=ts,
            site_url=v.site_url,
            portfolio_urls=list(v.portfolio_urls),
            approved_at=v.reviewed_at,
        )
        for v, ts in await repo.approved_serving(s, trades, sido, sgg)
    ]


async def is_approved(s: AsyncSession, vendor_id: uuid.UUID) -> bool:
    got = await repo.review_of(s, vendor_id)
    return got is not None and got[0] == "approved"


async def get_profile(s: AsyncSession, user: User) -> VendorProfileOut:
    """업체 정보 관리 읽기. 승인된 업체만 쓴다 (승인 대기 · 반려는 403)."""
    v = await repo.get(s, user.id)
    if v is None or v.status != "approved":
        raise AppError(403, "vendor_not_approved", NOT_APPROVED)
    trades, areas = await repo.trades_and_areas(s, [v.user_id])
    return VendorProfileOut(
        biz_name=v.biz_name,
        site_url=v.site_url,
        trades=sorted(trades[v.user_id]),
        areas=[AreaIn(sido=a, sgg=b) for a, b in sorted(areas[v.user_id])],
        portfolio_urls=list(v.portfolio_urls),
    )


async def save_profile(s: AsyncSession, user: User, data: VendorProfileIn) -> VendorProfileOut:
    """업체 정보 관리 저장 (통째로 바꿈). 한 트랜잭션에서 승인된 업체 행을 조건부 UPDATE로 잠근 뒤
    공정 · 지역은 차이만 반영한다. 같은 업체가 동시에 저장해도 잠근 순서대로 하나씩 들어가 섞이지 않는다.
    """
    ok = await repo.update_profile(
        s,
        user.id,
        biz_name=data.biz_name,
        site_url=data.site_url,
        portfolio_urls=data.portfolio_urls,
    )
    if not ok:  # 승인 대기 · 반려 (저장하는 사이 반려된 경우도)
        await s.rollback()
        raise AppError(403, "vendor_not_approved", NOT_APPROVED)
    try:
        await repo.set_trades(s, user.id, data.trades)
        await repo.set_areas(s, user.id, [(a.sido, a.sgg) for a in data.areas])
        await s.commit()
    except IntegrityError as exc:
        await s.rollback()
        raise AppError(409, "save_conflict", SAVE_CONFLICT) from exc
    return await get_profile(s, user)


async def approve(s: AsyncSession, admin: User, vendor_id: uuid.UUID) -> VendorAdminOut:
    ok = await repo.set_status(
        s,
        vendor_id,
        to="approved",
        allowed_from=("pending", "rejected"),
        reason=None,
        by=admin.id,
        at=now_utc(),
    )
    if not ok:
        await get_for_admin(s, vendor_id)  # 없으면 404
        raise AppError(409, "invalid_state", "이미 승인한 업체예요.")
    await s.commit()
    return await get_for_admin(s, vendor_id)


async def reject(s: AsyncSession, admin: User, vendor_id: uuid.UUID, reason: str) -> VendorAdminOut:
    ok = await repo.set_status(
        s,
        vendor_id,
        to="rejected",
        allowed_from=("pending", "approved"),
        reason=reason.strip(),
        by=admin.id,
        at=now_utc(),
    )
    if not ok:
        await get_for_admin(s, vendor_id)
        raise AppError(409, "invalid_state", "이미 반려한 업체예요.")
    await s.commit()
    return await get_for_admin(s, vendor_id)
