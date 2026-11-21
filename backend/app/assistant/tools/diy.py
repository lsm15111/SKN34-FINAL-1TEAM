"""반셀프 직접 할 일: 고객 읽기 도구 diy_plan · 챙기기(오늘 할 일 · 공사 1주 전 · 공사 전날) · 업체에 알리기.

- 고른 값은 칩(project.diy.diy_for)이 먼저예요. 칩을 아직 묻지 않았으면(None) 기억 diy 글(고객이 한 말)에서 낱말로
  찾아요. '없어요'(빈 목록)면 직접 할 일이 없어요. 에이전트 추측은 쓰지 않아요.
- 날짜는 공정표(schedule.service.plan_for: 확정이 있으면 확정, 없으면 예상) 블록 → schedule.service.diy_tasks(calc.diy)
  값만 써요. 글은 knowledge/diy.json 정해 둔 글(숫자 없음)이고, 날짜 말만 계산 엔진 값으로 적어요.
- 카드는 knowledge 카드의 체크 칸이에요: 모두 보기는 할 일마다 한 줄('페인트(문틀 · 몰딩) 칠하기 · 12월 4일(금)까지
  해요'), 한 가지를 물으면 그 일의 때 · 방법 · 주의점 줄과 준비물 체크 칸이에요.
- 챙기기는 확정 공정표(수락한 공사 날짜)가 있을 때만 해요: 7일 안 마감 줄(today_rows) · 공사 1주 전 할 일
  (prep_part) · 공사 전날 준비물(eve_card).
- 업체에 알리기(offer_part): 실측 요청 승인 카드 줄 '업체에 알릴 것'과 payload diy. 승인하면 요청에 고정돼요
  (visit.flow.request). 업체 브리핑은 그 사본만 보여요(told_labels, 자료).
- 무료 모드(free_answer, free.py가 한 줄로 불러요): '직접 할 일 알려 줘' · '페인트 언제 칠해요?' · (칩이 있을 때)
  '준비물 알려 줘'를 이 카드로 이어요. 콘센트 옮기기 · 배선은 직접 할 일이 아니라 원래 길잡이로 보내요.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import repository as repo
from app.assistant.schemas import CardOut, CheckItem, KnowledgeData, RowAction, SummaryRow, TodayRow
from app.assistant.tools import ToolCtx, ToolOut, cards, obj, tool
from app.assistant.tools.customer import pid_of
from app.auth.models import User
from app.calc import diy as calc_diy
from app.db import SessionLocal
from app.knowledge import diy as know
from app.project.diy import DIY, diy_for
from app.shared.errors import AppError

WEEK = "월화수목금토일"
KEYS = calc_diy.KEYS
# 고객 말 → 칩 키(기억 diy 글 · 무료 모드). '청소'만 말해도 입주 청소예요
WORDS: dict[str, re.Pattern[str]] = {
    "paint": re.compile(r"페인트|도장|(?<![가-힣])칠(?:하|해|할|을|은|이|부터)"),
    "outlet": re.compile(r"콘센트|스위치"),
    "light": re.compile(r"조명|전등|등기구|방등|거실등|LED", re.IGNORECASE),
    "silicone": re.compile(r"실리콘|줄눈|코킹|메지"),
    "handle": re.compile(r"손잡이|문고리|도어\s{0,2}(?:핸들|레버)"),
    "clean": re.compile(r"청소"),
}
# 무료 모드: 직접 할 일 모두 · 때 · 방법 · 준비물을 묻는 말
LIST = re.compile(
    r"직접\s{0,2}(?:할|하는|해야\s{0,2}할|하기로\s{0,2}한|하려는)\s{0,2}(?:일|것|거)|"
    r"셀프\s{0,2}(?:할|하는|로\s{0,2}할)\s{0,2}(?:일|것|거)|반\s{0,2}셀프|DIY",
    re.IGNORECASE,
)
ASK = re.compile(
    r"언제|순서|먼저|전에|후에|뒤에|다음에|어떻게|방법|준비물|공구|도구|필요한\s{0,2}(?:거|것)|"
    r"뭐가\s{0,2}필요|뭘\s{0,2}(?:사|준비)|주의|조심"
)
SELF_SAID = re.compile(r"직접|셀프|제가|혼자|DIY", re.IGNORECASE)
PREP_WORD = re.compile(r"준비물|공구|도구|뭐가\s{0,2}필요|뭘\s{0,2}(?:사|준비)")
# 콘센트 옮기기 · 늘리기 · 배선은 직접 할 일(커버 바꾸기)이 아니에요(전기 공사업체 일, 원래 길잡이로)
MOVE = re.compile(
    r"옮기|옮겨|이설|신설|증설|늘리|늘려|추가로\s{0,2}달|새로\s{0,2}(?:달|내|만들)|배선|위치"
)
WEEKEND = re.compile(r"주말")
PET = re.compile(
    r"강아지|고양이|반려|애완|펫"
)  # 이번 말에 반려동물이 나오면 반려동물 주의도 보여요
PHASE_KO = {"final": "확정", "expected": "예상"}
SRC_NOTE = {
    "chips": "고객이 고른 직접 할 일이에요.",
    "memory": "고객이 대화에서 직접 하겠다고 한 일이에요(칩은 아직 안 골랐어요).",
    "none": "고객이 직접 할 일은 없다고 골랐어요.",
    "not_asked": "고객이 아직 직접 할 일을 고르지 않았어요. 표준견적서 화면에서 고를 수 있어요.",
}
WHY_NOTE = {
    "short": "앞 공사와 뒤 공사 사이가 모자라 날이 빠듯해요. 업체와 날짜를 맞춰 보세요.",
    "no_free_day": "그 사이에 주말 · 공휴일이 없어요. 업체와 날짜를 맞추거나 하루를 비워 보세요.",
    "late": "마감이 지났어요.",
}
ELECTRIC = ("outlet", "light")
SAFETY = "전기 일은 분전함 차단기를 먼저 내리고 해요."
# 무료 모드 정해 둔 글
FREE_NONE = (
    "직접 할 일은 없다고 고르셨어요. 직접 하실 일이 생기면 표준견적서 화면에서 다시 골라 주세요."
)
FREE_NOT_ASKED = (
    "아직 직접 할 일을 고르지 않으셨어요. 표준견적서 화면에서 고르면 공정표에 날짜를 넣어 드려요. "
    "직접 하기 쉬운 일의 때를 카드에 적었어요."
)
FREE_LIST = "고르신 직접 할 일이에요. 날짜는 {phase} 공정표 기준이에요."
FREE_FIRST = " 가장 먼저 할 일은 {name}, {when}."
FREE_PREP = "직접 하실 일의 준비물이에요. 공사 날 준비할 것도 같이 적었어요."
FREE_TIGHT = " 날이 빠듯한 일({names})은 카드를 확인해 주세요."


def ko_day(d: date) -> str:
    return f"{d.month}월 {d.day}일({WEEK[d.weekday()]})"


def md_day(d: date) -> str:
    return f"{d.month:02d}.{d.day:02d}({WEEK[d.weekday()]})"


def keys_in(text: str) -> list[str]:
    """글에 나온 직접 할 일 칩 키(KEYS 순서)."""
    t = text or ""
    return [k for k in KEYS if WORDS[k].search(t)]


def when_text(t: calc_diy.DiyTask) -> str:
    """'언제부터 · 언제까지' 말(날짜는 계산 엔진 값)."""
    if t.day is None:
        return "공사 날짜가 정해지면 날짜를 알려 드려요"
    if t.late and t.end is not None:
        return f"{ko_day(t.end)}까지였어요"
    if t.why == "short":
        if t.kind == "before" and t.end is not None:
            return f"{ko_day(t.end)}까지 해야 하는데 날이 빠듯해요"
        return f"{ko_day(t.day)}부터 할 수 있는데 날이 빠듯해요"
    if t.why == "no_free_day" and t.start is not None and t.end is not None:
        return f"{ko_day(t.start)} ~ {ko_day(t.end)} 사이에 주말 · 공휴일이 없어요"
    if t.start is not None and t.end is not None:
        if t.start == t.end:
            return f"{ko_day(t.end)}에 해요"
        return f"{ko_day(t.start)} ~ {ko_day(t.end)} 사이에 해요"
    if t.end is not None:
        return f"{ko_day(t.end)}까지 해요"
    return f"{ko_day(t.day)}부터 해요"


def _item_key(t: calc_diy.DiyTask) -> str:
    return f"diy-{t.key}-{t.step}" if t.step else f"diy-{t.key}"


# ---- 고른 값 · 날짜 ----


async def keys_for(s: AsyncSession, user_id: uuid.UUID, pid: uuid.UUID) -> tuple[list[str], str]:
    """(고른 키, 출처). 출처: chips(칩) · none(칩 '없어요') · memory(기억 diy 글) · not_asked(아직 안 물음).
    칩이 기억보다 먼저예요."""
    chips = await diy_for(s, pid)
    if chips is not None:
        return chips, ("chips" if chips else "none")
    said = next((m.value for m in await repo.memories(s, user_id) if m.key == "diy"), "")
    got = keys_in(said)
    return got, ("memory" if got else "not_asked")


@dataclass
class Got:
    keys: list[str]
    src: str
    phase: str  # final · expected · none(공정표를 못 읽음)
    tasks: list[calc_diy.DiyTask] = field(default_factory=list)
    occupied: bool = False
    pet: bool = False
    trades: list[str] = field(default_factory=list)  # 공정표의 업체 공정(공사 준비물 카드에 써요)


async def gather(
    s: AsyncSession,
    user: User,
    pid: uuid.UUID,
    today: date,
    *,
    free: calc_diy.Free | None = None,
    keys: list[str] | None = None,
    final_only: bool = False,
) -> Got:
    """고른 값 + 공정표 기준 날짜. keys를 주면 그 일만(고객이 물은 일). free가 없으면 기억의 편한 요일(주말)을 봐요.
    final_only면 확정 공정표가 없을 때 날짜를 만들지 않아요(챙기기). 남의 공사면 AppError(404)."""
    from app.assistant import memory
    from app.project import service as project_service
    from app.schedule import service as schedule_service

    p = await project_service.get_for(s, user, pid)
    chosen, src = await keys_for(s, user.id, pid)
    rows = await repo.memories(s, user.id)
    if free is None:
        free = "weekend" if memory.prefs(rows)[1] == "weekend" else "any"
    got = Got(keys=chosen, src=src, phase="none", occupied=bool(p.occupied))
    got.pet = any(m.key == "pet" for m in rows)
    want = keys if keys is not None else chosen
    if not want:
        return got
    try:
        plan = await schedule_service.plan_for(s, user, pid, today)
    except (AppError, ValueError):
        plan = None
    if plan is None or (final_only and plan.kind != "final"):
        got.tasks = calc_diy.plan(want, {}, today) if not final_only else []
        return got
    got.phase = "final" if plan.kind == "final" else "expected"
    got.trades = [b.trade for b in plan.blocks if b.kind == "work" and b.trade]
    got.tasks = schedule_service.diy_tasks(
        plan, want, today, free=free, move_in=schedule_service.move_in_of(p)
    )
    return got


# ---- 카드 ----


def _home_lines(item: know.Item, g: Got) -> list[str]:
    return [*(item.living if g.occupied else ()), *(item.pet if g.pet else ())]


def list_card(pid: uuid.UUID, g: Got, *, tools: bool = False) -> CardOut:
    """고른 일 모두: 체크 칸은 할 일마다 한 줄(때 · 날짜), 줄은 일마다 때(tools면 준비물) · 빠듯함 · 전기 안전."""
    keys = list(dict.fromkeys(t.key for t in g.tasks))
    lines: list[str] = []
    if g.phase in PHASE_KO:
        lines.append(f"날짜는 {PHASE_KO[g.phase]} 공정표 기준이에요.")
    for k in keys:
        it = know.item(k)
        lines.append(
            f"{it.label}: {' · '.join(it.tools[:3])}" if tools else f"{it.label}: {it.when}"
        )
    lines += [f"{t.name}: {WHY_NOTE[t.why]}" for t in g.tasks if t.why in ("short", "no_free_day")]
    if any(k in ELECTRIC for k in keys):
        lines.append(SAFETY)
    srcs = list(dict.fromkeys(x.publisher for k in keys for x in know.item(k).sources))
    data = KnowledgeData(
        title="직접 할 일 준비물" if tools else "직접 할 일",
        lines=lines[:8],
        source=" · ".join([*srcs[:3], "믿집 안내"]),
        checklist=[
            CheckItem(key=_item_key(t), label=f"{t.name} · {when_text(t)}") for t in g.tasks
        ],
        href=cards.href(pid, "/plan"),
    )
    return CardOut(card_id=f"diy-{pid}", kind="knowledge", data=data.model_dump(mode="json"))


def item_card(pid: uuid.UUID, key: str, g: Got) -> CardOut:
    """한 가지: 때 · 이 집 날짜 · 방법 · 주의점 줄 + 준비물 체크 칸(정해 둔 글, 날짜만 계산 엔진)."""
    it = know.item(key)
    mine = [t for t in g.tasks if t.key == key]
    lines = [it.when]
    lines += [f"{t.name}: {when_text(t)}" for t in mine]
    if mine and g.phase in PHASE_KO:
        lines.append(f"날짜는 {PHASE_KO[g.phase]} 공정표 기준이에요.")
    lines += [*it.how[:3], *it.cautions[:2], *_home_lines(it, g)]
    data = KnowledgeData(
        title=f"{it.label} · 직접 할 때",
        lines=lines[:10],
        source=it.source_line(),
        checklist=[CheckItem(key=f"{key}-tool{i}", label=x) for i, x in enumerate(it.tools, 1)],
        href=cards.href(pid, "/plan"),
    )
    return CardOut(card_id=f"diy-{key}-{pid}", kind="knowledge", data=data.model_dump(mode="json"))


def model_of(g: Got, focus: str | None = None) -> dict:
    """모델에 보낼 값(허용 칸만): 출처 · 공정표 기준 · 할 일마다 날짜(계산 엔진) · 때 · 준비물 · 주의점."""
    items = []
    for t in g.tasks:
        it = know.item(t.key)
        row: dict = {
            "kind": t.key,
            "step": t.step or None,
            "title": t.name,
            "start": t.start,
            "end": t.end,
            "day": t.day,
            "fit": t.fit,
            "note": WHY_NOTE.get(t.why),
            "when": it.when,
            "source": it.source_line(),
        }
        if focus is None or focus == t.key:
            row |= {"prep": list(it.tools), "cautions": [*it.cautions, *_home_lines(it, g)]}
        items.append(row)
    return {"state": g.src, "phase": g.phase, "note": SRC_NOTE[g.src], "items": items}


def _overview_all(today: date) -> Got:
    """아직 고르지 않았을 때 보여 줄 직접 하기 쉬운 일(날짜 없이 순서만)."""
    keys = [k for k in KEYS if k != "clean"]
    return Got(keys=keys, src="not_asked", phase="none", tasks=calc_diy.plan(keys, {}, today))


# ---- 도구 ----


class DiyIn(BaseModel):
    item: Literal["all", "paint", "outlet", "light", "silicone", "handle", "clean"] = "all"
    days: Literal["any", "weekend"] | None = None


@tool(
    "diy_plan",
    surface="customer",
    kind="read",
    status="직접 할 일을 챙기고 있어요",
    description="고객이 직접 하기로 고른 일(반셀프: 페인트(문틀 · 몰딩) · 콘센트 · 스위치 커버 · 조명 교체 · 실리콘 · "
    "줄눈 · 손잡이 · 입주 청소)의 언제부터 · 언제까지(믿집 계산, 공정표 기준) · 하는 방법 · 준비물 · 주의점(출처)을 "
    "읽어요. item을 주면 그 일만(고르지 않은 일도 때 · 방법은 알려 줘요), all이면 고른 일 모두예요. days는 고객이 "
    "직접 할 수 있는 날이에요(weekend: 주말 · 공휴일만, 비우면 기억한 편한 요일). 고객이 직접 할 일 · 셀프 · "
    "'페인트 언제 칠해요'를 묻거나 준비물을 물을 때 써요. 콘센트 옮기기 · 배선은 직접 할 일이 아니라 전기 공사업체 "
    "일이에요.",
    model=DiyIn,
    schema=obj(
        {
            "item": {
                "type": "string",
                "enum": ["all", "paint", "outlet", "light", "silicone", "handle", "clean"],
                "description": "all 고른 일 모두 · 그 밖은 한 가지",
            },
            "days": {"type": "string", "enum": ["any", "weekend"]},
        },
        required=[],
    ),
)
async def diy_plan(tc: ToolCtx, a: DiyIn) -> ToolOut:
    pid = pid_of(tc)
    focus = None if a.item == "all" else a.item
    async with SessionLocal() as s:
        g = await gather(s, tc.user, pid, tc.today, free=a.days, keys=[focus] if focus else None)
    if focus is not None:
        return ToolOut(data=model_of(g, focus), cards=[item_card(pid, focus, g)])
    if not g.tasks:
        shown = _overview_all(tc.today) if g.src == "not_asked" else g
        data = model_of(g)
        return ToolOut(data=data, cards=[list_card(pid, shown)] if shown.tasks else [])
    return ToolOut(data=model_of(g), cards=[list_card(pid, g)])


# ---- 무료 모드(free.answer가 한 줄로 부른다) ----


async def free_answer(tc: ToolCtx, text: str) -> tuple[str, ToolOut] | None:
    """직접 할 일 모두 · 한 가지의 때 · 방법 · (칩이 있을 때) 준비물을 묻는 말 → diy 카드 + 정해 둔 글.
    해당하지 않으면 None(원래 길잡이로)."""
    if tc.surface != "customer" or tc.project_id is None:
        return None
    t = text or ""
    asked = [k for k in keys_in(t) if not (k == "outlet" and MOVE.search(t))]
    listing = bool(LIST.search(t))
    prep = bool(PREP_WORD.search(t))
    if not listing and not (asked and (ASK.search(t) or SELF_SAID.search(t))) and not prep:
        return None
    free: calc_diy.Free | None = "weekend" if WEEKEND.search(t) else None
    pid = tc.project_id
    try:
        async with SessionLocal() as s:
            if asked and not listing:
                keys = asked if len(asked) > 1 else [asked[0]]
                g = await gather(s, tc.user, pid, tc.today, free=free, keys=keys)
            else:
                g = await gather(s, tc.user, pid, tc.today, free=free)
    except AppError:
        return None
    g.pet = g.pet or bool(PET.search(t))
    if asked and not listing:
        if len(asked) == 1:
            key = asked[0]
            return _focus_text(key, g), ToolOut(data={}, cards=[item_card(pid, key, g)])
        return _list_text(g), ToolOut(data={}, cards=[list_card(pid, g)])
    if prep and not listing:
        if not g.tasks:
            return None  # 직접 할 일이 없으면 원래 길잡이(지식 답)로
        work = cards.prep_card(f"prep-{pid}", g.trades or ["dobae"])  # 공사 날 준비물(공정 설정)
        return FREE_PREP, ToolOut(data={}, cards=[list_card(pid, g, tools=True), work])
    if g.src == "none":
        return FREE_NONE, ToolOut(data={})
    if not g.tasks:
        return FREE_NOT_ASKED, ToolOut(data={}, cards=[list_card(pid, _overview_all(tc.today))])
    return _list_text(g), ToolOut(data={}, cards=[list_card(pid, g)])


def _list_text(g: Got) -> str:
    if g.phase not in PHASE_KO:
        return "고르신 직접 할 일이에요. 공사 날짜가 정해지면 날짜를 알려 드려요."
    said = FREE_LIST.format(phase=PHASE_KO[g.phase])
    first = next((t for t in g.tasks if t.day is not None and t.fit), None)
    if first is not None:
        said += FREE_FIRST.format(name=first.name, when=when_text(first))
    tight = [t.name for t in g.tasks if not t.fit and not t.late]
    if tight:
        said += FREE_TIGHT.format(names=", ".join(tight))
    return said


def _focus_text(key: str, g: Got) -> str:
    it = know.item(key)
    mine = [t for t in g.tasks if t.key == key and t.day is not None]
    said = f"{it.label}: {it.when}"
    if mine:
        dated = " · ".join(f"{t.name} {when_text(t)}" for t in mine)
        said += f" 이 집 {PHASE_KO.get(g.phase, '')} 공정표로는 {dated}."
    if key in ELECTRIC:
        said += f" {SAFETY}"
    return said + " 방법 · 준비물 · 주의점은 카드에 적었어요."


# ---- 챙기기(확정 공정표만) ----


async def today_rows(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date
) -> tuple[list[TodayRow], list[dict]]:
    """오늘 정할 일: 마감이 7일 안인 직접 할 일(확정 공정표 기준). (줄, 모델 값)."""
    try:
        g = await gather(s, user, pid, today, final_only=True)
    except AppError:
        return [], []
    soon = calc_diy.due_soon(g.tasks, today)
    rows = [
        TodayRow(
            id=_item_key(t),
            icon="bulb",
            title=f"{t.name} · {calc_diy.SELF}",
            sub=f"{md_day(t.end)}까지" if t.end else None,
            due=t.end is not None and (t.end - today).days <= 1,
            action=RowAction(label="방법 보기", say=f"{DIY[t.key]} 언제 · 어떻게 해요?"),
        )
        for t in soon
    ]
    model = [{"title": f"{t.name} · {calc_diy.SELF}", "end": t.end} for t in soon]
    return rows, model


async def prep_part(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date
) -> tuple[list[str], list[str]]:
    """공사 1주 전 할 일에 더할 (줄, 체크 칸): 고른 직접 할 일의 마감 · 시작(확정 공정표 기준)."""
    try:
        g = await gather(s, user, pid, today, final_only=True)
    except AppError:
        return [], []
    items = [f"{t.name} · {when_text(t)} · {calc_diy.SELF}" for t in g.tasks if not t.late]
    lines = [f"{t.name}: {WHY_NOTE[t.why]}" for t in g.tasks if t.why == "short"]
    return lines, items


async def eve_card(
    s: AsyncSession, user: User, pid: uuid.UUID | None, today: date, card: CardOut
) -> CardOut:
    """공사 전날 준비물 카드에 직접 할 일을 더한다: 오늘까지 할 일 · 끝냈는지 볼 일(마감 지남) · 공사 뒤 할 일.
    칩 · 기억이 없거나 확정 공정표가 없으면 카드 그대로."""
    if pid is None:
        return card
    try:
        g = await gather(s, user, pid, today, final_only=True)
    except AppError:
        return card
    if not g.tasks:
        return card
    extra: list[str] = []
    for t in g.tasks:
        if t.kind == "before" and t.late:
            extra.append(f"{t.name} · 끝냈는지 확인해요 · {calc_diy.SELF}")
        elif t.kind == "before" and t.end == today:
            extra.append(f"{t.name} · 오늘까지 해요 · {calc_diy.SELF}")
        elif t.kind == "after" and t.day is not None:
            extra.append(f"{t.name} · {when_text(t)} · {calc_diy.SELF}")
    if not extra:
        return card
    data = KnowledgeData.model_validate(card.data)
    have = len(data.checklist)
    data.checklist += [CheckItem(key=f"diy{i}", label=x) for i, x in enumerate(extra, have + 1)]
    if any(k in ELECTRIC for k in g.keys):
        data.lines = [*data.lines, SAFETY]
    return card.model_copy(update={"data": data.model_dump(mode="json")})


# ---- 업체에 알리기 ----


async def offer_part(
    s: AsyncSession, user_id: uuid.UUID, pid: uuid.UUID
) -> tuple[SummaryRow | None, list[str]]:
    """실측 요청 승인 카드 줄 '업체에 알릴 것'과 payload diy(고른 키). 직접 할 일이 없으면 (None, [])."""
    keys, _src = await keys_for(s, user_id, pid)
    keys = [k for k in KEYS if k in set(keys)]
    if not keys:
        return None, []
    row = SummaryRow(
        label="업체에 알릴 것",
        value="고객이 직접 해요 — " + " · ".join(DIY[k] for k in keys),
        sub="승인하면 요청에 남아 업체가 요청서에서 봐요",
    )
    return row, keys


async def told_labels(s: AsyncSession, visit_id: uuid.UUID) -> list[str]:
    """요청 때 고정한 '고객이 직접 할 일'(visits.diy) 화면 말. 업체 브리핑이 자료로 보여요."""
    from app.visit.models import Visit

    keys = await s.scalar(select(Visit.diy).where(Visit.id == visit_id)) or []
    return [DIY[k] for k in KEYS if k in set(keys)]
