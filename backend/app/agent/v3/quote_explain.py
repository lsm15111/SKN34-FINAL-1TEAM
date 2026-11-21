"""견적 설명: 계산 엔진이 낸 표준견적서 줄 · 가견적 차이 · 실측 견적서 비교를 정해 둔 글 + 계산 상자로 풀이한다.

금액을 만들지 않는다. 상자에 옮기는 값은 ProjectFacts(계산 엔진 결과) 그대로다.
업체 파일 · 메모 글은 풀이에 넣지 않는다(데이터 칸만). '파일을 열어 보세요 · 채팅으로 물어보세요'로 넘긴다.
"""

import re

from app.agent.v3 import screen, templates
from app.agent.v3.answer import KB, Part, Task, calc_box, knowledge, line_box, screen_box
from app.agent.v3.schemas import (
    CalcBox,
    Choice,
    ProjectFacts,
    ScreenLineFact,
    StandardFacts,
    StandardLineFact,
    UiCard,
    VendorScreenFacts,
)
from app.knowledge import bm25
from app.knowledge.suggest import COMMON

ESTIMATE_Q = re.compile(
    r"가견적|업체\s*(?:견적|금액)이?\s*(?:왜|달라|차이)|업체마다|업체끼리|어디가\s*(?:비싸|싸)"
)
VENDOR_QUOTE_Q = re.compile(
    r"실측\s*견적서?|받은\s*견적서|견적서\s*(?:두|세|2|3)\s*(?:곳|장|개)|비교"
)
VAT_Q = re.compile(r"부가세|공급가|VAT", re.IGNORECASE)
# 보던 업체 가견적을 무엇으로 견줄지 묻는 말(무료 모드 길. LLM 모드는 질문 분석이 맡을 자리예요)
COMPARE_Q = re.compile(
    r"비교|견주|견줘|뭘\s*(?:위주로\s*)?봐|무엇을\s*(?:위주로\s*)?봐|어떤\s*(?:걸|것을?)\s*봐"
)
# 줄 이름에 없는 말 → 줄 이름 낱말 (화면 말 그대로)
ALIAS = {
    "뜯": "철거",
    "떼": "철거",
    "벽지값": "벽지",
    "밑지": "초배지",
    "빠데": "퍼티",
    "인건비": "시공",
    "품삯": "시공",
}


def _words(t: str) -> set[str]:
    return {g for g in bm25.grams(t) if len(g) == 2 and g not in COMMON}


def match_line(q: str, lines: list[StandardLineFact]) -> StandardLineFact | None:
    for k, v in ALIAS.items():
        if k in q:
            q = f"{q} {v}"
    qw = _words(q)
    best: tuple[float, StandardLineFact] | None = None
    for ln in lines:
        nw = _words(ln.name)
        if not nw:
            continue
        s = len(qw & nw) / len(nw)
        if s > 0 and (best is None or s > best[0]):
            best = (s, ln)
    return best[1] if best and best[0] >= 0.3 else None


def match_screen_line(q: str, lines: list[ScreenLineFact]) -> ScreenLineFact | None:
    """보던 화면의 가견적 줄을 고객 화면 이름으로 맞춰요(screen.first_named). 여럿이면 질문에서 먼저 나온 줄."""
    i = screen.first_named(q, [ln.name for ln in lines])
    return lines[i] if i is not None else None


