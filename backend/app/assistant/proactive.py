"""먼저 말 걸기 (계약서 6장). 트리거 · 대상 · 점수 · 카드 · 승인 카드는 코드가, 문장만 Haiku가 쓴다.

- scan_events(2분): 상태를 바꾸는 트랜잭션이 함께 쓴 notifications를 아웃박스로 읽는다(LOOKBACK 안, 아직 줄이 없는
  알림만). 알림마다 기다리는 제안(feed) 한 줄을 만든다(dedup_key ev:{알림 id}). 대상을 못 찾으면 expired 줄로 남긴다.
- scan_time(매시간): 공사 시작 전날(10시) · 표준견적서 뒤 3일 담기 없음 · 무응답(보낸 feed 뒤 48시간 · 3일 ·
  2일(연기 1일), 상태 그대로)에 알림(notify) 제안을 만든다.
- evaluate_due(2분): 기한이 된 제안마다 ① 상태가 그대로인지(아니면 expired) ② 규칙(policy.NudgeRules: 쉬기 · 멈춤 ·
  밤 · 하루 상한, 미루면 기한이 지나는 알림은 대화 줄로 지금) ③ 점수(score) ④ 40~69면 Haiku 판정(judge) ⑤ 문장
  (write, 검사에 걸리면 틀) ⑥ 보냄(상태를 다시 보고, 카드 · 승인 카드 · 알림을 같은 트랜잭션에). LLM은 DB 세션 밖에서
  부른다. 보낸 뒤 화면 신호(state · notif)를 보낸다. 근원 알림이 이미 종을 울린 사건(done_remind)은 종 알림을 더하지
  않는다(같은 사건 알림은 하나).
- close_settled(2분): 보이는 줄 중 할 일이 끝난 줄을 닫는다. 새로 보낸 줄 + 오래 안 본 줄부터 돌아가며(보이는 줄의
  due_at = 정리가 마지막으로 본 때) 상태만 가볍게 본다. sweep 시작부터 정한 시간 예산 안에서만 돈다.
- 점수: 기본 50, 기한 24시간 안 +50(48시간 안 +30), 승인 카드 준비 +20, 돈 · 날짜 결정 +15, 같은 알림 읽음 −30,
  24시간 안 보낸 제안마다 −20, 같은 trigger를 7일 안에 닫음 −30. 70 이상 보냄, 40~69 판정, 40 미만 기록만(held).
  판정을 못 부르면(꺼짐 · 상한 · 실패) 대화 기록(feed)은 보내고 알림(notify)은 기록만 한다.
  사건 알림(NEWS: 견적서 도착 · 공사 날짜 · 추가 금액 · 업체 빠짐 · 공사 끝의 첫 알림)은 고객이 꼭 알아야 하는 새
  소식이라 점수 · 판정 없이 보낸다(리드 결정 2026-11-22, QA 3차 c1 P4: 같은 65점 견적서 줄 하나만 판정이 막음).
  하루 상한 · 밤 · 쉬기 · 멈춤(RULES)은 그대로다.
- 문장은 무엇 · 얼마 · 누구를 담는다(틀 more · AI 글 검사 kept_facts): 견적서가 여러 곳이면 모든 업체 이름, 추가 금액은
  금액(업체가 적은 '한 일'은 비서 문장에 넣지 않고 카드 칸에만, policy.vendor_note), 업체가 올린 날짜는 시작일과 고객
  요청(다른 날짜 · 날짜 바꾸기)의 답인지, 공사 전날 · 1주 전은 붙은 카드(준비물 · 할 일 · 이웃 안내문). AI 글이
  빠뜨리면 틀을 쓴다(QA 2차 t1 · 3차 c2 · c4).
- 대상마다 보이는 제안은 하나: 같은 대상의 새 제안을 보내면 앞 것은 expired(replaced).
"""

import asyncio
import json
import logging
import re
import time as time_mod
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import String, and_, cast, exists, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import aftercare, policy, prompts
from app.assistant import repository as repo
from app.assistant.models import AssistantNudge
from app.db import SessionLocal
from app.shared.clock import SEOUL
from app.shared.korean import i_ga

log = logging.getLogger(__name__)

Channel = Literal["feed", "notify"]
RULES = policy.NudgeRules()
LOOKBACK = timedelta(hours=48)  # 아웃박스로 읽는 알림 기간(worker가 멈췄다 돌아와도 놓치지 않게)
BATCH = 50
EVAL_SECONDS = 40.0  # 한 차례 평가 시간(assistant_sweep 시간 제한 60초 안)
# sweep 시작부터 앞 단계가 멈추는 때(초): 정리(close_settled)는 15초, 평가(evaluate_due)는 45초까지. worker 시간 제한
# 60초 안에서 앞 단계(만료 · 화면 처리 · 정리)가 길어져도 평가가 남은 시간만 쓰게 한다
SETTLE_SECONDS = 15.0
SWEEP_SECONDS = 45.0


def deadlines() -> tuple[float, float]:
    """sweep 시작에 부르면 (정리를 멈출 때, 평가를 멈출 때)를 time.monotonic 값으로 준다."""
    started = time_mod.monotonic()
    return started + SETTLE_SECONDS, started + SWEEP_SECONDS


# 판정 · 문장 한 번(Haiku)의 시간 제한: 느린 응답 하나가 sweep 시간 제한을 넘지 않게
NUDGE_LLM_SECONDS = 10.0
# 기한이 이 안이면 '천천히' 같은 말을 쓰지 않고, 틀이 있으면 기한을 말하는 틀(soon)을 쓴다
SOON_HOURS = 24
BASE = 50
SEND_AT = 70
JUDGE_AT = 40
SNOOZE_SEEN = timedelta(days=7)  # 같은 trigger 닫음(−30)을 보는 기간
DISMISS_SEEN = timedelta(days=14)  # 규칙(쉬기 · 멈춤)에 넘기는 닫음 기간
NOTIFY_KIND = "assistant_nudge"
WORK_EVE_AT = time(10)  # 공사 시작 전날 알림 시각(서울)
NO_PICK_AFTER = timedelta(days=3)
NO_PICK_SINCE = timedelta(days=14)  # 이보다 오래된 공사는 담기 없음 제안을 만들지 않는다
FOLLOW_MIN = timedelta(days=1)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TRADE_KO = {"dobae": "도배", "mokgong": "목공"}


@dataclass(frozen=True)
class Trigger:
    """트리거 하나(계약서 6장 표). 문장 틀은 {vendor} · {vendor_i_ga} · {trade} · {area}를 채운다."""

    name: str
    surface: Literal["customer", "vendor"]
    kinds: tuple[str, ...] = ()  # 아웃박스로 읽는 알림 kind(시간 트리거는 비움)
    channel: Channel = "feed"  # 처음 보낼 채널
    notify_kinds: tuple[str, ...] = ()  # 처음부터 알림(notify)으로 보낼 kind(예: 자동 끝 3일 전)
    follow: timedelta | None = None  # 보낸 feed 뒤 이만큼 상태가 그대로면 notify
    decision: bool = False  # 돈 · 날짜를 정하는 일(+15)
    action: bool = False  # 보낼 때 승인 카드를 만든다(+20)
    state: str = "visit"  # 보낸 뒤 화면 신호(realtime StateKind)
    say: str = ""  # 제안을 누르면 비서에게 보낼 말
    why: str = ""  # 제안 까닭(틀)
    feed: str = ""  # 문장 틀(대화 기록)
    notify: str = ""  # 문장 틀(알림)
    ask: str = ""  # 제안 카드 한 줄(먼저 말 건 문장을 되풀이하지 않게 할 일을 묻는 말)
    soon: str = ""  # 기한이 하루 안일 때 문장 틀(채널과 상관없이, {until}이 있을 때만)
    # 사실이 더 있으면 쓰는 틀: (바꿀 틀 feed · notify, 있어야 할 사실 이름들, 틀). 위에서부터 60자 안인 첫 것
    more: tuple[tuple[str, tuple[str, ...], str], ...] = ()


