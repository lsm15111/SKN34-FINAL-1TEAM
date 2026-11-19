"""공종 에이전트: 코드 한 벌 + 공종 설정(TradeSpec) 13개 (ADR agent-03).

- 정책 표시가 있으면 정해 둔 글 · 계산 상자를 먼저: 가격 · 기간(도배 · 목공은 계산 엔진, 10공종은 '아직 계산 안 함'),
  업체 · 제품 추천(기준만), 하자 판정(안 함 + 확인할 곳), 셀프(위험 공종은 전문 업체), 우리 집 상태(실측 때 확인).
- 그다음 카드 → 조각 문장 → 모름 (answer.knowledge).
- 도배 · 목공: 카드가 되묻는 칸(ask)이 아직 비어 있으면 하나만 되묻고, 칸 답이 오면 원래 질문 + 답으로 다시 찾는다.
- 하지 않는 일: 하자 판정, 브랜드 · 업체 추천, 10공종 금액, 다른 공종 부르기(필요하면 관문이 multi로 정함).
"""

from app.agent.v3 import calc_lines, templates
from app.agent.v3.answer import KB, Part, Task, drop_promise, knowledge
from app.agent.v3.schemas import UiCard
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

    nums = (
        calc_lines.Lines()
    )  # 계산 엔진 값으로 쓴 답(기간 · 비용 · 추천 업체), 묶음 하나로 맨 앞에
    if "price" in flags:
        if spec.calc or code == "common":
            nums.add(calc_lines.price(code, facts, task.general, task.text))
        if not nums.lines and spec.calc:
            lines.append(templates.PRICE_DEEP_NO_PROJECT)
            part.cards.append(UiCard(kind="next_step", choices=list(templates.NO_PROJECT_NEXT)))
        elif not nums.lines and code != "common":
            lines.append(templates.PRICE_KNOWLEDGE.format(ko=ko))
    if "period" in flags:
        before = len(nums.lines)
        if spec.calc or code == "common":
            nums.add(calc_lines.period(code, facts, task.general))
        if len(nums.lines) == before and not spec.calc and code != "common":
            lines.append(templates.PERIOD_KNOWLEDGE.format(ko=ko))
    if "vendor_reco" in flags and (spec.calc or code == "common"):
        nums.add(calc_lines.vendors(facts))
    elif "vendor_reco" in flags:
        lines.append(templates.VENDOR_RECO)
    if nums.lines:
        part.add(
            templates.section(
                nums.lines, title=f"[{ko}]", route="trade", trade=code, source="calc"
            ),
            f"{nums.calc_text}\n{templates.ALLOWED}",
            calc_text=nums.calc_text,
        )
        part.calc += nums.boxes
        part.cards += nums.cards
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
    if task.slot and task.value:  # 되물은 칸의 답: 원래 질문 + 고른 값으로 다시 찾는다
        q = f"{task.asked} {task.value}".strip()
    how = knowledge(
        part, kb, q, trade=code, route="trade", facts=facts, policy=task.policy,  # type: ignore[arg-type]
        also=task.trades[1:],  # 관문이 함께 고른 공종의 카드도 찾는다(검색 무게는 첫 공종)
    )  # fmt: skip
    if task.slot:
        part.ask = None  # 한 칸은 한 번만 묻는다(되묻기 반복 막기)
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
