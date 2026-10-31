"""출처마다 다른 지역 · 주소 · 번호 모양을 믿집 기준(shared/regions)으로 맞춘다. 순수 함수만 둔다."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.shared.regions import SIDO, is_region

# 행정 개편 전 이름과 주소에 흔한 줄임말
_ALIASES = {
    "서울시": "seoul",
    "부산시": "busan",
    "대구시": "daegu",
    "인천시": "incheon",
    "대전시": "daejeon",
    "울산시": "ulsan",
    "세종시": "sejong",
    "광주광역시": "jeonnam-gwangju",
    "광주": "jeonnam-gwangju",
    "전라남도": "jeonnam-gwangju",
    "전남": "jeonnam-gwangju",
    "강원도": "gangwon",
    "전라북도": "jeonbuk",
    "제주도": "jeju",
}
_SIDO_BY_NAME: dict[str, str] = {
    **{full: sid for sid, (_, full, _) in SIDO.items()},
    **{short: sid for sid, (short, _, _) in SIDO.items()},
    **_ALIASES,
}


def region_of(sido_name: str | None, sgg_name: str | None) -> tuple[str | None, str | None]:
    """('서울특별시', '마포구') → ('seoul', '마포구'). 일반구는 시 단위로('수원시 장안구' → '수원시').

    목록에 없는 시 · 군 · 구(개편 전 이름 등)는 시 · 도만 남긴다.
    """
    sid = _SIDO_BY_NAME.get((sido_name or "").strip())
    if sid is None:
        return None, None
    if sid == "sejong":
        return sid, "세종시"
    parts = (sgg_name or "").split()
    for cand in (parts[0] if parts else "", " ".join(parts)):
        if cand and is_region(sid, cand):
            return sid, cand
    return sid, None


def region_from_address(address: str | None) -> tuple[str | None, str | None]:
    """'서울특별시 마포구 월드컵로 1' → ('seoul', '마포구')"""
    parts = (address or "").split()
    return region_of(parts[0] if parts else None, parts[1] if len(parts) > 1 else None)


def clean_text(value: str | None, limit: int) -> str | None:
    text = " ".join((value or "").split())
    return text[:limit] if text else None


def office_phone(raw: str | None) -> str | None:
    """사무실 번호 · 대표번호만 숫자로 남긴다. 휴대전화(01x)와 모양이 이상한 번호는 버린다."""
    digits = re.sub(r"\D", "", raw or "")
    return digits if re.fullmatch(r"0[2-9]\d{7,10}|1[5-9]\d{6}", digits) else None


def biz_no(raw: str | None) -> str | None:
    """사업자등록번호: 숫자 10자리만"""
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 10 else None


def point(lat: str | None, lng: str | None) -> tuple[Decimal | None, Decimal | None]:
    """좌표는 국내 범위 안이고 둘 다 있을 때만 (소수 6자리)"""
    try:
        la, ln = Decimal((lat or "").strip()), Decimal((lng or "").strip())
    except InvalidOperation:
        return None, None
    if not (32 <= la <= 39 and 124 <= ln <= 132):
        return None, None
    q = Decimal("0.000001")
    return la.quantize(q, rounding=ROUND_HALF_UP), ln.quantize(q, rounding=ROUND_HALF_UP)


def phone_label(digits: str) -> str:
    """화면에 보일 모양: 0212345678 → 02-1234-5678, 15880000 → 1588-0000"""
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:]}"
    head = 2 if digits.startswith("02") else 3 if not digits.startswith("050") else 4
    mid = len(digits) - head - 4
    return f"{digits[:head]}-{digits[head : head + mid]}-{digits[-4:]}"
