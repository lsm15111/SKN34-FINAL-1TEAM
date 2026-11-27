"""바닥 상담의 기본 설정.

- 깊이는 'knowledge'예요. 계산 엔진에 바닥 항목이 생기면 'deep' · calc=True로 올려요.
- 정해 둔 글(주의 · 실측 때 볼 것 · 준비할 것)에는 숫자를 쓰지 않아요.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.v3.trades import Slot, TradeSpec

# 무늬 이름(헤링본) · 'PVC 시트'는 벽 타일 · 시트지(필름)에도 써서 넣지 않아요. 헤링본 마루 · PVC 장판은 '마루' · '장판'으로 잡혀요
# 매트는 층간소음 · 놀이방 매트(바닥에 까는 것)만: 매트리스 · 전기 매트 · 욕실 매트는 빼요
WORDS = (
    r"바닥재|강마루|강화마루|원목마루|합판마루|온돌마루|마루|장판|모노륨|데코타일|LVT|카펫|카페트|"
    r"(?<!전기 )(?<!전기)(?<!욕실 )(?<!욕실)매트(?!리스)|"
    r"(?:PVC|비닐)\s*타일|셀프\s*레벨링|폴리싱|층간소음|바닥(?!\s*타일)"
)


def build(spec_type: type[TradeSpec], slot_type: type[Slot]) -> TradeSpec:
    return spec_type(
        "floor",
        "바닥",
        "knowledge",
        WORDS,
        ("바닥재",),
        8,
        cautions=("바닥재는 도배가 끝난 뒤에 깔아요.",),
        survey=(
            "바닥 수평 · 들뜸",
            "기존 바닥 종류 · 습기",
            "문턱 · 걸레받이 높이",
            "난방 배관 위치",
        ),
        prep=("바닥에 둔 짐 옮기기", "살면서 공사하면 방을 나눠 비우기"),
        check_where="실측 때 바닥 업체",
    )
