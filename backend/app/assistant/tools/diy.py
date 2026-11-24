"""반셀프 직접 할 일: 고객 읽기 도구 diy_plan · 챙기기(오늘 할 일 · 공사 1주 전 · 공사 전날) · 업체에 알리기.

- 직접 할 일의 원본은 저장된 칩(project.diy.diy_for)뿐이에요(리드 결정 11-22, QA r3 s6). 칩을 아직 묻지
  않았으면(None) 고른 일이 없어요. 기억 diy 글(고객이 대화에서 한 말)은 원본이 아니라 카드 · 실측 요청 '업체에
  알릴 것' · 업체 브리핑에 넣지 않아요. '없어요'(빈 목록)면 직접 할 일이 없어요. 에이전트 추측은 쓰지 않아요.
- 고객이 직접 할 일 카드를 거두거나 줄이거나 '없어요'로 저장하면 같은 일을 말하는 기억 조각도 지워요(forget,
  assistant.actions가 불러요).
- 날짜는 공정표(schedule.service.plan_for: 확정이 있으면 확정, 없으면 예상) 블록 → schedule.service.diy_tasks(calc.diy)
  값만 써요. 글은 knowledge/diy.json 정해 둔 글(숫자 없음)이고, 날짜 말만 계산 엔진 값으로 적어요.
- 할 일 날짜(start · end · day)는 공정표 '고객이 직접' 줄과 같은 값이에요(모든 날 any · 사는 집 occupied). 고객이
  주말 · 공휴일만 된다고 했으면(도구 days · 기억 '주말에만') 주말 · 공휴일만으로 다시 찾은 값(alt)을 근거와 같이
  더해요: '12월 17일(목) ~ 12월 20일(일) 사이에 해요 · 주말이면 12월 19일(토)도 돼요'(QA r2 c3).
- 실측을 요청한 뒤 직접 할 일을 바꾸면 확정 전 요청 · 공사 시작 전 확정은 믿집이 사본을 고치고 알려요. 공사가
  시작된 확정 업체만 따로 알려야 해요(visit.flow.diy_reach · sync_diy, QA r2 c2 · r3 c2 · c6). diy_plan 결과의
  vendors는 requests(믿집이 알리는 업체) · deals(사본에 지금 직접 할 일이 빠져 따로 알려야 하는 업체)예요. 사본에
  이미 들어 있으면 따로 알리라고 하지 않아요.
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
from datetime import date, datetime
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
    # 벽지를 직접 사는 말만('벽지 직접 구매' · '벽지는 제가 살게요'). 벽지 고르기 · 도배 자체는 아니에요
    "paper_buy": re.compile(
        r"벽지[^.?!\n]{0,8}?(?:구매|구입|주문|사\s{0,2}(?:서|고|면|요|려|올|둘|두|다|는|러)|"
        r"살\s{0,2}(?:게|래|거|까)|샀)"
    ),
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
# 주말 · 공휴일만 되는 근거(free_src) → 카드 줄 · 모델 값
WEEKEND_LINE = {
    "memory": "주말에만 된다고 하셔서 주말 날도 같이 적었어요.",
    "asked": "주말 · 공휴일에 할 날도 같이 적었어요.",
}
DAYS_NOTE = {
    "memory": "고객이 주말에만 된다고 한 기억이 있어요.",
    "asked": "고객이 이번에 주말 · 공휴일만 된다고 했어요.",
}
DATES_NOTE = (
    "start · end · day는 공정표 '고객이 직접' 줄과 같은 값이에요. weekend는 주말 · 공휴일만으로 다시 찾은 값이라 "
    "공정표 날과 다르면 둘 다 알려요(text는 카드에 적은 말)."
)
# 직접 할 일을 바꾸면 닿는 업체(diy_plan · propose_home_info 결과 vendors)
REACH_LIVE = (
    "실측을 요청한 업체 · 공사 시작 전 확정 업체(requests)는 직접 할 일을 바꾸면 믿집이 요청 사본에 고쳐 적고 "
    "알림을 보내요."
)
REACH_SYNCED = (
    "지금 직접 할 일은 그 업체(requests) 요청 사본에 이미 들어 있어요. 따로 알리지 않아도 돼요."
)
REACH_DEALT = "확정한 업체(deals)는 {note}. 업체 채팅으로 알려 달라고 안내해요."
SRC_NOTE = {
    "chips": "고객이 고른 직접 할 일이에요.",
    "none": "고객이 직접 할 일은 없다고 골랐어요.",
    "not_asked": (
        "고객이 아직 직접 할 일을 고르지 않았어요. 대화에서 말한 일(기억)은 저장 전이라 카드 · 실측 요청 · 업체에 "
        "들어가지 않아요. 집 정보 승인 카드(직접 할 일)나 표준견적서 화면에서 저장해요."
    ),
}
WHY_NOTE = {
    "short": "앞 공사와 뒤 공사 사이가 모자라 날이 빠듯해요. 업체와 날짜를 맞춰 보세요.",
    "no_free_day": "그 사이에 주말 · 공휴일이 없어요. 업체와 날짜를 맞추거나 하루를 비워 보세요.",
    "late": "마감이 지났어요.",
}
# 시작이 날짜 없는 앞 공사 뒤인 일(calc.diy after, diy_v4): 카드 말 · 모델 값 note(QA r6 c2: 새 몰딩을 달기 전에
# 칠하라는 꼴이었어요)
AFTER_WORD = {"mokgong": "목공이 끝난 뒤"}
AFTER_NOTE = {
    "mokgong": (
        "공정표에 목공 날짜가 없어 시작(start)은 '목공이 끝난 뒤'예요. 새 몰딩 · 걸레받이 · 문틀을 달면 그 목공이 끝난 "
        "뒤에, 목공이 없으면 지금부터 마감(end)까지 칠해요."
    )
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


def when_text(t: calc_diy.DiyTask, alt: calc_diy.DiyTask | None = None) -> str:
    """'언제부터 · 언제까지' 말(날짜는 계산 엔진 값, 공정표와 같은 값). alt(주말 · 공휴일만으로 찾은 값)를 주면
    공정표 날과 다를 때 '주말이면 …도 돼요'를 붙여요(QA r2 c3)."""
    said = _when(t)
    extra = alt_text(t, alt)
    return f"{said} · {extra}" if extra else said


def alt_text(t: calc_diy.DiyTask, alt: calc_diy.DiyTask | None) -> str | None:
    """주말 · 공휴일만 되는 고객에게 같이 알릴 말: 공정표 날과 다른 주말 날 · 그 사이에 주말 · 공휴일이 없음.
    공정표 날이 이미 주말 · 공휴일이거나 날이 빠듯 · 지남이면 없어요(그 말은 when_text가 해요)."""
    if alt is None or t.day is None or t.late or t.why == "short":
        return None
    if alt.why == "no_free_day":
        return "그 사이에 주말 · 공휴일이 없어요"
    if alt.day is None or alt.day == t.day:
        return None
    return f"주말이면 {ko_day(alt.day)}도 돼요"


def _when(t: calc_diy.DiyTask) -> str:
    if t.day is None:
        return "공사 날짜가 정해지면 날짜를 알려 드려요"
    if t.late and t.end is not None:
        return f"{ko_day(t.end)}까지였어요"
    # 시작이 날짜 없는 목공 뒤(diy_v4)
    if t.after is not None and t.start is None and t.end is not None:
        head = AFTER_WORD.get(t.after, t.after)
        if t.why == "no_free_day":
            return f"{head} ~ {ko_day(t.end)} 사이에 주말 · 공휴일이 없어요"
        return f"{head} ~ {ko_day(t.end)} 사이에 해요"
    if t.why == "short":  # 공정표 줄과 같은 날: 할 수 있는 첫날(calc.diy diy_v2 day, 마감 날 아님)
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


async def keys_for(s: AsyncSession, pid: uuid.UUID) -> tuple[list[str], str]:
    """(고른 키, 출처). 출처: chips(칩) · none(칩 '없어요') · not_asked(아직 안 물음). 원본은 저장된 칩뿐이에요
    (기억 diy 글로 채우지 않아요: 거둔 일이 다음 실측 요청에 다시 들어갔어요, QA r3 s6)."""
    chips = await diy_for(s, pid)
    if chips is None:
        return [], "not_asked"
    return chips, ("chips" if chips else "none")


@dataclass
class Got:
    keys: list[str]
    src: str
    phase: str  # final · expected · none(공정표를 못 읽음)
    tasks: list[calc_diy.DiyTask] = field(default_factory=list)
    occupied: bool = False
    pet: bool = False
    trades: list[str] = field(default_factory=list)  # 공정표의 업체 공정(공사 준비물 카드에 써요)
    free: str = "any"  # 고객이 할 수 있는 날(any · weekend)
    free_src: str = ""  # weekend 근거: asked(이번 말 · 도구 값) · memory(기억 '주말에만')
    # 주말 · 공휴일만으로 다시 찾은 값((key, step) → 할 일). 공정표 값(tasks)은 그대로예요(QA r2 c3)
    alt: dict[tuple[str, str], calc_diy.DiyTask] = field(default_factory=dict)

    def alt_of(self, t: calc_diy.DiyTask) -> calc_diy.DiyTask | None:
        return self.alt.get((t.key, t.step))

    def when(self, t: calc_diy.DiyTask) -> str:
        return when_text(t, self.alt_of(t))


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
    """고른 값 + 공정표 기준 날짜. keys를 주면 그 일만(고객이 물은 일). 날짜(tasks)는 공정표와 같은 값(any ·
    사는 집)이고, 주말 · 공휴일만 되면(free weekend, 비우면 기억의 편한 요일) 그 값(alt)을 더해요.
    final_only면 확정 공정표가 없을 때 날짜를 만들지 않아요(챙기기). 남의 공사면 AppError(404)."""
    from app.assistant import memory
    from app.project import service as project_service
    from app.schedule import service as schedule_service

    p = await project_service.get_for(s, user, pid)
    chosen, src = await keys_for(s, pid)
    rows = await repo.memories(s, user.id)
    free_src = "asked" if free == "weekend" else ""
    if free is None:
        free = "weekend" if memory.prefs(rows)[1] == "weekend" else "any"
        free_src = "memory" if free == "weekend" else ""
    got = Got(
        keys=chosen,
        src=src,
        phase="none",
        occupied=bool(p.occupied),
        free=free,
        free_src=free_src,
    )
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
    move_in, occupied = schedule_service.move_in_of(p), bool(p.occupied)
    # 공정표 '고객이 직접' 줄과 같은 값(schedule.service._with_diy와 같은 인자)
    got.tasks = schedule_service.diy_tasks(plan, want, today, move_in=move_in, occupied=occupied)
    if free == "weekend":
        alt = schedule_service.diy_tasks(
            plan, want, today, free="weekend", move_in=move_in, occupied=occupied
        )
        got.alt = {(t.key, t.step): t for t in alt}
    return got


# ---- 카드 ----


def _home_lines(item: know.Item, g: Got) -> list[str]:
    return [*(item.living if g.occupied else ()), *(item.pet if g.pet else ())]


def _basis_line(g: Got) -> str | None:
    """'날짜는 확정 공정표 기준이에요.' + 주말 날을 같이 적은 까닭(기억 · 이번 말)."""
    if g.phase not in PHASE_KO:
        return None
    said = f"날짜는 {PHASE_KO[g.phase]} 공정표 기준이에요."
    if any(alt_text(t, g.alt_of(t)) for t in g.tasks):
        said += f" {WEEKEND_LINE[g.free_src]}"
    return said


def _tight_lines(g: Got) -> list[str]:
    """빠듯한 일 · (주말 · 공휴일만 되는 고객) 그 사이에 주말이 없는 일의 까닭 줄."""
    out = [f"{t.name}: {WHY_NOTE[t.why]}" for t in g.tasks if t.why in ("short", "no_free_day")]
    for t in g.tasks:
        a = g.alt_of(t)
        if a is not None and alt_text(t, a) and a.why == "no_free_day":
            out.append(f"{t.name}: {WHY_NOTE['no_free_day']}")
    return out


def list_card(pid: uuid.UUID, g: Got, *, tools: bool = False) -> CardOut:
    """고른 일 모두: 체크 칸은 할 일마다 한 줄(때 · 날짜), 줄은 일마다 때(tools면 준비물) · 빠듯함 · 전기 안전."""
    keys = list(dict.fromkeys(t.key for t in g.tasks))
    lines: list[str] = []
    if (basis := _basis_line(g)) is not None:
        lines.append(basis)
    for k in keys:
        it = know.item(k)
        lines.append(
            f"{it.label}: {' · '.join(it.tools[:3])}" if tools else f"{it.label}: {it.when}"
        )
    lines += _tight_lines(g)
    if any(k in ELECTRIC for k in keys):
        lines.append(SAFETY)
    srcs = list(dict.fromkeys(x.publisher for k in keys for x in know.item(k).sources))
    data = KnowledgeData(
        title="직접 할 일 준비물" if tools else "직접 할 일",
        lines=lines[:8],
        source=" · ".join([*srcs[:3], "믿집 안내"]),
        checklist=[CheckItem(key=_item_key(t), label=f"{t.name} · {g.when(t)}") for t in g.tasks],
        href=cards.href(pid, "/plan"),
    )
    return CardOut(card_id=f"diy-{pid}", kind="knowledge", data=data.model_dump(mode="json"))


def item_card(pid: uuid.UUID, key: str, g: Got) -> CardOut:
    """한 가지: 때 · 이 집 날짜 · 방법 · 주의점 줄 + 준비물 체크 칸(정해 둔 글, 날짜만 계산 엔진)."""
    it = know.item(key)
    mine = [t for t in g.tasks if t.key == key]
    lines = [it.when]
    lines += [f"{t.name}: {g.when(t)}" for t in mine]
    if mine and (basis := _basis_line(g)) is not None:
        lines.append(basis)
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
    """모델에 보낼 값(허용 칸만, policy.ALLOWED): 출처 · 공정표 기준 · 할 일마다 날짜(계산 엔진, 공정표와 같은 값) ·
    카드에 적은 말(text) · 주말 · 공휴일 값(weekend, 그 고객만) · 때 · 준비물 · 주의점."""
    items = []
    for t in g.tasks:
        it = know.item(t.key)
        a = g.alt_of(t)
        row: dict = {
            "kind": t.key,
            "step": t.step or None,
            "title": t.name,
            "start": t.start,
            "end": t.end,
            "day": t.day,
            "fit": t.fit,
            "note": WHY_NOTE.get(t.why) or (AFTER_NOTE.get(t.after) if t.after else None),
            "text": g.when(t),
            "when": it.when,
            "source": it.source_line(),
        }
        if a is not None:
            row["weekend"] = {
                "start": a.start,
                "end": a.end,
                "day": a.day,
                "fit": a.fit,
                "note": WHY_NOTE.get(a.why),
            }
        if focus is None or focus == t.key:
            row |= {"prep": list(it.tools), "cautions": [*it.cautions, *_home_lines(it, g)]}
        items.append(row)
    out: dict = {"state": g.src, "phase": g.phase, "note": SRC_NOTE[g.src], "items": items}
    basis = [DATES_NOTE] if g.phase in PHASE_KO and g.tasks else []
    if g.free == "weekend":  # 주말 · 공휴일만 되는 근거(이번 말 · 기억)
        out["days"] = "weekend"
        basis.append(DAYS_NOTE[g.free_src])
    if basis:
        out["basis"] = basis
    return out


def _overview_all(today: date) -> Got:
    """아직 고르지 않았을 때 보여 줄 직접 하기 쉬운 일(날짜 없이 순서만). 입주 청소 · 벽지 직접 구매(일이 아니라
    사는 것)는 빼요."""
    keys = [k for k in KEYS if k not in ("clean", "paper_buy")]
    return Got(keys=keys, src="not_asked", phase="none", tasks=calc_diy.plan(keys, {}, today))


# ---- 도구 ----


class DiyIn(BaseModel):
    item: Literal["all", "paint", "outlet", "light", "silicone", "handle", "clean", "paper_buy"] = (
        "all"
    )
    days: Literal["any", "weekend"] | None = None


@tool(
    "diy_plan",
    surface="customer",
    kind="read",
    status="직접 할 일을 챙기고 있어요",
    description="고객이 직접 하기로 고른 일(반셀프: 페인트(문틀 · 몰딩) · 콘센트 · 스위치 커버 · 조명 교체 · 실리콘 · "
    "줄눈 · 손잡이 · 입주 청소 · 벽지 직접 구매)의 언제부터 · 언제까지(믿집 계산, 공정표 기준) · 하는 방법 · 준비물 · "
    "주의점(출처)을 읽어요. item을 주면 그 일만(고르지 않은 일도 때 · 방법은 알려 줘요), all이면 고른 일 모두예요. "
    "days는 고객이 직접 할 수 있는 날이에요(weekend: 주말 · 공휴일만, 비우면 기억한 편한 요일). 날짜(start · end · "
    "day)는 공정표 값이고, 주말 · 공휴일만 되면 그 값(weekend)도 같이 줘요: 다르면 둘 다 알려요. 고객이 직접 할 일 · "
    "셀프 · '페인트 언제 칠해요'를 묻거나 준비물을 물을 때 써요. 콘센트 옮기기 · 배선은 직접 할 일이 아니라 전기 "
    "공사업체 일이에요. 벽지 직접 구매(paper_buy)는 벽지를 고객이 사서 도배 전날까지 현장에 받아 두는 일이에요.",
    model=DiyIn,
    schema=obj(
        {
            "item": {
                "type": "string",
                "enum": ["all", *KEYS],
                "description": "all 고른 일 모두 · 그 밖은 한 가지",
            },
            "days": {"type": "string", "enum": ["any", "weekend"]},
        },
        required=[],
    ),
)
async def diy_plan(tc: ToolCtx, a: DiyIn) -> ToolOut:
    from app.visit import flow as visit_flow

    pid = pid_of(tc)
    focus = None if a.item == "all" else a.item
    async with SessionLocal() as s:
        g = await gather(s, tc.user, pid, tc.today, free=a.days, keys=[focus] if focus else None)
        reach = await visit_flow.diy_reach(s, pid, tc.today)
    data = model_of(g, focus)
    # 직접 할 일이 닿는 업체 · 사본에 빠져 따로 알릴 업체(QA r2 c2 · r3 c2 · c3)
    if reach.live or reach.missing:
        data["vendors"] = vendors_of(reach, current=True)
    if focus is not None:
        return ToolOut(data=data, cards=[item_card(pid, focus, g)])
    if not g.tasks:
        shown = _overview_all(tc.today) if g.src == "not_asked" else g
        return ToolOut(data=data, cards=[list_card(pid, shown)] if shown.tasks else [])
    return ToolOut(data=data, cards=[list_card(pid, g)])


def vendors_of(reach, *, current: bool = False) -> dict:
    """직접 할 일이 닿는 업체(visit.flow.DiyReach): 확정 전 요청 · 공사 시작 전 확정(requests)은 믿집이 요청 사본을
    고치고 알려요. 공사가 시작된 확정 업체(deals)에는 비서가 업체 채팅으로 따로 알리라고 안내해요(QA r2 c2).
    current(지금 상태를 읽음, diy_plan)면 deals는 사본에 지금 직접 할 일이 빠진 업체만이고, requests 사본이 모두
    지금과 같으면 이미 들어 있다고 적어요(QA r3 c2 21턴 · c3: 이미 간 일을 '따로 알리세요'). current가 아니면(바꾸는
    카드, propose_home_info) 공사가 시작된 확정 업체 모두가 deals예요."""
    from app.visit.flow import DIY_DEALT_NOTE

    out: dict = {}
    notes: list[str] = []
    if reach.live:
        out["requests"] = list(reach.live)
        notes.append(REACH_LIVE)
        if current and reach.synced:
            notes.append(REACH_SYNCED)
    deals = reach.missing if current else reach.dealt
    if deals:
        out["deals"] = list(deals)
        notes.append(REACH_DEALT.format(note=DIY_DEALT_NOTE))
    out["notes"] = notes
    return out


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
            home = await home_ctx(s, tc.user, pid, tc.today) if prep else None
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
        work = cards.prep_card(f"prep-{pid}", g.trades or ["dobae"], home)  # 공사 날 준비물
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
        said += FREE_FIRST.format(name=first.name, when=g.when(first))
    tight = [t.name for t in g.tasks if not t.fit and not t.late]
    if tight:
        said += FREE_TIGHT.format(names=", ".join(tight))
    return said


def _focus_text(key: str, g: Got) -> str:
    it = know.item(key)
    mine = [t for t in g.tasks if t.key == key and t.day is not None]
    said = f"{it.label}: {it.when}"
    if mine:
        dated = " · ".join(f"{t.name} {g.when(t)}" for t in mine)
        said += f" 이 집 {PHASE_KO.get(g.phase, '')} 공정표로는 {dated}."
    if key in ELECTRIC:
        said += f" {SAFETY}"
    return said + " 방법 · 준비물 · 주의점은 카드에 적었어요."


# ---- 집에 맞추기: 공사 전 할 일 · 전날 준비물 ----


async def home_ctx(s: AsyncSession, user: User, pid: uuid.UUID, today: date) -> cards.HomeCtx:
    """이 집 사실(cards.HomeCtx): 살면서 공사 · 기억(반려동물 · 주말에만) · 수락한 공사 날에 평일이 있는지 · 고른
    직접 할 일 · 이 공사 공정(공사 정보 · 업체 확정) · 모은 조건 곰팡이 · 다가오는 공사 날(없으면 오늘)이 추운 철인지.
    남의 공사면 AppError(404)."""
    from datetime import timedelta

    from app.assistant import memory
    from app.project import service as project_service
    from app.schedule import service as schedule_service

    p = await project_service.get_for(s, user, pid)
    rows = await repo.memories(s, user.id)
    keys, _src = await keys_for(s, pid)
    conds = await project_service.conditions(s, pid)
    weekday = False
    trades = {c for c in ("dobae", "mokgong") if getattr(p.trades, c, None) is not None}
    ahead: list[date] = []  # 오늘부터의 공사 날
    for d in await schedule_service.deals_for(s, user, pid, None, today):
        trades.add(d.trade)
        if d.start_date is None or d.end_date is None:
            continue
        span = d.work_days or [
            d.start_date + timedelta(days=i) for i in range((d.end_date - d.start_date).days + 1)
        ]
        weekday = weekday or any(x.weekday() < 5 for x in span)
        ahead += [x for x in span if x >= today]
    return cards.HomeCtx(
        occupied=bool(p.occupied),
        pet=any(m.key == "pet" for m in rows),
        away_weekdays=memory.prefs(rows)[1] == "weekend",
        weekday_work=weekday,
        diy=tuple(keys),
        trades=tuple(sorted(trades)),
        mold=conds.get("dobae.mold") == "있어요",  # 공정 설정 칸 dobae.mold의 '있어요'
        cold=min(ahead, default=today).month in cards.COLD_MONTHS,
    )


def undated_items(keys) -> list[str]:
    """공사 날짜가 정해지기 전: 고른 직접 할 일을 공사 전 · 뒤로만(이름은 calc.diy, 업체 공사 날짜가 없으면
    calc.diy.plan은 날짜 없이 순서만 줘서 오늘 값을 쓰지 않아요)."""
    from app.shared.clock import today_seoul

    return [
        f"{t.name} · {'공사 전에 해요' if t.kind == 'before' else '공사 뒤에 해요'} · {calc_diy.SELF}"
        for t in calc_diy.plan(list(keys), {}, today_seoul())
    ]


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
    items = [f"{t.name} · {g.when(t)} · {calc_diy.SELF}" for t in g.tasks if not t.late]
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
            extra.append(f"{t.name} · {g.when(t)} · {calc_diy.SELF}")
    if not extra:
        return card
    data = KnowledgeData.model_validate(card.data)
    have = len(data.checklist)
    data.checklist += [CheckItem(key=f"diy{i}", label=x) for i, x in enumerate(extra, have + 1)]
    if any(k in ELECTRIC for k in g.keys):
        data.lines = [*data.lines, SAFETY]
    return card.model_copy(update={"data": data.model_dump(mode="json")})


# ---- 업체에 알리기 ----


TOLD_LABEL = "업체에 알릴 것"


def told_row(keys: list[str]) -> SummaryRow | None:
    """실측 요청 승인 카드 줄 '업체에 알릴 것'(칩 키 → 화면 말). 없으면 None."""
    keys = [k for k in KEYS if k in set(keys)]
    if not keys:
        return None
    return SummaryRow(
        label=TOLD_LABEL,
        value="고객이 직접 해요 — " + " · ".join(DIY[k] for k in keys),
        sub="승인하면 요청에 남아 업체가 요청서에서 봐요",
    )


async def offer_part(
    s: AsyncSession, user_id: uuid.UUID, pid: uuid.UUID
) -> tuple[SummaryRow | None, list[str]]:
    """실측 요청 승인 카드 줄 '업체에 알릴 것'과 payload diy(저장된 칩 키). 직접 할 일이 없으면 (None, []).
    user_id는 부르는 쪽 모양을 지키려고 남겨 둬요(기억은 읽지 않아요)."""
    keys, _src = await keys_for(s, pid)
    keys = [k for k in KEYS if k in set(keys)]
    return told_row(keys), keys


async def forget(
    s: AsyncSession, user_id: uuid.UUID, keys: list[str] | set[str], now: datetime
) -> int:
    """기억 '직접 할 일'에서 그 칩 일(keys)만 말하는 조각을 지운다(리드 결정 11-22: 고객이 직접 할 일 카드를
    거두거나 줄이거나 '없어요'로 저장하면 같은 일을 말하는 기억도 빠져요, 기억 화면에서도). 칩 낱말이 없는
    조각('장판 직접')과 남는 일도 같이 말하는 조각은 그대로예요. 다 빠지면 그 줄을 지워요. 바꾼 줄 수.
    commit은 부르는 쪽."""
    from app.assistant import memory

    drop = set(keys)
    if not drop:
        return 0

    def keep(part: str) -> bool:
        said = set(keys_in(part))
        return not said or not said <= drop

    return await memory.drop_parts(s, user_id, "diy", keep, now)


async def settle_memory(s: AsyncSession, user: User, now: datetime) -> int:
    """화면(PUT /diy)에서 칩을 줄이거나 '없어요'로 저장한 뒤 남은 직접 할 일 기억 조각을 늦게 맞춘다(리드 결정
    11-22: 층 규칙 예외를 더하지 않고 비서 쪽에서, 턴 시작 · 기억 화면 · 보드). 기억은 사람마다라 이 고객 공사 중
    칩을 저장한 공사의 칩(합)에 없는 칩 일 조각만 조용히 지운다. 칩을 한 번도 저장하지 않았으면('아직 안 물음',
    '없어요' 저장과 다름) 그대로예요. 바꾼 줄 수. commit은 부르는 쪽."""
    from app.project import service as project_service

    saved: set[str] | None = None
    for p in await project_service.list_mine(s, user):
        chips = await diy_for(s, p.id)
        if chips is not None:
            saved = (saved or set()) | set(chips)
    if saved is None:
        return 0
    return await forget(s, user.id, [k for k in KEYS if k not in saved], now)


async def told_labels(s: AsyncSession, visit_id: uuid.UUID) -> list[str]:
    """요청 때 고정한 '고객이 직접 할 일'(visits.diy) 화면 말. 업체 브리핑이 자료로 보여요."""
    from app.visit.models import Visit

    keys = await s.scalar(select(Visit.diy).where(Visit.id == visit_id)) or []
    return [DIY[k] for k in KEYS if k in set(keys)]