TRIGGERS: dict[str, Trigger] = {
    t.name: t
    for t in (
        Trigger(
            "visit_offered", "customer", ("visit_offered",), follow=timedelta(hours=48),
            decision=True, action=True, state="visit", say="실측 날짜 고를래요",
            why="업체가 갈 수 있는 기간을 보냈어요", ask="실측 날짜를 골라 볼까요?",
            feed="{vendor_i_ga} 실측 가능 기간을 보냈어요. 실측 일정 후보를 골라 뒀어요.",
            notify="{vendor_i_ga} 보낸 실측 가능 기간에서 아직 날짜를 고르지 않았어요. 후보를 확인해 주세요.",
        ),
        Trigger(
            "quote_sent", "customer", ("quote_sent", "quote_resent"), follow=timedelta(days=3),
            decision=True, state="quote", say="견적서 비교해 줘", why="실측 견적서가 왔어요",
            ask="받은 견적서를 견줘 볼까요?",
            feed="{vendor_i_ga} 실측 견적서를 보냈어요. 받은 견적서를 견줘 볼까요?",
            notify="받은 실측 견적서를 아직 확인하지 않았어요. 견줘 볼까요?",
            soon="{vendor_i_ga} 보낸 실측 견적서는 {until}까지 유효해요. 견줘 볼까요?",
            # 다시 올린 판이면 판 · 바뀐 것(QA r6 c4 2), 두 곳 넘게 왔으면 받은 곳 이름 모두(QA 3차 c2 · c4)
            more=(
                ("feed", ("version", "change"),
                 "{vendor_i_ga} 견적서를 {version}판으로 다시 올렸어요({change}). 견줘 볼까요?"),
                ("feed", ("version",), "{vendor_i_ga} 견적서를 {version}판으로 다시 올렸어요. 견줘 볼까요?"),
                ("feed", ("quoted",), "{quoted}에서 실측 견적서가 왔어요. 받은 견적서를 견줘 볼까요?"),
            ),
        ),
        Trigger(
            "dates_proposed", "customer", ("dates_proposed",), follow=timedelta(days=2),
            decision=True, action=True, state="deal", say="공사 날짜 보여 줘",
            why="업체가 공사 날짜를 올렸어요", ask="공사 날짜를 볼까요?",
            feed="{vendor_i_ga} 공사 날짜를 올렸어요. 날짜를 확인해 주세요.",
            notify="{vendor_i_ga} 올린 공사 날짜가 아직 수락 전이에요.",
            # 시작일 · 고객 요청(다른 날짜 · 날짜 바꾸기)의 답인지 · 업체가 바꾸자고 한 것인지(QA 3차 c4 #24)
            more=(
                ("feed", ("asked", "start"),
                 "요청하신 {asked}에 {vendor_i_ga} {start}부터로 답했어요. 확인하고 수락해 주세요."),
                ("feed", ("change", "start"),
                 "{vendor_i_ga} 공사 날짜를 {start}부터로 바꾸자고 했어요. 확인해 주세요."),
                ("feed", ("start",), "{vendor_i_ga} 공사 날짜를 {start}부터로 올렸어요. 확인하고 수락해 주세요."),
                ("notify", ("asked",), "요청하신 {asked}에 {vendor_i_ga} 올린 날짜가 아직 수락 전이에요."),
            ),
        ),
        Trigger(
            "work_eve", "customer", channel="notify", state="deal", say="공사 전날 준비물 알려 줘",
            why="내일 공사가 시작돼요", ask="공사 전날 준비물을 볼까요?",
            notify="내일 {trade} 공사가 시작돼요. 준비물을 챙겨 주세요.",
        ),
        Trigger(
            "no_pick", "customer", channel="notify", state="visit", say="업체 추천해 줘",
            why="표준견적서를 본 뒤 업체를 아직 담지 않았어요", ask="맞는 업체를 볼까요?",
            notify="{area}에서 이 집에 맞는 업체를 골라 봤어요. 살펴볼까요?",
        ),
        # 업체 쪽 문장은 틀로만 써요(write): 누가 무엇을 했는지 틀리지 않게(QA r1 c6: '고객이 날짜를 확정')
        Trigger(
            "visit_requested", "vendor", ("visit_requested",), action=True, state="visit",
            say="새 요청 브리핑해 줘", why="새 실측 요청이 왔어요", ask="새 요청을 정리해 볼까요?",
            feed="{area} {size} 실측 요청이 왔어요. 답할 기간을 확인해 주세요.",
        ),
        Trigger(
            "visit_picked", "vendor", ("visit_picked",), decision=True, state="visit",
            say="요청 브리핑해 줘", why="고객이 실측 날짜를 골랐어요", ask="고른 날을 볼까요?",
            feed="{area} 고객이 {picked} 실측을 골랐어요. 요청 화면에서 수락해 주세요.",
        ),
        Trigger(
            "deal_confirmed", "vendor", ("deal_confirmed",), follow=timedelta(days=1),
            decision=True, action=True, state="deal", say="공사 할 일 보여 줘", why="고객이 확정했어요",
            ask="공사 날짜를 정해 볼까요?",
            feed="{area} 고객이 보내신 견적서로 확정했어요. 이제 공사 날짜를 낼 차례예요.",
            notify="{area} 요청의 공사 날짜를 아직 내지 않았어요. 후보를 확인해 주세요.",
        ),
        *(Trigger(**x) for x in aftercare.TRIGGERS),  # 07 자동화(업체 빠짐 · 추가 금액 · 공사 끝 …)
    )
}  # fmt: skip
EVENT_KINDS: dict[str, str] = {k: t.name for t in TRIGGERS.values() for k in t.kinds}


# ---- 사실 · 점수 ----


@dataclass
class Ctx:
    """대상의 지금 상태에서 코드가 읽은 사실(문장 틀 · 판정 · 점수). 상태가 바뀌었으면 만들지 않는다."""

    project_id: uuid.UUID | None = None
    names: dict[str, str] = field(
        default_factory=dict
    )  # vendor · trade · area (+ 코드 값 trade_code)
    due: datetime | None = None  # 사용자가 할 일의 기한
    read: bool = False  # 근원 알림을 이미 읽음
    follow: timedelta | None = None  # 무응답 알림까지(트리거 기본값을 바꿀 때: 연기 1일)


@dataclass
class Facts:
    """점수 · 판정 · 문장이 보는 코드 사실(글 · id 없음)."""

    trigger: str
    channel: str
    surface: str
    hours_left: float | None = None
    action_ready: bool = False
    decision: bool = False
    read: bool = False
    sent_24h: int = 0
    dismissed_same: bool = False
    names: dict[str, str] = field(default_factory=dict)

    def public(self) -> dict:
        """Haiku에 보낼 사실(이름 · 공정 · 지역 · 날짜, id 없음)."""
        names = {k: v for k, v in self.names.items() if not k.endswith("_code")}
        return {
            "trigger": self.trigger,
            "channel": self.channel,
            "surface": self.surface,
            "hours_left": None if self.hours_left is None else round(self.hours_left),
            "action_ready": self.action_ready,
            "decision": self.decision,
            "read": self.read,
            "sent_24h": self.sent_24h,
            "dismissed_same": self.dismissed_same,
            **names,
        }


# 고객 문장 사실의 지금 단계 · 남은 할 일(nudge_write_v3가 읽어 할 일을 여기서 고른다). context()가 상태를 확인한
# 뒤라 트리거마다 단계가 하나다(QA r2 c3: 업체 확정 뒤 공사 날짜 줄에 '이 업체로 확정해 보세요')
STEPS: dict[str, tuple[str, str]] = {
    "visit_offered": ("실측 요청 뒤 · 업체가 실측 기간을 답함", "실측 날짜 고르기"),
    "quote_sent": ("실측 견적서 받음 · 업체 확정 전", "받은 견적서 견주고 업체 확정하기"),
    "dates_proposed": ("업체 확정 끝 · 공사 날짜 수락 전", "올라온 공사 날짜 확인하고 수락하기"),
    "work_eve": ("공사 날짜 수락 끝 · 내일 공사 시작", "공사 전날 준비물 챙기기"),
    "no_pick": ("표준견적서 뒤 · 업체 고르기 전", "맞는 업체 골라 담기"),
    "vendor_out": ("실측 요청 뒤 · 요청한 업체가 빠짐", "골라 둔 다른 업체 보기"),
    "extra_added": ("공사 중 · 추가 금액 답 전", "추가 금액 보고 승인 · 거절 고르기"),
    "work_done": ("업체가 공사를 끝냄 · 공사 끝 확인 전", "점검표로 보고 공사 끝 확인하기"),
    # 붙은 카드 둘(공사 전 할 일 · 이웃 안내문 초안)을 할 일로(QA 2차 t1: '대화에서 한번 확인해 보실래요?')
    "prep_week": (
        "공사 날짜 수락 끝 · 공사 일주일 전",
        "공사 전에 할 일 챙기고 이웃 안내문 초안 보기",
    ),
}


