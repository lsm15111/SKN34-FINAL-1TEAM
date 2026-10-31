"""목공 공정 에이전트 (TradeAgent 하나). 평가 스크립트가 아래 이름들을 쓴다."""

from app.agent import trade

AGENT = trade.TradeAgent.load("carpentry", "목공", "carpentry_v1.md")
PROMPT_VERSION = AGENT.plan_prompt_version
SOURCES = AGENT.sources
PlanResult = trade.PlanResult
plan = AGENT.plan
validate = AGENT.validate
