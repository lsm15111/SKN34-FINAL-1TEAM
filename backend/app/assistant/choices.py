"""카드 단추로 고른 값(TurnIn.context.choice) 풀기 (계약서 3장 · 4장 11). 사람이 누른 고르기라 LLM 판단 없이 코드가
승인 카드(대기 행동)를 만든다(무료 모드도). 실행은 여전히 사람이 그 카드를 승인할 때만이다.

- 집 정보 칸 `demolition:<full · partial · none>` → propose_home_info(고객)
- 행동 `<kind>:<이름표,…>` → 그 제안 도구. 이름표는 이 대화의 도구 · 카드가 준 것만 받는다.
  - 고객: `visit_request:v1,v2[,r1]` · `visit_slot:s1` · `vendor_confirm:m1` · `dates_accept:p1`(연기 날짜면 delay_accept)
  - 업체: `window_answer:m1,w1`(w1만 줘도 됨) · `decline:m1,<full · out_of_area · other>`(보던 요청이면 코드만) ·
    `dates:d1,n1`(n1만 줘도 됨)
- 그 밖(v1 · m1 같은 이름표)은 지금처럼 LLM에 '(카드에서 고름: …)'으로만 간다.
"""

from typing import TYPE_CHECKING

from app.assistant.tools import ToolCtx, ToolError, ToolOut
from app.shared.errors import AppError

if TYPE_CHECKING:
    from app.assistant.runtime import Emit, RefTable, TurnCtx, TurnResult

FIELDS: dict[str, tuple[str, ...]] = {"demolition": ("full", "partial", "none")}
ACTIONS: dict[str, str] = {
    "visit_request": "customer", "visit_slot": "customer", "vendor_confirm": "customer",
    "dates_accept": "customer", "delay_accept": "customer",
    "window_answer": "vendor", "decline": "vendor", "dates": "vendor",
}  # fmt: skip
LABEL = {
    "visit_request": "실측 요청", "visit_slot": "실측 시간 고르기", "vendor_confirm": "업체 확정",
    "dates_accept": "공사 날짜 수락", "delay_accept": "바뀐 날짜 수락", "window_answer": "기간 답하기",
    "decline": "못 받아요", "dates": "공사 날짜 보내기",
}  # fmt: skip
DECLINE_CODES = ("full", "out_of_area", "other")
MADE = "고른 것으로 승인 카드를 만들었어요. 카드를 확인하고 눌러 주세요."
MAX_ACTIONS = 2  # 한 턴에 단추로 만드는 제안 수


def field(choice: str) -> tuple[str, str] | None:
    """'demolition:full' → ("demolition", "full"). 허용한 칸 · 값이 아니면 None."""
    key, sep, value = choice.partition(":")
    return (key, value) if sep and value in FIELDS.get(key, ()) else None


def action(choice: str, refs: "RefTable | None" = None) -> tuple[str, list[str]] | None:
    """'visit_request:v1,v2' → ("visit_request", ["v1", "v2"]). refs를 주면 이 대화가 아는 이름표만 받는다."""
    kind, sep, rest = choice.partition(":")
    if not sep or kind not in ACTIONS:
        return None
    args = [a.strip() for a in rest.split(",") if a.strip()]
    if not 1 <= len(args) <= 4:
        return None
    if refs is not None and not all(a in DECLINE_CODES or refs.known(a) for a in args):
        return None
    return kind, args


def valid(choice: str, refs: "RefTable") -> bool:
    return refs.known(choice) or field(choice) is not None or action(choice, refs) is not None


def text_of(choice: str) -> str:
    """LLM에 보낼 고른 것: 이름표는 그대로, 칸은 화면 말('철거 범위: 전체 철거'), 행동은 '실측 요청 v1, v2'."""
    from app.assistant.tools.propose import FIELD_LABEL, _show

    f = field(choice)
    if f is not None:
        return f"{FIELD_LABEL[f[0]]}: {_show(*f)}"
    a = action(choice)
    if a is not None:
        return f"{LABEL[a[0]]} {', '.join(a[1])}"
    return choice


def _refs(args: list[str], prefix: str) -> list[str]:
    return [a for a in args if a[:1] == prefix and a[1:].isdigit()]


