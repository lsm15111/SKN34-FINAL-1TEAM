"""공정 → 업종 대응표. 외부 업체를 어느 공정 후보로 볼지 이 표 하나로 정한다.

공정 키는 지금 dobae · mokgong 둘이지만, 나머지 8개(공정 에이전트 확장 계획)도 같은 표에 둔다.
- KISCON: 건설업 등록 업종 이름. 2022 업종 개편 뒤 이름이 기준이고, 개편 전 이름은 옛 공시를 읽으려고 둔다(확인 필요).
  전기공사업은 KISCON(건설산업기본법)이 아니라 전기공사업법 등록이라 여기서는 비어 있다.
- 상가정보: 표준산업분류(KSIC 10차) 코드와 상권업종 소분류 이름. 실제 파일을 받으면 업종코드표와 한 번 맞춰 본다.
"""

import re
from dataclasses import dataclass

TRADES = (
    "dobae",
    "mokgong",
    "floor",
    "film",
    "paint",
    "tile",
    "bath",
    "kitchen",
    "electric",
    "window",
)
TRADE_LABEL = {
    "dobae": "도배",
    "mokgong": "목공",
    "floor": "바닥재",
    "film": "필름",
    "paint": "도장",
    "tile": "타일",
    "bath": "욕실",
    "kitchen": "주방",
    "electric": "전기·조명",
    "window": "창호",
}


@dataclass(frozen=True)
class Industries:
    kiscon: tuple[str, ...] = ()  # KISCON 등록 업종 이름
    ksic: tuple[str, ...] = ()  # 상가정보 표준산업분류 코드 (숫자 5자리)
    sangga: tuple[str, ...] = ()  # 상가정보 상권업종 소분류 이름


_INTERIOR = "실내건축공사업"
_WET = "도장·습식·방수·석공사업"
_WINDOW = "금속창호·지붕건축물조립공사업"
# 개편 전 이름 (2021년 이전 공시)
_OLD_PAINT, _OLD_WET, _OLD_STONE = "도장공사업", "미장·방수·조적공사업", "석공사업"
_OLD_WINDOW = "금속구조물·창호·온실공사업"

_DESIGN = "73201"  # 인테리어 디자인업: 종합 인테리어라 모든 공정의 후보로 본다
_DESIGN_NAME = "인테리어 디자인업"
_FINISH = "42412"  # 도배, 실내 장식 및 내장 목공사업
_FLOOR_SHOP, _FLOOR_SHOP_NAME = "47523", "벽지/장판/마루 소매업"

TRADE_INDUSTRIES: dict[str, Industries] = {
    "dobae": Industries(
        (_INTERIOR,), (_FINISH, _FLOOR_SHOP, _DESIGN), (_DESIGN_NAME, _FLOOR_SHOP_NAME)
    ),
    "mokgong": Industries((_INTERIOR,), (_FINISH, _DESIGN), (_DESIGN_NAME,)),
    "floor": Industries(
        (_INTERIOR,), (_FINISH, _FLOOR_SHOP, _DESIGN), (_DESIGN_NAME, _FLOOR_SHOP_NAME)
    ),
    "film": Industries((_INTERIOR,), (_FINISH, _DESIGN), (_DESIGN_NAME,)),
    "paint": Industries((_WET, _OLD_PAINT), ("42411", _DESIGN), (_DESIGN_NAME,)),  # 도장 공사업
    "tile": Industries(
        (_WET, _OLD_WET, _OLD_STONE), ("42491", _DESIGN), (_DESIGN_NAME,)
    ),  # 미장, 타일 및 방수 공사업
    "bath": Industries((_INTERIOR, _WET, _OLD_WET), ("42491", _DESIGN), (_DESIGN_NAME,)),
    "kitchen": Industries((_INTERIOR,), (_DESIGN,), (_DESIGN_NAME,)),
    "electric": Industries((), (_DESIGN,), (_DESIGN_NAME,)),
    "window": Industries(
        (_WINDOW, _OLD_WINDOW), ("42420", _DESIGN), (_DESIGN_NAME,)
    ),  # 유리 및 창호 공사업
}


def _name_key(s: str) -> str:
    """띄어쓰기 · 가운뎃점 · 빗금 차이를 없앤다 ('도장ㆍ습식' = '도장·습식' = '도장 습식')."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "")


def _kiscon_key(s: str) -> str:
    return _name_key(s).removesuffix("공사업")  # '실내건축' = '실내건축공사업'


def _ksic_key(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")  # 상가정보는 'F42412'처럼 대분류 글자를 붙인다
    return digits[:5]


def _index(pick, key) -> dict[str, frozenset[str]]:
    out: dict[str, set[str]] = {}
    for trade, ind in TRADE_INDUSTRIES.items():
        for name in pick(ind):
            out.setdefault(key(name), set()).add(trade)
    return {k: frozenset(v) for k, v in out.items()}


_BY_KISCON = _index(lambda i: i.kiscon, _kiscon_key)
_BY_KSIC = _index(lambda i: i.ksic, _ksic_key)
_BY_SANGGA = _index(lambda i: i.sangga, _name_key)


def ordered(trades) -> list[str]:
    """공정 키를 정해진 순서로 (DB · 화면이 늘 같은 순서를 보게)."""
    got = set(trades)
    return [t for t in TRADES if t in got]


def trades_for_kiscon(item_name: str) -> list[str]:
    return ordered(_BY_KISCON.get(_kiscon_key(item_name), ()))


def trades_for_sangga(ksic_code: str | None, sub_name: str | None) -> list[str]:
    """표준산업분류 코드나 상권업종 소분류 이름 중 하나라도 맞으면 그 공정 후보로 본다."""
    found = set(_BY_KSIC.get(_ksic_key(ksic_code or ""), ()))
    found |= _BY_SANGGA.get(_name_key(sub_name or ""), frozenset())
    return ordered(found)


def kiscon_items() -> list[str]:
    """거를 KISCON 업종 이름 (보고 · 테스트용)."""
    return sorted({n for ind in TRADE_INDUSTRIES.values() for n in ind.kiscon})
