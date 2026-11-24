"""카드 단추로 고른 값(TurnIn.context.choice) 풀기 (계약서 3장 · 4장 11). 사람이 누른 고르기라 LLM 판단 없이 코드가
승인 카드(대기 행동)를 만든다(무료 모드도). 실행은 여전히 사람이 그 카드를 승인할 때만이다.

- 집 정보 칸 `demolition:<full · partial · none>` · `grade:<economy · basic>` → propose_home_info(고객)
- 앞 공사 답 `prework.<mokgong · electric · film · floor>:<done · todo · none>`(도배 전 점검 카드, 여럿이면 한 승인
  카드) → tools.prework.propose_answers(고객). LLM 도구는 없어요: 앞 공사 답은 단추로 고른 값만 저장해요.
- 행동 `<kind>:<이름표,…>` → 그 제안 도구. 이름표는 이 대화의 도구 · 카드가 준 것만 받는다.
  - 고객: `visit_request:v1,v2[,r1]` · `visit_slot:s1` · `vendor_confirm:m1` · `dates_accept:p1`(연기 날짜면 delay_accept)
  - 업체: `window_answer:m1,w1`(w1만 줘도 됨) · `decline:m1,<full · out_of_area · other>`(보던 요청이면 코드만) ·
    `dates:d1,n1`(n1만 줘도 됨)
- 그 밖(v1 · m1 같은 이름표)은 지금처럼 LLM에 '(카드에서 고름: …)'으로만 간다.
- 지난 카드 단추(stale): 이 화면의 행동 꼴인데 이름표를 이 대화가 모르거나(표가 지워짐 · 다른 곳에서 만든 카드),
  카드 id의 대상(slots- · dates- · brief- + id)과 이름표가 가리키는 대상이 다르면 버리지 않는다. 그 종류의 카드를 이
  대화 이름표로 새로 만들어 보내고 '카드를 새로 불러왔어요. 다시 골라 주세요.'로 답한다(무료 · LLM 모드 같음,
  LLM은 부르지 않는다). 행동은 만들지 않는다(사람이 새 카드에서 다시 고른다).
"""

import uuid
from typing import TYPE_CHECKING

from app.assistant.schemas import CardOut
from app.assistant.tools import ToolCtx, ToolError, ToolOut
from app.assistant.tools import aftercare as aftercare_tools
from app.shared.errors import AppError

if TYPE_CHECKING:
    from app.assistant.runtime import Emit, RefTable, TurnCtx, TurnResult

# 집 정보 칸 고르기: 철거 범위 · 벽지(벽지 두 종류 견주기 카드의 [○○로 바꾸기])
FIELDS: dict[str, tuple[str, ...]] = {
    "demolition": ("full", "partial", "none"),
    "grade": ("economy", "basic"),
}
ACTIONS: dict[str, str] = {
    "visit_request": "customer", "visit_slot": "customer", "vendor_confirm": "customer",
    "dates_accept": "customer", "delay_accept": "customer",
    "window_answer": "vendor", "decline": "vendor", "dates": "vendor",
    "extra_answer": "customer", "work_check": "customer", "visit_again": "customer",  # 07
}  # fmt: skip
LABEL = {
    "visit_request": "실측 요청", "visit_slot": "실측 날짜 고르기", "vendor_confirm": "업체 확정",
    "dates_accept": "공사 날짜 수락", "delay_accept": "바뀐 날짜 수락", "window_answer": "기간 답하기",
    "decline": "못 받아요", "dates": "공사 날짜 보내기",
    "extra_answer": "추가 금액 답", "work_check": "공사 끝 확인", "visit_again": "한 번 더 요청",
}  # fmt: skip
DECLINE_CODES = ("full", "out_of_area", "other")
# 이름표가 아닌 단추 값: 못 받아요 까닭 + 07 추가 금액 답(approve · reject · ask) · 공사 끝(done · fixing)
WORDS = (*DECLINE_CODES, *aftercare_tools.WORDS)
MADE = "고른 것으로 승인 카드를 만들었어요. 카드를 확인하고 눌러 주세요."
SAME = "고른 것과 같은 승인 카드가 이미 있어요. 그 카드를 확인하고 눌러 주세요."
RELOADED = "카드를 새로 불러왔어요. 다시 골라 주세요."
GONE = "지금은 고를 수 있는 것이 없어요. 진행 상황을 확인해 주세요."
# 코드가 답을 정해 턴을 끝낸 고르기(TurnResult.reason): 잠긴 집의 칸 단추(옛 벽지 견주기 카드 [합지로 바꾸기] 등,
# QA r3 v1 M6). LLM을 부르지 않고 까닭 한 줄(propose_home_info의 locked 글)로 답한다
ANSWERED = "locked"
MAX_ACTIONS = 2  # 한 턴에 단추로 만드는 제안 수
# 카드 id 머리(slots- · dates- · brief- + 대상 id) → 이름표 종류마다 그 id가 든 칸(지난 카드 단추 가려내기)
CARD_TARGET: dict[str, dict[str, str]] = {
    "slots": {"slot": "visit_id", "visit": "id"},
    "dates": {"proposal": "id"},
    "brief": {"window": "visit_id", "visit": "id"},
    "extra": {"extra": "id"},  # 07 추가 금액 카드
}


