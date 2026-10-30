"""회원 탈퇴. 여러 기능에 흩어진 내 데이터를 한 번에 지운다.

- 진행 중인 프로젝트가 있어도 막지 않는다 (가입보다 어려운 절차를 만들지 않음, 개인정보 보호법 제38조④).
- DB 행은 회원 행 하나를 지우면 함께 지워진다(ON DELETE CASCADE). 디스크의 파일은 commit 뒤에 지운다.
- 관리자 계정은 여기서 지우지 않는다 (다른 관리자가 정리).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.models import User
from app.files import service as files_service
from app.files import storage
from app.shared.errors import AppError

log = logging.getLogger(__name__)


async def withdraw(s: AsyncSession, user: User, password: str, ip: str) -> None:
    if user.role == "admin":
        raise AppError(403, "admin_withdraw", "관리자 계정은 여기서 탈퇴할 수 없어요.")
    await auth_service.confirm_password(user, password, ip)
    keys = await files_service.storage_keys_of(s, user.id)
    await auth_service.delete_user(s, user)
    await s.commit()
    failed = 0
    for key in keys:
        try:
            storage.remove(key)
        except OSError:
            failed += 1
    if failed:  # DB에는 이미 없다. 디스크에 남은 파일은 정리 작업이 지운다
        log.error("탈퇴 뒤 파일 %d개를 지우지 못했어요", failed)
