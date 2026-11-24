"""회원 상태 바꾸기 (관리자 정지 · 풀기, A03). users · user_sessions는 auth 표지만 회원 관리 기능이
여기 있어서 상태 칸만 바꾼다(auth.service에 함수가 생기면 그것을 부른다, b1b.md 부탁).
탈퇴 때 고객 쪽에 남길 파일도 여기서 찾는다(읽기 조인만)."""

import uuid

from sqlalchemy import column, delete, select, table, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserSession
from app.files.models import File

# 업체 · 견적 · 확정 · 공사 표는 위층 · 같은 층 기능이라 모델을 import하지 않고 읽기 조인할 칸만 적는다
_VENDORS = table("vendors", column("user_id"))
_QUOTE_FILES = table("vendor_quote_files", column("quote_id"), column("file_id"))
_DEALS = table("deals", column("quote_id"), column("project_id"))
_PROJECTS = table("projects", column("id"), column("owner_id"))


async def set_status(s: AsyncSession, user_id: uuid.UUID, status: str) -> bool:
    """고객 · 업체 회원의 상태를 바꾼다(관리자는 못 바꿈). 이미 그 상태면 False.
    정지하면 로그인 세션을 모두 지운다(다음 요청부터 401, 실시간 줄기는 60초 안에 닫힘)."""
    q = (
        update(User)
        .where(User.id == user_id, User.role != "admin", User.status != status)
        .values(status=status)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    changed = (await s.execute(q)).scalar_one_or_none() is not None
    if changed and status == "suspended":
        await s.execute(delete(UserSession).where(UserSession.user_id == user_id))
    return changed


async def confirmed_quote_files(
    s: AsyncSession, vendor_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    """업체가 올린 파일 중 고객이 확정한 견적서 버전(deals.quote_id)에 붙은 것 → 그 공사 고객.
    공사 상태(확정 · 진행 중 · 끝남 · 다시 고름)와 상관없이 고객이 확정한 버전이다. 업체 행을 먼저 잠가
    (FOR UPDATE) 그사이 들어오는 확정(업체 행을 FK로 읽음)이 탈퇴 앞이나 뒤로 줄 서게 한다."""
    await s.execute(
        select(_VENDORS.c.user_id).where(_VENDORS.c.user_id == vendor_id).with_for_update()
    )
    q = (
        select(File.id, _PROJECTS.c.owner_id)
        .join(_QUOTE_FILES, _QUOTE_FILES.c.file_id == File.id)
        .join(_DEALS, _DEALS.c.quote_id == _QUOTE_FILES.c.quote_id)
        .join(_PROJECTS, _PROJECTS.c.id == _DEALS.c.project_id)
        .where(File.owner_id == vendor_id)
    )
    return {fid: owner for fid, owner in (await s.execute(q)).all()}
