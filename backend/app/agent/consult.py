"""상담 라우터 (LLM 한 번): 대화에서 바꿀 칸과 공정별 질문을 뽑고 고객 말에 짧게 답한다.

공정 지식(SKILL)은 넣지 않는다. 질문은 공정 전문가(agent.trade)가 답한다. 그래서 시스템 프롬프트가 짧고,
공정 칸 목록은 레지스트리로 만든 고정 글이라 프롬프트 캐시가 맞는다.
무엇을 물을지, 뽑은 값이 맞는지, 언제 계산하고 누구를 부를지는 코드(consult.service)가 정한다.
"""

import json
from pathlib import Path

from app.agent import llm
from app.agent.schemas import RouterOut
from app.agent.trade import NUMBER_CLAIM

PROMPT_VERSION = "consult-v5"
_PROMPT = (Path(__file__).parent / "prompts" / "consult_v5.md").read_text(encoding="utf-8")
_CATALOG_HEAD = (
    "# 공정과 칸\n\n"
    "칸 줄: 칸 이름 | 화면 말 | 종류(choice 하나 · multi 여러 개 · count 숫자) | 값=뜻 | 구분 설명\n\n"
)


def system(catalog: str) -> str:
    """프롬프트 + 레지스트리 전 공정의 칸 목록 (공정이 바뀌지 않는 한 같은 글)"""
    return _PROMPT + "\n\n" + _CATALOG_HEAD + catalog


async def route(
    system_text: str, turns: list[tuple[str, str]], trades: list[str], card: dict
) -> tuple[RouterOut, llm.Usage]:
    convo = "\n".join(f"{'고객' if role == 'user' else '상담사'}: {text}" for role, text in turns)
    user = (
        f"고객 공정: {', '.join(trades)}\n"
        f"지금까지 채운 칸: {json.dumps(card, ensure_ascii=False, sort_keys=True)}\n\n"
        f"<conversation>\n{convo}\n</conversation>"
    )
    return await llm.parse(system_text, user, RouterOut, role="router")


def reply_ok(text: str) -> bool:
    """비었거나 너무 길거나 금액 · 기간 · 면적을 지어낸 답은 쓰지 않는다."""
    return bool(text.strip()) and len(text) <= 300 and not NUMBER_CLAIM.search(text)
