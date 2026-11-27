"""바닥 전문가: 장판 · 마루 · 데코타일을 고르고, 업체와 이야기하고, 공사 전후를 챙기게 돕는다.

- 지식: pack.json(자재 · 조건 · 맞춤 규칙 · 체크리스트 · 업체 질문, 문장마다 근거) + 바닥 무게 검색 + 바닥 답 카드
- 도구: tools.py · 무료 모드: offline.py · 지시문: prompt_v1.md
- 금액 · 기간은 계산 엔진이 바닥을 다루기 전까지 말하지 않는다(정해 둔 글).
"""

from pathlib import Path

from app.agent.hub.experts.base import Expert, load_pack
from app.agent.hub.experts.floor import offline, tools

HERE = Path(__file__).parent
PROMPT_VERSION = "floor_v1"


def build() -> Expert:
    return Expert(
        code="floor",
        pack=load_pack(HERE / "pack.json"),
        prompt=(HERE / "prompt_v1.md").read_text(encoding="utf-8"),
        prompt_version=PROMPT_VERSION,
        tools=tools.tools(),
        offline=offline.run,
    )