def write_facts(f: Facts) -> dict:
    """문장(write)에 보낼 사실. 지금 단계 · 남은 할 일은 그것을 읽는 판(nudge_write_v3부터)에만 더한다(v2 판 그대로)."""
    facts = f.public()
    step = STEPS.get(f.trigger) if f.surface == "customer" else None
    if step is not None and prompts.version("nudge_write") != "nudge_write_v2":
        facts["step"], facts["todo"] = step
    return facts


def score(f: Facts) -> int:
    """'부를 만한가' 점수(0~100, 계약서 6장)."""
    s = BASE
    if f.hours_left is not None and f.hours_left >= 0:
        s += 50 if f.hours_left <= 24 else 30 if f.hours_left <= 48 else 0
    s += 20 if f.action_ready else 0
    s += 15 if f.decision else 0
    s -= 30 if f.read else 0
    s -= 20 * f.sent_24h
    s -= 30 if f.dismissed_same else 0
    return max(0, min(100, s))


def fresh_event(t: Trigger, n: AssistantNudge) -> bool:
    """업체 · 고객이 한 일로 생긴 첫 알림인지(아웃박스 kind가 있는 트리거, 무응답 다시 알림 ':notify'가 아님).

    새 소식이라 24시간 감점을 받지 않고, 고객이 [괜찮아요]로 닫은 다른 대상의 같은 종류 줄의 쉬기(−30 · 3일)에도
    걸리지 않는다(같은 대상을 닫았으면 쉰다). QA r2 c1 · c2 · x1: 견적서 · 추가 금액 알림이 앞서 보낸 줄 감점으로
    보류됨, t1: 한 줄을 닫자 같은 종류의 새 알림이 3일 쉬기에 막힘. 하루 상한 · 밤 미룸 · 두 번 닫아 멈춘 종 알림은
    그대로 지킨다(고정 선 6)."""
    return bool(t.kinds) and not n.dedup_key.endswith(":notify")


# 놓치면 안 되는 시간 알림: 24시간 감점을 받지 않는다(QA r2 t1: 공사 전날 알림이 그날 보낸 줄 감점으로 판정 문턱까지)
MUST_SEND = frozenset({"work_eve"})


def no_24h_penalty(t: Trigger, n: AssistantNudge) -> bool:
    """24시간 감점을 빼는 줄: 새 소식(fresh_event) 또는 놓치면 안 되는 시간 알림(MUST_SEND)."""
    return fresh_event(t, n) or t.name in MUST_SEND


# 사건 알림(리드 결정 2026-11-22): 견적서 도착 · 공사 날짜 · 추가 금액 · 업체 빠짐 · 공사 끝은 고객이 꼭 알아야 하는 새
# 소식이라 점수 · 판정(Haiku 40~69) 없이 보낸다. QA 3차 c1 P4: 같은 65점 견적서 줄 중 하나만 판정이 막았다
NEWS = frozenset({"quote_sent", "dates_proposed", "extra_added", "vendor_out", "work_done"})


def news(t: Trigger, n: AssistantNudge) -> bool:
    """판정 없이 보내는 사건 알림인지: NEWS 트리거의 첫 알림(무응답 다시 알림 ':notify'는 아님). 하루 상한 · 밤 ·
    쉬기 · 멈춤(RULES)은 그대로 본다."""
    return t.name in NEWS and fresh_event(t, n)


class JudgeOut(BaseModel):
    send: bool


class WriteOut(BaseModel):
    text: str


async def judge(f: Facts, user_id: uuid.UUID | None) -> bool | None:
    """40~69점: Haiku가 코드 사실만 보고 보낼지 정한다. 못 부르면 None(꺼짐 · 상한 · 공급자 실패)."""
    from app.agent import llm

    try:
        with llm.call_ctx(user_id=user_id, purpose="nudge"):
            got = await asyncio.wait_for(
                llm.claude_json(
                    "nudge",
                    JudgeOut,
                    prompts.text("nudge_judge"),
                    json.dumps(f.public(), ensure_ascii=False),
                    max_tokens=512,
                ),
                NUDGE_LLM_SECONDS,
            )
    except (llm.LLMError, TimeoutError):
        return None
    return got.send


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


def quote_change(prev, last) -> str | None:
    """견적서 앞 판 → 새 판에서 바뀐 것 글: '220,000원 내려감 · 3일 → 2일'(차액은 계산 엔진 visit_view.grade_diff,
    부가세 포함 합계끼리). 바뀐 것이 없으면 None."""
    from app.calc import visit_view

    parts = []
    if prev.total is not None and last.total is not None and prev.total != last.total:
        diff = visit_view.grade_diff(last.total, prev.total)
        parts.append(f"{abs(diff):,}원 {'내려감' if diff < 0 else '올라감'}")
    if prev.days is not None and last.days is not None and prev.days != last.days:
        parts.append(f"{prev.days}일 → {last.days}일")
    return " · ".join(parts) or None


def _soon(f: Facts) -> bool:
    return f.hours_left is not None and f.hours_left <= SOON_HOURS


# 틀 글 길이(먼저 말 건 한 줄, AI 글 검사 SENTENCE_MAX와 같다)
TEMPLATE_MAX = 60


def _fill(raw: str, names: dict) -> str:
    return " ".join(raw.format_map(_Safe(names)).split())


def template(f: Facts) -> str:
    """정해 둔 틀 글. 기한이 하루 안이면 기한 틀(soon), 사실이 더 있으면 그 사실을 넣은 틀(more, 60자 안인 첫 것)."""
    t = TRIGGERS[f.trigger]
    base = "notify" if (f.channel == "notify" and t.notify) or not t.feed else "feed"
    raw = t.notify if base == "notify" else t.feed
    names = {**f.names, "vendor_i_ga": i_ga(f.names["vendor"]) if f.names.get("vendor") else ""}
    h = f.hours_left
    # 기한이 하루 안: 기한을 말한다(유효기간이 오늘인 견적서에 '견줘 볼까요?'만 하지 않게)
    if t.soon and f.names.get("until") and h is not None and 0 <= h <= SOON_HOURS:
        return _fill(t.soon, names)
    for ch, keys, more in t.more:
        if ch == base and all(f.names.get(k) for k in keys):
            got = _fill(more, names)
            if len(got) <= TEMPLATE_MAX:
                return got
    return _fill(raw, names)


# 붙은 카드 말: 공사 전날은 준비물, 1주 전은 공사 전 할 일 · 이웃 안내문(QA 2차 t1: 준비물 카드에 '업체 일정 확인')
CARD_WORDS: dict[str, tuple[str, ...]] = {"work_eve": ("준비",), "prep_week": ("할 일", "안내문")}


def kept_facts(text: str, f: Facts) -> bool:
    """AI 글이 이 줄의 사실을 담았는지(빠뜨리면 틀을 쓴다): 견적서가 여러 곳이면 모든 업체 이름, 다시 올린 견적서는
    다시 올렸다는 말(판), 추가 금액은 금액, 업체가 올린 날짜는 시작일 · 고객 요청의 답이면 '요청', 공사 전날 · 1주 전은
    붙은 카드 말."""
    n = f.names
    if n.get("quoted") and not all(x in text for x in n["quoted"].split(" · ")):
        return False
    if n.get("won") and n["won"] not in text:
        return False
    if f.trigger == "dates_proposed" and n.get("start") and n["start"].split("(")[0] not in text:
        return False
    if n.get("asked") and "요청" not in text:
        return False
    # 다시 올린 견적서는 다시 올렸다는 것(판)을 말해야 해요(QA r6 c4 2)
    if (
        f.trigger == "quote_sent"
        and n.get("version")
        and not ("다시" in text or f"{n['version']}판" in text)
    ):
        return False
    words = CARD_WORDS.get(f.trigger)
    return not words or any(w in text for w in words)


# 이 길이 이상의 이름 조각이 이름 밖에 있으면 잘린 이름이다('도배' 같은 2자 공정 이름은 빼요)
NAME_PIECE = 3
# 기한이 하루 안인데 미뤄도 된다고 읽히는 말
SLOW = re.compile(
    r"천천히|여유(?:\s|롭|있|가|를)|느긋|급하지\s{0,2}않|나중에|편하실\s{0,2}때|편할\s{0,2}때|시간\s{0,2}(?:날|나실)\s{0,2}때"
)


