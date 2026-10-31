"""도배 공정 에이전트 (TradeAgent 하나). 평가 스크립트가 아래 이름들을 쓴다."""

from app.agent import trade

AGENT = trade.TradeAgent.load("wallpaper", "도배", "wallpaper_v1.md")
PROMPT_VERSION = AGENT.plan_prompt_version
SKILL = trade.skill("wallpaper")
SOURCES = AGENT.sources
PlanResult = trade.PlanResult
plan = AGENT.plan
validate = AGENT.validate
