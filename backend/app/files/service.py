"""파일 올리기 · 읽기 권한. 형식은 이름표(Content-Type)가 아니라 파일 앞부분 바이트로 확인한다.

사진은 저장하기 전에 위치 정보(GPS) · EXIF를 지운다 (images.py). 원본은 남기지 않는다.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.models import User
from app.files import images, storage
from app.files.models import File
from app.shared import ratelimit
from app.shared.errors import AppError

MB = 1024 * 1024
IMAGES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
# 종류별로 받는 형식과 최대 크기
RULES: dict[str, tuple[set[str], int]] = {
    "photo": (IMAGES, 10 * MB),
    "plan": (IMAGES | {"application/pdf"}, 20 * MB),
    "license": ({"image/jpeg", "image/png", "application/pdf"}, 10 * MB),
    "portfolio": ({"image/jpeg", "image/png", "image/webp"}, 10 * MB),
}
# 누가 어떤 종류를 올릴 수 있는지
UPLOADERS: dict[str, set[str]] = {
    "photo": {"customer"},
    "plan": {"customer"},
    "license": {"vendor"},
    "portfolio": {"vendor"},
}


def sniff(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return "image/heic"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def clean_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:200] or "file"


@dataclass
class Prepared:
    """검사하고 위치 정보를 지운, 아직 저장하지 않은 파일"""

    kind: str
    data: bytes
    content_type: str
    filename: str


async def prepare(kind: str, upload: UploadFile) -> Prepared:
    """형식 · 크기를 검사하고 사진의 위치 정보를 지운다. DB를 쓰지 않는다 (느린 일을 트랜잭션 밖에서)."""
    if kind not in RULES:
        raise AppError(422, "file_kind", "파일 종류가 맞지 않아요.")
    allowed, limit = RULES[kind]
    data = await upload.read(limit + 1)
    if not data:
        raise AppError(422, "file_empty", "빈 파일이에요.")
    if len(data) > limit:
        raise AppError(413, "file_too_big", f"{limit // MB}MB까지 올릴 수 있어요.")
    ctype = sniff(data[:16])
    if ctype not in allowed:
        raise AppError(415, "file_type", "이 형식의 파일은 올릴 수 없어요.")
    name = clean_filename(upload.filename)
    if ctype in IMAGES:
        try:
            # 그림 처리는 CPU를 쓰므로 요청 처리 흐름을 막지 않게 따로 돌린다
            data, out_type = await run_in_threadpool(images.clean, data, ctype)
        except images.BadImage as exc:
            raise AppError(
                422, "file_broken", "사진을 열 수 없어요. 다른 파일로 올려 주세요."
            ) from exc
        if out_type != ctype:  # HEIC → JPEG
            name = re.sub(r"\.(heic|heif)$", "", name, flags=re.IGNORECASE) + ".jpg"
            ctype = out_type
    return Prepared(kind=kind, data=data, content_type=ctype, filename=name)


async def persist(s: AsyncSession, owner_id: uuid.UUID, f: Prepared) -> File:
    """디스크에 쓰고 파일 행을 더한다. commit은 부르는 쪽이 하고, 실패하면 discard로 디스크 파일을 지운다."""
    key = await run_in_threadpool(storage.save, f.data)
    row = File(
        owner_id=owner_id,
        kind=f.kind,
        storage_key=key,
        filename=f.filename,
        content_type=f.content_type,
        size=len(f.data),
        sha256=hashlib.sha256(f.data).hexdigest(),
    )
    s.add(row)
    try:
        await s.flush()
    except Exception:
        storage.remove(key)
        raise
    return row


def discard(row: File) -> None:
    """DB에 넣지 못한 파일을 디스크에서도 지운다 (주인 없는 파일을 남기지 않음)."""
    storage.remove(row.storage_key)


UPLOADS_PER_HOUR = 120


async def upload_by(s: AsyncSession, user: User, kind: str, upload: UploadFile) -> File:
    if kind not in RULES:
        raise AppError(422, "file_kind", "파일 종류가 맞지 않아요.")
    if user.role not in UPLOADERS[kind]:
        raise AppError(403, "forbidden", "이 종류의 파일을 올릴 권한이 없어요.")
    await ratelimit.hit(
        ratelimit.key("upload", str(user.id)),
        UPLOADS_PER_HOUR,
        3600,
        "파일을 너무 많이 올렸어요. 잠시 뒤에 다시 해 주세요.",
    )
    await s.commit()  # 로그인 확인에 쓴 DB 연결을 돌려준다 (사진 처리 동안 붙잡지 않게)
    prepared = await prepare(kind, upload)
    row = await persist(s, user.id, prepared)
    try:
        await s.commit()
    except Exception:
        discard(row)
        raise
    return row


async def readable(s: AsyncSession, user: User, file_id: uuid.UUID) -> File | None:
    """볼 수 있는 파일만 돌려준다: 올린 사람, 관리자. (견적을 요청받은 업체는 가견적 기능에서 더한다)"""
    f = await s.get(File, file_id)
    if f is None:
        return None
    if f.owner_id == user.id or user.role == "admin":
        return f
    return None


async def owned(
    s: AsyncSession, owner_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, File]:
    rows = (
        (await s.execute(select(File).where(File.id.in_(ids), File.owner_id == owner_id)))
        .scalars()
        .all()
    )
    return {r.id: r for r in rows}


async def storage_keys_of(s: AsyncSession, owner_id: uuid.UUID) -> list[str]:
    """그 회원이 올린 파일의 저장 위치 (탈퇴할 때 디스크에서 지우려고)"""
    return list(
        (await s.execute(select(File.storage_key).where(File.owner_id == owner_id))).scalars()
    )
