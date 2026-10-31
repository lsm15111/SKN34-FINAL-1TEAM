"""목공 공정 에이전트. 상담 오케스트레이터가 목공 칸을 다 채우면 도구처럼 부른다 (읽기 전용).

계산 엔진 결과를 받아 할 일 · 실측 때 확인할 것 · 주의사항을 쓴다. 숫자는 쓰지 않는다.
"""

from app.agent import llm, trade
from app.agent.schemas import TradePlan
from app.calc.mokgong import MokgongQuote

PROMPT_VERSION = "carpentry-v1"
SKILL = trade.skill("carpentry")
SYSTEM = trade.system("carpentry_v1.md", "목공 지식", SKILL)
SOURCES = trade.sources(SKILL)
PlanResult = trade.PlanResult


def validate(plan: TradePlan, step_keys: set[str]) -> tuple[TradePlan, int]:
    return trade.validate(plan, step_keys, SOURCES)


async def plan(card_text: str, q: MokgongQuote) -> PlanResult:
    raw, usage = await llm.parse(SYSTEM, trade.render(card_text, q), TradePlan)
    clean, dropped = validate(raw, {s.key for s in q.steps})
    return PlanResult(clean, dropped, usage)