def name_cut(text: str, name: str | None) -> bool:
    """업체 이름이 잘리거나 바뀌어 들어갔는지('믿집시험도배' → '시험도배'). 이름 그대로 쓴 곳은 빼고, 이름의 3자
    이상 조각(이름 전체는 빼고)이 남았는지 본다."""
    name = (name or "").strip()
    n = len(name)
    if n <= NAME_PIECE:
        return False
    rest = (text or "").replace(name, " ")
    return any(
        name[i:j] in rest for i in range(n) for j in range(i + NAME_PIECE, n + 1) if j - i < n
    )


async def write(f: Facts, user_id: uuid.UUID | None) -> tuple[str, str]:
    """문장 하나(60자 안): Haiku가 쓰고 검사에 걸리거나 못 부르면 틀. (글, 출처 ai · guide)
    검사: vendor.sentence_ok(길이 · 숫자 · 한 일처럼 …) + 업체 이름이 잘리지 않았는지 + 기한이 하루 안인데 '천천히'
    같은 말을 쓰지 않았는지 + 이 줄의 사실(kept_facts: 여러 곳 이름 · 금액 · 시작일 · 요청의 답 · 붙은 카드)을 담았는지.
    업체 쪽은 틀만 쓴다: Haiku가 '고객이 공사 날짜를 확정했어요'처럼 누가 무엇을 했는지 틀린 적이 있다(QA r1 c6)."""
    from app.agent import llm
    from app.assistant.tools.vendor import sentence_ok

    if f.surface == "vendor":
        return template(f), "guide"
    facts = json.dumps(write_facts(f), ensure_ascii=False)
    try:
        with llm.call_ctx(user_id=user_id, purpose="nudge"):
            got = await asyncio.wait_for(
                llm.claude_json(
                    "nudge", WriteOut, prompts.text("nudge_write"), facts, max_tokens=512
                ),
                NUDGE_LLM_SECONDS,
            )
    except (llm.LLMError, TimeoutError):
        return template(f), "guide"
    text = " ".join(got.text.split())
    slow = _soon(f) and bool(SLOW.search(text))
    if (
        not sentence_ok(text, facts)
        or name_cut(text, f.names.get("vendor"))
        or slow
        or not kept_facts(text, f)
    ):
        return template(f), "guide"
    return text, "ai"


# ---- 상태 읽기 ----


def _end_of(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time(0), SEOUL)


def _start_of(d: date) -> datetime:
    return datetime.combine(d, time(0), SEOUL)


async def _visit_ctx(
    s: AsyncSession,
    t: Trigger,
    ref: uuid.UUID,
    user_id: uuid.UUID,
    today: date,
    check: bool = False,
) -> Ctx | None:
    from app.notify.catalog import work_name
    from app.project.models import Project
    from app.quote.models import VendorQuote
    from app.visit.models import Visit, VisitHold, VisitWindow

    want = {
        "visit_offered": "offered",
        "quote_sent": "quoted",
        "visit_requested": "requested",
        "visit_picked": "picked",
    }[t.name]
    v = await s.get(Visit, ref, populate_existing=True)
    if v is None or v.status != want:
        return None
    p = await s.get(Project, v.project_id)
    if p is None:
        return None
    owner = p.owner_id if t.surface == "customer" else v.vendor_id
    if owner != user_id:
        return None
    c = Ctx(
        project_id=v.project_id,
        names={
            "vendor": v.vendor_name,
            "trade": TRADE_KO.get(v.trade, v.trade),
            "trade_code": v.trade,
            "area": work_name(p.sgg, p.emd, v.trade) if t.surface == "vendor" else p.sgg,
        },
    )
    if check:  # 정리: 상태가 그대로인지만 본다(기한 · 평형 · 고른 날 사실은 보낼 때만)
        return c
    if t.name == "visit_offered":
        c.due = await s.scalar(
            select(VisitWindow.pick_due_at)
            .where(VisitWindow.visit_id == v.id)
            .order_by(VisitWindow.answered_at.desc())
            .limit(1)
        )
    elif t.name == "quote_sent":
        sent = (
            await s.execute(
                select(
                    VendorQuote.version,
                    VendorQuote.total,
                    VendorQuote.days,
                    VendorQuote.valid_until,
                )
                .where(VendorQuote.visit_id == v.id, VendorQuote.sent_at.is_not(None))
                .order_by(VendorQuote.version.desc())
                .limit(2)
            )
        ).all()
        until = sent[0].valid_until if sent else None
        c.due = _end_of(until) if until else None
        # 다시 올린 견적서(2판 넘게): 판 · 바뀐 것(QA r6 c4 2: 2판이 와도 첫 도착과 같은 글)
        if len(sent) == 2:
            c.names["version"] = str(sent[0].version)
            if change := quote_change(sent[1], sent[0]):
                c.names["change"] = change
        # 견적서를 보낸 곳(먼저 보낸 곳부터)이 둘 넘으면 이름 모두: 같은 공사의 견적서 줄은 새 줄 하나로 합쳐 보이니
        # 그 줄 글이 받은 곳을 다 말한다(QA 3차 c2 · c4: 두 곳이 왔는데 한 곳 이름만)
        quoted = await _quoted(s, v)
        if len(quoted) > 1:
            c.names["quoted"] = " · ".join(quoted)
        # 유효기간(문장 사실 · 기한이 하루 안이면 쓰는 틀): '오늘' · '내일' · '12월 3일(목)'
        if until:
            c.names["until"] = (
                "오늘"
                if until == today
                else "내일"
                if until == today + timedelta(days=1)
                else _ko_day(until)
            )
    elif t.name == "visit_requested":
        c.due = v.reply_due_at
        c.names["size"] = await _size(s, v.project_id, v.trade)  # '32평'(업체 틀: 어느 요청인지)
    else:
        hold = (
            await s.execute(
                select(VisitHold.day, VisitHold.half, VisitHold.until).where(
                    VisitHold.visit_id == v.id, VisitHold.status == "active"
                )
            )
        ).first()
        c.due = hold.until if hold else None
        if hold is not None:  # 업체 틀: 고객이 고른 반나절
            c.names["picked"] = f"{_md_week(hold.day)} {HALF_KO.get(hold.half, '')}".strip()
    return c


async def _quoted(s: AsyncSession, v) -> list[str]:
    """같은 공사 · 공정에서 실측 견적서를 보내 고객이 고를 수 있는 업체 이름(먼저 보낸 곳부터). 읽기 조인."""
    from app.quote.models import VendorQuote
    from app.visit.models import Visit

    first = func.min(VendorQuote.sent_at)
    rows = await s.execute(
        select(Visit.vendor_name, first)
        .join(VendorQuote, VendorQuote.visit_id == Visit.id)
        .where(
            Visit.project_id == v.project_id,
            Visit.trade == v.trade,
            Visit.status == "quoted",
            VendorQuote.sent_at.is_not(None),
        )
        .group_by(Visit.id, Visit.vendor_name)
        .order_by(first)
    )
    return list(dict.fromkeys(name for name, _ in rows if name))


HALF_KO = {"am": "오전", "pm": "오후"}
# 업체 틀: 카드 · 승인 카드를 못 만들었을 때 다음 걸음
NO_CARD_NEXT = "공사 화면에서 확인해 주세요."


def _md_week(d: date) -> str:
    return f"{d.month:02d}.{d.day:02d}({'월화수목금토일'[d.weekday()]})"


def _ko_day(d: date) -> str:
    return f"{d.month}월 {d.day}일({'월화수목금토일'[d.weekday()]})"


async def _size(s: AsyncSession, project_id: uuid.UUID, trade: str) -> str:
    """표준견적서 평형 '32평'(없으면 빈 글)."""
    from decimal import Decimal

    from app.quote import service as quote_service

    std = (await quote_service.latest_of(s, [project_id])).get((project_id, trade))
    return f"{Decimal(std.pyeong).normalize():f}평" if std is not None and std.pyeong else ""


