"""바닥 상담의 기본 설정(docs/v3/floor-agent.md 4.2).

- 깊이는 아직 'knowledge'예요. 계산 엔진 바닥 줄(W4 · W5)이 붙으면 'deep' · calc=True로 올려요.
- 되묻기 칸은 고객이 단추로 고른 값만 쓰고 에이전트는 저장하지 않아요. 기본 정보 칸(W3)이 생기면 fact로 이어요.
- 정해 둔 글(주의 · 칸 질문 · 단추)에는 숫자를 쓰지 않아요.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.v3.trades import Slot, TradeSpec

WORDS = (
    r"바닥재|강마루|강화마루|원목마루|합판마루|온돌마루|마루|장판|모노륨|데코타일|헤링본|"
    r"PVC\s*(?:타일|시트|장판)|비닐\s*(?:타일|시트|장판)|셀프\s*레벨링|폴리싱|층간소음|바닥(?!\s*타일)"
)


def build(spec_type: type[TradeSpec], slot_type: type[Slot]) -> TradeSpec:
    return spec_type(
        "floor",
        "바닥",
        "knowledge",
        WORDS,
        ("바닥재",),
        8,
        cautions=("마루는 도배 전에, 장판 · 데코타일은 도배 뒤에 깔아요.",),
        survey=(
            "바닥 수평 · 들뜸",
            "기존 바닥 종류 · 습기",
            "문턱 · 걸레받이 높이",
            "난방 배관 위치",
        ),
        prep=("바닥에 둔 짐 옮기기", "살면서 공사하면 방을 나눠 비우기"),
        slots=(
            slot_type(
                "floor.kind",
                "바닥재는 어떤 걸로 생각하세요?",
                ("마루", "장판", "데코타일", "아직 몰라요"),
            ),
            slot_type(
                "floor.maru_type",
                "마루는 어떤 종류로 보세요?",
                ("강마루", "강화마루", "원목마루", "아직 몰라요"),
            ),
            slot_type(
                "floor.sheet_thick",
                "장판 두께는 어느 쪽으로 보세요?",
                ("얇은 장판", "보통 두께", "두꺼운 쿠션 장판", "아직 몰라요"),
            ),
            slot_type(
                "floor.existing",
                "지금 바닥에는 무엇이 깔려 있어요?",
                ("장판", "강마루", "강화마루", "타일", "잘 몰라요"),
            ),
            slot_type(
                "floor.remove",
                "기존 바닥은 걷어내고 새로 까세요?",
                ("걷어내요", "위에 덧대요", "아직 몰라요"),
            ),
            slot_type(
                "floor.baseboard",
                "걸레받이도 새로 하세요?",
                ("새로 해요", "그대로 둬요", "아직 몰라요"),
            ),
            slot_type(
                "floor.threshold",
                "방 문턱은 없애실 건가요?",
                ("없애요", "그대로 둬요", "아직 몰라요"),
            ),
        ),
        check_where="실측 때 바닥 업체",
    )
