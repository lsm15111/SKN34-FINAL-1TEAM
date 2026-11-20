"""화면 도구 (코드, 읽기만, docs/v3/agent-orchestrator.md 5장). 질문 분석기가 낸 조각마다 꼴 · 항목으로 담당을 골라
계산 엔진 값을 묶음 · 상자로 옮기고, 작성기에 넘길 '보는 화면' 글을 만들어요. 숫자는 모두 ProjectFacts 값 그대로예요.

| 꼴 | 도구 |
| --- | --- |
| line(항목을 가리키는 판단 · 비교 · 뜻도) | 견적 설명(그 줄: 무엇을 곱했는지 · 단위 · 표준에 없는 줄 · 시장 기준값 + 계산 상자), 항목마다 |
| compare · judge | 견적 설명 비교(업체 화면: 같은 수량 · 따로 받는 줄 · 실측 뒤 줄, 표준 화면: 업체 가견적 차이) |
| rank | 없음(작성기가 '보는 화면'의 금액 큰 순서로 답해요) |
| what · how · choose · other | 항목을 가리키면 그 줄 풀이, 아니면 공종(카드 · 조각 · 계산) |
| price · period | 공종(계산 엔진 금액 · 기간) |
| schedule | 공정표 담당 |

- 담당끼리는 서로 부르지 않고, 조각 묶음은 오케스트레이터 합치기 그대로 이어 붙여요(다시 쓰지 않음).
- 같은 담당 · 같은 항목은 한 번만 불러요. 담당 호출은 턴당 MAX_CALLS번까지.
- 표준견적서와 견준 %는 '보는 화면' 글에 넣지 않아요(사용자 결정 2026-11-21).
"""

from app.agent.v3 import guide, orchestrator, policy, quote_explain, schedule_agent, trade_agent
from app.agent.v3.answer import KB, Part, Task
from app.agent.v3.planner import STANDARD_MEANING, STATE_KO, Ask, Plan
from app.agent.v3.schemas import ProjectFacts

MAX_CALLS = 3
SCREEN_REF = "rule:screen"
GRADE_KO = {"basic": "실크(기본형)", "economy": "합지(저가형)"}
OTHER_GRADE = {"basic": "economy", "economy": "basic"}


def _won(v: int | None) -> str:
    return "" if v is None else f"{v:,}원"


def screen_text(view: str | None, facts: ProjectFacts | None) -> dict | None:
    """'보는 화면' 근거(작성기용). 화면에 보이는 계산 엔진 값을 그대로 글로 옮겨요. 없으면 None."""
    if facts is None or facts.standard is None:
        return None
    st = facts.standard
    v = facts.screen.vendor if facts.screen is not None else None
    out: list[str] = []
    if view == "vendor" and v is not None:
        title = f"지금 보는 화면 · {v.vendor} 가견적"
        out.append(
            f"{v.vendor} 가견적(업체 자세히 화면) · 벽지 {GRADE_KO.get(v.grade, v.grade)} · "
            f"합계 {_won(v.total)}(부가세 포함, 공급가 {_won(v.supply)} + 부가세 {_won(v.vat)})."
        )
        if v.grade_diff is not None and v.grade in OTHER_GRADE:
            other = GRADE_KO[OTHER_GRADE[v.grade]]
            sign = "+" if v.grade_diff > 0 else "−"
            out.append(f"벽지를 {other}으로 바꾸면 합계가 {sign}{abs(v.grade_diff):,}원 달라져요.")
        out.append("줄(금액 큰 순서, 단가는 부가세 빼고):")
        for x in sorted(v.lines, key=lambda x: -x.amount):
            same = "표준견적서와 같은 일" if x.in_standard else "표준견적서에 없는 줄"
            row = f"- {x.name}: {x.qty:g} {x.unit}"
            row += (
                f" × {_won(x.unit_price)} = {_won(x.amount)}"
                if x.unit_price is not None
                else f" · {_won(x.amount)}"
            )
            row += f" · {same}" + (f" · 뜻: {x.note}" if x.note else "")
            m = x.market
            if m is not None:
                stat = "가운데 값" if m.stat == "median" else "평균"
                row += (
                    f" · 믿집이 모은 실견적 {m.n}건: {x.basis or x.unit}당 {stat} {_won(m.base)}, "
                    f"절반이 {_won(m.p25)}~{_won(m.p75)}(부가세 빼고, {m.checked.year}.{m.checked.month} 기준)"
                )
            out.append(row)
        others = [e for e in facts.estimates if e.vendor != v.vendor]
    elif view == "standard":
        title = "지금 보는 화면 · 이 집 표준견적서"
        out.append(
            "이 집 표준견적서(공공 기준 단가로 믿집이 계산한 참고 금액, 업체 견적이 아님) · "
            f"합계 {_won(st.total)}(부가세 포함, 공급가 {_won(st.supply)} + 부가세 {_won(st.vat)})."
        )
        others = list(facts.estimates)
    else:
        return None
    if facts.calc_m2 is not None:
        basis = "공급면적" if facts.calc_basis == "supply" else "전용면적"
        out.append(
            f"이 집 면적: {facts.calc_m2:g}㎡({basis}) · 살면서 공사: {'예' if facts.living == 'living' else '아니요'}."
        )
    out.append(
        "이 집 표준견적서 줄(금액 큰 순서):"
        if view == "standard"
        else f"이 집 표준견적서 합계 {_won(st.total)}, 줄:"
    )
    for x in sorted(st.lines, key=lambda x: -(x.amount or 0)):
        row = f"- {x.name}: "
        if x.qty is not None and x.unit_price is not None:
            row += f"{x.qty:g} {x.unit} × {_won(x.unit_price)} = {_won(x.amount)}"
        else:
            row += _won(x.amount) or "금액 없음"
        bits = [STANDARD_MEANING.get(x.key, ""), STATE_KO.get(x.state, "")]
        row += " · " + " · ".join(b for b in bits if b)
        out.append(row)
    if others:
        out.append("업체 가견적: " + " / ".join(f"{e.vendor} {_won(e.total)}" for e in others[:3]))
    return {"ref": SCREEN_REF, "제목": title, "글": "\n".join(out)}


