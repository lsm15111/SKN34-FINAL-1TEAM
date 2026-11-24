"""파일 올리기 · 읽기 권한. 형식은 이름표(Content-Type)가 아니라 파일 앞부분 바이트로 확인한다.

사진은 저장하기 전에 위치 정보(GPS) · EXIF를 지운다 (images.py). 원본은 남기지 않는다.
업체 종류 파일은 승인된 업체만 올린다(가입 · 보완 서류인 사업자등록증은 예외). 한 사람이 가진 파일은 개수 · 용량
몫이 있고, 올린 뒤 하루가 지나도록 어디에도 붙이지 않은 파일은 정리 작업(worker clean_files)이 지운다(sec M5).
"""

import hashlib
import io
import logging
import re
import uuid
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, column, delete, exists, func, select, table, text, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import service as auth_service
from app.auth.models import User
from app.config import settings
from app.db import SessionLocal
from app.files import images, storage
from app.files.models import KINDS, File, FileView
from app.shared import ratelimit
from app.shared.errors import AppError

log = logging.getLogger(__name__)
MB = 1024 * 1024
IMAGES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCS = {"application/pdf", XLSX, "image/jpeg", "image/png", "image/heic"}
# 종류별로 받는 형식과 최대 크기. 사진 종류는 모두 위치 정보를 지운 새 그림으로만 저장한다
RULES: dict[str, tuple[set[str], int]] = {
    "photo": (IMAGES, 10 * MB),
    "plan": (IMAGES | {"application/pdf"}, 20 * MB),
    "license": ({"image/jpeg", "image/png", "application/pdf"}, 10 * MB),
    "portfolio": ({"image/jpeg", "image/png", "image/webp"}, 10 * MB),
    "price_doc": (DOCS, 20 * MB),
    "quote_doc": (DOCS, 20 * MB),
    "work_photo": (IMAGES, 10 * MB),
    "chat_photo": (IMAGES, 10 * MB),  # 채팅 '+ 메뉴'로 보내는 사진 (v3)
    "review_photo": (IMAGES, 10 * MB),  # 리뷰 사진 (v3)
    "done_photo": (IMAGES, 10 * MB),  # 공사 끝 사진 (v3)
}
# 누가 어떤 종류를 올릴 수 있는지
UPLOADERS: dict[str, set[str]] = {
    "photo": {"customer"},
    "plan": {"customer"},
    "license": {"vendor"},
    "portfolio": {"vendor"},
    "price_doc": {"vendor"},
    "quote_doc": {"vendor"},
    "work_photo": {"vendor"},
    "chat_photo": {"customer", "vendor"},
    "review_photo": {"customer"},
    "done_photo": {"vendor"},
}
# 볼 때마다 열람 기록(file_views)을 남기는 종류 (안전성 확보조치 기준 제8조 접속기록, security.md LG-02)
VIEW_LOGGED = frozenset({"license"})
# 승인 전 업체도 올리는 종류: 가입 · 보완 · 다시 신청 서류(사업자등록증)
BEFORE_APPROVAL = frozenset({"license"})
# 한 사람이 가진 파일 몫(붙인 파일까지 모두, sec M5). 붙이지 않은 파일은 하루 뒤 지워져 몫이 돌아와요
USER_FILES_MAX = 5_000
USER_BYTES_MAX = 10 * 1024 * MB
QUOTA = "올릴 수 있는 파일 수나 용량을 넘었어요. 어디에도 붙이지 않은 파일은 하루 뒤에 지워져요."
UNATTACHED_HOURS = 24  # 올린 뒤 이만큼 지나도록 어디에도 붙지 않은 파일은 정리 작업이 지운다
SWEEP_BATCH = 500  # 정리 작업 한 번에 지우는 파일 수

