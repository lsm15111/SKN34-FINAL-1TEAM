"""에이전트가 내는 몫(Reply)과 대화 기억(Memory).

- Reply는 v3 Part를 넓힌 것이다. v3 담당(가이드 · 견적 설명 · 일정 · 아직 옮기지 않은 공종)의 몫과 섞어
  v3 합치기(orchestrator.merge) · 출력 검사를 그대로 쓴다.
- 더한 칸: 업체에 보낼 말(vendor) · 이번 턴에 알게 된 조건(memory) · 부른 도구 · 지시문 판 · 어느 길로 답했는지(how).
- Memory는 대화 하나의 일하는 기억이다. 공종별 조건(브리프)을 모아 다음 턴 · 다른 전문가가 이어 쓴다.
  저장은 chat.service가 한다(에이전트는 저장하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.v3.answer import Part

How = Literal["llm", "offline", "legacy"]


@dataclass
class Reply(Part):
    agent: str = ""  # floor · concierge · v3:guide …
    vendor: list[str] = field(default_factory=list)  # 업체에 이렇게 물어보세요(고객이 복사해 보냄)
    memory: dict[str, str] = field(default_factory=dict)  # 이번 턴에 알게 된 조건 칸 → 값
    tools: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    how: How = "offline"

    @classmethod
    def of(cls, part: Part, agent: str, how: How = "legacy") -> Reply:
        """v3 담당의 몫을 그대로 옮긴다(문장을 다시 쓰지 않음)."""
        if isinstance(part, Reply):
            return part
        return cls(
            sections=part.sections, calc=part.calc, cards=part.cards, ask=part.ask,
            unknown=part.unknown, suggest=part.suggest, used_cards=part.used_cards,
            used_chunks=part.used_chunks, dropped=part.dropped, route=part.route, trade=part.trade,
            scores=part.scores, agent=agent, how=how,
        )  # fmt: skip

    def text(self, limit: int = 600) -> str:
        """다른 에이전트(총괄)에게 넘기는 짧은 요약: 묶음 문장 · 모름 · 되묻기."""
        lines = [x.text for s in self.sections for x in s.sentences]
        lines += self.unknown
        if self.ask is not None:
            lines.append(f"(되묻기) {self.ask.question}")
        return "\n".join(lines)[:limit] or "(답할 거리를 찾지 못했어요)"


class Asked(BaseModel):
    """되물은 칸. 다음 턴의 짧은 답('어린 아이가 있어요')을 그 전문가가 받는다."""

    trade: str
    slot: str
    q: str = ""  # 되물은 원래 질문


class Memory(BaseModel):
    """대화 하나의 일하는 기억(지워져도 다시 물으면 되는 값만)."""

    brief: dict[str, str] = Field(default_factory=dict)  # 'floor.family' → '어린 아이'
    last_trade: str | None = None
    asked: Asked | None = None

    def remember(self, updates: dict[str, str]) -> None:
        for k, v in updates.items():
            if k and v:
                self.brief[k[:40]] = v[:40]
        if len(self.brief) > 40:  # 오래된 칸부터 덜어 낸다
            for k in list(self.brief)[: len(self.brief) - 40]:
                del self.brief[k]

    def of_trade(self, code: str) -> dict[str, str]:
        return {k: v for k, v in self.brief.items() if k.startswith(f"{code}.")}