async def _deal_ctx(
    s: AsyncSession, t: Trigger, ref: uuid.UUID, user_id: uuid.UUID, today: date
) -> Ctx | None:
    from app.notify.catalog import work_name
    from app.project.models import Project
    from app.schedule.models import DateProposal, Deal

    proposal = None
    if t.name == "dates_proposed":
        proposal = await s.get(DateProposal, ref, populate_existing=True)
        if proposal is None or proposal.status != "pending":
            return None
        deal = await s.get(Deal, proposal.deal_id, populate_existing=True)
    else:
        deal = await s.get(Deal, ref, populate_existing=True)
    if deal is None:
        return None
    p = await s.get(Project, deal.project_id)
    if p is None or (p.owner_id if t.surface == "customer" else deal.vendor_id) != user_id:
        return None
    c = Ctx(
        project_id=deal.project_id,
        names={
            "vendor": deal.vendor_name,
            "trade": TRADE_KO.get(deal.trade, deal.trade),
            "trade_code": deal.trade,
            "area": work_name(p.sgg, p.emd, deal.trade) if t.surface == "vendor" else p.sgg,
        },
    )
    if proposal is not None:
        # '12월 14일(월)'(코드 꼴 날짜를 옮기지 않게)
        c.names["start"] = _ko_day(proposal.start_date)
        if proposal.request_id is not None:  # 고객이 한 요청에 업체가 답한 날짜(QA 3차 c4 #24)
            c.names["asked"] = "날짜 바꾸기" if proposal.kind == "change" else "다른 날짜"
        elif proposal.kind == "change":  # 업체가 먼저 바꾸자고 한 날짜(연기)
            c.names["change"] = "업체가 공사 날짜를 바꾸자고 함"
        c.due = _start_of(proposal.start_date)
        c.follow = timedelta(days=1) if proposal.kind == "change" else None
        return c
    if t.name == "work_eve":
        if deal.status != "scheduled" or deal.start_date != today + timedelta(days=1):
            return None
        c.due = _start_of(deal.start_date)
        return c
    # deal_confirmed: 아직 공사 날짜를 내지 않았을 때만
    pending = await s.scalar(
        select(exists().where(DateProposal.deal_id == deal.id, DateProposal.status == "pending"))
    )
    if deal.status != "confirmed" or pending:
        return None
    c.due = deal.dates_due_at
    return c


async def _project_ctx(s: AsyncSession, ref: uuid.UUID, user_id: uuid.UUID) -> Ctx | None:
    """표준견적서 뒤 담기 없음: 잠기지 않았고(요청 전) 담은 업체 · 요청이 하나도 없을 때만."""
    from app.project.models import Project
    from app.visit.models import Shortlist, Visit

    p = await s.get(Project, ref, populate_existing=True)
    if p is None or p.owner_id != user_id or p.locked_at is not None:
        return None
    picked = await s.scalar(
        select(
            exists().where(Shortlist.project_id == p.id) | exists().where(Visit.project_id == p.id)
        )
    )
    if picked:
        return None
    return Ctx(project_id=p.id, names={"area": p.sgg, "trade": "도배", "trade_code": "dobae"})


async def context(
    s: AsyncSession, n: AssistantNudge, now: datetime, *, check: bool = False
) -> Ctx | None:
    """제안 대상의 지금 상태. 상태가 바뀌었거나(상태가 그대로일 때만 보낸다) 대상이 없으면 None.
    check(정리): 상태가 그대로인지만 가볍게 본다. 기한 · 이름 사실 · 근원 알림 읽음은 읽지 않고, 업체 빠짐 줄은 이을
    업체가 잠깐 없어도(추천 계산) 닫지 않는다(아무것도 안 했는데 '완료'로 보이지 않게)."""
    from app.notify.models import Notification

    t = TRIGGERS[n.trigger]
    today = now.astimezone(SEOUL).date()
    if t.name in ("visit_offered", "quote_sent", "visit_requested", "visit_picked"):
        c = await _visit_ctx(s, t, n.ref_id, n.user_id, today, check)
    elif t.name in ("dates_proposed", "work_eve", "deal_confirmed"):
        c = await _deal_ctx(s, t, n.ref_id, n.user_id, today)
    elif t.name in aftercare.NAMES:
        c = await aftercare.context(s, t, n, now, check=check)
    else:
        c = await _project_ctx(s, n.ref_id, n.user_id)
    if c is None or check:
        return c
    src = UUID_RE.search(n.dedup_key) if n.dedup_key.startswith("ev:") else None
    if src is not None:
        read_at = await s.scalar(
            select(Notification.read_at).where(
                Notification.id == uuid.UUID(src.group(0)), Notification.user_id == n.user_id
            )
        )
        c.read = read_at is not None
    return c


# ---- 아웃박스 · 시간 ----


async def _resolve(s: AsyncSession, kind: str, dedup_key: str) -> uuid.UUID | None:
    """알림의 dedup_key 첫 id → 제안 대상 id(견적서는 그 실측 요청)."""
    from app.quote.models import VendorQuote

    m = UUID_RE.search(dedup_key or "")
    if m is None:
        return None
    ref = uuid.UUID(m.group(0))
    if kind in ("quote_sent", "quote_resent"):
        return await s.scalar(select(VendorQuote.visit_id).where(VendorQuote.id == ref))
    if kind in aftercare.RESOLVE:  # 공사 끝(이력) · 날짜 요청(요청) → 그 확정
        return await aftercare.resolve(s, kind, ref)
    return ref


async def scan_events(now: datetime, limit: int = BATCH) -> int:
    """상태 전이 알림(아웃박스) → 기다리는 feed 제안. 만든 줄 수(대상이 없어 expired로 남긴 줄 포함)."""
    from app.notify.models import Notification

    key = literal("ev:") + cast(Notification.id, String)
    made = 0
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(
                    Notification.id,
                    Notification.user_id,
                    Notification.kind,
                    Notification.dedup_key,
                    Notification.project_id,
                )
                .where(
                    Notification.kind.in_(list(EVENT_KINDS)),
                    Notification.created_at >= now - LOOKBACK,
                    ~exists().where(
                        AssistantNudge.user_id == Notification.user_id,
                        AssistantNudge.dedup_key == key,
                    ),
                )
                .order_by(Notification.created_at)
                .limit(limit)
            )
        ).all()
        for nid, user_id, kind, dedup, pid in rows:
            t = TRIGGERS[EVENT_KINDS[kind]]
            ref = await _resolve(s, kind, dedup)
            made += await repo.insert_nudge(
                s,
                user_id=user_id,
                surface=t.surface,
                project_id=pid if t.surface == "customer" else None,
                trigger=t.name,
                ref_id=ref or nid,
                dedup_key=f"ev:{nid}",
                channel="notify" if kind in t.notify_kinds else t.channel,
                status="pending" if ref else "expired",
                reason=None if ref else "gone",
                due_at=now,
            )
        await s.commit()
    return made


async def scan_time(now: datetime) -> int:
    """매시간: 공사 시작 전날 · 표준견적서 뒤 담기 없음 · 무응답 알림 제안을 만든다. 만든 줄 수."""
    from app.project.models import Project
    from app.quote.models import StandardQuote
    from app.schedule.models import DateProposal, Deal

    today = now.astimezone(SEOUL).date()
    tomorrow = today + timedelta(days=1)
    made = 0
    async with SessionLocal() as s:
        # 공사 시작 전날 10시(지났으면 지금)
        eve = max(now, datetime.combine(today, WORK_EVE_AT, SEOUL))
        rows = (
            await s.execute(
                select(Deal.id, Deal.project_id, Project.owner_id)
                .join(Project, Project.id == Deal.project_id)
                .where(Deal.status == "scheduled", Deal.start_date == tomorrow)
            )
        ).all()
        for did, pid, owner in rows:
            made += await repo.insert_nudge(
                s,
                user_id=owner,
                surface="customer",
                project_id=pid,
                trigger="work_eve",
                ref_id=did,
                dedup_key=f"work_eve:{did}:{tomorrow.isoformat()}",
                channel="notify",
                due_at=eve,
            )
        # 표준견적서 뒤 3일 담기 없음(공사마다 한 번)
        first = (
            select(StandardQuote.project_id, func.min(StandardQuote.created_at).label("at"))
            .group_by(StandardQuote.project_id)
            .subquery()
        )
        rows = (
            await s.execute(
                select(Project.id, Project.owner_id)
                .join(first, first.c.project_id == Project.id)
                .where(
                    first.c.at <= now - NO_PICK_AFTER,
                    first.c.at >= now - NO_PICK_SINCE,
                    Project.locked_at.is_(None),
                )
            )
        ).all()
        for pid, owner in rows:
            made += await repo.insert_nudge(
                s,
                user_id=owner,
                surface="customer",
                project_id=pid,
                trigger="no_pick",
                ref_id=pid,
                dedup_key=f"no_pick:{pid}",
                channel="notify",
                due_at=now,
            )
        # 무응답: 보낸 feed 뒤 정한 시간 동안 상태가 그대로면 알림(상태는 보낼 때 다시 본다)
        follows = [t.name for t in TRIGGERS.values() if t.follow is not None]
        late = AssistantNudge.__table__.alias("late")
        rows = (
            await s.execute(
                select(AssistantNudge).where(
                    AssistantNudge.trigger.in_(follows),
                    AssistantNudge.channel == "feed",
                    AssistantNudge.status.in_(repo.SHOWN),
                    AssistantNudge.sent_at <= now - FOLLOW_MIN,
                    # 무응답 알림이 밤 · 상한으로 대화 줄이 된 것(규칙 quiet)에는 또 무응답 알림을 만들지 않는다
                    ~AssistantNudge.dedup_key.endswith(":notify"),
                    ~exists().where(
                        and_(
                            late.c.user_id == AssistantNudge.user_id,
                            late.c.dedup_key == AssistantNudge.dedup_key + ":notify",
                        )
                    ),
                )
            )
        ).scalars()
        for n in list(rows):
            wait = TRIGGERS[n.trigger].follow or FOLLOW_MIN
            if n.trigger == "dates_proposed":
                kind = await s.scalar(select(DateProposal.kind).where(DateProposal.id == n.ref_id))
                wait = timedelta(days=1) if kind == "change" else wait
            if n.sent_at is None or now - n.sent_at < wait:
                continue
            made += await repo.insert_nudge(
                s,
                user_id=n.user_id,
                surface=n.surface,
                project_id=n.project_id,
                trigger=n.trigger,
                ref_id=n.ref_id,
                dedup_key=f"{n.dedup_key}:notify"[:80],
                channel="notify",
                due_at=now,
            )
        made += await aftercare.scan_time(s, now)  # 07: 공사 1주 전 · 견적서 기한 하루 전
        await s.commit()
    return made


