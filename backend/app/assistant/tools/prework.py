"""도배 전 점검(갈래 P2): 고객 읽기 도구 prework_brief · 점검 카드(prework_check) · 카드 단추 답 → 승인 카드(prework).

- 앞 공사(목공 · 전기 · 필름 · 바닥)가 끝났는지만 점검해요. 그 업체를 잇거나 견적을 내지 않아요(고정 선 8).
  · 공정마다 '왜 먼저인지' 한 줄(정해 둔 글, 숫자 없음). 근거는 믿집 공정 순서(agent.v3.trades.ORDER_RULES)와 공정 지식
    조각(LX Z:IN 시공 가이드 K178 · 반셀프 경험담 K1360 · K1361, knowledge/other_trades.json)이에요.
  · 이미 아는 것은 채워요: 저장된 답(모은 조건 prework.*), 이 공사에 고른 목공(공사 공정 · 공정표 블록), 직접 할 일 중
    도배 전에 끝낼 일(calc.diy, 공정표 '고객이 직접' 줄과 같은 날짜).
  · 모르는 것은 카드 단추(끝났어요 · 아직이에요 · 안 해요)로 물어요. 단추는 고른 것을 턴(context.choice
    'prework.<공정>:<값>')으로 보내고 코드가 승인 카드를 만들어요(choices.apply → propose_answers). 저장은 고객이 그 카드를
    누를 때만이에요(고정 선 1, actions._prework). 고객 글로 받은 답은 저장하지 않아요(단추 값만, LLM 제안 도구 없음).
- 벽지 직접 구매(직접 할 일 paper_buy)면 살 롤 수 · 자투리 몫 · 여분 · 부자재(풀 · 초배지 · 부직포) 포함 상태를 같이
  보여요. 숫자는 계산 엔진(calc.dobae_rolls) 값만이고, 소요량은 이 집 표준견적서 판 값이라 표준견적서 화면 롤 수와 같아요
  (고정 선 2). 저장 전이어도 이번 고객 말이 벽지를 직접 산다고 하거나 그 집 정보 승인 카드가 열려 있으면 보여요.
- 다음 걸음 한 줄: 실측 요청 전이면 업체 고르기 · 실측 요청, 요청 뒤면 실측 때 업체와 맞추기.
"""

import logging
import uuid
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.schemas import (
    ActionSummary,
    CardOut,
    PreworkCheckData,
    PreworkMaterial,
    PreworkPaper,
    PreworkRow,
    PreworkTask,
    SummaryRow,
)
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards, obj, tool
from app.assistant.tools.customer import NoArgs, pid_of
from app.assistant.tools.propose import LINE_STATE, _offer
from app.auth.models import User
from app.calc import dobae_rolls
from app.calc.dobae import num
from app.db import SessionLocal
from app.project import prework

log = logging.getLogger(__name__)

