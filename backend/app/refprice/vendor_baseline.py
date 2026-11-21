"""업체 단가표 1201~1209 줄의 시장 기준값. 업체가 넣은 값이 기준과 10배 넘게 다르면 경고해요(리드 결정 L01).

- 단위는 9판 업체 단가표(D02)를 따라요. 줄마다 `unit_ko`로 분명히 보여요.
- 기준값(`base`)은 경고에만 써요. 가견적 금액은 업체 단가로만 계산해요.
- 자료: data/v3/vendor_baseline/baseline.json (`python -X utf8 data/v3/scripts/vendor_baseline.py`)
- 1209 합지 부자재(2026-11-21 더함)는 저장소 밖 시장 실견적 모음(d10- price-sources `cases.csv` 본표)의
  합지 집 부자재 줄 요약 숫자만 옮겼어요. 판은 `vendor-base-2026.11b`이고, 다른 줄은 앞 판 그대로예요.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

VERSION = "vendor-base-2026.11"
CHECKED = date(2026, 11, 18)
WARN_RATIO = 10
SOURCE_FILE = "data/v3/vendor_baseline/baseline.json"
# 1209 합지 부자재 줄 판 · 확인한 날(자료 파일 밖, 시장 실견적 모음)
VERSION_B = "vendor-base-2026.11b"
CHECKED_B = date(2026, 11, 21)

Stat = Literal["median", "mean", "upper_estimate"]


@dataclass(frozen=True)
class VendorBase:
    code: str  # 화면 코드 1201~1209
    key: str  # 계산 엔진 PRICE_ROWS['dobae_v3'] 키
    name: str
    unit: str  # 수량 단위: 공급 평 · 벽지 평 · 품 · 대
    unit_ko: str  # 화면에 붙일 단위 설명
    base: int  # 기준값(원/단위, 부가세 별도)
    stat: Stat  # base를 만든 통계. upper_estimate는 직접 자료가 없어 경비 줄에서 잡은 상한
    p25: int
    p75: int
    n: int
    source: str
    version: str = VERSION
    checked: date = CHECKED

    @property
    def warn_above(self) -> int:
        return self.base * WARN_RATIO

    @property
    def warn_below(self) -> int:
        return math.ceil(self.base / WARN_RATIO)


@dataclass(frozen=True)
class PriceWarning:
    code: str
    kind: Literal["too_high", "too_low"]
    ratio: float  # 넣은 값 ÷ 기준값
    message: str  # 해요체 화면 글


VENDOR_BASE_2026_11: dict[str, VendorBase] = {
    b.code: b
    for b in (
        VendorBase("1201", "putty", "퍼티작업", "공급 평", "공급면적 1평(3.3058㎡)당", 15_625, "median",
                   15_267, 17_935, 8, "실견적 퍼티 줄(품 × 일당) ÷ 공급 평형"),
        VendorBase("1203", "paper_hapji", "합지", "벽지 평", "벽지(도배지) 면적 1평(3.3058㎡)당", 4_577, "mean",
                   4_608, 4_608, 58, "광폭합지 롤값 평균 ÷ 16.5㎡ × 3.3058(wallpaper_market)"),
        VendorBase("1204", "paper_silk", "실크", "벽지 평", "벽지(도배지) 면적 1평(3.3058㎡)당", 10_749, "mean",
                   9_016, 13_223, 279, "실크 롤값 평균 ÷ 16.5㎡ × 3.3058(wallpaper_market)"),
        VendorBase("1205", "material", "부자재", "공급 평", "공급면적 1평(3.3058㎡)당", 6_875, "median",
                   6_279, 7_586, 129, "실견적 부자재 줄 ÷ 공급 평형(실크 7,059 · 합지 3,600)"),
        VendorBase("1209", "material_hapji", "합지 부자재", "공급 평", "공급면적 1평(3.3058㎡)당", 3_333,
                   "median", 2_739, 3_820, 87,
                   "시장 실견적 합지 집 부자재 줄 ÷ 공급 평형(영진벽지 59 · 대동벽지 27 · 디시 1, 2025~2026)",
                   VERSION_B, CHECKED_B),
        VendorBase("1206", "labor", "인건비", "품", "1품(1명이 하루 하는 일)당", 270_000, "median",
                   250_000, 290_000, 22, "실견적 도배 일당(견적서 인건비 줄 ÷ 인원)"),
        VendorBase("1207", "meal", "식대", "품", "1품당", 10_000, "upper_estimate",
                   6_000, 16_000, 78, "경비(식대 · 운반) 한 집당 5만 원 ÷ 집당 5품 — 식대만 적은 자료가 없어요"),
        VendorBase("1208", "truck", "운송비", "대", "1대당", 50_000, "upper_estimate",
                   30_000, 80_000, 78, "경비(식대 · 운반) 한 집당 5만 원 — 운송비만 적은 자료가 없어요"),
    )
}  # fmt: skip


def vendor_base(code: str) -> VendorBase:
    """1201~1209 줄의 기준값. 없는 코드면 KeyError."""
    return VENDOR_BASE_2026_11[code]


def price_warning(code: str, value: int) -> PriceWarning | None:
    """업체가 넣은 단가(원/단위)가 기준의 10배를 넘거나 10분의 1보다 작으면 경고. 0 이하는 이 함수가 아니라 입력 검사에서 막아요."""
    if value <= 0:
        raise ValueError("단가는 0보다 커야 해요")
    b = VENDOR_BASE_2026_11[code]
    ratio = value / b.base
    if value > b.warn_above:  # 9판 D02 글 그대로(copy-fixes CF-79)
        return PriceWarning(
            code, "too_high", ratio, "기준 단가의 10배쯤이에요. 0을 더 넣지 않았나요?"
        )
    if value < b.warn_below:  # 같은 꼴(문제 + 고치는 법, copy-guide W9)
        return PriceWarning(
            code, "too_low", ratio, "기준 단가의 10분의 1쯤이에요. 0을 빠뜨리지 않았나요?"
        )
    return None