# ---- 평가 · 보내기 ----


def _day_start(now: datetime) -> datetime:
    return _start_of(now.astimezone(SEOUL).date())


async def evaluate_due(
    now: datetime, limit: int = BATCH, *, until: float | None = None
) -> Counter[str]:
    """기한이 된 기다리는 제안을 평가해 보낸다 · 미룬다 · 기록만 한다 · 닫는다. 결과 이름 → 수.
    worker 차례(60초) 안에 끝나게 EVAL_SECONDS가 지나거나 until(sweep이 정한 멈출 때, time.monotonic 값)이 지나면
    멈추고 남은 줄은 다음 차례에 본다."""
    started = time_mod.monotonic()
    stop = started + EVAL_SECONDS if until is None else min(until, started + EVAL_SECONDS)
    async with SessionLocal() as s:
        due = await repo.due_nudges(s, now, limit)
    tally: Counter[str] = Counter()
    for n in due:
        if time_mod.monotonic() > stop:
            tally["later"] += 1
            continue
        try:
            tally[await _evaluate(n, now)] += 1
        except Exception as e:  # noqa: BLE001 - 제안 하나의 실패가 다른 제안을 막지 않게(종류 이름만 로그)
            log.warning("먼저 말 걸기 평가 실패 (%s, %s)", n.trigger, type(e).__name__)
            tally["error"] += 1
            try:  # 같은 줄을 2분마다 끝없이 다시 보지 않게 까닭을 남기고 닫는다(사라지는 실패 막기)
                await _close(n, "expired", "error")
            except Exception as e2:  # noqa: BLE001 - DB까지 안 되면 다음 차례에 다시 본다
                log.warning("먼저 말 걸기 실패 기록 실패 (%s)", type(e2).__name__)
    return tally


SETTLE_BATCH = 200  # 정리 한 번에 보는 보이는 줄 수