async def _run(tc: ToolCtx, kind: str, args: list[str]) -> ToolOut:
    """행동 고르기 하나 → 그 제안 도구(모르는 이름표 · 바뀐 상태는 도구가 ToolError)."""
    from app.assistant.tools import propose

    refs = tc.refs
    if kind == "visit_request":
        vs = _refs(args, "v")
        if not vs:
            raise ToolError("unknown_ref", "고른 업체가 없어요. 업체 카드에서 다시 골라 주세요.")
        trade = refs.get(vs[0], "vendor").get("trade") or "dobae"
        wish = next(iter(_refs(args, "r")), None)
        return await propose.propose_visit_request(
            tc, propose.VisitReqIn(trade=trade, vendor_refs=vs, wish_ref=wish)
        )
    if kind == "visit_slot":
        return await propose.propose_visit_slot(tc, propose.SlotIn(slot_ref=args[0]))
    if kind == "vendor_confirm":
        return await propose.propose_vendor_confirm(tc, propose.VisitRefIn(visit_ref=args[0]))
    if kind in ("dates_accept", "delay_accept"):
        p = refs.get(args[0], "proposal")
        fn = (
            propose.propose_delay_accept
            if p.get("type") == "delay"
            else propose.propose_dates_accept
        )
        return await fn(tc, propose.ProposalIn(proposal_ref=args[0]))
    if kind == "window_answer":
        w = next(iter(_refs(args, "w")), None)
        if w is None:
            raise ToolError("unknown_ref", "고른 기간이 없어요. 빈 기간 카드에서 다시 골라 주세요.")
        m = next(iter(_refs(args, "m")), None) or refs.put(
            "visit", {"id": refs.get(w, "window")["visit_id"]}
        )
        return await propose.propose_window_answer(
            tc, propose.WindowAnswerIn(visit_ref=m, window_ref=w)
        )
    if kind == "decline":
        code = next((a for a in args if a in DECLINE_CODES), "other")
        m = next(iter(_refs(args, "m")), None)
        if m is None:
            if tc.visit_id is None:
                raise ToolError("no_visit", "어느 요청인지 몰라요. 요청을 열고 다시 눌러 주세요.")
            m = refs.put("visit", {"id": str(tc.visit_id)})
        return await propose.propose_decline(
            tc,
            propose.DeclineIn(visit_ref=m, code=code),  # type: ignore[arg-type]
        )
    n = next(iter(_refs(args, "n")), None)  # dates
    if n is None:
        raise ToolError("unknown_ref", "고른 공사 날 후보가 없어요. 할 일에서 다시 골라 주세요.")
    d = next(iter(_refs(args, "d")), None) or refs.put(
        "deal", {"id": refs.get(n, "days")["deal_id"]}
    )
    return await propose.propose_dates(tc, propose.DatesPropose(deal_ref=d, days_ref=n))


async def apply(ctx: "TurnCtx", emit: "Emit", res: "TurnResult") -> str | None:
    """카드 고르기 → 승인 카드(모드와 상관없이). 만든 카드 · 행동 · 밀려 닫힌 행동은 이 턴 이벤트로 보낸다.
    돌려주는 값: 모델 · 무료 답에 붙일 한 줄(고른 행동 · 칸이 없으면 None)."""
    from app.assistant.runtime import send_card
    from app.assistant.tools import propose

    fields = dict(x for x in (field(c) for c in ctx.choice) if x)
    acts = [
        a
        for a in (action(c, ctx.refs) for c in ctx.choice)
        if a is not None and ACTIONS[a[0]] == ctx.surface
    ][:MAX_ACTIONS]
    if ctx.surface != "customer":
        fields = {}
    if not fields and not acts:
        return None
    tc = ToolCtx(
        user=ctx.user,
        surface=ctx.surface,  # type: ignore[arg-type]
        turn_id=ctx.turn_id,
        chat_id=ctx.chat_id,
        project_id=ctx.project_id,
        visit_id=ctx.visit_id,
        today=ctx.today,
        now=ctx.now,
        refs=ctx.refs,
    )
    outs: list[ToolOut] = []
    errors: list[str] = []
    jobs = [("home", [])] if fields else []
    for kind, args in [*jobs, *acts]:
        try:
            if kind == "home":
                home = propose.HomeIn(fields=propose.HomeFields(**fields))
                outs.append(await propose.propose_home_info(tc, home))
            else:
                outs.append(await _run(tc, kind, args))
        except (ToolError, AppError) as e:
            errors.append(e.message)
    for out in outs:
        await _send(out, emit, res, send_card)
    lines = ([MADE] if outs else []) + errors
    return " ".join(dict.fromkeys(lines)) or None


async def _send(out: ToolOut, emit: "Emit", res: "TurnResult", send_card) -> None:
    for a in out.closed:
        await emit("action", a.model_dump(mode="json"))
    for c in out.cards:
        await send_card(res, emit, c)
    for a in out.actions:
        if str(a.action_id) not in res.actions:
            res.actions.append(str(a.action_id))
        await emit("action", a.model_dump(mode="json"))
