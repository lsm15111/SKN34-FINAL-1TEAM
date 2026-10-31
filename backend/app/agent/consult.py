"""상담 오케스트레이터의 LLM 부분: 대화에서 칸 값을 뽑고 고객 말에 짧게 답한다.

무엇을 물을지, 언제 계산하고 공정 에이전트를 부를지는 코드(consult.service)가 정한다.
"""

import json
import re
from pathlib import Path

from app.agent import llm
from app.agent.schemas import CardUpdate

PROMPT_VERSION = "consult-v2"
_DIR = Path(__file__).parent
SKILL = (_DIR / "skills" / "wallpaper" / "SKILL.md").read_text(encoding="utf-8")
SYSTEM = (
    (_DIR / "prompts" / "consult_v2.md").read_text(encoding="utf-8") + "\n\n# 도배 지식\n\n" + SKILL
)

# 답에 금액 · 기간 · 면적을 새로 만들어 넣었으면 쓰지 않는다 (숫자는 계산 엔진만)
_NUMBER_CLAIM = re.compile(r"\d[\d,.]*\s*(원|만|천|억|%|일|시간|주|㎡|m2|제곱)")


async def extract(turns: list[tuple[str, str]], card: dict) -> tuple[CardUpdate, llm.Usage]:
    convo = "\n".join(f"{'고객' if role == 'user' else '상담사'}: {text}" for role, text in turns)
    user = (
        f"지금까지 채운 칸: {json.dumps(card, ensure_ascii=False, sort_keys=True)}\n\n"
        f"<conversation>\n{convo}\n</conversation>"
    )
    return await llm.parse(SYSTEM, user, CardUpdate)


def reply_ok(text: str) -> bool:
    return bool(text.strip()) and len(text) <= 300 and not _NUMBER_CLAIM.search(text)