# 왜 도배 전에 끝내는지(정해 둔 글, 숫자 없음). 바닥은 마루 · 장판 순서가 반대라 둘을 한 줄에 같이 적어요. 아직인
# 공정은 단추 턴에도 이 글을 모델에 같이 줘요(choices.text_of, QA r10 c3 T2)
WHY = {
    # 믿집 공정 순서(목공 → 도배) · LX Z:IN 시공 가이드 K178(문틀 · 몰딩을 바꾸면 벽에 틈이 생겨 메운 뒤 덮어요)
    "mokgong": "문틀 · 몰딩을 바꾸면 벽에 틈이 생겨, 메우고 덮은 뒤에 도배해요.",
    # 반셀프 경험담 K1361 · 공정 쌍 글(전기 → 도배): 도배 뒤에 배선을 옮기면 벽을 다시 뜯어요
    "electric": "도배한 뒤에 배선을 옮기면 벽을 다시 뜯어야 해서, 전기 공사를 먼저 끝내요.",
    # 믿집 공정 순서(목공 → 필름 → 도배) · K1360(순서가 어긋나면 비용이 겹치고 하자가 생길 수 있어요)
    "film": "필름은 목공 뒤 도배 전에 붙여요. 순서가 어긋나면 비용이 겹치고 하자가 생길 수 있어요.",
    # 공정 쌍 글(도배 → 바닥) · 다른 공정 알아 두기(바닥재)
    "floor": "마루는 도배 전에, 장판은 도배 뒤에 까는 게 보통이에요. 업체마다 다를 수 있어 실측 때 순서를 맞춰요.",
}
MOKGONG_PLAN = "이 공사 공정표에서 도배 전에 잡혀 있어요"
MOKGONG_PICKED = "이 공사에 목공을 골랐어요"
NOT_ASKED = "모름"  # 모델 값: 아직 고르지 않은 답
NEXT_VISIT = "다음은 도배 업체를 골라 실측을 요청하는 거예요."
NEXT_TODO = "아직인 앞 공사는 실측 때 업체에 알려 도배 날을 맞춰요."
NEXT_LOCKED = "앞 공사 상황은 실측 때 도배 업체에 알려 도배 날을 맞춰요."
NEXT_LABEL = "업체 고르기"
NEXT_SAY = "도배 업체 추천해 주세요"
BRIEF_NOTE = (
    "앞 공사 답은 고객이 이 카드 단추(끝났어요 · 아직이에요 · 안 해요)로 고르고 승인 카드를 눌러야 저장돼요. 글로 받은 "
    "답은 저장하지 않으니 카드에서 골라 달라고 해요. 믿집은 목공 · 전기 · 필름 · 바닥 업체를 잇거나 견적을 내지 않아요."
)
PAPER_NOTE = (
    "롤 수는 표준견적서 벽지 양과 같은 셈이에요(계산 엔진). 실측 뒤 업체가 잰 면적으로 다시 확인해요. "
    f"여분 {dobae_rolls.SPARE[0]}~{dobae_rolls.SPARE[1]}롤은 셈 밖이에요."
)
CHECK_STATE = "업체 확인"  # 표준견적서에 그 자재를 단 줄이 없음
CHECK_AMOUNT = "양은 업체 확인"
NO_DOBAE = "도배가 있는 공사에서만 도배 전 점검을 해요."
SAY = "도배 전에 끝낼 일을 모아 봤어요."
PROPOSE_NOTE = "저장하면 도배 전 점검 카드에 남아요. 업체 연결 · 견적은 하지 않아요."
NO_CHANGE = "고른 답이 지금 저장된 답과 같아요."
BAD_ANSWER = "앞 공사 답을 다시 골라 주세요."
NOT_PICKED = "고르지 않음"  # 승인 카드 '지금' 칸: 아직 고르지 않은 답


def card_id(pid: uuid.UUID) -> str:
    return f"prework-{pid}"


def _amount(m: dobae_rolls.Material) -> str | None:
    return None if m.qty is None else f"약 {num(m.qty)}{m.unit}"


def paper_part(r: dobae_rolls.DobaeRolls) -> tuple[PreworkPaper, dict]:
    """롤 수 · 부자재(계산 엔진 값) → (카드 칸, 모델 값)."""
    basis = (
        f"도배 면적 {num(r.area_m2)}㎡ × 소요량 {num(r.ratio)} = 벽지 {num(r.paper_m2)}㎡"
        f"({num(r.paper_py)} 벽지 평)"
    )
    mats = [
        PreworkMaterial(name=m.name, state=m.state, line=m.line, amount=_amount(m))
        for m in r.materials
    ]
    card = PreworkPaper(
        name=r.name,
        size=r.size,
        area_m2=r.area_m2,
        count=r.count,
        base=r.base,
        loss=r.loss,
        spare_min=r.spare_min,
        spare_max=r.spare_max,
        basis=basis,
        materials=mats,
    )
    model = {
        "name": r.name,
        "size": r.size,
        "area_m2": r.area_m2,
        "count": r.count,  # 필요 롤(자투리 포함)
        "text": f"{r.name}({r.size}) {r.count}롤 · 여분 {r.spare_min}~{r.spare_max}롤은 따로",
        "rows": [
            {"label": "면적만 덮는 롤", "count": r.base},
            {"label": "자투리 몫(필요 롤에 포함)", "count": r.loss},
            {"label": "여분(셈 밖)", "value": f"{r.spare_min}~{r.spare_max}롤"},
        ],
        "basis": basis,
        "items": [
            {
                "name": m.name,
                "state": LINE_STATE.get(m.state, m.state) if m.state else CHECK_STATE,
                "line": m.line,
                "text": f"{_amount(m)}({m.source})" if m.qty is not None else CHECK_AMOUNT,
            }
            for m in r.materials
        ],
        "source": f"{dobae_rolls.PAPER_RATIO_SOURCE} · 롤 규격 제조사 공식 · 여분 {dobae_rolls.SPARE_SOURCE}",
        "note": PAPER_NOTE,
    }
    return card, model