_XLSX_MAIN = b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_MACRO = ("vbaproject.bin", "xl/macrosheets/")
_TYPES_MAX = 256 * 1024
_ZIP_ERRORS = (
    zipfile.BadZipFile,
    KeyError,
    RuntimeError,
    NotImplementedError,
    EOFError,
    ValueError,
    OSError,
    zlib.error,
)


def _is_xlsx(data: bytes) -> bool:
    """엑셀 통합 문서(xlsx)인지 본다: 목차([Content_Types].xml)가 일반 통합 문서이고 xl/ 폴더가 있다.

    매크로 파일(xlsm · vbaProject · 매크로 시트) · 서식 파일(xltx)은 받지 않는다.
    목차 한 개만 풀어 본다(크기를 먼저 봐서 압축 폭탄을 풀지 않는다).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            info = z.getinfo("[Content_Types].xml")
            if info.file_size > _TYPES_MAX or not any(n.startswith("xl/") for n in names):
                return False
            if any(m in n.lower() for n in names for m in _MACRO):
                return False
            with z.open(info) as f:
                types = f.read(_TYPES_MAX + 1)
    except _ZIP_ERRORS:
        return False
    return _XLSX_MAIN in types and b"macroenabled" not in types.lower()


def sniff(data: bytes) -> str | None:
    """파일 앞부분 바이트로 형식을 본다. 엑셀은 ZIP 안의 목차까지 확인한다."""
    head = data[:16]
    if head.startswith(b"PK\x03\x04"):
        return XLSX if _is_xlsx(data) else None
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


# 글 방향을 바꾸는 보이지 않는 글자(LRM · RLM · LRE~RLO · LRI~PDI). 'photo(U+202E)gpj.exe'가 'photoexe.jpg'처럼
# 보이게 만들 수 있어 이름에서 지운다(sec L2)
_BIDI = "\u200e\u200f\u202a-\u202e\u2066-\u2069"


def clean_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(rf"[\x00-\x1f\x7f{_BIDI}]", "", base).strip()
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
    ctype = await run_in_threadpool(sniff, data)  # 엑셀은 ZIP 목차를 읽는다
    if ctype not in allowed:
        raise AppError(415, "file_type", "이 형식의 파일은 올릴 수 없어요.")
    name = clean_filename(upload.filename)
    if ctype in IMAGES:
        try:
            # 그림 처리는 CPU를 쓰므로 요청 처리 흐름을 막지 않게 따로 돌린다(한 장씩, images.clean)
            data, out_type = await images.clean(data, ctype)
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


async def drop(s: AsyncSession, owner_id: uuid.UUID, file_id: uuid.UUID) -> str | None:
    """내 파일 행을 지우고 저장 위치를 돌려준다. commit은 부르는 쪽이 하고, 그 뒤 remove_stored를 부른다."""
    row = await s.get(File, file_id)
    if row is None or row.owner_id != owner_id:
        return None
    await s.delete(row)
    return row.storage_key


async def remove_stored(key: str) -> bool:
    """commit 뒤에 저장소의 내용을 지운다. 못 지우면 기록만 남기고 False(DB에는 이미 없다).
    행이 없는 저장소 내용을 다시 지우는 정리 일은 없다(sweep_unattached는 DB 행 기준): 남은 수는 로그로 본다."""
    try:
        await run_in_threadpool(storage.remove, key)
    except (OSError, BotoCoreError, ClientError):
        log.error("지운 파일의 내용을 저장소에서 지우지 못했어요")
        return False
    return True


UPLOADS_PER_HOUR = 120


async def _approved_vendor(s: AsyncSession, user: User) -> bool:
    """업체 승인 상태(관리자 승인). files는 업체 기능보다 아래 층이라 /me와 같은 auth 길로 읽는다."""
    return (await auth_service.me(s, user)).vendor_status == "approved"


async def _check_quota(s: AsyncSession, owner_id: uuid.UUID, size: int) -> None:
    """한 사람 파일 몫(개수 · 바이트). 넘으면 409 file_quota"""
    n, used = (
        await s.execute(
            select(func.count(), func.coalesce(func.sum(File.size), 0)).where(
                File.owner_id == owner_id
            )
        )
    ).one()
    if n + 1 > USER_FILES_MAX or used + size > USER_BYTES_MAX:
        raise AppError(409, "file_quota", QUOTA)


async def upload_by(s: AsyncSession, user: User, kind: str, upload: UploadFile) -> File:
    # DB가 받는 종류(models.KINDS)에도 있어야 한다: 새 종류는 migration이 들어온 뒤에 열린다(그 전에는 422)
    if kind not in RULES or kind not in KINDS:
        raise AppError(422, "file_kind", "파일 종류가 맞지 않아요.")
    if user.role not in UPLOADERS[kind]:
        raise AppError(403, "forbidden", "이 종류의 파일을 올릴 권한이 없어요.")
    if (
        user.role == "vendor"
        and kind not in BEFORE_APPROVAL
        and not await _approved_vendor(s, user)
    ):
        raise AppError(403, "vendor_not_approved", "승인된 업체만 쓸 수 있어요.")
    await ratelimit.hit(
        ratelimit.key("upload", str(user.id)),
        UPLOADS_PER_HOUR,
        3600,
        "파일을 너무 많이 올렸어요. 잠시 뒤에 다시 해 주세요.",
    )
    await s.commit()  # 로그인 확인에 쓴 DB 연결을 돌려준다 (사진 처리 동안 붙잡지 않게)
    prepared = await prepare(kind, upload)
    await _check_quota(s, user.id, len(prepared.data))
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


async def record_view(s: AsyncSession, user: User, f: File) -> None:
    """사업자등록증을 누가 · 언제 · 어느 파일을 봤는지 file_views에 한 줄 남긴다(관리자 · 업체 본인만 볼 수 있다).
    이름 · 파일 이름 같은 값은 쓰지 않는다. 기록을 남기지 못하면 파일도 내주지 않는다(커밋 오류가 그대로 오른다)."""
    if f.kind not in VIEW_LOGGED:
        return
    s.add(
        FileView(
            file_id=f.id, owner_id=f.owner_id, viewer_id=user.id, viewer_role=user.role, kind=f.kind
        )
    )
    await s.commit()


async def respond(f: File) -> Response:
    """파일 내용을 내준다. 볼 권한은 부르는 쪽(파일 · 업체 자세히 router)이 먼저 확인한다."""
    # 그림 · PDF만 브라우저 안에서 열고, 엑셀 같은 문서는 내려받게 한다 (security.md FI-03)
    shown = f.content_type.startswith("image/") or f.content_type == "application/pdf"
    headers = {
        "Content-Disposition": f"{'inline' if shown else 'attachment'}; "
        f"filename*=UTF-8''{quote(f.filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        # 올린 파일 안의 스크립트가 우리 주소에서 돌지 못하게 (PDF · SVG 같은 것), 다른 사이트 틀에도 안 들어가게
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline';"
        " frame-ancestors 'self'; sandbox",
    }
    if settings.files_s3_bucket:
        try:
            data = await run_in_threadpool(storage.read, f.storage_key)
        except FileNotFoundError as exc:
            log.error("파일 행은 있는데 S3에 없어요: %s", f.id)
            raise AppError(404, "not_found", "파일을 찾을 수 없어요.") from exc
        return Response(data, media_type=f.content_type, headers=headers)
    path = storage.path_of(f.storage_key)
    if not path.is_file():  # DB에는 있는데 디스크에 없다: 볼륨 유실 · 다른 서버
        log.error("파일 행은 있는데 디스크에 없어요: %s", f.id)
        raise AppError(404, "not_found", "파일을 찾을 수 없어요.")
    return FileResponse(path, media_type=f.content_type, headers=headers)


async def owned(
    s: AsyncSession, owner_id: uuid.UUID, ids: list[uuid.UUID], *, lock: bool = False
) -> dict[uuid.UUID, File]:
    """그 회원이 올린 파일. lock이면 행을 잠가 같은 파일을 붙이는 요청이 줄 선다."""
    q = select(File).where(File.id.in_(ids), File.owner_id == owner_id).order_by(File.id)
    if lock:
        q = q.with_for_update()
    return {r.id: r for r in (await s.execute(q)).scalars().all()}


async def storage_keys_of(s: AsyncSession, owner_id: uuid.UUID) -> list[str]:
    """그 회원이 올린 파일의 저장 위치 (탈퇴할 때 디스크에서 지우려고)"""
    return list(
        (await s.execute(select(File.storage_key).where(File.owner_id == owner_id))).scalars()
    )


async def hand_over(s: AsyncSession, owner_id: uuid.UUID, to: dict[uuid.UUID, uuid.UUID]) -> int:
    """내 파일을 다른 회원 몫으로 넘긴다(파일 id → 새 주인). 탈퇴하는 업체의 확정 견적서를 그 공사 고객 쪽에 남길 때
    쓴다: 회원 행을 지워도 파일(주인 CASCADE)이 남고, 새 주인이 탈퇴하면 함께 지워진다. commit은 부르는 쪽.
    돌려주는 값: 넘긴 수."""
    moved = 0
    for new_owner in set(to.values()):
        ids = [f for f, o in to.items() if o == new_owner]
        res = await s.execute(
            update(File)
            .where(File.id.in_(ids), File.owner_id == owner_id)
            .values(owner_id=new_owner)
            .execution_options(synchronize_session=False)
        )
        moved += res.rowcount
    return moved


# ---- 붙이지 않은 파일 정리 (sec M5) ----

# 파일을 가리키는 외래 키(표 · 칸). 기능마다 붙이는 표가 달라 DB 목록에서 읽는다(새 표도 저절로 지켜요)
_REFS = text(
    "select cl.relname, att.attname from pg_constraint con"
    " join pg_class cl on cl.oid = con.conrelid"
    " join pg_attribute att on att.attrelid = con.conrelid and att.attnum = any(con.conkey)"
    " where con.contype = 'f' and con.confrelid = 'files'::regclass"
)


def _unattached(refs: list[tuple[str, str]]):
    """어느 표에서도 가리키지 않는 파일 조건"""
    conds = [~exists().where(table(t, column(c)).c[c] == File.id) for t, c in refs]
    return and_(*conds) if conds else true()


async def sweep_unattached(now: datetime, limit: int = SWEEP_BATCH) -> int:
    """올린 지 UNATTACHED_HOURS가 넘도록 어디에도 붙지 않은 파일(외래 키로 가리키는 행이 없는 파일)을 지우고, commit
    뒤 저장소 내용도 지운다. 지울 파일 행을 먼저 잠가(FOR UPDATE SKIP LOCKED) 그사이 붙이는 요청은 기다리게 하고,
    지울 때 붙은 데가 없는지 한 번 더 본다. 열람 기록(file_views)은 FK가 없어 남는다. 돌려주는 값: 지운 수."""
    cut = now - timedelta(hours=UNATTACHED_HOURS)
    async with SessionLocal() as s:
        refs = [(t, c) for t, c in (await s.execute(_REFS)).all()]
        free = _unattached(refs)
        ids = list(
            (
                await s.execute(
                    select(File.id)
                    .where(File.created_at < cut, free)
                    .order_by(File.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        keys: list[str] = []
        if ids:
            res = await s.execute(
                delete(File).where(File.id.in_(ids), free).returning(File.storage_key)
            )
            keys = list(res.scalars())
        await s.commit()
    for key in keys:
        await remove_stored(key)
    if keys:
        log.info("붙이지 않은 파일 %d개를 지웠어요", len(keys))
    return len(keys)
