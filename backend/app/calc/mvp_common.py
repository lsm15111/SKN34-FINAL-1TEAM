"""MVP 계산(mvp_dobae · mvp_mokgong · market_band)이 같이 쓰는 것."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import Basis, Line

# 단가 근거: 공공 기준 · 실견적 · 고른 자재 판매가 · 팀 가정값 · 업체 견적에서 확인
PriceBasis = Literal["public", "market", "pick", "assumed", "none"]
# 등급: 화면 이름은 frontend가 정한다 (지금 MVP 화면: 베이직 · 스탠다드 · 프리미엄)
Grade = Literal["economy", "basic", "premium"]


@dataclass(frozen=True)
class MvpLine(Line):
    """팀 Line에 자세한 단가 근거와 수량 풀이를 더한 줄. 팀 basis는 공공이 아닌 값을 assumed로 둔다."""

    price_basis: PriceBasis = "public"
    calc: str = ""


def team_basis(b: PriceBasis) -> Basis:
    return "public" if b == "public" else "none" if b == "none" else "assumed"


def num(x: Decimal) -> str:
    """글에 넣는 숫자: 25.0 → 25, 2.4 → 2.4"""
    return format(x.normalize(), "f")
