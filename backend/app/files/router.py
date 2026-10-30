import logging
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user
from app.auth.models import User
from app.db import get_session
from app.files import service, storage
from app.files.schemas import FileOut
from app.shared.errors import AppError

router = APIRouter(tags=["파일"])
log = logging.getLogger(__name__)


@router.post(
    "/files",
    status_code=201,
    response_model=FileOut,
    summary="파일 올리기 (공간 사진 · 도면 · 포트폴리오)",
)
async def upload(
    kind: Annotated[str, Form()],
    file: UploadFile,
    user: User = Depends(current_user),
    s: AsyncSession = Depends(get_session),
) -> FileOut:
    row = await service.upload_by(s, user, kind, file)
    return FileOut.model_validate(row, from_attributes=True)


@router.get("/files/{file_id}", summary="파일 보기 (올린 사람 · 관리자)")
async def download(
    file_id: uuid.UUID, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)
) -> FileResponse:
    f = await service.readable(s, user, file_id)
    if f is None:  # 남의 파일은 있는지조차 알려 주지 않는다
        raise AppError(404, "not_found", "파일을 찾을 수 없어요.")
    path = storage.path_of(f.storage_key)
    if not path.is_file():  # DB에는 있는데 디스크에 없다: 볼륨 유실 · 다른 서버
        log.error("파일 행은 있는데 디스크에 없어요: %s", f.id)
        raise AppError(404, "not_found", "파일을 찾을 수 없어요.")
    return FileResponse(
        path,
        media_type=f.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(f.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            # 올린 파일 안의 스크립트가 우리 주소에서 돌지 못하게 (PDF · SVG 같은 것)
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        },
    )
