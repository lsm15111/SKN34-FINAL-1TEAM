"""올린 사진에서 위치(GPS) · 촬영 정보(EXIF) · 글 상자를 지운다.

픽셀만 새 그림에 옮겨 다시 저장하므로 메타데이터는 남지 않는다. 원본은 저장하지 않는다.
- 회전: 휴대폰이 EXIF에 적어 둔 방향을 먼저 픽셀에 반영한다(지우면 사진이 눕기 때문).
- HEIC(아이폰): 브라우저가 못 보여 줘서 JPEG로 바꾼다.
- 색 프로필(ICC)은 위치 정보가 아니라서 남긴다.
"""

import io
import threading

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

# 약 8000×5000. 이보다 큰 그림은 압축 폭탄(작은 파일이 메모리를 크게 먹는 그림)으로 보고 거부한다.
# 픽셀을 풀기 전에 크기를 직접 본다(경고 필터는 스레드끼리 섞여서 쓰지 않음). Pillow의 2배 한도는 마지막 안전망.
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
# 그림 하나가 수백 MB를 쓸 수 있어서 프로세스마다 한 장씩만 처리한다 (uvicorn 프로세스 2개 = 동시에 2장)
_SLOTS = threading.BoundedSemaphore(1)


class BadImage(Exception):
    """열 수 없거나 너무 큰 그림"""


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))  # 머리만 읽는다 (픽셀은 아직 안 풂)
        if img.width * img.height > MAX_PIXELS:
            raise BadImage("too many pixels")
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise BadImage from exc
    except Image.DecompressionBombError as exc:
        raise BadImage from exc
    return img


def clean(data: bytes, mime: str) -> tuple[bytes, str]:
    """(지운 뒤 내용, 형식)을 돌려준다. mime은 파일 앞부분으로 확인한 형식."""
    with _SLOTS:
        return _clean(data, mime)


def _clean(data: bytes, mime: str) -> tuple[bytes, str]:
    img = _open(data)
    icc = img.info.get("icc_profile")
    img = ImageOps.exif_transpose(img)
    to_jpeg = mime in ("image/jpeg", "image/heic")
    alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if to_jpeg:
        mode = "L" if img.mode in ("L", "1") else "RGB"
    else:
        mode = "RGBA" if alpha else ("L" if img.mode in ("L", "1") else "RGB")
    if img.mode != mode:
        img = img.convert(mode)
    bare = Image.frombytes(mode, img.size, img.tobytes())  # 픽셀만 옮긴다 (info · EXIF 없음)

    out = io.BytesIO()
    extra = {"icc_profile": icc} if icc else {}
    if to_jpeg:
        bare.save(out, "JPEG", quality=90, **extra)
        return out.getvalue(), "image/jpeg"
    if mime == "image/png":
        bare.save(out, "PNG", **extra)
    else:
        bare.save(out, "WEBP", quality=90, **extra)
    return out.getvalue(), mime
