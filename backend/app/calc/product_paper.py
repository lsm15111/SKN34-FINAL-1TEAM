"""조사로 찾은 벽지 판매가로 이 집 도배 금액 다시 세기(2026-11-23 사용자 'A안으로 해보고').

- 벽지 값 = 롤 수(calc.rolls: 판매처 규격 또는 그 벽지 종류 표준 롤, 올림) × 1롤 판매가(판매처 페이지에 적힌 값).
  판매가는 고객이 사는 값이라 부가세 포함으로 봐요(판매처 표시 값 그대로, 공급가로 나누지 않아요).
- 나머지 = 같은 벽지 종류 표준견적서에서 도배지 줄을 뺀 합계(부가세 포함, calc.dobae.paper_split).
  '벽지를 직접 사면'과 같은 값이에요(시공 · 부자재 · 퍼티 · 운송 …).
- 합계 = 나머지 + 벽지 값. 여분 롤(1~2롤)은 셈 밖이에요(rolls.SPARE).
- DB · HTTP · 시계를 모르는 순수 함수이고 금액은 원 정수예요.
"""

from dataclasses import dataclass

from app.calc.dobae import PaperSplit
from app.calc.rolls import RollNeed


@dataclass(frozen=True)
class ProductPaper:
    rolls: RollNeed
    price_won: int  # 1롤 판매가(판매처 표시 값, 부가세 포함으로 봄)
    paper_won: int  # 벽지 값 = 롤 수 × 1롤 판매가
    rest_won: int  # 벽지 뺀 표준견적서 합계(부가세 포함)
    total_won: int  # 나머지 + 벽지 값
    standard_won: int  # 같은 벽지 종류 표준견적서 합계(벽지 포함, 부가세 포함)


def product_paper(split: PaperSplit, rolls: RollNeed, price_won: int) -> ProductPaper:
    """표준견적서 벽지 나눔(split) + 롤 수 + 1롤 판매가 → 이 제품으로 센 도배 합계."""
    if price_won <= 0:
        raise ValueError("판매가는 0보다 커야 해요")
    paper = rolls.count * price_won
    rest = split.without_paper.total
    return ProductPaper(
        rolls=rolls,
        price_won=price_won,
        paper_won=paper,
        rest_won=rest,
        total_won=rest + paper,
        standard_won=split.with_paper.total,
    )