def _trades(task: Task, ask: Ask) -> list[str]:
    own = [t for t in ask.trades if t in ("dobae", "mokgong")]
    if not own and task.facts is not None:
        own = [t for t in task.facts.trades if t in ("dobae", "mokgong")]
    return own or ["dobae"]


def _sub(task: Task, ask: Ask, route: str, **kw) -> Task:
    flags = list(policy.policy_of(ask.text))
    if ask.kind in ("price", "period") and ask.kind not in flags:
        flags.append(ask.kind)
    return Task(
        text=ask.text, route=route, trades=_trades(task, ask), policy=flags,  # type: ignore[arg-type]
        ctx=task.ctx, facts=task.facts, general=task.general, **kw,
    )  # fmt: skip


def calls(task: Task, ask: Ask) -> list[Task]:
    """조각 하나 → 부를 담당 일. rank는 비어요(작성기가 보는 화면으로 답해요)."""
    k = ask.kind
    if (
        k not in ("rank", "price", "period", "schedule") and ask.items
    ):  # 줄을 가리키면 그 줄 풀이(판단 · 비교도)
        return [_sub(task, ask, "quote_explanation", item=i, want="line") for i in ask.items[:2]]
    if k == "line":
        return [_sub(task, ask, "quote_explanation", want="line")]
    if k in ("compare", "judge"):
        return [_sub(task, ask, "quote_explanation", want="compare")]
    if k == "rank":
        return []
    if k == "schedule":
        return [_sub(task, ask, "schedule")]
    return [_sub(task, ask, "trade")]


AGENTS = {
    "guide": guide.run,
    "trade": trade_agent.run,
    "quote_explanation": quote_explain.run,
    "schedule": schedule_agent.run,
}


def run(p: Plan, task: Task, kb: KB) -> tuple[Part, list[str]]:
    """조각마다 담당을 불러 합친 몫과 부른 이름들. 담당이 낸 것이 없으면 빈 몫(작성기가 보는 화면으로 답해요)."""
    jobs: list[Task] = []
    seen: set[tuple] = set()
    for ask in p.asks:
        for t in calls(task, ask):
            key = (t.route, t.item, t.want, t.text if t.route != "quote_explanation" else "")
            if key not in seen and len(jobs) < MAX_CALLS:
                seen.add(key)
                jobs.append(t)
    parts = [AGENTS[t.route](t, kb) for t in jobs]
    names = [f"{t.route}:{t.item or t.want or (t.trades[0] if t.trades else '-')}" for t in jobs]
    kept = [x for x in parts if not x.empty]
    if not kept:
        return Part(route="quote_explanation", trade="dobae"), names
    if len(kept) == 1:
        return kept[0], names
    return orchestrator.merge(kept, kb, asked=task.text), names