def field(choice: str) -> tuple[str, str] | None:
    """'demolition:full' → ("demolition", "full"). 허용한 칸 · 값이 아니면 None."""
    key, sep, value = choice.partition(":")
    return (key, value) if sep and value in FIELDS.get(key, ()) else None


def prework_field(choice: str) -> tuple[str, str] | None:
    """'prework.mokgong:done' → ("mokgong", "done"). 앞 공사 공정 · 단추 값(project.prework)이 아니면 None."""
    from app.project import prework

    key, sep, value = choice.partition(":")
    trade = key.removeprefix(prework.PREFIX)
    if not sep or trade == key or trade not in prework.PREWORK or value not in prework.STATES:
        return None
    return trade, value


def action(choice: str, refs: "RefTable | None" = None) -> tuple[str, list[str]] | None:
    """'visit_request:v1,v2' → ("visit_request", ["v1", "v2"]). refs를 주면 이 대화가 아는 이름표만 받는다."""
    kind, sep, rest = choice.partition(":")
    if not sep or kind not in ACTIONS:
        return None
    args = [a.strip() for a in rest.split(",") if a.strip()]
    if not 1 <= len(args) <= 4:
        return None
    if refs is not None and not all(a in WORDS or refs.known(a) for a in args):
        return None
    return kind, args


def valid(choice: str, refs: "RefTable") -> bool:
    return (
        refs.known(choice)
        or field(choice) is not None
        or prework_field(choice) is not None
        or action(choice, refs) is not None
    )


def card_target(card_id: str | None) -> tuple[str, uuid.UUID | None]:
    """'slots-<실측 id>' → ("slots", id). 대상 id가 없는 카드(compare-dobae · today …)면 (머리, None)."""
    head, _, tail = (card_id or "").partition("-")
    try:
        return head, uuid.UUID(tail)
    except ValueError:
        return head, None


def fits_card(choice: str, refs: "RefTable", card_id: str | None) -> bool:
    """카드 id에 대상 id가 든 카드면 고른 이름표가 그 대상을 가리키는지(아니면 지난 카드 단추)."""
    a = action(choice)
    head, target = card_target(card_id)
    want = CARD_TARGET.get(head)
    if a is None or target is None or want is None:
        return True
    for x in a[1]:
        it = refs.items.get(x)
        key = want.get(it["kind"]) if it else None
        if key is not None and str(it.get(key)) != str(target):
            return False
    return True


