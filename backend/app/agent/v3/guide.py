"""가이드: 처음 고객의 궁금증 · 시작 순서 · 서비스 · 공통 지식(계약 · 하자 · 관리사무소). 프로젝트 없이도 돈다.

- 일반 금액 · 기간은 숫자 대신 표준견적서 · 예상 공정표(계산 엔진)로 안내한다(프로젝트가 있으면 계산 상자).
- 답: 정책 글 → 서비스 카드 · 공통 카드(없으면 다른 공종 카드도) → 조각 문장 → 모름 + 단계별 다음 할 일.
"""

from app.agent.v3 import calc_lines, templates
from app.agent.v3.answer import KB, Part, Task, drop_promise, knowledge
from app.agent.v3.gate import START
from app.agent.v3.schemas import UiCard

GENERAL_PRICE = (
    "일반 시세 숫자는 말하지 않아요. 기본 정보를 넣으면 이 집 조건으로 표준견적서를 계산해 드려요."
)


def run(task: Task, kb: KB) -> Part:
    part = Part(route="guide", trade="common")
    f = task.facts
    flags = set(task.policy)
    lines: list[str] = []
    # 계산 엔진 값(기간 · 비용 · 추천 업체). 공종 없는 일반 질문은 도배 기준으로 센다
    nums = calc_lines.Lines()
    if "price" in flags:
        nums.add(calc_lines.price("common", f, task.general, task.text))
        if not nums.lines:
            lines.append(GENERAL_PRICE)
    if "period" in flags:
        nums.add(calc_lines.period("common", f, task.general))
    if "vendor_reco" in flags:
        nums.add(calc_lines.vendors(f))
    if nums.lines:
        part.add(
            templates.section(nums.lines, route="guide", source="calc", table=nums.table),
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
    if "my_house" in flags and not ({"price", "period"} & flags):
        lines.append(templates.MY_HOUSE)
    if lines:
        part.add(templates.section(lines, route="guide"), "\n".join([*lines, templates.ALLOWED]))
    if START.search(task.text) and not flags - {"my_house"}:
        # 시작 순서 질문: 믿집 흐름을 단계로 보여 주고, 지식 검색은 하지 않아요(엉뚱한 공종 조각이 섞여서)
        steps = [*templates.START_STEPS, *([templates.START_HERE[f.stage]] if f else [])]
        part.add(
            templates.section(steps, title="[시작 순서]", route="guide"),
            "\n".join([*steps, templates.ALLOWED]),
        )
        how = "template"
    else:
        how = knowledge(
            part, kb, task.text, trade="common", route="guide", facts=f, policy=task.policy
        )
    if how == "unknown" and nums.lines:
        part.unknown = []  # 계산 엔진 값으로 이미 답했으면 '모름' 줄을 붙이지 않아요
        drop_promise(part)
    elif how == "unknown" and lines:
        part.unknown = [
            u for u in part.unknown if u != templates.UNKNOWN
        ]  # 정책 글로 답했으면 확인할 곳만
        drop_promise(part)
    nxt = templates.NEXT.get(f.stage, []) if f else templates.NO_PROJECT_NEXT
    if nxt:
        part.cards.append(UiCard(kind="next_step", choices=list(nxt)))
    return part