def _screen_line(
    part: Part, lines: list[str], allowed: list[str], ln: ScreenLineFact, v: VendorScreenFacts,
    f: ProjectFacts,
) -> None:  # fmt: skip
    """가견적 줄 하나: 무엇을 곱했는지 · 수량 단위 · 품 세는 법 · 표준에 없는 줄인지. 숫자는 상자에만."""
    eun = templates.josa(ln.name, "은", "는")
    if ln.unit_price is None and ln.included_in:
        lines.append(templates.SCREEN_INCLUDED.format(eun=eun))
    else:
        who = templates.josa(v.vendor, "이", "가") if v.vendor else "업체가"
        lines.append(templates.SCREEN_LINE.format(name=ln.name, vendor=who, unit=ln.unit))
        if ln.basis:
            lines.append(templates.SCREEN_BASIS.format(basis=ln.basis))
    if (
        ln.note and ln.unit != "품"
    ):  # 인건비 '품 = 1명이 하루 하는 일'은 수량 단위 문장이 이미 말해요
        lines.append(
            templates.SCREEN_NOTE.format(name=ln.name, note=templates.josa(ln.note, "이", "가"))
        )
    if ln.unit == "품":
        lines.append(templates.SCREEN_MAN_DAY)
        if f.living == "living":
            lines.append(templates.SCREEN_MAN_DAY_LIVING)
    if ln.optional:  # '선택' 줄(퍼티 · 운송비, ADR 0006): 표준견적서 선택 줄과 같은 말
        lines.append(templates.LINE_STATE["optional"].format(eun=eun))
    elif not ln.in_standard:
        lines.append(templates.SCREEN_EXTRA.format(eun=eun))
    m = ln.market
    if m is not None:
        tpl = templates.SCREEN_MARKET if m.p25 < m.p75 else templates.SCREEN_MARKET_ONE
        lines.append(
            tpl.format(
                n=m.n,
                name=ln.name,
                basis=ln.basis or f"{ln.unit} 1",
                stat="가운데 값이" if m.stat == "median" else "평균이",
                base=f"{m.base:,}",
                p25=f"{m.p25:,}",
                p75=f"{m.p75:,}",
                ym=f"{m.checked.year}.{m.checked.month}",
            )
        )
    part.calc.append(screen_box(ln, v.vendor))
    allowed += [ln.name, v.vendor, ln.unit, ln.basis]


def _screen_compare(
    part: Part, lines: list[str], allowed: list[str], v: VendorScreenFacts, st: StandardFacts,
    f: ProjectFacts,
) -> None:  # fmt: skip
    """보던 업체 가견적을 견줄 때 볼 것: 같은 수량 · 표준에 없는 줄 · 실측 뒤 정하는 줄.
    표준견적서와 견준 %는 글 · 계산 상자에 넣지 않아요(사용자 결정 2026-11-21)."""
    lines.append(templates.SCREEN_COMPARE_SAME)
    # 표준견적서에 없는 줄. '선택' 줄(퍼티 · 운송비)은 표준견적서에도 선택 줄로 있고 가견적 합계 밖이라 빼요
    extra = [x.name for x in v.lines if not x.in_standard and not x.optional and x.amount > 0]
    if extra:
        lines.append(templates.SCREEN_COMPARE_EXTRA.format(lines=" · ".join(extra)))
    after = [x.name for x in st.lines if x.state == "after_visit"]
    if after:
        names = [*after[:-1], templates.josa(after[-1], "은", "는")]
        lines.append(templates.SCREEN_COMPARE_AFTER.format(lines=" · ".join(names)))
    part.calc.append(CalcBox(label=f"{v.vendor} 가견적", ref="screen.vendor.total", amount=v.total))
    box = calc_box("standard.total", f)
    if box:
        part.calc.append(box)
    part.cards.append(
        UiCard(kind="next_step", choices=[Choice(text="업체 보기", action="vendors")])
    )
    allowed += [v.vendor, *extra, *after]


