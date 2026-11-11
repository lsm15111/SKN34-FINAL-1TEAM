"""v2 화면(커스텀 MVP v10 이식)이 쓰는 자료.

- v2_estimate_ref.json: 도배 · 목공 밖 공정의 참고 산식(평형별 수량 · 단가 범위 · 공공 단가). v10 estimate_ref.json 사본
- v2_materials.json: 믿집 자재 자료의 가격대(id · 공정 · 등급 · 브랜드 · 이름 · 가격). v10 data.json에서 뺀 것
- 공정 이름 · 공간 이름 · v10이 팀 목록에 더한 공휴일
"""

import json
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path

from app.calc.v2_ref_trade import RefMaterial

_DIR = Path(__file__).parent

CAT_KO = {
    "wallpaper": "도배",
    "floor": "바닥재",
    "tile": "타일",
    "bath": "욕실",
    "furniture": "가구",
    "carpentry": "목공",
    "film": "필름",
    "paint": "도장",
    "middoor": "중문",
    "light": "조명",
    "window": "창호",
    "finish": "마감",
}
SPACE_KO = {
    "room": "거실 · 방",
    "kitchen": "주방",
    "bath": "욕실",
    "entry": "현관",
    "window": "창호",
}

# 팀 목록(refprice/holidays.py)에 없는 공휴일: 2026-04-28 '관공서의 공휴일에 관한 규정' 개정(노동절 · 제헌절).
# 2027 대체공휴일은 우주항공청 2027 월력요항 보도 기준 (v10 HOLIDAYS_EXTRA)
HOLIDAYS_EXTRA: dict[date, str] = {
    date(2026, 5, 1): "노동절",
    date(2026, 7, 17): "제헌절",
    date(2027, 5, 3): "노동절 대체공휴일",
    date(2027, 7, 19): "제헌절 대체공휴일",
}

# 목공 자재 한 개 단위 (v10 MOK10.prod per)
PRODUCT_PER = {"door_set": "짝", "door_leaf": "짝", "slide": "세트", "hidden": "세트"}

# 도배 '기존 벽지 철거' 줄 풀이 (v10 CALC.dobae 글 그대로)
DOBAE_REMOVAL_CALC = "보통인부 노임 172,698원 × 0.01"


@cache
def estimate_ref() -> dict:
    return json.loads(
        (_DIR / "v2_estimate_ref.json").read_text(encoding="utf-8"), parse_float=Decimal
    )


@cache
def materials() -> dict[str, RefMaterial]:
    rows = json.loads((_DIR / "v2_materials.json").read_text(encoding="utf-8"))
    return {
        r["id"]: RefMaterial(
            id=r["id"],
            cat=r["cat"],
            tier=r["tier"],
            brand=r["brand"],
            name=r["name"],
            price_min=r["price"]["min"],
            price_max=r["price"]["max"],
            unit=r["price"]["unit"] or "",
        )
        for r in rows
    }