def stale(choice: str, surface: str) -> bool:
    """이 화면의 행동 꼴(valid · fits_card를 못 지난 것): 지난 카드 단추라 카드를 새로 불러온다."""
    a = action(choice)
    return a is not None and ACTIONS[a[0]] == surface


def text_of(choice: str) -> str:
    """LLM에 보낼 고른 것: 이름표는 그대로, 칸은 화면 말('철거 범위: 전체 철거'), 앞 공사 답은 화면 말(아직이면 카드
    근거까지), 행동은 '실측 요청 v1, v2'."""
    from app.assistant.tools.propose import FIELD_LABEL, _show

    f = field(choice)
    if f is not None:
        return f"{FIELD_LABEL[f[0]]}: {_show(*f)}"
    if (pw := prework_field(choice)) is not None:  # '앞 공사 목공: 끝났어요'
        from app.assistant.tools.prework import WHY
        from app.project import prework

        got = f"{prework.LABEL} {prework.PREWORK[pw[0]]}: {prework.STATES[pw[1]]}"
        # 아직인 공정은 점검 카드 근거를 그대로 같이 줘요(순서를 지어 말하지 않게, QA r10 c3 T2)
        return f"{got}(카드 근거: {WHY[pw[0]]})" if pw[1] == "todo" else got
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
    if kind in aftercare_tools.CHOICES:  # 07: 추가 금액 답 · 공사 끝 확인 · 한 번 더 요청
        return await aftercare_tools.run_choice(tc, kind, args)
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


async def reload(tc: ToolCtx, kinds: list[str], card_id: str | None) -> list[CardOut]:
    """지난 카드 단추: 그 행동을 고르는 카드를 이 대화 이름표로 새로 만든다(카드마다 따로, 못 만들면 뺀다).
    고객 업체 추천(visit_request) · 반나절(visit_slot) · 견적 비교(vendor_confirm) · 공사 날짜(dates_accept ·
    delay_accept), 업체 브리핑(window_answer · decline). 업체 공사 날 후보(dates)는 카드가 없어 빈 목록."""
    from app.assistant import memory
    from app.assistant import repository as repo
    from app.assistant.tools import cards
    from app.assistant.tools import vendor as vendor_tools
    from app.db import SessionLocal
    from app.schedule import service as schedule_service

    head, target = card_target(card_id)
    pid = tc.project_id
    out: list[CardOut] = []

    async def one(s, kind: str) -> list[CardOut]:
        if kind in aftercare_tools.CHOICES:
            return await aftercare_tools.reload_cards(s, tc, kind)
        if kind == "visit_request" and pid:
            card, model = await cards.vendor_picks(s, tc.user, pid, "dobae", tc.refs)
            return [card] if model["picks"] else []
        if kind == "visit_slot" and pid:
            prefer, days = memory.prefs(await repo.memories(s, tc.user.id))
            if head == "slots" and target is not None:
                ids = [target]
            else:
                o = await schedule_service.overview_for(s, tc.user, pid, tc.today)
                ids = [v.visit_id for v in o.vendors if v.status in ("offered", "proposed")][:2]
            got = []
            for vid in ids:
                card, model = await cards.visit_slots(
                    s, tc.user, pid, vid, tc.now, tc.refs, prefer=prefer, days=days
                )
                if model["candidates"]:
                    got.append(card)
            return got
        if kind == "vendor_confirm" and pid:
            card, model = await cards.compare(s, tc.user, pid, "dobae", tc.today, tc.refs)
            return [card] if any(c.get("version") for c in model["cols"]) else []
        if kind in ("dates_accept", "delay_accept") and pid:
            card, _ = await cards.schedule(s, tc.user, pid, tc.today, tc.refs)
            return [card] if card is not None else []
        visit = target if head == "brief" and target is not None else tc.visit_id
        if kind in ("window_answer", "decline") and visit is not None:
            card, *_ = await vendor_tools.brief(
                s, tc.user, visit, tc.today, tc.now, tc.refs, tc.turn_id, propose_window=False
            )
            return [card]
        return []

    async with SessionLocal() as s:
        for kind in dict.fromkeys(kinds):
            try:
                out += [c for c in await one(s, kind) if c.card_id not in {x.card_id for x in out}]
            except AppError:
                await s.rollback()  # 이 카드는 못 만든다(남의 것 · 바뀐 상태): 다른 카드는 그대로
    return out


