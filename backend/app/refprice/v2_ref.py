"""v2 화면(v10 이식)이 쓰는 자료.

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

# 예전에 여기 따로 두던 노동절 · 제헌절 4일은 refprice/holidays.py로 옮겼어요(2026-11-18, 공정표도 같은 목록을 써요).
# v2 화면이 이 이름을 합쳐 쓰므로 빈 표로 남겨요
HOLIDAYS_EXTRA: dict[date, str] = {}

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
            kind=r.get("kind", ""),
        )
        for r in rows
    }