async def _settle_rows(s: AsyncSession, limit: int) -> list[AssistantNudge]:
    """정리가 볼 보이는 줄: 새로 보낸 줄(새것부터, 넷 중 하나) + 오래 안 본 줄부터(due_at 순) 나머지. 보이는 줄의
    due_at은 정리가 마지막으로 본 때라 창보다 줄이 많아도 옛 줄까지 돌아가며 본다(새것 200만 보던 창)."""
    shown = AssistantNudge.status.in_(repo.SHOWN)
    new = list(
        (
            await s.scalars(
                select(AssistantNudge)
                .where(shown)
                .order_by(AssistantNudge.sent_at.desc())
                .limit(min(limit, max(1, limit // 4)))
            )
        ).all()
    )
    old = (
        await s.scalars(
            select(AssistantNudge)
            .where(shown, AssistantNudge.id.not_in([n.id for n in new]))
            .order_by(AssistantNudge.due_at, AssistantNudge.id)
            .limit(max(0, limit - len(new)))
        )
    ).all()
    return [*new, *old]


async def close_settled(
    now: datetime, limit: int = SETTLE_BATCH, *, until: float | None = None
) -> int:
    """정리(2분): 보이는 먼저 말 건 줄(sent · opened) 중 할 일이 끝난 줄을 닫는다. 달린 승인 카드가 실행됐으면
    acted, 대상 상태가 바뀌었으면(context 없음: 승인 카드가 없는 업체 추천 · 견적 도착 줄도) handled. 닫은 줄 수.
    (승인으로 실행한 행동은 actions.execute가 바로 닫는다. 이것은 화면 단추 · 상대 응답 · 시간으로 바뀐 줄을 닫는다)
    상태는 가볍게(context check) 보고, 본 줄은 줄 뒤로 보낸다(due_at = now). until(sweep이 정한 멈출 때,
    time.monotonic 값, 없으면 지금부터 SETTLE_SECONDS)이 지나면 멈추고 남은 줄은 다음 차례에 본다.
    닫은 줄은 대화 기록에 '완료'로 남고, commit 뒤 그 사람에게 화면 신호(state)를 보낸다."""
    from app.assistant.models import AssistantAction

    stop = time_mod.monotonic() + SETTLE_SECONDS if until is None else until
    closed: list[AssistantNudge] = []
    seen: list[uuid.UUID] = []
    if time_mod.monotonic() > stop:
        return 0
    async with SessionLocal() as s:
        rows = await _settle_rows(s, limit)
        ids = [n.action_id for n in rows if n.action_id is not None]
        ran = (
            set(
                await s.scalars(
                    select(AssistantAction.id).where(
                        AssistantAction.id.in_(ids), AssistantAction.status == "executed"
                    )
                )
            )
            if ids
            else set()
        )
        for n in rows:
            # 시간 예산: 남은 줄은 다음 차례(아직 안 본 줄이라 앞에 선다)
            if time_mod.monotonic() > stop:
                break
            try:
                if n.action_id in ran:
                    reason = "acted"
                elif await context(s, n, now, check=True) is None:
                    reason = "handled"
                else:
                    seen.append(n.id)
                    continue
            except Exception as e:  # noqa: BLE001 - 줄 하나를 못 읽어도 다른 줄은 정리한다(종류 이름만 로그)
                log.warning("먼저 말 건 줄 정리 실패 (%s, %s)", n.trigger, type(e).__name__)
                seen.append(n.id)
                continue
            if await repo.set_nudge(s, n.id, repo.SHOWN, status="expired", reason=reason):
                closed.append(n)
        if seen:  # 본 줄은 줄 뒤로: 다음 차례는 오래 안 본 줄부터
            await s.execute(
                update(AssistantNudge)
                .where(AssistantNudge.id.in_(seen), AssistantNudge.status.in_(repo.SHOWN))
                .values(due_at=now)
            )
        await s.commit()
    for n in closed:  # 열어 둔 대화가 그 줄을 '완료'로 다시 그리게(commit 뒤)
        await _signal(n, TRIGGERS[n.trigger], unread=False)
    return len(closed)


NEWS_DAYS = timedelta(days=2)  # 끝난 일 소식 정리가 보는 안 읽은 알림 기간
NEWS_BATCH = 500


async def settle_news(now: datetime) -> int:
    """정리(2분): 끝난 일의 종 알림을 읽음으로 한다(QA r6 c1 #11 · r5 A5 · r4 s6: 고른 뒤의 '날짜를 골라 주세요',
    취소한 요청의 '실측이 정해졌어요'가 '새'로 남음). 끝난 일은 보드 '새 소식'에서 빼는 기준(repo.settled_events)과
    같다. 최근 NEWS_DAYS 안 읽은 알림만 보고, commit 뒤 바뀐 사람에게 안 읽은 수를 보낸다. 읽음으로 바꾼 수."""
    from app.notify import service as notify_service

    async with SessionLocal() as s:
        mine: dict[uuid.UUID, list[uuid.UUID]] = {}
        for nid, uid in await notify_service.unread_since(s, now - NEWS_DAYS, NEWS_BATCH):
            mine.setdefault(uid, []).append(nid)
        done: dict[uuid.UUID, set[uuid.UUID]] = {}
        for uid, ids in mine.items():
            if got := await repo.settled_events(s, uid, ids):
                done[uid] = got
        n = await notify_service.mark_read_ids(s, [i for ids in done.values() for i in ids], now)
        await s.commit()
        if n:
            try:
                await notify_service.push_unread(s, list(done))
            except Exception as e:  # noqa: BLE001 - 신호는 지워져도 되는 것(화면은 다시 읽어 맞춘다)
                log.warning("끝난 일 소식 신호 실패 (%s)", type(e).__name__)
    return n


async def _close(n: AssistantNudge, status: str, reason: str, **values) -> None:
    async with SessionLocal() as s:
        await repo.set_nudge(s, n.id, ["pending"], status=status, reason=reason, **values)
        await s.commit()


async def _evaluate(n: AssistantNudge, now: datetime) -> str:
    t = TRIGGERS[n.trigger]
    async with SessionLocal() as s:  # 사실 읽기(짧게). LLM은 이 세션 밖에서 부른다
        c = await context(s, n, now)
        if c is None:
            await repo.set_nudge(s, n.id, ["pending"], status="expired", reason="gone")
            await s.commit()
            return "expired"
        gone = await repo.dismissals(s, n.user_id, now - DISMISS_SEEN)
        sent_today = await repo.sent_count(s, n.user_id, _day_start(now), "notify")
        sent_24h = await repo.sent_count(s, n.user_id, now - timedelta(hours=24))
    dismissals = [policy.Dismissal(trigger, at, ref) for trigger, at, ref in gone]
    # 새 소식은 다른 대상의 같은 종류 줄을 닫은 쉬기(−30 · 3일)에 걸리지 않는다(같은 대상을 닫았으면 쉰다).
    # 두 번 닫아 멈춘 종 알림은 그대로 지킨다
    fresh = fresh_event(t, n)
    rule = RULES.check(
        trigger=t.name,
        channel=n.channel,
        surface=n.surface,
        now=now,
        sent_today=sent_today,
        dismissals=dismissals,
        due=c.due,
        snooze_ref=n.ref_id if fresh else None,
    )
    if rule.verdict == "hold":
        await _close(n, "held", rule.reason or "rule")
        return "held"
    if rule.verdict == "defer":
        async with SessionLocal() as s:
            await repo.set_nudge(s, n.id, ["pending"], due_at=rule.until, reason=rule.reason)
            await s.commit()
        return "deferred"
    # 미루면 기한이 지나요(밤 · 상한에 걸린 공사 전날 알림): 종 알림 대신 조용한 대화 줄로 지금 보낸다
    channel = "feed" if rule.verdict == "quiet" else n.channel
    f = Facts(
        trigger=t.name,
        channel=channel,
        surface=n.surface,
        hours_left=(c.due - now).total_seconds() / 3600 if c.due else None,
        action_ready=t.action,
        decision=t.decision,
        read=c.read,
        sent_24h=0 if no_24h_penalty(t, n) else sent_24h,
        dismissed_same=any(
            d.trigger == t.name and (not fresh or d.ref == n.ref_id) and now - d.at < SNOOZE_SEEN
            for d in dismissals
        ),
        names=c.names,
    )
    points = score(f)
    if not news(t, n):  # 사건 알림은 점수 · 판정 없이 보낸다(점수는 기록만)
        if points < JUDGE_AT:
            await _close(n, "held", "low", score=points)
            return "held"
        if points < SEND_AT:
            yes = await judge(f, n.user_id)
            if yes is None:
                yes = channel == "feed"  # 판정을 못 하면 조용한 줄만 보낸다
            if not yes:
                await _close(n, "held", "judge", score=points)
                return "held"
    text, src = await write(f, n.user_id)
    return await _send(n, t, c, now, text, src, points, channel)


async def _rang(s: AsyncSession, n: AssistantNudge, t: Trigger) -> bool:
    """이 줄의 근원 알림이 이미 종을 울린 사건(t.notify_kinds: 자동 끝 3일 전 done_remind)인지. 그러면 비서 알림을
    더하지 않는다(같은 사건 종 알림이 1분 사이 두 번 가던 것)."""
    from app.notify.models import Notification

    src = UUID_RE.search(n.dedup_key) if t.notify_kinds and n.dedup_key.startswith("ev:") else None
    if src is None:
        return False
    kind = await s.scalar(
        select(Notification.kind).where(
            Notification.id == uuid.UUID(src.group(0)), Notification.user_id == n.user_id
        )
    )
    return kind in t.notify_kinds


async def _send(
    n: AssistantNudge,
    t: Trigger,
    c: Ctx,
    now: datetime,
    text: str,
    src: str,
    points: int,
    channel: str | None = None,
) -> str:
    """카드 · 승인 카드 · (알림) · 상태 바꾸기를 한 트랜잭션으로. 보낸 뒤 화면 신호.
    판정 · 문장(LLM)을 기다리는 사이 상태가 바뀌었을 수 있어 보내기 직전 상태를 다시 보고, 바뀌었으면 보내지 않고
    닫는다(gone). channel은 이번에 보낼 채널(규칙이 알림을 조용한 대화 줄로 바꿨으면 feed)."""
    from app.auth.models import User
    from app.notify import service as notify_service
    from app.shared.errors import AppError

    channel = channel or n.channel
    async with SessionLocal() as s:
        user = await s.get(User, n.user_id)
        if user is None:
            return "expired"
        fresh = await context(s, n, now)
        if fresh is None:
            await repo.set_nudge(s, n.id, ["pending"], status="expired", reason="gone")
            await s.commit()
            return "expired"
        c = fresh
        refs = None
        try:
            refs = await _chat_refs(s, n)
            card, action_id = await _build(s, t, n, user, c, now, refs)
        except Exception as e:  # noqa: BLE001 - 카드 · 승인 카드를 못 만들어도 문장은 보낸다(종류 이름만 로그)
            if not isinstance(e, AppError):
                log.warning("먼저 말 걸기 카드 실패 (%s, %s)", n.trigger, type(e).__name__)
            await s.rollback()
            card, action_id, refs = None, None, None
        if n.surface == "vendor":
            # 업체 쪽 틀은 카드를 만든 뒤 사실(고객이 바란 날이 겹침 · 후보 없음)로 채운다
            if card is None and action_id is None:
                c.names.setdefault("next", NO_CARD_NEXT)
            text = template(Facts(t.name, channel, n.surface, names=c.names))
        got = await repo.set_nudge(
            s,
            n.id,
            ["pending"],
            status="sent",
            sent_at=now,
            body=text[:200],
            src=src,
            score=points,
            reason=None,
            card=card,
            action_id=action_id,
            channel=channel,
        )
        if got is None:  # 다른 평가가 먼저 바꿨다
            await s.rollback()
            return "raced"
        await repo.replace_shown(s, n.user_id, n.ref_id, n.id)
        if t.name == "quote_sent" and n.project_id is not None:
            # 같은 공사의 견적서 줄은 새 줄 하나로(새 줄의 비교 카드가 받은 견적서를 모두 견줘요)
            await s.execute(
                update(AssistantNudge)
                .where(
                    AssistantNudge.user_id == n.user_id,
                    AssistantNudge.project_id == n.project_id,
                    AssistantNudge.trigger == "quote_sent",
                    AssistantNudge.id != n.id,
                    AssistantNudge.status.in_(repo.SHOWN),
                )
                .values(status="expired", reason="replaced")
            )
        ring = channel == "notify" and not await _rang(s, n, t)
        if ring:
            await notify_service.add(
                s,
                user_id=n.user_id,
                kind=NOTIFY_KIND,
                body=text,
                link=_link(t, n),
                dedup_key=f"nudge:{n.id}",
                project_id=n.project_id,
            )
        await s.commit()
    if refs is not None and card is not None:
        await refs.save()  # 카드 이름표를 대화 표에 넣는다(commit 뒤: 대화 행이 남은 다음)
    await _signal(n, t, unread=ring)
    return "sent"


async def _chat_refs(s: AsyncSession, n: AssistantNudge):
    """보낼 카드의 이름표 표: 그 사람 비서 대화의 표(없으면 대화를 만든다). 카드 단추를 누르면 대화가 같은 이름표를
    알아 그 대상으로 승인 카드를 만든다(따로 만든 표면 단추가 버려지거나 같은 번호의 다른 대상으로 갔다)."""
    from app.assistant.runtime import RefTable
    from app.assistant.service import ensure_chat

    chat = await ensure_chat(s, n.user_id, n.project_id if n.surface == "customer" else None)
    return await RefTable.load(chat.id)


def _link(t: Trigger, n: AssistantNudge) -> str:
    if n.surface == "customer":
        return f"/projects/{n.project_id}"
    if got := aftercare.link(t.name, n.ref_id):
        return got
    if t.name == "deal_confirmed":
        return f"/vendor/jobs/{n.ref_id}"
    return f"/vendor/requests/{n.ref_id}"


async def _signal(n: AssistantNudge, t: Trigger, *, unread: bool) -> None:
    """commit 뒤 화면 신호: 대화 기록을 다시 읽게(state, 그 공사 · 업체는 공사 없음), 종 알림을 더했으면(unread) 안
    읽은 수(notif). 보낼 때와 할 일이 끝나 닫을 때(unread=False) 보낸다. 실패해도 바꾼 것은 그대로(화면은 다음에 다시
    읽어 맞춘다)."""
    from app.notify import service as notify_service
    from app.realtime import service as realtime

    try:
        await realtime.push_state([n.user_id], t.state, n.ref_id, n.project_id)  # type: ignore[arg-type]
        if unread:
            async with SessionLocal() as s:
                await notify_service.push_unread(s, [n.user_id])
    except Exception as e:  # noqa: BLE001 - 신호는 지워져도 되는 것(화면은 다시 읽어 맞춘다)
        log.warning("먼저 말 걸기 신호 실패 (%s)", type(e).__name__)


async def _build(
    s: AsyncSession, t: Trigger, n: AssistantNudge, user, c: Ctx, now: datetime, refs
) -> tuple[dict | None, uuid.UUID | None]:
    """보낼 때 카드(CardOut JSON 통째) · 승인 카드(origin nudge, 같은 트랜잭션). 못 만들면 (None, None).
    이름표는 그 사람 비서 대화의 표(refs)에 넣는다: 카드 단추(vendor_confirm:m… 등)를 대화가 안다. 표는 commit 뒤
    _send가 저장한다. 표가 지워진 뒤 누르면 choices가 카드를 새로 불러온다."""
    from app.assistant import actions, memory
    from app.assistant.tools import ToolError, cards, propose
    from app.assistant.tools import vendor as vendor_tools
    from app.schedule import service as schedule_service
    from app.visit import service as visit_service

    today = now.astimezone(SEOUL).date()
    pid = n.project_id
    card = None
    offer: dict | None = None
    try:
        # 07 자동화: 카드(둘이면 목록) · 승인 카드를 aftercare가 만든다
        if t.name in aftercare.NAMES:
            return await aftercare.build(s, t, n, user, c, now, refs)
        if t.name == "visit_offered":
            prefer, days = memory.prefs(await repo.memories(s, user.id))
            card, _ = await cards.visit_slots(
                s, user, pid, n.ref_id, now, refs, prefer=prefer, days=days
            )
            # 같은 공사의 다른 업체 실측과 같은 반나절은 미리 고르지 않아요(두 업체가 같은 때 오지 않게)
            taken = await _taken_halves(s, user.id, pid, n.ref_id)
            cands = card.data.get("candidates") or []
            first = next((x for x in cands if (x["day"], x["half"]) not in taken), None)
            if first is not None:
                v = await visit_service.pick_view(s, user, pid, n.ref_id, now)
                offer = propose.slot_offer(v, refs.get(first["ref"], "slot"))
        elif t.name == "quote_sent":
            trade = c.names.get("trade_code", "dobae")
            card, _ = await cards.compare(s, user, pid, trade, today, refs)
        elif t.name == "dates_proposed":
            card, _ = await cards.schedule(s, user, pid, today, refs)
            sch = await schedule_service.schedule_for(s, user, pid, today)
            row = next((x for x in sch.trades if x.proposal and x.proposal.id == n.ref_id), None)
            if row is not None:
                kind = propose.dates_kind(row.deal.status)
                offer = propose.dates_offer(sch, str(n.ref_id), kind, now)
        elif t.name == "work_eve":
            # 공정 준비물(이 집에 맞춤) + 반셀프 직접 할 일(오늘까지 · 끝냈는지 · 공사 뒤)
            from app.assistant.tools import diy as diy_tools

            home = await diy_tools.home_ctx(s, user, pid, today) if pid else None
            card = cards.prep_card(f"prep-{n.ref_id}", [c.names.get("trade_code", "dobae")], home)
            card = await diy_tools.eve_card(s, user, pid, today, card)
        elif t.name == "no_pick":
            card, _ = await cards.vendor_picks(s, user, pid, "dobae", refs)
            if not card.data.get("picks"):
                card = None
        elif t.name in ("visit_requested", "visit_picked"):
            card, _, _, made, _ = await vendor_tools.brief(
                s, user, n.ref_id, today, now, refs, commit=False, origin="nudge"
            )
            live = [a for a in made if a.status == "proposed"]
            return card.model_dump(mode="json"), live[0].action_id if live else None
        elif t.name == "deal_confirmed":
            job = await schedule_service.job_for(s, user, n.ref_id, today)
            # 같은 업체의 다른 공사에 열린(아직 안 누른) 공사 날짜 카드가 잡은 날도 피한다(QA 3차 c6: 12.15 이중 예약)
            held = await vendor_tools.held_days(s, user.id, n.ref_id, now)
            cands = vendor_tools.date_candidates(job, n.ref_id, today, held=held)
            if cands and job.dates_state in ("waiting", "requested"):
                offer = propose.vendor_dates_offer(job, n.ref_id, cands[0], now)
    except ToolError:
        offer = None
    action_id = None
    if offer is not None:
        # 같은 대상 · 같은 종류의 열린 카드(대화에서 만든 것 포함)가 있으면 그 행을 쓰고, 거절한 같은 제안은 다시
        # 만들지 않는다(actions.offer). 카드는 단 승인 카드와 맞춘다
        row, _ = await actions.propose(
            s,
            user,
            surface=n.surface,
            now=now,
            turn_id=None,
            origin="nudge",
            project_id=pid,
            **offer,
        )
        action_id = row.id if row.status == "proposed" else None
        if action_id is not None and card is not None:
            _pin(card, row)
    return (card.model_dump(mode="json") if card is not None else None), action_id


async def _taken_halves(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None, visit_id: uuid.UUID
) -> set[tuple[str, str]]:
    """같은 공사의 다른 실측이 잡은 반나절(확정 · 업체 수락 기다림)과 열린 실측 시간 승인 카드가 고른 반나절
    ('YYYY-MM-DD', am · pm). 먼저 말 걸기가 같은 반나절을 미리 고르지 않게 본다. 읽기 조인."""
    from app.visit.models import Visit, VisitHold

    if project_id is None:
        return set()
    held = await s.execute(
        select(VisitHold.day, VisitHold.half)
        .join(Visit, Visit.id == VisitHold.visit_id)
        .where(Visit.project_id == project_id, Visit.id != visit_id, VisitHold.status == "active")
    )
    out = {(d.isoformat(), h) for d, h in held}
    opened = await repo.open_slot_halves(s, user_id, project_id, visit_id)  # 대화 도구와 같은 셈
    return out | {(d.isoformat(), h) for d, h in opened}


def _pin(card, row) -> None:
    """보낼 카드를 단 승인 카드와 맞춘다: 반나절 후보는 승인 카드의 반나절을 고른 것(chosen)으로, 공사 날짜 카드는
    수락 단추를 승인 카드 하나로(카드 단추 proposal_ref · proposal_kind를 비우고 action_id)."""
    pl = row.payload or {}
    if card.kind == "visit_slots":
        hit = next(
            (
                c["ref"]
                for c in card.data.get("candidates") or []
                if (c.get("day"), c.get("half")) == (pl.get("day"), pl.get("half"))
            ),
            None,
        )
        card.data = {**card.data, "chosen": hit}
    elif card.kind == "schedule" and card.data.get("phase") == "dates":
        card.data = {
            **card.data,
            "proposal_ref": None,
            "proposal_kind": None,
            "action_id": str(row.id),
        }


# ---- 대화 기록 · 다음에 물을 말 ----


def suggest_of(n: AssistantNudge) -> dict:
    """보낸 제안 → 다음에 물을 말 하나(SuggestOut 꼴). 한 줄은 할 일을 묻는 말(ask)이라 바로 위 먼저 말 건 문장을
    되풀이하지 않는다."""
    t = TRIGGERS[n.trigger]
    return {
        "id": f"n-{n.id}",
        "text": t.ask or n.body or t.why,
        "why": t.why,
        "say": t.say,
        "nudge_id": n.id,
    }
