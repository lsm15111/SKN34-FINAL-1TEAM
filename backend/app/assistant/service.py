"""비서 서비스 (계약서 3장 · 4장): 턴 시작 · 끝 · SSE · 승인 · 거절 · 대화 기록 · 보드 · 오늘 · 업체 브리핑.

- start_turn(짧은 세션): 같은 client_key면 되돌림(done) 또는 409(running) → 권한(남의 공사 · 요청 404) → 시간당
  요청 제한 → 비서 대화(chats.kind=assistant) → 멈춘 턴 정리 → running 행(대화 잠금, 부분 UNIQUE → 409
  turn_running) → 최근 24줄 · 열린 제안 · 턴 사실(업체마다 상태 · 채팅 · 실제 단계) → commit. 세션을 닫은 뒤
  LLM을 부른다.
- finish_turn(한 트랜잭션): rev 올리기(조건부) → 가린 질문 · 검사한 답 두 줄 → (기억할 말이면 기억 일) →
  턴 done → commit → 다음에 물을 말(suggest_for) → done 이벤트.
- SSE: 모든 data에 seq, 머리에 id {turn_id}:{seq}. action은 행 commit 뒤, done은 대화 저장 commit 뒤.
  스트림을 열기 전 오류(404 · 409 · 429)는 같은 오류 모양이다. 화면이 끊어도 턴은 끝까지 돌려 저장한다.
- 먼저 말 걸기(proactive): 대화 기록 첫 쪽 · 오늘 · 다음에 물을 말에 보낸 줄을 넣고, 열기 · 닫기는 nudge_act.
  worker는 sweep(2분: 이벤트 · 평가) · hourly(시간 · 무응답)를 부른다.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.assistant import actions, choices, policy, runtime
from app.assistant import repository as repo
from app.assistant.models import AssistantTurn
from app.assistant.runtime import RefTable, TurnCtx, TurnResult
from app.assistant.schemas import (
    ActionOut,
    ActionPart,
    ApproveIn,
    AssistantItem,
    AssistantThreadOut,
    BoardMoneyOut,
    BoardOut,
    BoardPeriod,
    BoardVendors,
    CardOut,
    CardPart,
    ErrorOut,
    FeedPage,
    HealthOut,
    LinkOut,
    MemoryOut,
    NudgeOut,
    QuoteChecklistData,
    SuggestOut,
    TextPart,
    TodayData,
    TurnContextIn,
    TurnOut,
    UserItem,
    VendorBriefData,
    VendorTodayData,
)
from app.auth.models import User
from app.chat import repository as chat_repo
from app.chat.models import Chat, ChatMessage
from app.config import settings
from app.db import SessionLocal
from app.shared import kdate
from app.shared.clock import SEOUL, now_utc, today_seoul
from app.shared.errors import AppError

log = logging.getLogger(__name__)

TURNS_PER_HOUR = 60  # 사용자별 시간당 턴 수(APP_ENV=local이면 세지 않음, v3와 같음)
# 지난 글 줄 수(계약서 4장 1). 12줄(여섯 턴)이면 앞에서 한 말을 '처음 나왔다'고 고쳐 말해 24줄로 늘렸다(QA r3 c5).
# 턴 비용(상한 $0.06)을 지키려고 최근 HISTORY_FULL줄은 그대로, 그 앞 비서 글은 앞 HISTORY_CUT자(문장 단위)만 보낸다
HISTORY = 24
HISTORY_FULL = 12
HISTORY_CUT = 200
# 지난 글 창보다 앞 대화가 있을 때 턴 사실에 넣는 줄(앞 대화를 몰라 고객 말을 틀리게 고치지 않게)
OLDER = "지난 대화: 앞부분은 안 보이고 최근 {n}턴만 보여요"
STALL = timedelta(minutes=2)  # heartbeat가 이만큼 멈추면 failed 'stalled'
FEED_LIMIT = 30
RUNNING = "앞 답을 만드는 중이에요. 끝나면 다시 보내 주세요."
TOO_MANY = "비서에게 너무 많이 물었어요. 잠시 뒤에 다시 해 주세요."
FAILED = "답을 끝까지 만들지 못했어요. 다시 해 주세요."
CARDS_ONLY = "(카드를 보여 줬어요"
_BACKGROUND: set[asyncio.Task] = set()  # 화면이 끊어도 끝까지 도는 턴


# ---- 턴 시작 ----


def clip(text: str, n: int = HISTORY_CUT) -> str:
    """긴 글 → 앞 문장들(n자 안). 첫 문장부터 n자를 넘으면 n자에서 자르고 '…'. n자 안이면 그대로."""
    text = text.strip()
    if len(text) <= n:
        return text
    out = ""
    for x in (p.strip() for p in runtime.SENT_END.split(text) if p.strip()):
        joined = f"{out} {x}".strip()
        if len(joined) > n:
            break
        out = joined
    return (out or text[: n - 1]) + "…"


def _history(rows: list[ChatMessage]) -> list[dict]:
    """지난 글(Claude 꼴). 최근 HISTORY_FULL줄 앞의 비서 글은 앞부분만 보낸다(고객 말은 그대로)."""
    old = len(rows) - HISTORY_FULL
    out = [
        {
            "role": m.role,
            "content": clip(m.text) if i < old and m.role == "assistant" else m.text,
        }
        for i, m in enumerate(rows)
        if m.text.strip()
    ]
    while out and out[0]["role"] != "user":  # Claude는 user로 시작한다
        out.pop(0)
    return out


# 처리한 제안 상태 → 턴 사실 말(모델이 이미 처리된 카드를 '안 만들어졌다'고 고쳐 말하지 않게).
# 실행 못 한 카드(실패 · 실행 없이 닫힘)는 서버가 고객에게 준 말을 까닭으로 붙인다(비서가 까닭을 지어내지 않게)
DECIDED = {
    "executed": "승인해 실행됨",
    "rejected": "거절함",
    "failed": "승인했지만 실행 못 함",
    "expired": "실행 안 됨 · 닫힘",
}
# 실행 없이 닫힌 제안 중 턴 사실에 넣는 까닭. 새 카드로 바뀐 카드도 넣는다(QA r3 c6 T13 · s4: 닫힌 앞 카드를
# '아직 남아 있을 수 있어요' · '거둘까요?'라고 말함)
CLOSED_REASONS = ("due", "handled_elsewhere", "replaced")
DECIDED_MAX = 6  # 턴 사실 '최근 처리한 카드' 수(바뀐 카드까지 넣어 넷에서 늘림)
# 승인 카드 종류 → (턴 사실에 붙일 종류 말, 제목에 있으면 종류 말을 붙이지 않는 낱말). 제목만으로는 무엇에 대한 카드인지
# 모르는 것이 있어요(QA r3 c1 16 · 17턴: '도배 12월 14일(월)~16일(수) 수락'이 열려 있는데 수락 카드를 또 만들까 물음)
CARD_KIND: dict[str, tuple[str, tuple[str, ...]]] = {
    "home_info": ("집 정보", ("집 정보", "직접 할 일")),
    "visit_request": ("실측 요청", ("실측 요청",)),
    "visit_slot": ("실측 시간", ("실측 시간", "반나절")),
    "vendor_confirm": ("업체 확정", ("업체 확정",)),
    "dates_accept": ("공사 날짜 수락", ("공사 날짜 수락",)),
    "delay_accept": ("바뀐 공사 날짜 수락", ("바뀐 공사 날짜",)),
    "date_change": ("공사 날짜 바꾸기", ("날짜 바꾸기", "날짜 요청")),
    "visit_cancel": ("실측 요청 취소", ("취소",)),
    "extra_answer": ("추가 금액 답", ("추가 금액",)),
    "work_check": ("공사 끝 확인", ("공사 끝", "남은 일")),
    "visit_again": ("실측 다시 요청", ("한 번 더", "다시 요청")),
    "window_answer": ("기간 답하기", ("답하기",)),
    "decline": ("못 받아요", ("못 받아요",)),
    "dates": ("공사 날짜 보내기", ("보내기",)),
}


def card_name(a, label: str | None = None) -> str:
    """승인 카드 한 장 → 턴 사실 이름: 종류 말(제목에 없을 때) + 제목 + 업체 · 요청 이름(제목에 없을 때).
    label은 업체 쪽 요청 이름('노원구 32평 도배')이에요. 고객 카드의 업체는 요약 칸 '업체'에서 읽어요."""
    summary = a.summary or {}
    title = summary.get("title") or a.kind
    kind = CARD_KIND.get(a.kind)
    head = f"{kind[0]}: " if kind and not any(w in title for w in kind[1]) else ""
    rows = summary.get("rows") or []
    vendor = next(
        (str(r.get("value")) for r in rows if isinstance(r, dict) and r.get("label") == "업체"),
        None,
    )
    tail = "".join(f" · {x}" for x in dict.fromkeys((vendor, label)) if x and x not in title)
    return f"{head}{title}{tail}"


def _why_not(a) -> str | None:
    """실행 못 한 카드의 까닭(첫 문장): 서버가 남긴 말(result.message), 없으면 그 카드를 누를 때 서버가 주는 말."""
    from app.visit.service import QUOTE_CHANGED

    res = a.result or {}
    if a.status not in ("failed", "expired"):
        return None
    reason = res.get("reason") if a.status == "expired" else (a.error_code or "failed")
    said = res.get("message") or (
        QUOTE_CHANGED
        if reason == "quote_changed"
        else actions.CLOSED.get(reason or "failed", actions.CLOSED["failed"])
    )
    return runtime.SENT_END.split(str(said).strip())[0]


def decided_line(rows: list, label_of=None) -> str | None:
    """최근 처리한 카드 한 줄('제목(상태) · …'). 실행 못 한 카드는 '제목(상태 · 까닭: 화면이 알린 말)'. 없으면 None.
    '서버가 알린 까닭'이라고 쓰면 비서가 '서버가'를 그대로 말해(QA r3 c6 T16 · T17 · T20) '까닭'만 쓴다.
    label_of(카드) → 업체 쪽 요청 이름(없으면 None): 어느 요청의 카드인지 붙인다(QA r3 c6 T3)."""
    got = []
    for a in rows:
        if a.status not in DECIDED:
            continue
        if a.status == "expired" and (a.result or {}).get("reason") not in CLOSED_REASONS:
            continue
        title = card_name(a, label_of(a) if label_of else None)
        why = _why_not(a)
        got.append(
            f"{title}({DECIDED[a.status]} · 까닭: {why})"
            if why
            else f"{title}({DECIDED[a.status]})"
        )
    return "최근 처리한 카드: " + " · ".join(got) if got else None


def time_lines(now: datetime) -> list[str]:
    """턴 사실의 시각 줄(고객 · 업체 같음): 지금 서울 시각 · 올해(다른 해 날짜를 가르게) · 밤 알림 규칙. 알림 때는
    먼저 말 걸기 규칙 값(proactive.RULES)에서 읽는다(글에 손으로 적지 않는다). 때 말은 표 하나(kdate.PERIODS)."""
    from app.assistant import proactive

    r = proactive.RULES
    night = f"{kdate.hour_text(r.night_from)}~{kdate.hour_text(r.night_to)}"
    return [
        f"지금: {kdate.now_text(now)}",
        f"올해: {now.astimezone(SEOUL).year}년",
        f"알림: {night}엔 {kdate.period(r.night_to)}에 보내요",
    ]


# 실측 요청 뒤(집 정보 잠김)에는 공사 시작 희망을 집 정보 카드로 바꿀 수 없다: '아직 몰라요' 대신 업체와 정한다는 사실
# (QA r2 c5: 잠긴 뒤에도 시작 희망일을 거듭 물음). 집 카드 · 보드의 사실 글(cards.home)은 그대로 둔다
START_WISH = "공사 시작 희망"
START_LOCKED = "공사 시작 희망 안 정함(실측 요청 뒤라 업체와 정해요)"


# 집 카드 사실의 평('32평', 표준견적서에 저장한 공급 기준 평). 전용 ㎡로 넣은 집은 환산 비율로 어림한 평이라 턴 사실에
# 넣지 않는다(QA r3 c4b: 전용 59㎡ 집을 '21평'이라고 말함). 공급 기준이면 평형이라고 밝힌다
PYEONG_FACT = re.compile(r"^(\d+(?:\.\d+)?)평$")


def home_facts(home: dict) -> list[str]:
    """턴 사실 '집:' 줄의 사실(집 카드와 같은 글). 잠긴 뒤 비어 있는 시작 희망을 바꾸고, 평은 공급 기준 평형으로만
    둔다(전용 면적 집은 ㎡만)."""
    facts = list(home["facts"])
    if home["locked"] and home.get("start_date") is None:
        facts = [START_LOCKED if f.startswith(START_WISH) else f for f in facts]
    out = []
    for f in facts:
        if m := PYEONG_FACT.match(f):
            if home.get("area_basis") == "exclusive":
                continue
            f = f"{m[1]}평형(공급)"
        out.append(f)
    return out


def period_line(period, today) -> str | None:
    """턴 사실 '공정표:' 줄(공정표 기간). 확정 공정표인지 예상 공정표인지 이름으로 밝힌다(QA r2 c5: 예상 공정표가
    있는데 정해지지 않았다고 답함, QA r3 c2: 확정 뒤에 '지금 예상 공정표 기준'이라고 답함)."""
    if period is None:
        return None
    days = kdate.long_range(period.start, period.end, today)
    if period.kind == "final":
        return (
            f"공정표: 확정 공정표 · 공사 {days} · 일하는 날 {period.work_days}일(수락한 공사 날짜)"
        )
    return (
        f"공정표: 예상 공정표 · 예상 공사 {days} · 일하는 날 {period.work_days}일"
        "(업체가 공사 날짜를 올리기 전 예상)"
    )


# ---- 턴 사실: 업체마다 지금 상태 · 채팅 · 실제 단계(QA r3 c4: 단계가 '실측 요청 뒤' 한 줄뿐이라 먼저 '견적서가
# 왔어요'라고 알린 1분 뒤에 '견적서가 오면'이라고 답하고, 확정 때 닫힌 실측을 '잡혀 있었어요'라고 답함) ----

HALF_KO = {"am": "오전", "pm": "오후"}
# 실측 요청 상태 → 고객 화면 말(날짜 · 견적서가 붙는 상태는 visit_words가 만든다)
VISIT_WORDS = {
    "requested": "실측 요청함(업체 답 기다림)",
    "offered": "실측 기간 답 옴(반나절 고를 차례)",
    "picked": "실측 시간 고름(업체 수락 기다림)",
    "proposed": "업체가 다른 실측 시간을 냄(고를 차례)",
    "booked": "실측 날짜 정해짐",
    "visited": "실측 받음(견적서 기다림)",
    "quoted": "견적서 옴",
}
ENDED_WHY = {"declined": "업체가 못 받음", "no_show": "업체가 실측에 안 옴"}
EXPIRED_WHY = {"reply": "업체 답 기한 지남", "pick": "반나절 고르기 기한 지남"}
# 확정한 업체의 공사 날짜 상태(schedule.service.dates_states) → 화면 말. scheduled는 업체 공사 날로 쓴다
DATES_WORDS = {
    "waiting": "업체가 공사 날짜를 정하는 중",
    "proposed": "업체가 올린 공사 날짜를 수락할 차례",
    "requested": "다른 공사 날짜를 요청함(업체 답 기다림)",
    "change_requested": "공사 날짜 바꾸기를 요청함(업체 답 기다림)",
    "change_proposed": "업체가 바뀐 공사 날짜를 올림(수락할 차례)",
}
BEFORE_CHAT = ("requested", "offered", "picked", "proposed")  # 채팅이 열리기 전(업체 수락 전)
CHAT_WAIT = "업체가 실측 시간을 수락하면 열려요"
LIVE_VISITS = ("requested", "offered", "picked", "proposed", "booked", "visited", "quoted")
NO_DOBAE = "표준견적서 · 상담(업체 연결은 도배만이라 이 공사는 업체 단계가 없어요)"
UNKNOWN_STAGE = "지금 단계를 읽지 못했어요(도구로 확인해요)"


def visit_words(r, chosen: bool, today) -> str:
    """실측 일정 상태판 줄(visit.service.board_now) → 고객 화면 말. chosen: 이 공정에서 확정한 업체가 있다."""
    st, b = r.status, r.booked
    slot = f"{kdate.md_long(b.day, today)} {HALF_KO[b.half]}" if b is not None else None
    if st == "picked" and slot:
        return f"실측 시간 고름({slot} · 업체 수락 기다림)"
    if st == "booked" and r.next.kind == "change":
        return (
            "실측 날짜 바꾸기를 요청함(업체 답 기다림)"
            if r.next.who == "vendor"
            else "업체가 다른 실측 날을 냄(고를 차례)"
        )
    if st == "booked" and slot:
        return f"실측 날짜 정해짐({slot})"
    if st == "quoted" and r.quote is not None:
        return f"견적서 옴({r.quote.version}판 · 부가세 포함 {r.quote.total:,}원)"
    if st == "closed":
        return "닫힘(다른 업체 확정 때)" if chosen else "닫힘"
    if st == "cancelled":
        return "닫힘(견적서가 늦어 취소)" if r.cancel_code == "late_quote" else "닫힘(고객 취소)"
    if st == "expired":
        return f"닫힘({EXPIRED_WHY.get(r.expired_reason or '', '기한 지남')})"
    if st in ENDED_WHY:
        return f"닫힘({ENDED_WHY[st]})"
    return VISIT_WORDS.get(st, "진행 중")


def deal_words(d, dates: str | None, today) -> str:
    """확정한 업체(schedule.service.deals_for 한 건) → '확정 · 공사 금액 … · 공사 날짜 상태'."""
    parts = ["확정"]
    if d.grand_total is not None:
        parts.append(f"공사 금액 부가세 포함 {d.grand_total:,}원")
    if d.status == "checking":
        parts.append("업체가 공사를 끝냈다고 함(끝 확인할 차례)")
    elif d.status == "fixing":
        parts.append("남은 일 하는 중")
    elif d.status == "done":
        parts.append("공사 끝")
    elif dates in DATES_WORDS:
        parts.append(DATES_WORDS[dates])
    elif d.start_date is not None and d.end_date is not None:
        parts.append(f"업체 공사 날 {kdate.long_range(d.start_date, d.end_date, today)}")
    return " · ".join(parts)


def vendors_line(rows: list, deal, dates: str | None, today) -> str | None:
    """턴 사실 '업체:' 줄: 이 공사에 걸린 업체마다 지금 상태(요청한 순). 없으면 None."""
    items = []
    for r in rows:
        if deal is not None and r.visit_id == deal.visit_id:
            items.append(f"{r.vendor_name} {deal_words(deal, dates, today)}")
        else:
            items.append(f"{r.vendor_name} {visit_words(r, deal is not None, today)}")
    if deal is not None and all(r.visit_id != deal.visit_id for r in rows):
        items.append(f"{deal.vendor_name} {deal_words(deal, dates, today)}")
    return "업체: " + " / ".join(items) if items else None


def chat_line(rows: list, deal, opened: set) -> str:
    """턴 사실 '채팅:' 줄: 믿집 채팅이 열린 업체 · 아직 안 열린 업체(업체가 실측 시간을 수락하면 열려요)."""
    names = [(r.vendor_id, r.vendor_name, r.status) for r in rows]
    if deal is not None and all(v != deal.vendor_id for v, _, _ in names):
        names.append((deal.vendor_id, deal.vendor_name, "chosen"))
    on = [n for v, n, _ in names if v in opened]
    wait = [n for v, n, st in names if v not in opened and st in BEFORE_CHAT]
    parts = [f"{' · '.join(on)} 열림"] if on else []
    if wait:
        parts.append(f"{' · '.join(wait)} 아직 안 열림({CHAT_WAIT})")
    return "채팅: " + (" / ".join(parts) if parts else f"열린 채팅 없음({CHAT_WAIT})")


def stage_of(rows: list, deal, dates: str | None, today) -> tuple[str, str | None]:
    """(턴 사실 단계 말, 다음에 물을 말 단계 키). 단계는 업체 고르기 · 실측 · 견적 견주기 · 확정 · 공사 · 끝이고,
    업체 상태에서 나온다(요청을 모두 취소 · 거절당하면 다시 업체 고르기)."""
    if deal is not None:
        st, start = deal.status, deal.start_date
        if st == "done":
            return "끝(공사를 마쳤어요)", None
        if st == "checking":
            return "공사(업체가 끝냈다고 함 · 끝 확인할 차례)", "check"
        if st == "fixing":
            return "공사(남은 일 하는 중)", None
        if st == "scheduled" and start is not None and today >= start:
            return "공사(공사 날짜가 됐어요)", None
        if st == "scheduled":
            if dates != "scheduled":  # 날짜 바꾸기가 열려 있다
                return "확정(공사 날짜 바꾸는 중)", None
            key = "eve" if start == today + timedelta(days=1) else "prep"
            return "확정(공사 날짜 수락함 · 공사 전)", key
        return "확정(공사 날짜 정하기)", "dates"
    quoted = [r for r in rows if r.status == "quoted"]
    live = [r for r in rows if r.status in LIVE_VISITS and r.status != "quoted"]
    if quoted:
        wait = f" · 견적서 기다리는 업체 {len(live)}곳" if live else ""
        return f"견적 견주기(받은 견적서 {len(quoted)}곳{wait})", "deal"
    if live:
        return f"실측(요청한 업체 {len(live)}곳 · 견적서 전)", "visit"
    if rows:
        return "업체 고르기(보낸 실측 요청이 모두 닫힘)", "pick"
    return "업체 고르기(실측 요청 전)", "pick"


@dataclass(frozen=True)
class WorkNow:
    """턴 사실 · 다음에 물을 말이 같이 쓰는 지금 공사 상태(도배, 업체 연결은 도배만)."""

    stage: str
    key: str | None  # 다음에 물을 말 단계 키(STEP_IDEAS)
    vendors: str | None = None
    chat: str | None = None


async def work_now(s, user: User, p, today, now: datetime) -> WorkNow:
    """업체마다 지금 상태(visit.service.board_now) · 확정(schedule.service.deals_for · dates_states) · 열린 채팅
    (cards.chat_links). 모두 읽기만 한다(턴 시작 트랜잭션 중간에 부른다)."""
    from app.assistant.tools import cards
    from app.schedule import service as schedule_service
    from app.visit import service as visit_service

    if getattr(p.trades, "dobae", None) is None:
        return WorkNow(NO_DOBAE, None)
    rows = await visit_service.board_now(s, p.id, "dobae", now)
    deals = await schedule_service.deals_for(s, user, p.id, "dobae", today)
    deal = deals[-1] if deals else None
    dates = (await schedule_service.dates_states(s, [deal.id])).get(deal.id) if deal else None
    ids = [r.vendor_id for r in rows] + ([deal.vendor_id] if deal else [])
    opened = set(await cards.chat_links(s, p.id, ids))
    stage, key = stage_of(rows, deal, dates, today)
    return WorkNow(
        stage,
        key,
        vendors_line(rows, deal, dates, today),
        chat_line(rows, deal, opened) if rows or deal else f"채팅: 열린 채팅 없음({CHAT_WAIT})",
    )


async def _customer_facts(s, user: User, p, now: datetime, opened: list, decided: list) -> str:
    from app.assistant import memory
    from app.assistant.tools import cards
    from app.schedule import service as schedule_service

    today = now.astimezone(SEOUL).date()
    _, home = await cards.home(s, user, p.id)
    try:  # 업체 상태를 못 읽어도 턴은 돈다(세이브포인트: 턴 행을 넣은 트랜잭션을 지킨다)
        async with s.begin_nested():
            w = await work_now(s, user, p, today, now)
    except Exception as e:  # noqa: BLE001 - 종류 이름만 남기고 옛 단계 말로
        log.warning("턴 사실 업체 상태 읽기 실패 (%s)", type(e).__name__)
        w = WorkNow(UNKNOWN_STAGE, None)
    lines = [
        *time_lines(now),
        "화면: 고객 비서",
        "단계: " + w.stage + (" · 집 정보 잠김(실측 요청 뒤)" if home["locked"] else ""),
        "집: " + " · ".join(home_facts(home)),
        *(x for x in (w.vendors, w.chat) if x),
    ]
    period = period_line(await schedule_service.period_now(s, p), today)
    if period:
        lines.append(period)
    if opened:
        lines.append("승인 기다리는 카드: " + " / ".join(card_name(a) for a in opened))
    if done := decided_line(decided):
        lines.append(done)
    from app.assistant.tools import diy as diy_tools

    # 화면에서 뺀 직접 할 일 기억 조각을 맞춰요(commit은 start_turn이 해요)
    await diy_tools.settle_memory(s, user, now)
    remembered = memory.facts_line(await repo.memories(s, user.id))
    if remembered:
        lines.append(remembered)
    from app.assistant import research  # 조사 담당(09): 진행 중 · 방금 끝난 조사 한 줄

    if looked := await research.facts_line(s, user.id, p.id, now):
        lines.append(looked)
    return "\n".join(lines)


# ---- 업체 턴 사실: 요청 · 공사마다 지금 상태와 카드가 어느 요청 것인지(QA r3 c6 T3: '세 건'이라 하고 한 건만 말함 ·
# 다른 요청의 못 받아요를 이 요청에 붙임, T12 · T13: 닫힌 카드를 '아직 남아 있을 수 있어요') ----

VENDOR_ROWS_MAX = 8  # 한 줄에 넣는 요청 · 공사 수
TRADE_KO = {"dobae": "도배", "mokgong": "목공"}


def request_name(r) -> str:
    """업체 작업함 줄(구 · 평 · 공정) → '노원구 32평 도배'. 고객 이름 · 동 · 호는 없다."""
    py = f"{Decimal(r.pyeong).normalize():f}평" if r.pyeong else None
    return " ".join(x for x in (r.area_name, py, TRADE_KO.get(r.trade, r.trade)) if x)


def row_words(r, slot: str | None = None) -> str:
    """작업함 줄 상태(화면 글자 그대로) + 고객이 고른 · 잡힌 반나절(있으면 다음 일 글 대신) · 기한."""
    from app.assistant.tools.cards import seoul_text

    state = r.state.label if r.state else r.status
    nxt = r.next.label if r.next and r.next.label not in (state, "") and not slot else None
    due = seoul_text(r.next.due_at) if r.next and r.next.due_at else None
    extra = " · ".join(x for x in (slot, nxt, due and f"{due}까지") if x)
    return f"{state}({extra})" if extra else state


@dataclass
class VendorBook:
    """업체 턴 사실 재료: 요청 · 공사 줄과 대상(요청 id · 확정 id) → 요청 이름."""

    lines: list[str]
    names: dict[uuid.UUID, str]

    def label_of(self, a) -> str | None:
        tid = getattr(a, "target_id", None)
        return self.names.get(tid) if tid else None


async def vendor_book(s, vendor: User, today, targets: list) -> VendorBook:
    """업체 작업함(schedule.service.vendor_inbox: 할 일 · 기다림 · 일정 · 공사)과 고객이 고른 반나절(일정)로
    '요청:' · '공사:' 줄을 만든다. targets(카드)의 대상 중 작업함에 없는 요청(끝난 요청)은 visit.service.rows_for로
    이름만 읽는다. 모두 읽기만 한다."""
    from app.assistant.tools import vendor as vendor_tools
    from app.schedule import service as schedule_service
    from app.visit import service as visit_service

    rows = []
    for tab in ("todo", "waiting", "sched"):
        rows += (await schedule_service.vendor_inbox(s, vendor, tab, today, None, 50)).items
    jobs = (await schedule_service.vendor_inbox(s, vendor, "jobs", today, None, 50)).items
    picked, booked = await vendor_tools.visit_slots_of(s, vendor, today, vendor_tools.PICK_DAYS)
    slots = {x.visit_id: f"{kdate.md_long(x.day, today)} {HALF_KO[x.half]}" for x in picked}
    slots |= {x.visit_id: f"{kdate.md_long(x.day, today)} {HALF_KO[x.half]}" for x in booked}
    names: dict[uuid.UUID, str] = {r.id: request_name(r) for r in [*rows, *jobs]}
    names |= {r.deal_id: request_name(r) for r in jobs if r.deal_id}
    lost = [
        a.target_id
        for a in targets
        if getattr(a, "target_kind", None) == "visit" and a.target_id not in names
    ]
    if lost:
        for vid, r in (await visit_service.rows_for(s, lost, today)).items():
            names[vid] = request_name(r)
    lines = []
    if rows:
        got = [f"{names[r.id]} {row_words(r, slots.get(r.id))}" for r in rows[:VENDOR_ROWS_MAX]]
        lines.append(f"요청: {len(rows)}건 · " + " / ".join(got))
    else:
        lines.append("요청: 답하거나 챙길 실측 요청 없음")
    if jobs:
        got = [f"{names[r.id]} {row_words(r)}" for r in jobs[:VENDOR_ROWS_MAX]]
        lines.append(f"공사: {len(jobs)}건 · " + " / ".join(got))
    return VendorBook(lines, names)


async def _vendor_facts(
    s,
    vendor: User,
    now: datetime,
    visit_id: uuid.UUID | None,
    visit_ref: str | None,
    opened: list,
    decided: list,
) -> str:
    today = now.astimezone(SEOUL).date()
    try:  # 작업함을 못 읽어도 턴은 돈다(세이브포인트: 턴 행을 넣은 트랜잭션을 지킨다)
        async with s.begin_nested():
            book = await vendor_book(s, vendor, today, [*opened, *decided])
    except Exception as e:  # noqa: BLE001 - 종류 이름만 남기고 요청 줄 없이
        log.warning("업체 턴 사실 작업함 읽기 실패 (%s)", type(e).__name__)
        book = VendorBook([], {})
    lines = [*time_lines(now), "화면: 업체 비서"]
    if visit_ref:
        name = book.names.get(visit_id) if visit_id else None
        lines.append(f"지금 보는 요청: {visit_ref}" + (f"({name})" if name else ""))
    lines += book.lines
    if opened:
        lines.append(
            "승인 기다리는 카드: " + " / ".join(card_name(a, book.label_of(a)) for a in opened)
        )
    if done := decided_line(decided, book.label_of):
        lines.append(done)
    return "\n".join(lines)


def card_of(card_id: str | None) -> str | None:
    """화면이 보낸 카드 id → 대상 카드 id. 할 일이 끝난 먼저 말 건 줄 카드는 '@줄 id'가 붙어 오니 뗀다(QA P4)."""
    if not card_id:
        return None
    return card_id.split("@", 1)[0] or None


def _choices(ctx: TurnContextIn | None) -> list[str]:
    if ctx is None or ctx.choice is None:
        return []
    return [ctx.choice] if isinstance(ctx.choice, str) else list(ctx.choice)[:5]


async def ensure_chat(s, user_id: uuid.UUID, project_id: uuid.UUID | None) -> Chat:
    """그 사람 · 그 공사의 비서 대화(없으면 만든다, commit은 부르는 쪽). 고객 공사는 공사 행을, 업체(공사 없음)는
    사람 단위 트랜잭션 잠금을 먼저 잡고 다시 읽어 같은 대화를 둘 만들지 않는다(작업함이 오늘 · 요청 브리핑을 한꺼번에
    열어도 하나, 리뷰 R8). 턴 · 먼저 말 걸기 · 업체 브리핑(REST)이 같은 대화의 이름표 표를 쓰게 한다."""
    from app.project import service as project_service

    chat = await repo.assistant_chat(s, user_id, project_id)
    if chat is not None:
        return chat
    if project_id is not None:
        await project_service.lock(s, project_id)
    else:
        key = f"assistant-chat:{user_id}"
        await s.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
    chat = await repo.assistant_chat(s, user_id, project_id)
    if chat is not None:
        return chat
    return await chat_repo.insert_chat(s, user_id, project_id=project_id, kind="assistant")


async def start_turn(
    user: User,
    *,
    surface: str,
    client_key: str,
    text: str,
    project_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
    context: TurnContextIn | None = None,
) -> TurnCtx | AssistantTurn:
    """돌 턴의 문맥, 또는 같은 client_key로 이미 끝난 턴(되돌림). 오류는 스트림을 열기 전에 난다."""
    from app.project import service as project_service
    from app.shared import ratelimit
    from app.visit import service as visit_service

    now, today = now_utc(), today_seoul()
    masked = policy.mask_in(text)
    # 공백 · 제어 문자만: LLM에 빈 글 블록을 보내지 않는다(리뷰 R1 · QA P1, 차단기를 걸지 않게)
    if not masked:
        raise AppError(422, "invalid", "보낼 말을 적어 주세요.")
    async with SessionLocal() as s:
        old = await repo.turn_by_key(s, user.id, client_key)
        if old is not None:
            if old.surface != surface:
                raise AppError(404, "not_found", "대화를 찾을 수 없어요.")
            if old.status == "running":
                raise AppError(409, "turn_running", RUNNING)
            return old
        project = None
        if surface == "customer":
            project = await project_service.get_for(s, user, project_id)  # 남의 · 없는 공사 404
            await project_service.lock(s, project_id)  # 같은 공사의 대화 만들기가 줄 선다
        elif visit_id is not None:
            await visit_service.vendor_visit(s, user, visit_id, today)  # 남의 요청 404
        if settings.app_env != "local":
            await ratelimit.hit(
                ratelimit.key("assistant-turn", str(user.id)), TURNS_PER_HOUR, 3600, TOO_MANY
            )
        chat = await ensure_chat(s, user.id, project_id)
        await repo.fail_stalled(s, now, now - STALL, chat_id=chat.id)
        turn = AssistantTurn(
            user_id=user.id,
            chat_id=chat.id,
            surface=surface,
            project_id=project_id,
            visit_id=visit_id,
            client_key=client_key,
            status="running",
            mode="llm",
            heartbeat_at=now,
            created_at=now,
        )
        s.add(turn)
        try:
            await s.flush()
        except IntegrityError as e:
            await s.rollback()
            if "uq_assistant_turns_running" in str(e.orig):
                raise AppError(409, "turn_running", RUNNING) from None
            old = await repo.turn_by_key(s, user.id, client_key)  # 같은 키가 거의 같이 왔다
            if old is None or old.status == "running":
                raise AppError(409, "turn_running", RUNNING) from None
            return old
        rows = await repo.messages(s, chat.id, HISTORY)
        opened = [  # 기한이 지난 카드는 정리(sweep) 전이어도 누를 수 없어 열린 카드로 넣지 않는다
            a
            for a in await repo.actions_of(
                s, user.id, surface, project_id=project_id, status="proposed", limit=5
            )
            if a.expires_at > now
        ]
        decided = await repo.decided_of(
            s, user.id, surface, project_id=project_id, limit=DECIDED_MAX, closed=CLOSED_REASONS
        )
        refs = await RefTable.load(chat.id)
        visit_ref = (
            refs.put("visit", {"id": str(visit_id)}) if surface == "vendor" and visit_id else None
        )
        facts = (
            await _customer_facts(s, user, project, now, opened, decided)
            if project is not None
            else await _vendor_facts(s, user, now, visit_id, visit_ref, opened, decided)
        )
        if _has_older(rows, HISTORY):
            facts += "\n" + OLDER.format(n=sum(1 for m in rows if m.role == "user"))
        rev = chat.rev
        await s.commit()
    # 이번 대화에서 도구 · 카드가 준 이름표와 카드의 집 정보 칸 고르기(칸:값)만 넘긴다. 이 화면의 행동 꼴인데
    # 이름표를 모르거나 보던 카드의 대상과 다르면(지난 카드 단추) 버리지 않고 카드를 새로 불러온다. 그 밖은 버린다
    card_id = card_of(context.card_id) if context else None
    picked = _choices(context)
    choice = [r for r in picked if choices.valid(r, refs) and choices.fits_card(r, refs, card_id)]
    stale = [r for r in picked if r not in choice and choices.stale(r, surface)]
    return TurnCtx(
        turn_id=turn.id,
        chat_id=chat.id,
        user=user,
        surface=surface,
        project_id=project_id,
        visit_id=visit_id,
        today=today,
        now=now,
        text=masked,
        choice=choice,
        history=_history(rows),
        facts=facts,
        rev=rev,
        refs=refs,
        client_key=client_key,
        card_id=card_id,
        stale=stale,
        pressed=bool(picked),
    )


# ---- 턴 끝 ----


async def finish_turn(ctx: TurnCtx, res: TurnResult) -> int:
    """대화 저장과 턴 끝을 한 트랜잭션으로. 새 rev를 돌려준다.
    고객 말에 기억할 낱말이 있으면 기억 뽑기 일(jobs kind=assistant_memory, ref = 고객 메시지)도 같이 넣는다.
    카드 단추가 보낸 글('11.28(토) 오전로 할래요')은 화면이 만든 말이라 기억을 뽑지 않는다."""
    from app.assistant import memory
    from app.jobs import service as jobs_service

    now = now_utc()
    ms = int((now - ctx.now).total_seconds() * 1000)
    async with SessionLocal() as s:
        if not await chat_repo.bump_rev(s, ctx.user.id, ctx.chat_id, ctx.rev, None):
            await s.rollback()
            raise AppError(409, "conflict", "다른 질문이 먼저 저장됐어요. 다시 물어봐 주세요.")
        chat_repo.add_turn(s, ctx.chat_id, ctx.rev, ctx.text, res.text, None)
        if ctx.surface == "customer" and not ctx.pressed and memory.wants(ctx.text):
            await s.flush()
            said = await s.scalar(
                select(ChatMessage.id).where(
                    ChatMessage.chat_id == ctx.chat_id,
                    ChatMessage.turn == ctx.rev,
                    ChatMessage.role == "user",
                )
            )
            await jobs_service.add(
                s,
                kind="assistant_memory",
                ref_id=said,
                run_at=now,
                dedup_key=f"assistant_memory:{said}",
            )
        ended = await repo.end_turn(
            s,
            ctx.turn_id,
            now,
            status=res.status,
            mode=res.mode,
            tool_calls=min(res.tool_calls, policy.TOOL_MAX),
            cost_micros=res.cost_micros,
            trace=res.trace(ctx.rev, ms),
            cards=res.cards,
        )
        if not ended:  # sweep이 멈춤(stalled)으로 닫았다
            await s.rollback()
            raise AppError(409, "turn_stalled", "답이 너무 오래 걸려 멈췄어요. 다시 물어봐 주세요.")
        await s.commit()
    await ctx.refs.save()
    return ctx.rev + 1


async def fail_turn(ctx: TurnCtx, code: str, res: TurnResult | None = None) -> None:
    try:
        async with SessionLocal() as s:
            await repo.end_turn(
                s,
                ctx.turn_id,
                now_utc(),
                status="failed",
                error_code=code[:40],
                mode=res.mode if res else "llm",
                tool_calls=min(res.tool_calls, policy.TOOL_MAX) if res else 0,
                cost_micros=res.cost_micros if res else 0,
                cards=res.cards if res else [],
                trace=res.trace(ctx.rev, 0) if res else {"rev": None},
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001 - 실패 기록 실패는 sweep이 stalled로 닫는다
        log.warning("비서 턴 실패 기록 실패 (%s)", type(e).__name__)


def _sse(turn_id: uuid.UUID, name: str, seq: int, data: dict) -> str:
    body = json.dumps({**data, "seq": seq}, ensure_ascii=False, default=str)
    return f"id: {turn_id}:{seq}\nevent: {name}\ndata: {body}\n\n"


async def stream(ctx: TurnCtx) -> AsyncIterator[str]:
    """한 턴의 SSE. 일은 따로 돈다(화면이 끊어도 저장까지 간다).
    턴 자리(request_guards.TURNS)는 router 의존성이 응답 끝까지 쥔다. 화면이 끊어 응답이 먼저 끝나면 남은 일이 자리를
    넘겨받아 같이 세고, 대화를 저장하면(또는 실패로 끝나면) 바로 놓는다(자리를 쥔 채 뒷일을 하지 않게)."""
    from app.shared import request_guards as guards

    q: asyncio.Queue[str | None] = asyncio.Queue()
    seq = 0
    held = False  # 화면이 끊은 뒤 남은 일이 턴 자리를 쥐었다

    async def emit(name: str, data: dict) -> None:
        nonlocal seq
        seq += 1
        q.put_nowait(_sse(ctx.turn_id, name, seq, data))

    def let_go() -> None:
        nonlocal held
        if held:
            held = False
            guards.TURNS.give()

    async def work() -> None:
        res: TurnResult | None = None
        try:
            await emit(
                "ack",
                {
                    "turn_id": str(ctx.turn_id),
                    "chat_id": str(ctx.chat_id),
                    "at": ctx.now.isoformat(),
                },
            )
            res = await runtime.run_turn(ctx, emit)
            res.chips = runtime.chips_for(
                res.cards, await chip_facts(ctx.user, ctx.surface, ctx.project_id, res.cards)
            )
            rev = await finish_turn(ctx, res)
            let_go()  # 저장했다: 끊긴 턴이 쥔 자리는 바로 놓는다
            ideas = await suggest_for(
                ctx.user, ctx.surface, ctx.project_id, said=ctx.text, chips=res.chips
            )
            await emit(
                "done",
                {
                    "rev": rev,
                    "mode": res.mode,
                    "cards": [c["card_id"] for c in res.cards],
                    "actions": res.actions,
                    "stopped": res.status == "stopped",
                    "chips": res.chips,
                    "suggest": [x.model_dump(mode="json") for x in ideas],
                },
            )
        except AppError as e:
            await fail_turn(ctx, e.code, res)
            await emit("error", {"code": e.code, "message": e.message})
        except Exception as e:  # noqa: BLE001 - 스트림이 열린 뒤라 error 이벤트로 알린다(종류 이름만 로그)
            log.warning("비서 턴 실패 (%s)", type(e).__name__)
            await fail_turn(ctx, "failed", res)
            await emit("error", {"code": "failed", "message": FAILED})
        finally:
            let_go()
            q.put_nowait(None)

    task = asyncio.create_task(work())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    try:
        while (item := await q.get()) is not None:
            yield item
    finally:
        if not task.done():
            # 화면이 끊었다: router가 응답과 함께 자리를 돌려줘도 남은 일(저장까지)은 자리에 센다. 이미 들어온 턴이라
            # 자리 수를 넘겨도 세고(새 턴이 503을 받는다), 저장하면 let_go가 놓는다
            guards.TURNS.used += 1
            held = True


async def replay(user: User, turn: AssistantTurn) -> AsyncIterator[str]:
    """같은 client_key의 끝난 턴을 다시 보낸다(카드 · 행동 지금 상태 · 저장한 답 · done 또는 error)."""
    async with SessionLocal() as s:
        text = await _answer_text(s, turn)
        ids = [uuid.UUID(x) for x in (turn.trace or {}).get("actions", [])]
        acts = await repo.actions_by_id(s, user.id, ids)
        chat = await s.get(Chat, turn.chat_id)
    seq = 0

    def ev(name: str, data: dict) -> str:
        nonlocal seq
        seq += 1
        return _sse(turn.id, name, seq, data)

    yield ev(
        "ack",
        {"turn_id": str(turn.id), "chat_id": str(turn.chat_id), "at": turn.created_at.isoformat()},
    )
    for c in turn.cards or []:
        yield ev("card", c)
    for i in ids:
        if i in acts:
            yield ev("action", actions.out(acts[i]).model_dump(mode="json"))
    if turn.status == "failed":
        yield ev("error", {"code": turn.error_code or "failed", "message": FAILED})
        return
    if text and turn.mode == "llm" and not text.startswith(CARDS_ONLY):
        yield ev("token", {"text": text})
    elif text and (kept := (turn.trace or {}).get("kept")):  # 무료 모드 앞에 보낸 LLM 글(R14)
        yield ev("token", {"text": text[:kept]})
    r = (turn.trace or {}).get("rev")
    rev = r + 1 if isinstance(r, int) else (chat.rev if chat else 1)
    facts = await chip_facts(user, turn.surface, turn.project_id, turn.cards or [])
    yield ev(
        "done",
        {
            "rev": rev,
            "mode": turn.mode,
            "cards": [c["card_id"] for c in turn.cards or []],
            "actions": [str(i) for i in ids],
            "stopped": turn.status == "stopped",
            "chips": runtime.chips_for(turn.cards or [], facts),
            "suggest": [],
        },
    )


async def _answer_text(s, turn: AssistantTurn) -> str | None:
    rev = (turn.trace or {}).get("rev")
    if rev is None:
        return None
    return await s.scalar(
        select(ChatMessage.text).where(
            ChatMessage.chat_id == turn.chat_id,
            ChatMessage.turn == rev,
            ChatMessage.role == "assistant",
        )
    )


async def turn_out(user: User, turn_id: uuid.UUID, surface: str) -> TurnOut:
    async with SessionLocal() as s:
        t = await repo.turn_owned(s, user.id, turn_id)
        if t is None or t.surface != surface:
            raise AppError(404, "not_found", "대화를 찾을 수 없어요.")
        ids = [uuid.UUID(x) for x in (t.trace or {}).get("actions", [])]
        acts = await repo.actions_by_id(s, user.id, ids)
        text = await _answer_text(s, t)
    return TurnOut(
        turn_id=t.id,
        chat_id=t.chat_id,
        surface=t.surface,  # type: ignore[arg-type]
        status=t.status,  # type: ignore[arg-type]
        mode=t.mode,  # type: ignore[arg-type]
        tool_calls=t.tool_calls,
        text=text,
        cards=[CardOut.model_validate(c) for c in t.cards or []],
        actions=[actions.out(acts[i]) for i in ids if i in acts],
        error_code=t.error_code,
        created_at=t.created_at,
        ended_at=t.ended_at,
    )


async def latest_thread(user: User, project_id: uuid.UUID) -> AssistantThreadOut | None:
    from app.project import service as project_service

    async with SessionLocal() as s:
        await project_service.get_for(s, user, project_id)
        chat = await repo.assistant_chat(s, user.id, project_id)
    return (
        AssistantThreadOut(chat_id=chat.id, rev=chat.rev, updated_at=chat.updated_at)
        if chat
        else None
    )


# ---- 행동 ----


async def approve(user: User, action_id: uuid.UUID, body: ApproveIn, surface: str) -> ActionOut:
    return await actions.execute(user, action_id, surface, body.seen, now_utc())


async def reject(user: User, action_id: uuid.UUID, surface: str) -> ActionOut:
    return await actions.reject(user, action_id, surface, now_utc())


async def actions_for(
    user: User, surface: str, project_id: uuid.UUID | None, status: str | None
) -> list[ActionOut]:
    from app.project import service as project_service

    async with SessionLocal() as s:
        if project_id is not None:
            await project_service.get_for(s, user, project_id)
        rows = await repo.actions_of(s, user.id, surface, project_id=project_id, status=status)
    return [actions.out(a) for a in rows]


# ---- 대화 기록 ----


async def feed_for(
    user: User,
    surface: str,
    project_id: uuid.UUID | None,
    before: int | None = None,
    limit: int = FEED_LIMIT,
) -> FeedPage:
    """대화 기록 한 쪽(오래된 것부터). 카드는 턴에 남긴 것, 승인 카드는 지금 상태(새 판이면 새 행동)로 그린다.
    먼저 말 건 줄은 보낸 때 자리에 끼운다(대화가 없어도): 그 쪽 말 사이에 보낸 줄만(첫 쪽은 맨 뒤까지, 앞 쪽은
    다음 쪽 첫 말 앞까지, 더 앞 쪽이 없으면 처음부터). 창 안 줄은 NUDGE_FEED까지 모두 넣는다. 고객은 할 일이 끝나
    닫힌 줄(acted · handled)도 '완료'로 남긴다(settled)."""
    from app.assistant import proactive, research
    from app.assistant.tools import cards
    from app.project import service as project_service

    now = now_utc()
    rows: list[ChatMessage] = []
    turns: dict = {}
    acts: dict = {}
    failed: list = []
    nudges: list = []
    looked: list = []  # 끝난 조사 줄(조사 담당 09, 먼저 말 걸기 규칙 밖)
    task = None
    async with SessionLocal() as s:
        if surface == "customer":
            await project_service.get_for(s, user, project_id)
        chat = await repo.assistant_chat(s, user.id, project_id)
        since = until = None
        if chat is not None:
            rows = await repo.messages(s, chat.id, limit, before)
            turns = {
                t.trace.get("rev"): t
                for t in await repo.turns_of(s, chat.id, [m.turn for m in rows])
            }
            ids = {uuid.UUID(x) for t in turns.values() for x in (t.trace or {}).get("actions", [])}
            acts = await repo.actions_by_id(s, user.id, list(ids))
            failed = (
                await repo.failed_turns(s, chat.id, rows[-1].created_at if rows else None, 3)
                if before is None
                else []
            )
            # 쪽 경계는 턴 첫 말 시각: 앞 쪽(before)의 끝과 그다음 쪽의 처음이 같은 값이라 줄이 빠지거나 겹치지 않는다
            if _has_older(rows, limit):
                since = await repo.turn_started(s, chat.id, rows[0].turn)
            if before is not None:
                until = await repo.turn_started(s, chat.id, before)
        if before is None or until is not None:
            nudges = await repo.feed_nudges(
                s,
                user.id,
                surface,
                project_id if surface == "customer" else None,
                since=since,
                until=until,
                settled=surface == "customer",
                limit=NUDGE_FEED,
            )
            acts.update(
                await repo.actions_by_id(
                    s, user.id, [n.action_id for n in nudges if n.action_id not in (None, *acts)]
                )
            )
            if surface == "customer":
                looked = await research.feed_items(s, user.id, project_id, since, until)
            if (
                before is None
                and surface == "customer"
                and any(n.trigger in TASK_TRIGGERS for n in nudges)
            ):
                task = await cards.visit_task_for(s, user, project_id, today_seoul(), now)
        later = {
            uuid.UUID(a.result["superseded_by"])
            for a in acts.values()
            if a.result and a.result.get("superseded_by")
        }
        acts.update(await repo.actions_by_id(s, user.id, list(later - set(acts))))
    items: list = []
    for m in rows:
        if m.role == "user":
            items.append(UserItem(id=f"u-{m.id}", at=m.created_at, text=m.text))
            continue
        t = turns.get(m.turn)
        parts: list = [CardPart(card=CardOut.model_validate(c)) for c in (t.cards if t else [])]
        for x in (t.trace or {}).get("actions", []) if t else []:
            a = acts.get(uuid.UUID(x))
            nxt = (a.result or {}).get("superseded_by") if a else None
            a = acts.get(uuid.UUID(nxt), a) if nxt else a
            if a is not None:
                parts.append(ActionPart(action=actions.out(a)))
        if t is not None and t.mode == "llm" and not m.text.startswith(CARDS_ONLY):
            parts.append(TextPart(text=m.text, src="ai"))
        elif t is not None and (kept := (t.trace or {}).get("kept")):  # 무료 모드 앞 LLM 글(R14)
            parts.append(TextPart(text=m.text[:kept], src="ai"))
        elif t is None:
            parts.append(TextPart(text=m.text, src="guide"))
        items.append(
            AssistantItem(
                id=f"a-{m.id}",
                at=m.created_at,
                turn_id=t.id if t else None,
                parts=parts,
                mode=t.mode if t else None,  # type: ignore[arg-type]
            )
        )
    for t in reversed(failed):
        items.append(
            AssistantItem(
                id=f"f-{t.id}",
                at=t.created_at,
                turn_id=t.id,
                parts=[CardPart(card=CardOut.model_validate(c)) for c in t.cards or []],
                mode=t.mode,  # type: ignore[arg-type]
                error=ErrorOut(code=t.error_code or "failed", message=FAILED),
            )
        )
    # 작업 카드는 실측 · 견적서 줄 가장 새것 하나에만(열린 줄이 있으면 그것, 없으면 완료 줄)
    tasks = [n for n in nudges if n.trigger in TASK_TRIGGERS]
    tasked = next((n.id for n in tasks if not _settled(n)), tasks[0].id if tasks else None)
    for n in nudges:
        items.append(_nudge_item(n, acts, task if n.id == tasked else None, proactive))
    items.extend(looked)
    items.sort(key=lambda x: x.at)  # 같은 때면 원래 순서(질문 → 답)
    last = turns.get(max(turns)) if turns else None
    more = _has_older(rows, limit)
    chips = (
        runtime.chips_for(last.cards, await chip_facts(user, surface, project_id, last.cards))
        if last
        else []
    )
    return FeedPage(
        items=items,
        before=rows[0].turn if more else None,
        rev=chat.rev if chat is not None else 1,
        chips=chips,
        now=now,
    )


async def chip_facts(
    user: User, surface: str, project_id: uuid.UUID | None, cards: list[dict]
) -> set[str]:
    """칩을 고를 공사 단계 사실(코드 값만, runtime.CHIPS): 고객은 visits 실측을 요청함 · quote 받은 실측 견적서가 있고
    아직 업체를 확정하지 않음(확정 뒤엔 견적 비교 칩이 지난 단계, QA r3 c1 20턴 · c2 13턴) · dates 수락한 공사 날짜가
    있음, 업체는 마지막 브리핑 카드 요청의 requested(답할 요청) · visited(견적서를 낼 요청). 읽기 조인만 하고, 못 읽으면
    빈 집합(사실이 필요한 칩은 빠진다)."""
    from sqlalchemy import exists

    from app.quote.models import VendorQuote
    from app.schedule.models import Deal
    from app.visit.models import Visit

    out: set[str] = set()
    try:
        async with SessionLocal() as s:
            if surface == "customer" and project_id is not None:
                mine = Visit.project_id == project_id
                if await s.scalar(select(exists().where(mine))):
                    out.add("visits")
                sent = exists().where(
                    VendorQuote.visit_id == Visit.id, VendorQuote.sent_at.is_not(None), mine
                )
                dealt = exists().where(Deal.project_id == project_id, Deal.status != "reselected")
                if await s.scalar(select(sent)) and not await s.scalar(select(dealt)):
                    out.add("quote")
                dated = exists().where(Deal.project_id == project_id, Deal.start_date.is_not(None))
                if await s.scalar(select(dated)):
                    out.add("dates")
            elif surface == "vendor":
                brief = next((c for c in reversed(cards) if c.get("kind") == "vendor_brief"), None)
                vid = (brief or {}).get("data", {}).get("visit_id")
                status = (
                    await s.scalar(
                        select(Visit.status).where(
                            Visit.id == uuid.UUID(str(vid)), Visit.vendor_id == user.id
                        )
                    )
                    if vid
                    else None
                )
                if status == "requested":
                    out.add("requested")
                if status in ("visited", "quoted"):
                    out.add("visited")
    except (SQLAlchemyError, ValueError) as e:
        log.warning("비서 칩 사실 읽기 실패 (%s)", type(e).__name__)
    return out


# 한 쪽 창에 끼우는 먼저 말 건 줄 상한(보이는 줄 + 완료 줄). 줄에는 따로 커서가 없어 창 안 줄은 모두 보이게 넉넉히
# 둔다(30이면 대화 말이 적은 공사에서 그 밖 옛 줄을 다시 볼 길이 없었어요, 리뷰 R13). 하루 알림 상한이 있어 보통 수십 줄
NUDGE_FEED = 200
TASK_TRIGGERS = ("visit_offered", "quote_sent")  # 실측 진행 작업 카드를 붙이는 제안


def _has_older(rows: list[ChatMessage], limit: int) -> bool:
    """이 쪽 앞에 더 읽을 말이 있다(쪽이 꽉 찼고 첫 말이 첫 턴이 아님)."""
    return len(rows) == limit and bool(rows) and rows[0].turn > 1


def _settled(n) -> bool:
    """할 일이 끝나 닫힌 줄(대화 기록에 '완료'로 남는다)."""
    return n.status == "expired" and n.reason in repo.SETTLED


def _nudge_item(n, acts: dict, task, proactive) -> AssistantItem:
    """먼저 말 건 줄 → 대화 기록 한 줄: 문장 · 카드 · 승인 카드(지금 상태) · 작업 카드 · 다음에 물을 말.
    할 일이 끝난 줄(settled)은 다음에 물을 말을 빼고, 카드는 보낸 때 모습 그대로 둔다(card_id에 줄 id를 붙여 뒤
    턴 · 새 줄의 같은 카드와 한 자리로 합쳐지지 않게)."""
    from app.assistant.schemas import SuggestOut, SuggestPart, TaskPart

    done = _settled(n)
    parts: list = [TextPart(text=n.body or "", src=n.src or "guide")]
    for c in n.card if isinstance(n.card, list) else [n.card] if n.card else []:  # 07: 카드 둘
        card = {**c, "card_id": f"{c.get('card_id')}@{n.id}"} if done else c
        parts.append(CardPart(card=CardOut.model_validate(card)))
    a = acts.get(n.action_id) if n.action_id else None
    nxt = (a.result or {}).get("superseded_by") if a else None
    a = acts.get(uuid.UUID(nxt), a) if nxt else a
    if a is not None:
        parts.append(ActionPart(action=actions.out(a)))
    if task is not None:
        parts.append(TaskPart(task=task))
    if not done:
        parts.append(SuggestPart(suggest=SuggestOut(**proactive.suggest_of(n))))
    return AssistantItem(
        id=f"n-{n.id}", at=n.sent_at, turn_id=None, parts=parts, nudge_id=n.id, settled=done
    )


# ---- 보드 · 오늘 ----

STEP = {"house": 0, "standard": 1, "pick": 2, "visit": 3, "deal": 4, "dates": 5}


async def _estimates(s, project_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """요청 때 고정한 가견적(실측 요청 id → 부가세 포함 원). 읽기 조인."""
    from app.visit.models import Visit

    rows = await s.execute(
        select(Visit.id, Visit.estimate_total).where(
            Visit.project_id == project_id, Visit.estimate_total.is_not(None)
        )
    )
    return {i: won for i, won in rows}


def money_range(o, estimates: dict[uuid.UUID, int]) -> list[int] | None:
    """확정 전 업체 금액 범위: 업체마다 받은 실측 견적서 합계, 없으면 요청 때 고정한 가견적(둘 다 서버 값).
    두 곳 이상일 때 [가장 작은 값, 가장 큰 값]. 닫힌 요청은 빼고, 모두 확정했으면 비운다."""
    from app.assistant.tools.cards import ENDED

    if o.money.all_confirmed:
        return None
    vals = [
        v.total if v.total is not None else estimates.get(v.visit_id)
        for v in o.vendors
        if v.status not in ENDED
    ]
    got = [x for x in vals if x is not None]
    return [min(got), max(got)] if len(got) >= 2 else None


def memory_out(m) -> MemoryOut:
    from app.assistant import memory

    return MemoryOut(
        id=m.id,
        key=m.key,
        label=memory.LABEL.get(m.key, m.key),
        value=m.value,
        evidence_message_id=m.evidence_message_id,
        evidence_quote=m.evidence_quote,
        updated_at=m.updated_at,
    )


async def board_for(user: User, project_id: uuid.UUID) -> BoardOut:
    """내 공사 보드(우리 집 · 지금 단계 · 낼 금액(범위) · 업체 · 기간 · 서류 · 기억). 값은 기능 service 그대로."""
    from app.assistant.tools import cards
    from app.assistant.tools import diy as diy_tools
    from app.project import service as project_service
    from app.schedule import service as schedule_service

    today = today_seoul()
    async with SessionLocal() as s:
        p = await project_service.get_for(s, user, project_id)
        _, home = await cards.home(s, user, project_id)
        o = await schedule_service.overview_for(s, user, project_id, today)
        works = {w.trade: w for w in await schedule_service.work_money(s, user, project_id)}
        opened = await repo.open_count(s, user.id, project_id)
        estimates = await _estimates(s, project_id)
        if await diy_tools.settle_memory(s, user, now_utc()):  # 화면에서 뺀 직접 할 일 기억 조각
            await s.commit()
        remembered = await repo.memories(s, user.id)
    tr = next((t for t in o.trades if t.trade == "dobae"), o.trades[0] if o.trades else None)
    now_key = next((x.key for x in tr.steps if x.state == "now"), "house") if tr else "house"
    step = 6 if o.phase in ("work", "done") else STEP.get(now_key, 0)
    m = o.money
    dealt = any(x.source == "deal" for x in m.by_trade)
    total, extra = cards.work_total(m, works)  # 승인한 추가 금액은 공사 금액에 들어가요(계산 엔진)
    label = (
        ("공사 금액 · 부가세 포함" if extra else "확정 금액 · 부가세 포함")
        if m.all_confirmed
        else "낼 금액 · 부가세 포함"
        if dealt
        else "표준견적서 · 부가세 포함"
    )
    rows = [cards.board_row(v, o, works, today) for v in o.vendors]
    final = o.period.kind == "final"
    docs = [
        LinkOut(label="표준견적서", href=cards.href(p.id, "/standard")),
        LinkOut(label="확정 공정표" if final else "예상 공정표", href=cards.href(p.id, "/plan")),
    ]
    if any(v.total is not None for v in o.vendors):
        docs.append(LinkOut(label="실측 견적서", href=cards.href(p.id, "/quotes")))
    trades = " · ".join(cards.TRADE[t] for t in ("dobae", "mokgong") if getattr(p.trades, t, None))
    return BoardOut(
        project_name=f"{p.sgg} 아파트 {trades}".strip(),
        step=step,
        facts=home["facts"],
        confirmed=p.home is not None,
        todo=opened + (1 if cards.todo_kind(o.todo) == "todo" else 0),
        waiting=sum(1 for v in o.vendors if v.next.who == "vendor")
        + (1 if cards.todo_kind(o.todo) == "waiting" else 0),
        money=BoardMoneyOut(
            label=label, won=total, range=money_range(o, estimates), extra_won=extra or None
        )
        if m.by_trade
        else None,
        vendors=BoardVendors(title="업체", rows=rows) if rows else None,
        period=BoardPeriod(
            label="공사" if final else "예상 공사",
            value=kdate.md_range(o.period.start, o.period.end, today),  # 화면 날짜 꼴(F2 · F5)
            sub=f"일하는 날 {o.period.work_days}일",
        )
        if o.period.start
        else None,
        docs=docs,
        plan_example=not final,
        memory=[memory_out(x) for x in remembered],
        today_pin=opened,
    )


# 오늘 정할 일 '알아 두기'에 보일 먼저 말 건 줄(시간 트리거: 공사 전날 · 담기 없음 · 07 공사 1주 전)
KNOW_TRIGGERS = ("work_eve", "no_pick", "prep_week")


async def today_for(user: User, project_id: uuid.UUID) -> TodayData:
    """오늘 정할 일. nudge_id는 이 공사의 열린(보내고 아직 열지 않은) 먼저 말 건 줄 가장 새것('오늘은 그만'이
    닫는다), dismissed는 오늘 닫은 줄이 있고 열린 줄이 없을 때. 알아 두기는 시간 트리거 줄(정해 둔 말)."""
    from app.assistant import proactive
    from app.assistant.schemas import RowAction, TodayRow
    from app.assistant.tools import cards

    now = now_utc()
    async with SessionLocal() as s:
        card, _ = await cards.today(s, user, project_id, today_seoul(), now, RefTable(uuid.uuid4()))
        shown = await repo.shown_nudges(s, user.id, "customer", project_id, open_only=True)
        gone = (
            None
            if shown
            else await repo.last_dismissed(s, user.id, project_id, proactive._day_start(now))
        )
    data = TodayData.model_validate(card.data)
    data.nudge_id = shown[0].id if shown else None
    data.dismissed = gone is not None
    data.know = [
        TodayRow(
            id=f"k-{n.id}",
            icon="bulb",
            title=n.body or proactive.TRIGGERS[n.trigger].why,
            action=RowAction(label="보기", say=proactive.TRIGGERS[n.trigger].say),
        )
        for n in shown
        if n.trigger in KNOW_TRIGGERS
    ][:3]
    return data


# ---- 먼저 말 걸기 · 기억 · 다음에 물을 말 ----

NUDGE_GONE = "제안을 찾을 수 없어요."


def nudge_out(n) -> NudgeOut:
    return NudgeOut(
        nudge_id=n.id,
        trigger=n.trigger,
        channel=n.channel,
        status=n.status,
        body=n.body,
        src=n.src,
        action_id=n.action_id,
        sent_at=n.sent_at,
        acted_at=n.acted_at,
    )


async def nudge_act(user: User, nudge_id: uuid.UUID, surface: str, to: str) -> NudgeOut:
    """보낸 제안 열기(opened) · 닫기(dismissed). 보이지 않는 줄(기다림 · 기록만)과 남의 것은 404.
    이미 그 상태거나 더 바꿀 수 없으면(닫힘 · 밀려 닫힘) 지금 상태를 돌려준다(두 번 눌러도 같음)."""
    frm = ("sent",) if to == "opened" else ("sent", "opened")
    async with SessionLocal() as s:
        n = await repo.nudge_owned(s, user.id, nudge_id, surface)
        if n is None or n.status in ("pending", "held"):
            raise AppError(404, "not_found", NUDGE_GONE)
        if n.status in frm:
            got = await repo.set_nudge(s, n.id, frm, status=to, acted_at=now_utc())
            await s.commit()
            n = got or await repo.nudge_owned(s, user.id, nudge_id, surface)
        return nudge_out(n)


async def memory_for(user: User) -> list[MemoryOut]:
    from app.assistant.tools import diy as diy_tools

    async with SessionLocal() as s:
        if await diy_tools.settle_memory(s, user, now_utc()):  # 화면에서 뺀 직접 할 일 기억 조각
            await s.commit()
        return [memory_out(m) for m in await repo.memories(s, user.id)]


async def forget(user: User, memory_id: uuid.UUID) -> None:
    """기억 한 줄 지우기(내 것만, 남의 것 · 없는 것은 404). 다음 턴부터 쓰지 않는다."""
    async with SessionLocal() as s:
        if not await repo.delete_memory(s, user.id, memory_id):
            raise AppError(404, "not_found", "기억을 찾을 수 없어요.")
        await s.commit()


SUGGEST_MAX = 3
STEP_IDEAS = {
    "house": (
        "집 정보부터 확인할까요?",
        "집 정보가 맞아야 표준견적서가 맞아요",
        "집 정보 확인해 줘",
    ),
    "standard": ("업체 3곳을 골라 둘까요?", "표준견적서 다음은 업체 고르기예요", "업체 추천해 줘"),
    "pick": ("실측 시간 후보를 볼까요?", "담은 업체에 실측을 요청할 차례예요", "실측 시간 찾아 줘"),
    # 이름과 보내는 말을 맞춰요(QA r3 s5: '실측 일정을 챙길까요?'를 누르면 '오늘 할 일 알려 줘'가 감)
    "visit": ("오늘 할 일을 볼까요?", "업체 답과 실측 날짜를 볼 차례예요", "오늘 할 일 알려 줘"),
    "deal": (
        "견적서를 견줘 볼까요?",
        "받은 실측 견적서로 업체를 정할 차례예요",
        "견적서 비교해 줘",
    ),
    "dates": (
        "공사 날짜를 볼까요?",
        "확정한 업체의 공사 날짜를 챙길 차례예요",
        "공사 날짜 보여 줘",
    ),
    # 공사 단계(날짜 수락 뒤): 때에 맞는 것만(work_idea). 3주 전에 '공사 전날 준비물'을 권하지 않아요
    "prep": ("공사 전에 할 일을 볼까요?", "공사 전에 챙길 것이 있어요", "공사 전에 할 일 알려 줘"),
    "eve": ("공사 전날 준비물을 볼까요?", "내일 공사가 시작돼요", "공사 전날 준비물 알려 줘"),
    "check": (
        "공사 끝 점검표를 볼까요?",
        "업체가 공사를 끝냈다고 했어요",
        "공사 끝 점검표 보여 줘",
    ),
    # 이 지역에 고를 수 있는 업체가 없을 때 업체 고르기 대신(QA r3 s3: 0곳 지역에 '업체 3곳을 골라 둘까요?' 10턴)
    "outside": (
        "믿집 밖에서 찾아볼까요?",
        "이 지역엔 믿집이 단가를 확인한 업체가 아직 없어요",
        "믿집 밖 도배 업체 찾아 줘",
    ),
}
# 고를 수 있는 업체가 셋보다 적을 때 업체 고르기 말(QA r3 c4 · f1: 2곳인 구에 '업체 3곳을 골라 둘까요?')
PICK_FEW = "업체 {n}곳을 골라 둘까요?"
# 제안이 이어지는 카드 종류: 바로 앞 턴에 그 카드를 보였으면 같은 제안을 되풀이하지 않아요
STEP_CARD = {
    "house": "home_info",
    "standard": "vendor_picks",
    "pick": "visit_slots",
    "visit": "today",
    "deal": "quote_compare",
    "dates": "schedule",
    "prep": "knowledge",
    "eve": "knowledge",
    "check": "knowledge",
    "outside": "research",
}
# 먼저 말 건 줄의 할 일이 끝났다고 보는 것: 그 줄 뒤 턴에 보인 카드 종류 · 그 줄 뒤에 만든 승인 카드 종류. 끝났으면
# 그 줄에서 온 다음에 물을 말을 빼요(QA r3 c4: 견준 뒤 · 확정 카드를 연 뒤에도 '받은 견적서를 견줘 볼까요?', 추가 금액
# 카드를 보인 뒤에도 '추가 금액을 볼까요?'가 9턴). 줄은 정리(sweep)가 대상 상태를 보고 따로 닫아요
NUDGE_DONE: dict[str, tuple[str, frozenset[str]]] = {
    "quote_sent": ("quote_compare", frozenset({"vendor_confirm"})),
    "extra_added": ("extra", frozenset({"extra_answer"})),
    "dates_proposed": ("schedule", frozenset({"dates_accept", "delay_accept"})),
    "visit_offered": ("visit_slots", frozenset({"visit_slot"})),
    "vendor_out": ("vendor_picks", frozenset({"visit_request"})),
    "no_pick": ("vendor_picks", frozenset({"visit_request"})),
}
# 그 단계의 다음 일이 이미 열린 승인 카드로 와 있으면(누르기만 남음) 단계 제안을 하지 않아요(QA r2 c5: 업체를 골라
# 실측 요청 카드가 열렸는데 '업체 3곳을 골라 둘까요?')
STEP_OPEN = {
    "standard": frozenset({"visit_request"}),
    "pick": frozenset({"visit_request"}),
    "visit": frozenset({"visit_slot"}),
    "deal": frozenset({"vendor_confirm"}),
    "dates": frozenset({"dates_accept", "delay_accept"}),
}
RECENT_SAID = 6  # 고객이 최근에 한 말 줄 수(이미 물은 제안은 빼요)
VENDOR_IDEAS = {
    "new": ("새 요청을 정리해 볼까요?", "답할 새 요청이 있어요", "새 요청 브리핑해 줘"),
    "quote": ("보낼 견적서를 챙길까요?", "실측을 마친 요청이 있어요", "견적서 체크리스트 보여 줘"),
}


def step_key(o, today) -> str | None:
    """공사 요약(overview) → 다음에 물을 말 단계 키. 날짜를 수락한 뒤에는 때에 맞는 것(공사 1주 전 할 일 ·
    전날 준비물 · 끝 확인)만, 맞는 것이 없으면 None."""
    if o.phase in ("work", "done"):
        code = o.todo.code if o.todo else ""
        if code == "check":
            return "check"
        if code == "before_work":
            start = o.next.day if o.next is not None and o.next.kind == "start" else None
            return "eve" if start == today + timedelta(days=1) else "prep"
        return None
    tr = next((t for t in o.trades if t.trade == "dobae"), o.trades[0] if o.trades else None)
    return next((x.key for x in tr.steps if x.state == "now"), "house") if tr else "house"


async def suggest_for(
    user: User,
    surface: str,
    project_id: uuid.UUID | None,
    *,
    said: str = "",
    chips: list[str] | tuple[str, ...] = (),
) -> list[SuggestOut]:
    """다음에 물을 말 0~3개(코드가 고름): 열린 먼저 말 걸기 줄 → 지금 단계 다음 일(업체는 오늘 할 일).
    이번 말 · 칩과 같은 말, 고객이 최근에 이미 물은 말, 바로 앞 턴에 보인 카드로 이어지는 단계 제안은 뺀다(같은
    제안을 여러 턴 되풀이하지 않게). 먼저 말 건 줄의 제안은 그 일이 끝났으면 뺀다(NUDGE_DONE). 단계는 공사 날짜를
    수락하기 전엔 업체 상태에서 나온 실제 단계(work_now)다. 담은 업체가 없으면 '실측 시간' 대신 업체 고르기를, 고를
    수 있는 업체 수만큼(0곳이면 믿집 밖 찾기) 권한다. 못 읽으면(어떤 오류든) 비운다: 턴 저장 commit 뒤라 error
    이벤트로 끝내면 화면은 실패, 다시 열면 답이 있다."""
    from app.assistant import proactive
    from app.project import service as project_service
    from app.schedule import service as schedule_service
    from app.visit import service as visit_service

    out: list[SuggestOut] = []
    recent: set[str] = set()
    try:
        async with SessionLocal() as s:
            shown = await repo.shown_nudges(
                s, user.id, surface, project_id if surface == "customer" else None, open_only=True
            )
            if surface == "customer" and project_id is not None:
                gone = await _nudges_done(s, user.id, project_id, shown)
                shown = [n for n in shown if n.id not in gone]
            out += [SuggestOut(**proactive.suggest_of(n)) for n in shown]
            if surface == "customer" and project_id is not None:
                today, now = today_seoul(), now_utc()
                o = await schedule_service.overview_for(s, user, project_id, today)
                key = step_key(o, today)
                p = await project_service.get_for(s, user, project_id)
                if o.phase not in ("work", "done") and getattr(p.trades, "dobae", None):
                    key = (await work_now(s, user, p, today, now)).key  # 업체 상태에서 나온 단계
                if key == "pick":  # 담은 업체가 없으면 실측 시간이 아니라 업체 고르기부터
                    lst = await visit_service.shortlist_for(s, user, project_id, "dobae")
                    key = "pick" if lst.items else "standard"
                text: str | None = None
                # 고를 수 있는 업체 수로 권한다(0곳이면 믿집 밖 찾기, 이미 찾는 중이면 없음)
                if key == "standard":
                    n = await _pickable(s, user, project_id)
                    if n == 0:
                        key = None if await _looking(s, user.id, project_id, now) else "outside"
                    elif n < 3:
                        text = PICK_FEW.format(n=n)
                if key in STEP_OPEN:  # 다음 일이 열린 승인 카드로 와 있으면 그 카드가 다음 걸음
                    live = await repo.actions_of(
                        s, user.id, surface, project_id=project_id, status="proposed", limit=20
                    )
                    if any(a.kind in STEP_OPEN[key] and a.expires_at > now for a in live):
                        key = None
                last, recent = await _recent(s, user.id, project_id)
                if key is not None and STEP_CARD.get(key) not in last:
                    idea, why, say = STEP_IDEAS[key]
                    out.append(SuggestOut(id=f"step-{key}", text=text or idea, why=why, say=say))
            elif surface == "vendor":
                from app.assistant.tools import vendor as vendor_tools

                rows = (await vendor_tools.vendor_today(s, user, today_seoul())).rows
                for r in rows:
                    if r.id in VENDOR_IDEAS:
                        text, why, say = VENDOR_IDEAS[r.id]
                        out.append(SuggestOut(id=f"today-{r.id}", text=text, why=why, say=say))
    except Exception as e:  # noqa: BLE001 - 저장까지 끝난 턴을 오류로 끝내지 않는다(비우기, 리뷰 R10)
        if not isinstance(e, AppError):
            log.warning("다음에 물을 말 만들기 실패 (%s)", type(e).__name__)
        return []
    skip = {said.strip(), *chips}
    seen: set[str] = set()
    picked: list[SuggestOut] = []
    for x in out:
        if x.say in skip or x.say in seen or (x.id.startswith("step-") and x.say in recent):
            continue
        seen.add(x.say)
        picked.append(x)
    return picked[:SUGGEST_MAX]


async def _recent(s, user_id: uuid.UUID, project_id: uuid.UUID) -> tuple[set[str], set[str]]:
    """(바로 앞 턴에 보인 카드 종류, 고객이 최근에 한 말). 대화가 없으면 둘 다 빈 집합."""
    chat = await repo.assistant_chat(s, user_id, project_id)
    if chat is None:
        return set(), set()
    rows = await repo.messages(s, chat.id, RECENT_SAID * 2)
    said = {m.text.strip() for m in rows if m.role == "user"}
    turns = await repo.turns_of(s, chat.id, [rows[-1].turn]) if rows else []
    kinds = {c.get("kind") for t in turns for c in (t.cards or [])}
    return {k for k in kinds if k}, said


async def _nudges_done(s, user_id: uuid.UUID, project_id: uuid.UUID, shown: list) -> set[uuid.UUID]:
    """열린 먼저 말 건 줄 중 할 일이 끝난 줄(NUDGE_DONE): 그 줄 뒤 턴에 그 카드를 보였거나 그 줄 뒤에 그 승인 카드를
    만들었다(누름 · 거둠 상관없이). 줄의 제안(다음에 물을 말)만 빼고 줄은 그대로 둔다."""
    mine = [n for n in shown if n.trigger in NUDGE_DONE and n.sent_at is not None]
    if not mine:
        return set()
    since = min(n.sent_at for n in mine)
    chat = await repo.assistant_chat(s, user_id, project_id)
    turns = (
        (
            await s.execute(
                select(AssistantTurn.created_at, AssistantTurn.cards).where(
                    AssistantTurn.chat_id == chat.id, AssistantTurn.created_at > since
                )
            )
        ).all()
        if chat is not None
        else []
    )
    made = [
        a
        for a in await repo.actions_of(s, user_id, "customer", project_id=project_id, limit=20)
        if a.created_at > since
    ]
    gone: set[uuid.UUID] = set()
    for n in mine:
        card, kinds = NUDGE_DONE[n.trigger]
        seen = any(
            at > n.sent_at and any(c.get("kind") == card for c in cards or [])
            for at, cards in turns
        )
        acted = any(
            a.kind in kinds and a.created_at > n.sent_at and a.id != n.action_id for a in made
        )
        if seen or acted:
            gone.add(n.id)
    return gone


async def _pickable(s, user: User, project_id: uuid.UUID) -> int:
    """지금 고를 수 있는 도배 업체 수(업체 추천 카드와 같은 셈, 3곳까지). 이미 요청 · 확정했거나 빠진 업체는 뺀다."""
    from app.assistant.tools import cards

    _, model = await cards.vendor_picks(s, user, project_id, "dobae", RefTable(uuid.uuid4()))
    return len(model.get("picks") or [])


async def _looking(s, user_id: uuid.UUID, project_id: uuid.UUID, now: datetime) -> bool:
    """믿집 밖 업체 조사가 도는 중이거나 방금(12시간 안) 끝났다(같은 제안을 다시 하지 않게)."""
    from app.assistant import research
    from app.assistant.models import RESEARCH_LIVE

    r = await research.latest(s, user_id, project_id)
    if r is None or r.kind != "outside_vendors":
        return False
    return r.status in RESEARCH_LIVE or (
        r.ended_at is not None and now - r.ended_at <= research.RECENT
    )


# ---- 업체 ----


async def brief_for(vendor: User, visit_id: uuid.UUID, *, propose: bool = False) -> VendorBriefData:
    """업체 요청 브리핑(REST). 기간 후보 이름표(w…)는 업체 비서 대화의 표에 넣어 카드 단추(window_answer:w…)로
    고를 수 있게 한다.
    - GET(propose=False): 읽기만. 제안 행을 만들거나 닫지 않고 Haiku도 부르지 않는다(캐시 문장 또는 틀). 이 요청에
      열린 기간 답하기 제안이 있으면 추천 응답으로 보인다(다른 사이트가 연 GET이 상태를 바꾸지 않게, 보안 L4).
    - POST(propose=True, 화면 브리핑 카드): 요청함이면 추천 기간 답하기 제안 행을 만든다(실행은 승인 뒤). 이 요청에
      열린 제안(대화에서 고른 못 받아요 · 다른 기간)이 있으면 새로 만들지 않고 덮지 않는다(리뷰 B3). 한 문장은 세션을
      닫은 뒤 Haiku가 쓴다(같은 사실이면 하루 캐시, 실패하면 틀)."""
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        chat = await ensure_chat(s, vendor.id, None)
        refs = await RefTable.load(chat.id)
        _, _, data, _, _ = await vendor_tools.brief(
            s,
            vendor,
            visit_id,
            today_seoul(),
            now_utc(),
            refs,
            propose_window=propose,
            keep_open=True,
            show_open=not propose,
        )
        await s.commit()  # 처음이면 만든 업체 대화를 남긴다(제안 행은 brief가 commit했다)
    await refs.save()
    data.sentence = await vendor_tools.brief_sentence(data, vendor.id, call=propose)
    return data


async def checklist_for(vendor: User, visit_id: uuid.UUID) -> QuoteChecklistData:
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        _, _, data = await vendor_tools.checklist(
            s, vendor, visit_id, today_seoul(), RefTable(uuid.uuid4())
        )
    return data


async def vendor_today(vendor: User) -> VendorTodayData:
    """업체 오늘 브리핑(REST). 공사 날짜 줄의 공사 날 후보 이름표(d# · n#)는 업체 비서 대화의 표에 넣어
    단추(choice 'dates:d#,n#')로 보낸 턴이 승인 카드를 만들게 한다."""
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        chat = await ensure_chat(s, vendor.id, None)
        # 처음이면 만든 업체 대화를 먼저 남긴다(예상 공정표 저장의 rollback과 섞지 않게)
        await s.commit()
        refs = await RefTable.load(chat.id)
        data = await vendor_tools.vendor_today(s, vendor, today_seoul(), refs)
    await refs.save()
    return data


# ---- 상태 · 정리 ----


async def health(user: User) -> HealthOut:
    """화면에 필요한 값만(보안 I3): 모드와, 고객 본인 하루 상한이면 budget. 서비스 전체 상한 · 차단기는 알리지 않고
    off로 묶는다(상한을 다 쓰게 하는 공격이 먹혔는지 보는 데 쓰이지 않게). 턴 모드는 runtime이 따로 정한다."""
    from app.agent import llm
    from app.usage import service as usage

    if not llm.available() or await runtime.breaker_open():
        return HealthOut(mode="free", reason="off")
    try:
        await usage.allow(user.id, "health")
    except usage.OverCap as e:
        return HealthOut(mode="free", reason="budget" if e.scope == "user_day" else "off")
    except usage.DB_ERRORS:  # 셀 수 없으면 닫힘 쪽(턴도 무료 모드로 간다)
        return HealthOut(mode="free", reason="off")
    return HealthOut(mode="llm", reason="ok")


async def sweep(now: datetime) -> dict[str, int]:
    """worker assistant_sweep(2분): 만료 제안 · 멈춘 승인 · 화면에서 직접 처리한 제안(handled_elsewhere) · 할 일이 끝난
    먼저 말 건 줄(settled) · 멈춘 턴 · 상태 전이 알림 → 먼저 말 걸기 · 기한이 된 제안 평가(보냄 · 미룸 · 기록만 · 닫음).
    기억 뽑기는 sweep_jobs(jobs kind=assistant_memory)가 한다."""
    from app.assistant import proactive

    # 시작부터 정한 시간 예산(앞 단계가 길어도 worker 시간 제한 60초 안)
    settle_until, eval_until = proactive.deadlines()
    expired, stuck = await actions.expire_due(now)
    handled = await actions.close_handled()
    # 할 일이 끝난 먼저 말 건 줄(실행 · 대상 상태 바뀜)
    settled = await proactive.close_settled(now, until=settle_until)
    async with SessionLocal() as s:
        stalled = await repo.fail_stalled(s, now, now - STALL)
        await s.commit()
    events = await proactive.scan_events(now)
    tally = await proactive.evaluate_due(now, until=eval_until)
    return {
        "expired": expired,
        "stuck": stuck,
        "handled": handled,
        "settled": settled,
        "stalled": stalled,
        "events": events,
        **{f"nudge_{k}": v for k, v in tally.items()},
    }


async def hourly(now: datetime) -> dict[str, int]:
    """worker assistant_hourly(매시간): 시간 · 무응답 트리거 → 기다리는 알림 제안(보내기는 sweep이 한다)."""
    from app.assistant import proactive

    return {"time": await proactive.scan_time(now)}
