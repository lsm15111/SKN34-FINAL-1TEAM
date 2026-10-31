"""출처별 원본 → 업체 행. DB · HTTP를 모르는 순수 함수만 둔다 (테스트는 가짜 원본으로).

- 상가정보 CSV: 업종(표준산업분류 코드 · 상권업종 소분류)으로 거르고 업소번호를 출처 번호로 쓴다. 전화 칸은 없다.
- KISCON 공시: 등록 · 변경 · 말소 · 양도 · 양수 이벤트를 날짜 순으로 다시 돌려 지금 등록된 업체를 만든다.
  대표자 이름(ncrGsMaster)은 읽지 않는다. 휴대전화 번호는 버린다.
"""

import codecs
import csv
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Literal

from app.directory.address import (
    biz_no,
    clean_text,
    office_phone,
    point,
    region_from_address,
    region_of,
)
from app.directory.industry import ordered, trades_for_kiscon, trades_for_sangga


@dataclass(frozen=True)
class VendorRow:
    """출처에서 읽은 업체 한 곳 (DB에 넣기 전)"""

    source: str
    source_id: str
    name: str
    trades: list[str]
    industries: list[str] = field(default_factory=list)
    sido: str | None = None
    sgg: str | None = None
    address: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    reg_kind: str | None = None
    reg_no: str | None = None
    phone: str | None = None


# ── 상가정보 CSV ──

SANGGA_REQUIRED = {"상가업소번호", "상호명", "시도명", "시군구명"}


def sangga_row(r: dict[str, str | None]) -> VendorRow | None:
    """인테리어 관련 업종이 아니거나 번호 · 이름이 없으면 None"""
    trades = trades_for_sangga(r.get("표준산업분류코드"), r.get("상권업종소분류명"))
    sid = clean_text(r.get("상가업소번호"), 64)
    name = clean_text(" ".join(x for x in (r.get("상호명"), r.get("지점명")) if x), 100)
    if not trades or not sid or not name:
        return None
    sido, sgg = region_of(r.get("시도명"), r.get("시군구명"))
    lat, lng = point(r.get("위도"), r.get("경도"))
    industry = clean_text(r.get("상권업종소분류명") or r.get("표준산업분류명"), 60)
    return VendorRow(
        source="sangga",
        source_id=sid,
        name=name,
        trades=trades,
        industries=[industry] if industry else [],
        sido=sido,
        sgg=sgg,
        address=clean_text(r.get("도로명주소") or r.get("지번주소"), 200),
        lat=lat,
        lng=lng,
    )


def _encoding(path: Path) -> str:
    """상가정보 파일은 해에 따라 UTF-8 또는 CP949다. 앞부분이 UTF-8로 읽히면 UTF-8로 본다."""
    with path.open("rb") as f:
        head = f.read(1 << 16)
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
    except UnicodeDecodeError:
        return "cp949"
    return "utf-8-sig"


def read_sangga_csv(path: Path) -> tuple[int, list[VendorRow]]:
    """(읽은 행 수, 인테리어 관련 행). 파일이 커도 맞는 행만 메모리에 둔다. 작업 스레드에서 부른다."""
    with path.open(encoding=_encoding(path), newline="") as f:
        reader = csv.DictReader(f)
        missing = SANGGA_REQUIRED - set(reader.fieldnames or ())
        if missing:
            raise ValueError("상가정보 CSV 열이 아니에요: " + ", ".join(sorted(missing)))
        total, rows = 0, []
        for r in reader:
            total += 1
            row = sangga_row(r)
            if row is not None:
                rows.append(row)
    return total, rows


# ── KISCON 공시 이벤트 ──

EventKind = Literal["register", "change", "close", "transfer_out", "transfer_in"]
# 공시구분 글자 → 이벤트. '양도양수'는 그 행의 업체가 받은 쪽이라 양수를 먼저 본다 (응답으로 확인 필요)
_FLAGS: tuple[tuple[str, EventKind], ...] = (
    ("양수", "transfer_in"),
    ("양도", "transfer_out"),
    ("말소", "close"),
    ("폐업", "close"),
    ("반납", "close"),
    ("취소", "close"),
    ("신규", "register"),
    ("등록", "register"),
    ("정정", "change"),
    ("변경", "change"),
)
# 공시일 칸 이름은 응답으로 확인해야 해서 둘 다 본다
_DATE_FIELDS = ("ncrNtcDate", "ncrGsDate")


@dataclass(frozen=True)
class KisconEvent:
    kind: EventKind
    reg_no: str
    item: str  # 등록 업종 이름 (원문)
    name: str
    address: str | None
    phone: str | None
    at: str  # 공시일 숫자 (YYYYMMDD), 정렬용


def kiscon_event(item: dict[str, str]) -> KisconEvent | None:
    """거를 업종이 아니거나, 사업자번호 · 이름 · 공시구분을 못 읽으면 None. 대표자 칸은 보지 않는다."""
    trade_item = clean_text(item.get("ncrItemName"), 60)
    if not trade_item or not trades_for_kiscon(trade_item):
        return None
    flag = item.get("ncrGsFlag") or ""
    kind = next((k for word, k in _FLAGS if word in flag), None)
    no = biz_no(item.get("ncrMasterNum"))
    name = clean_text(item.get("ncrGsKname"), 100)
    if kind is None or no is None or name is None:
        return None
    at = next((re.sub(r"\D", "", item[f]) for f in _DATE_FIELDS if item.get(f)), "")
    return KisconEvent(
        kind=kind,
        reg_no=no,
        item=trade_item,
        name=name,
        address=clean_text(item.get("ncrGsAddr"), 200),
        phone=office_phone(item.get("ncrOffTel")),
        at=at,
    )


@dataclass(frozen=True)
class Holding:
    """한 사업자가 지금 가진 등록 업종"""

    name: str
    items: frozenset[str]
    address: str | None = None
    phone: str | None = None


def replay(state: dict[str, Holding], events: Iterable[KisconEvent]) -> dict[str, Holding]:
    """이벤트를 공시일 순으로 다시 돌린다. 등록 업종이 하나도 안 남은 사업자는 빠진다. state는 바꾸지 않는다."""
    out = dict(state)
    for e in sorted(events, key=lambda e: e.at):  # 같은 날은 받은 순서 그대로
        h = out.get(e.reg_no)
        if e.kind in ("register", "transfer_in", "change"):
            base = h or Holding(name=e.name, items=frozenset())
            out[e.reg_no] = replace(
                base,
                name=e.name,
                items=base.items | {e.item},
                address=e.address or base.address,
                phone=e.phone or base.phone,
            )
        elif h is not None:  # close · transfer_out
            left = h.items - {e.item}
            if left:
                out[e.reg_no] = replace(h, items=left)
            else:
                del out[e.reg_no]
    return out


def kiscon_row(reg_no: str, h: Holding) -> VendorRow:
    trades = ordered({t for item in h.items for t in trades_for_kiscon(item)})
    sido, sgg = region_from_address(h.address)
    return VendorRow(
        source="kiscon",
        source_id=reg_no,
        name=h.name,
        trades=trades,
        industries=sorted(h.items)[:10],
        sido=sido,
        sgg=sgg,
        address=h.address,
        reg_kind="construction",
        reg_no=reg_no,
        phone=h.phone,
    )


def kiscon_events(items: Iterable[dict[str, str]]) -> Iterator[KisconEvent]:
    for item in items:
        e = kiscon_event(item)
        if e is not None:
            yield e