async def _paper(s: AsyncSession, user: User, pid: uuid.UUID) -> dobae_rolls.DobaeRolls | None:
    """이 집 표준견적서 도배 줄(벽 · 천장 면적 · 포함 상태)과 그 판 소요량으로 센 롤 수. 셀 수 없으면 None."""
    from app.quote import service as quote_service
    from app.refprice.book import dobae_prices_of

    out = await quote_service.standard_for(s, user, pid)
    t = next((x for x in out.trades if x.trade == "dobae"), None)
    if t is None or t.grade is None:
        return None
    row = (await quote_service.latest_of(s, [pid])).get((pid, "dobae"))
    dp = dobae_prices_of(row.price_ver if row else None)
    ratio = dp.profile.paper_ratio[t.grade] if dp.profile else dp.paper_ratio
    lines = {ln.key: ln for ln in t.lines}

    def face(key: str) -> Decimal:
        ln = lines.get(key)
        ok = ln is not None and ln.state != "excluded" and ln.qty is not None
        return Decimal(ln.qty) if ok else Decimal(0)  # type: ignore[union-attr, arg-type]

    try:
        r = dobae_rolls.need(face("wall"), face("ceiling"), t.grade, ratio=ratio, lines=t.lines)
    except ValueError:
        return None
    if t.rolls is not None and t.rolls.count != r.count:  # 같은 셈이어야 해요(판이 다르면 로그만)
        log.warning(
            "도배 전 점검 롤 수가 표준견적서와 달라요 (판 %s)", row.price_ver if row else "-"
        )
    return r


async def _buying(s: AsyncSession, user: User, pid: uuid.UUID, text: str) -> bool:
    """벽지 직접 구매를 저장하기 전에도 롤 수를 보일지(QA r10 c3 T1: '벽지는 제가 사요' 턴 카드에 롤 수가 없었어요).
    이번 고객 말이 벽지를 직접 산다고 하거나(무료 모드 직접 할 일 말과 같은 낱말), 직접 할 일에 벽지 직접 구매를 넣는
    집 정보 승인 카드가 열려 있을 때."""
    from app.assistant import repository as repo
    from app.assistant.tools import diy as diy_tools
    from app.project.diy import PAPER_BUY

    if PAPER_BUY in diy_tools.keys_in(text) and diy_tools.SELF_SAID.search(text):
        return True
    rows = await repo.actions_of(s, user.id, "customer", project_id=pid, status="proposed")
    for a in rows:
        fields = (a.payload or {}).get("fields") or {}
        if a.kind == "home_info" and PAPER_BUY in (fields.get("diy") or ()):
            return True
    return False


async def brief(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date, text: str = ""
) -> tuple[CardOut, dict]:
    """도배 전 점검 카드 · 모델 값(text: 이번 고객 말). 남의 공사면 AppError(404), 도배가 없는 공사면
    ToolError(no_dobae)."""
    from app.assistant.tools import diy as diy_tools
    from app.project import service as project_service

    p = await project_service.get_for(s, user, pid)
    if p.trades.dobae is None:
        raise ToolError("no_dobae", NO_DOBAE)
    answers = await prework.prework_for(s, pid)
    g = await diy_tools.gather(s, user, pid, today)
    rows: list[PreworkRow] = []
    for key, label in prework.PREWORK.items():
        note = None
        if key == "mokgong" and "mokgong" in g.trades:
            note = MOKGONG_PLAN
        elif key == "mokgong" and p.trades.mokgong is not None:
            note = MOKGONG_PICKED
        rows.append(
            PreworkRow(key=key, label=label, state=answers.get(key), why=WHY[key], note=note)  # type: ignore[arg-type]
        )
    before = [t for t in g.tasks if t.kind == "before"]
    tasks = [PreworkTask(label=t.name, when=g.when(t)) for t in before]
    paper = None
    paper_model = None
    if "paper_buy" in g.keys or await _buying(s, user, pid, text):
        got = await _paper(s, user, pid)
        if got is not None:
            paper, paper_model = paper_part(got)
    todo = any(r.state == "todo" for r in rows)
    if p.locked:
        nxt, label, say = NEXT_LOCKED, None, None
    else:
        nxt = f"{NEXT_TODO} {NEXT_VISIT}" if todo else NEXT_VISIT
        label, say = NEXT_LABEL, NEXT_SAY
    data = PreworkCheckData(
        rows=rows,
        tasks=tasks,
        paper=paper,
        next=nxt,
        next_label=label,
        next_say=say,
        href=cards.href(pid, "/plan"),
    )
    card = CardOut(
        card_id=card_id(pid), kind="prework_check", data=data.model_dump(mode="json"), say=SAY
    )
    model: dict = {
        "rows": [
            {
                "trade": r.label,
                "state": prework.STATES[r.state] if r.state else NOT_ASKED,
                "why": r.why,
                "note": r.note,
            }
            for r in rows
        ],
        "next": nxt,
        "note": BRIEF_NOTE,
    }
    if tasks:  # 도배 전에 끝낼 직접 할 일(공정표와 같은 날짜)
        model["items"] = [{"title": t.label, "text": t.when} for t in tasks]
    if paper_model is not None:
        model["paper"] = paper_model
    return card, model