def run(task: Task, kb: KB) -> Part:
    part = Part(route="quote_explanation")
    f = task.facts
    q = task.text
    if f is None or f.standard is None:
        part.add(
            templates.section([templates.NO_STANDARD], route="quote_explanation"),
            templates.NO_STANDARD,
        )
        part.cards.append(UiCard(kind="next_step", choices=list(templates.NO_PROJECT_NEXT)))
        return part
    st = f.standard
    lines: list[str] = []
    allowed: list[str] = []
    trade = task.trades[0] if task.trades else None
    seen = (
        f.screen.vendor if f.screen else None
    )  # 업체 자세히 화면에서 물으면 그 업체 가견적 줄부터 맞춰요
    # 질문 분석기가 항목 · 할 일을 골랐으면(LLM 모드 데이터 화면) 글 맞추기 대신 그 줄 · 그 비교로 답해요
    item, want = task.item, task.want
    sline = None
    if seen is not None and item and item.startswith("vendor."):
        sline = next((x for x in seen.lines if f"vendor.{x.key}" == item), None)
    elif seen is not None and item is None:
        sline = match_screen_line(q, seen.lines)
    std_item = next((x for x in st.lines if f"standard.{x.key}" == item), None) if item else None
    compare = want == "compare" and std_item is None and sline is None
    if seen is not None and sline is not None:
        _screen_line(part, lines, allowed, sline, seen, f)
        trade = trade or "dobae"
    elif (
        std_item is None
        and f.estimates
        and ((compare and seen is None) or (want is None and ESTIMATE_Q.search(q)))
    ):
        lines.append(templates.ESTIMATE_GAP)
        for i, e in enumerate(f.estimates[:3]):
            part.calc.append(
                CalcBox(label=f"{e.vendor} 가견적", ref=f"estimates.{i}.total", amount=e.total)
            )
            up = sorted((x for x in e.lines if x.diff > 0), key=lambda x: -x.diff)[:2]
            if up:
                lines.append(
                    templates.ESTIMATE_GAP_TOP.format(
                        vendor=templates.josa(e.vendor, "은", "는"),
                        lines=" · ".join(x.name for x in up),
                    )
                )
                part.calc.extend(
                    CalcBox(
                        label=f"{e.vendor} {x.name}",
                        ref=f"estimates.{i}.{x.key}",
                        amount=x.diff,
                        note="줄 차이",
                    )
                    for x in up
                )
            if e.separate:
                lines.append(
                    templates.ESTIMATE_SEPARATE.format(
                        vendor=templates.josa(e.vendor, "은", "는"),
                        lines=" · ".join(e.separate[:3]),
                    )
                )
            allowed.append(e.vendor)
        part.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="업체 보기", action="vendors")])
        )
    elif want is None and VENDOR_QUOTE_Q.search(q) and "실측" in q:
        lines.append(templates.QUOTE_COMPARE)
        part.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="실측 견적서 비교", action="quotes")])
        )
    elif seen is not None and (
        compare or (want is None and std_item is None and COMPARE_Q.search(q))
    ):
        _screen_compare(part, lines, allowed, seen, st, f)
        trade = trade or "dobae"
    else:
        ln = std_item or (match_line(q, st.lines) if item is None else None)
        if ln is not None:
            key = (ln.key, ln.state)
            text = templates.LINE_STATE_SPECIAL.get(key) or templates.LINE_STATE[ln.state].format(
                name=ln.name, eun=templates.josa(ln.name, "은", "는")
            )
            lines.append(text)
            part.calc.append(line_box(ln))
            trade = trade or ln.trade
            allowed.append(ln.name)
        else:
            lines.append(templates.STANDARD_IS)
            box = calc_box("standard.total", f)
            if box:
                part.calc.append(box)
        if VAT_Q.search(q):
            part.calc.append(CalcBox(label="공급가", ref="standard.supply", amount=st.supply))
            part.calc.append(CalcBox(label="부가세", ref="standard.vat", amount=st.vat))
    part.add(
        templates.section(lines, route="quote_explanation", trade=trade),
        "\n".join([*lines, *allowed, templates.ALLOWED]),
    )
    # 줄 풀이에 이어 용어 · 견적 읽기 카드가 맞으면 붙인다(모름 문장은 붙이지 않음: 이미 계산으로 답함)
    how = knowledge(
        part, kb, q, trade=trade, route="quote_explanation", facts=f, allow_extract=False
    )
    if how == "unknown":
        part.unknown = []
    return part