async def apply(ctx: "TurnCtx", emit: "Emit", res: "TurnResult") -> str | None:
    """카드 고르기 → 승인 카드(모드와 상관없이). 만든 카드 · 행동 · 밀려 닫힌 행동은 이 턴 이벤트로 보낸다.
    지난 카드 단추(ctx.stale)는 그 카드를 새로 불러온다. 돌려주는 값: 모델 · 무료 답에 붙일 한 줄(고른 행동 ·
    칸 · 지난 단추가 없으면 None)."""
    from app.assistant.runtime import send_card
    from app.assistant.tools import prework as prework_tools
    from app.assistant.tools import propose

    fields = dict(x for x in (field(c) for c in ctx.choice) if x)
    # 앞 공사 답(여럿이어도 승인 카드 하나)
    answers = dict(x for x in (prework_field(c) for c in ctx.choice) if x)
    acts = [
        a
        for a in (action(c, ctx.refs) for c in ctx.choice)
        if a is not None and ACTIONS[a[0]] == ctx.surface
    ][:MAX_ACTIONS]
    if ctx.surface != "customer":
        fields, answers = {}, {}
    if not fields and not answers and not acts and not ctx.stale:
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
        pressed=True,  # 사람이 누른 고르기: 거절했던 제안도 다시 만든다
        text=ctx.text,
    )
    outs: list[ToolOut] = []
    errors: list[str] = []
    locked = False  # 칸 단추가 잠긴 집 정보에 막힘
    jobs = [("home", [])] if fields else []
    if answers:
        jobs.append(("prework", []))
    for kind, args in [*jobs, *acts]:
        try:
            if kind == "home":
                home = propose.HomeIn(fields=propose.HomeFields(**fields))
                outs.append(await propose.propose_home_info(tc, home))
            elif kind == "prework":
                outs.append(await prework_tools.propose_answers(tc, answers))
            else:
                outs.append(await _run(tc, kind, args))
        except (ToolError, AppError) as e:
            errors.append(e.message)
            locked = locked or (kind == "home" and e.code == "locked")
    for out in outs:
        await _send(out, emit, res, send_card)
    if locked and not outs and not acts and not ctx.stale:
        res.reason = ANSWERED  # 잠긴 집의 칸 단추: 까닭 한 줄로 끝내요(LLM 없음)
    states = {out.data.get("state") for out in outs}
    lines = ([MADE] if "new" in states else [SAME] if "same" in states else []) + errors
    # 잠긴 집의 칸 단추가 취소 카드를 냈으면(요청이 살아 있음) 그 안내 한 줄: 모두 취소하면 이어서 집 정보 카드
    needs = [o.data["note"] for o in outs if o.data.get("step") == propose.NEED_CANCEL]
    if needs:
        lines = [*needs, *errors]
        if not acts and not ctx.stale:
            res.reason = ANSWERED  # 이 안내 한 줄로 끝내요(LLM 없음, 잠긴 집의 칸 단추와 같은 길)
    if ctx.stale:
        kinds = [a[0] for a in (action(c) for c in ctx.stale) if a is not None]
        fresh = await reload(tc, kinds, ctx.card_id)
        for c in fresh:
            await send_card(res, emit, c)
        lines.append(RELOADED if fresh else GONE)
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
    if out.data.get("state") == "new":  # 모델이 '카드를 만들었어요'라고 해도 맞는 턴(SentenceGate)
        res.made |= {a.kind for a in out.actions}
        res.made_ids |= {str(a.action_id) for a in out.actions}  # 같은 턴 다시 제안도 '새로 만듦'