@tool(
    "prework_brief",
    surface="customer",
    kind="read",
    status="도배 전에 끝낼 일을 모으고 있어요",
    description="도배 실측 요청 전에 점검할 것을 한 카드로 보여 줘요: 앞 공사(목공 · 전기 · 필름 · 바닥)가 끝났는지와 "
    "왜 먼저인지, 도배 전에 끝낼 직접 할 일(공정표 날짜), 벽지 직접 구매면 살 롤 수(자투리 포함 · 여분 따로) · 풀 · 초배지 "
    "· 부직포가 표준견적서에 들어 있는지예요. 반셀프(직접 할 일이 있거나 벽지 직접 구매) 고객이 실측 요청 전일 때, 또는 "
    "고객이 앞 공사 · 도배 전 준비 · 벽지 몇 롤을 물을 때 불러요. rows의 state가 모름인 공정은 고객이 카드 단추로 골라 "
    "승인 카드를 눌러야 저장돼요(글로 받은 답은 저장하지 않아요). 믿집은 그 공정 업체를 잇거나 견적을 내지 않아요. 롤 수 · "
    "면적은 결과 값 그대로 말해요.",
    model=NoArgs,
    schema=obj({}),
)
async def prework_brief(tc: ToolCtx, _: NoArgs) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await brief(s, tc.user, pid_of(tc), tc.today, tc.text)
    return ToolOut(data=model, cards=[card])


async def propose_answers(tc: ToolCtx, answers: Mapping[str, str]) -> ToolOut:
    """카드 단추로 고른 앞 공사 답 → 승인 카드(prework, choices.apply가 불러요). 지금 저장된 답과 다른 것만 싣고, 다
    같으면 no_change예요. 저장은 고객이 그 카드를 누를 때만이에요(actions._prework). 남의 공사면 AppError(404)."""
    from app.project import service as project_service

    pid = pid_of(tc)
    try:
        got = prework.clean(answers)
    except ValueError as e:
        raise ToolError("bad_input", BAD_ANSWER) from e
    async with SessionLocal() as s:
        await project_service.get_for(s, tc.user, pid)
        now = await prework.prework_for(s, pid)
    changes = {k: v for k, v in got.items() if now.get(k) != v}
    if not changes:
        raise ToolError("no_change", NO_CHANGE)
    rows = [
        SummaryRow(
            label=prework.PREWORK[k],
            value=prework.STATES[v],
            sub=f"지금 {prework.STATES[now[k]] if k in now else NOT_PICKED}",
        )
        for k, v in changes.items()
    ]
    out, _ = await _offer(
        tc,
        kind="prework",
        target_kind="project",
        target_id=pid,
        target_ver=prework.prework_ver(now),
        payload={"answers": changes},
        summary=ActionSummary(
            title="앞 공사 답 저장", rows=rows, note=PROPOSE_NOTE, approve_label="맞아요, 저장"
        ),
        expires_at=tc.now + timedelta(days=7),
        project_id=pid,
    )
    return out
