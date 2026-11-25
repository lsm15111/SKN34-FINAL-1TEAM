"""공종 에이전트: 코드 한 벌 + 공종 설정(TradeSpec) 13개 (ADR agent-03).

- 정책 표시가 있으면 정해 둔 글 · 계산 상자를 먼저: 가격 · 기간(도배 · 목공은 계산 엔진, 10공종은 '아직 계산 안 함'),
  업체 · 제품 추천(기준만), 하자 판정(안 함 + 확인할 곳), 셀프(위험 공종은 전문 업체), 우리 집 상태(실측 때 확인).
- 그다음 카드 → 조각 문장 → 모름 (answer.knowledge).
- 도배 · 목공: 카드가 되묻는 칸(ask)이 아직 비어 있으면 하나만 되묻고, 칸 답이 오면 원래 질문 + 답으로 다시 찾는다.
- 하지 않는 일: 하자 판정, 브랜드 · 업체 추천, 10공종 금액, 다른 공종 부르기(필요하면 관문이 multi로 정함).
"""

from app.agent.v3 import templates
from app.agent.v3.answer import (
    KB,
    Part,
    Task,
    calc_box,
    drop_promise,
    knowledge,
    next_card,
    use_card,
)
from app.agent.v3.schemas import AskSlot, Choice, UiCard
from app.agent.v3.trades import BY_CODE


def primary(task: Task) -> str:
    return task.trades[0] if task.trades else "common"


def run(task: Task, kb: KB) -> Part:
    code = primary(task)
    spec = BY_CODE[code]
    part = Part(route="trade", trade=code)  # type: ignore[arg-type]
    facts = task.facts
    flags = set(task.policy)
    lines: list[str] = []
    ko = spec.ko

    if "price" in flags:
        if spec.calc and facts and facts.standard:
            lines.append(templates.PRICE_DEEP)
            box = calc_box("standard.total", facts)
            if box:
                part.calc.append(box)
        elif spec.calc:
            lines.append(templates.PRICE_DEEP_NO_PROJECT)
            part.cards.append(UiCard(kind="next_step", choices=list(templates.NO_PROJECT_NEXT)))
        elif code != "common":
            lines.append(templates.PRICE_KNOWLEDGE.format(ko=ko))
    if "period" in flags:
        if spec.calc and facts and facts.plan:
            lines.append(templates.PERIOD_PLAN)
            box = calc_box("plan.range", facts)
            if box:
                part.calc.append(box)
        elif spec.calc:
            lines.append(templates.PERIOD_NO_PROJECT)
        elif code != "common":
            lines.append(templates.PERIOD_KNOWLEDGE.format(ko=ko))
    if "vendor_reco" in flags:
        lines.append(templates.VENDOR_RECO)
        if spec.calc:
            part.cards.append(
                UiCard(kind="next_step", choices=[Choice(text="업체 보기", action="vendors")])
            )
    if "brand_reco" in flags:
        lines.append(templates.BRAND_RECO)
    if "defect_judgement" in flags:
        lines.append(templates.DEFECT)
    if "legal_case" in flags:
        lines.append(templates.OUT["legal"])
    if "diy" in flags and spec.risky_diy:
        lines.append(templates.DIY_RISKY.format(ko=ko))
    if "my_house" in flags and not ({"price", "period"} & flags):
        lines.append(templates.MY_HOUSE)
    if lines:
        part.add(
            templates.section(lines, title=f"[{ko}]", route="trade", trade=code),
            "\n".join([*lines, templates.ALLOWED]),
        )

    q = task.text
    pick = next_card(kb, task.slot, task.value) if task.slot and task.value else None
    # 카드가 정해 둔 '고른 답 → 다음 카드'(상황별 안내)
    if pick is not None and pick.card is not None:
        use_card(part, kb, pick.card, route="trade", trade=code, facts=facts)  # type: ignore[arg-type]
        how = "card"
    elif pick is not None and pick.again:
        # 둘 다 고르거나 하나만 빼서 정할 수 없으면 남은 선택지로 다시 묻기(일반 검색으로 넘기지 않음)
        part.add(
            templates.section([templates.ASK_AGAIN], title=f"[{ko}]", route="trade", trade=code),
            templates.ASK_AGAIN,
        )
        part.ask = AskSlot(
            trade=code,  # type: ignore[arg-type]
            slot=task.slot,  # type: ignore[arg-type]
            question=templates.ASK_AGAIN,
            options=pick.again,
        )
        how = "ask"
    else:
        if task.slot and task.value:  # 되물은 칸의 답: 원래 질문 + 고른 값으로 다시 찾는다
            q = f"{task.asked} {task.value}".strip()
        how = knowledge(part, kb, q, trade=code, route="trade", facts=facts, policy=task.policy)  # type: ignore[arg-type]
    if task.slot and how != "ask":
        part.ask = None  # 한 칸은 한 번만 묻는다(되묻기 반복 막기). 정할 수 없을 때만 다시 물어요
    if how == "unknown" and lines:
        part.unknown = [
            u for u in part.unknown if u != templates.UNKNOWN
        ]  # 정책 글로 이미 답했으면 '모름'은 확인할 곳만
        drop_promise(part)
    if spec.calc and not any(c.kind == "next_step" for c in part.cards):
        stage = facts.stage if facts else None
        nxt = templates.NEXT.get(stage or "", []) if facts else templates.NO_PROJECT_NEXT
        if nxt:
            part.cards.append(UiCard(kind="next_step", choices=list(nxt)))
    return part
