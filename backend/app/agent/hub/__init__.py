"""믿집 에이전트 허브: 총괄 에이전트(관문 + 오케스트레이터) → 공종 전문가 · 업무 도구.

- concierge.run_turn: 한 턴의 입구(chat.service가 부른다)
- experts/: 공종 전문가(폴더 하나 = 공종 하나). 지금은 바닥(floor)
- core: 도구 · LLM ↔ 도구 루프 · 턴 예산 / reply: 전문가 몫 · 대화 기억
설계 문서: docs/agent-hub.md
"""
