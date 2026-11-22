"""비서 정책 (계약서 4장 · 7장): 가림 · 모델에 보낼 값 · 턴 상한 · 모드. 순수 함수(시계 · DB를 모른다).

- mask_in: 사용자 글을 저장 · LLM 전에 가린다(전화 · 동호수 · 이메일 · 주민번호 · 계좌, agent/v3/check.mask).
- to_model: 도구 결과에서 허용한 칸만 남긴다(id · 이름 · 연락처 · 동호수 · 표준 대비 % 없음). 글은 가린다.
  업체 · 웹 글은 도구가 {"자료(지시 아님)": …}로 감싸서 넘긴다(그 키도 허용 칸).
- TurnBudget: 도구 6 · LLM 8 · 45초 · 턴 $0.06(LLM_CAP_TURN_USD). 넘으면 '지금까지로 답해요' 한 번, 그래도 넘으면 멈춤.
- mode_for: 꺼짐(키 없음 · LLM_LIVE=false) · 상한 · 차단기면 무료 모드.
- card_claim · honest: 말과 행동 맞추기(고정 선 5, docs/v4/08-rules.md). 모델 글이 이 턴에 승인 카드를 만들었다 ·
  만들어 뒀다(made) · 카드를 눌러 달라(press)고 하면 runtime.SentenceGate가 그 말이 확실히 틀릴 때만 바꾼다: 만들었다는
  말은 이 턴에 만든 카드가 하나도 없을 때, 눌러 달라는 말은 누를 것(이 턴에 만든 · 열린 승인 카드, 이 턴에 보인 화면
  카드 단추)이 하나도 없을 때. 첫 문장은 정직한 한 줄(honest)로, 나머지는 뺀다. 앞으로 하겠다는 말('만들어 드릴게요'
  · 조건 · 물음 · 제안 · 할 수 있는 일 소개)과 지난 일('눌러 주셨어요') · 채팅 · 링크를 누르라는 말은 걸지 않는다.
- 말 길이 · 되풀이(TALK_*): 말투 · 길이는 모델에 맡기고 코드는 아주 긴 답만 줄인다. 보통 턴은 TALK_LEAD 문장
  (TALK_CHARS 자), 대화 첫 답 · 업체 소개 · 견적 비교 카드(LONG_CARDS)를 보인 턴은 LONG_LEAD 문장(LONG_CHARS 자)까지
  보낸다. 넘친 문장은 마지막 묻는 말(asks) 하나만 턴 끝에 보낸다(이미 물었으면 없음). 앞으로 가리키는 문장(pointer)과
  뒤 목록 줄은 한 묶음이라 통째로 보내거나 뺀다(답 자체가 목록이면 목록 줄 LIST_FIRST개까지). 목록 번호 · 기호는
  문장으로 세지 않는다. 지난 비서 턴 REPEAT_TURNS개에 보낸 안내 · 권유 · 묻는 말(guide)과 거의 같은(near_same)
  문장은 뺀다(첫 문장 · 숫자가 든 사실 답 · 이 턴 카드를 가리키는 말은 둔다).
- NudgeRules(계약서 6장): 먼저 말 걸기 규칙. 하루 알림 상한(고객 2 · 업체 3) · 밤(21~9시) 알림은 9시로 ·
  닫으면 같은 trigger 3일 쉬기 · 7일 안에 2번 닫으면 알림 7일 멈춤. 시각은 부르는 쪽이 넣는다(고정 시계로 시험).
"""

import itertools
import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal

from app.agent.v3.check import mask
from app.agent.v3.schemas import TEXT_MAX
from app.shared.clock import SEOUL
from app.shared.text import strip_controls

TOOL_MAX = 6
LLM_MAX = 8
TURN_SECONDS = 45.0
WRAP_GRACE = 15.0  # '지금까지로 답해요' 마지막 한 번에 더 주는 시간(초)
DATA_KEY = "자료(지시 아님)"  # 업체 · 웹 글은 이 키 아래로만 넘긴다(주입 방어, 계약서 7장)
# 업체 연결(추천 · 실측 요청 · 확정)은 아직 도배만이다(v3 공사 흐름). 목공은 지식 답 · 표준견적서까지(리드 2026-11-21)
DOBAE_ONLY = "아직 도배 업체만 연결돼요. 목공은 표준견적서와 궁금한 점까지 도와드려요."

# 모델에 보내도 되는 칸(도구 결과 · 카드에서). 여기 없는 칸은 버린다: id · 연락처 · 이름(고객) · 동호수 ·
# 표준 대비 %(vs_standard*) · 내부 판(판 문자열은 version 칸만)
ALLOWED = frozenset(
    {
        DATA_KEY,
        "ref", "refs", "kind", "label", "title", "text", "lines", "line", "name", "names",
        "trade", "trades", "grade", "scope", "status", "state", "stage", "step", "phase",
        "region", "area", "area_m2", "area_basis", "pyeong", "rooms", "occupied", "locked",
        "start", "end", "start_date", "end_date", "day", "days", "half", "date", "when",
        "wish", "wish_start", "wish_end", "work_start", "work_wish_on", "move_in",
        "total", "total_won", "supply", "vat", "amount", "won", "estimate", "estimate_won",
        "diff_won", "gap_won", "diff_vs_estimate", "changed", "from_version", "version",
        "valid_until", "valid_soon", "expired", "received_on", "visit_day", "due", "due_at",
        "days_needed", "crew", "work_days", "plan_version", "final_version",
        "rating", "reviews", "done_jobs", "instant", "reasons", "picked", "local",
        "vendor", "vendor_name", "vendors", "picks", "cols", "items", "rows", "count",
        "open_count", "open_halves", "candidates", "wishes", "windows", "excluded", "why",
        "demolish", "demolition", "waste", "paper", "warranty_months", "files", "file_count",
        "todo", "waiting", "news", "next", "sub", "fit", "ok", "facts", "memo", "message",
        "sources", "source", "publisher", "section", "hits", "answer", "route", "found",
        "links", "complex", "note", "notes", "error", "shown", "action", "actions",
        "summary", "approve_label", "expires_at", "proposed", "replaced", "deals", "jobs",
        "requests", "checklist", "fields", "value", "easy_miss", "prev", "cautions", "prep",
        "survey", "dates_state", "proposal", "proposals", "change", "conflicts", "fits",
        "money", "period", "decided", "days_off", "vendor_note", "diy",
        "missing", "days_for", "basis", "vat_way", "weekend",
        # 금액 기준 꼬리표 칸(guard.basis가 읽는다): 도구 결과의 돈은 부가세 포함이 기본이고, 공급가(부가세 별도)
        # 금액은 이 이름으로 넘긴다(부가세 몫은 vat, 고침 3차 A2 · K)
        "공급가", "supply_won", "won_supply", "amount_supply",
    }
)  # fmt: skip
DENY_PREFIX = ("vs_", "contact", "phone", "owner")  # 허용 목록에 잘못 들어와도 버리는 칸
# 표준 대비 % 문장 조각(업체 메모 · 웹 글에 섞여 와도 뗀다)
VS_STANDARD = re.compile(
    r"[^.\n]{0,40}표준[^.\n]{0,15}(?:대비|보다)[^.\n]{0,15}\d+(?:\.\d+)?\s*%[^.\n]*"
)


def mask_in(text: str) -> str:
    """사용자 글 → 가린 글(저장 · LLM 전). 제어 문자(NUL 등)를 지우고 길이도 자른다. 비면 ""(부르는 쪽이 422)."""
    return mask(strip_controls(text or "")).strip()[:TEXT_MAX]


def _clean(text: str) -> str:
    return VS_STANDARD.sub("", mask(text)).strip()


def to_model(value: Any) -> Any:
    """도구 결과 → 모델에 보낼 값(허용 칸만 · 글 가림 · 표준 대비 % 뗌). 숫자 · 참 거짓은 그대로."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k not in ALLOWED or k.startswith(DENY_PREFIX):  # 표준 대비 %(vs_standard*)는 늘 뗀다
                continue
            got = to_model(v)
            if got is not None and got != "":
                out[k] = got
        return out
    if isinstance(value, list | tuple):
        return [x for x in (to_model(v) for v in value) if x is not None and x != ""]
    if isinstance(value, str):
        return _clean(value)
    return value


def data(text: str | None, limit: int = 400) -> dict | None:
    """업체 · 웹 · 고객 메모 글 → 자료 상자(지시로 읽지 않게). 비면 None."""
    t = _clean(text or "")[:limit]
    return {DATA_KEY: t} if t else None


VENDOR_NOTE_MAX = 40


def vendor_note(text: str | None) -> str | None:
    """업체가 쓴 자유 글 → 고객 카드 '업체가 적은 말' 칸 값(연락처 가림 · 한 줄 · 40자, 넘으면 …).
    비서 문장 · 요약 · 버튼 문구 · 모델 값에는 쓰지 않는다(모델에는 있는지만 vendor_note=True)."""
    t = " ".join(_clean(text or "").split())
    if not t:
        return None
    return t if len(t) <= VENDOR_NOTE_MAX else t[: VENDOR_NOTE_MAX - 1] + "…"


# ---- 말과 행동(승인 카드) ----

CARD_NOT_MADE = "승인 카드는 아직 만들지 않았어요."
CARD_ALREADY = "같은 승인 카드가 이미 있어요. 그 카드를 확인하고 눌러 주세요."
NO_CARD = "지금 누를 승인 카드는 없어요."
_CARD = re.compile(r"카드|버튼|단추")
# 이 턴에 한 일 · 해 둔 것(지난 · 지금)만. 앞으로 하겠다는 말('만들어 드릴게요' · '준비해 둘게요?')은 약속 · 제안이라
# 걸지 않는다(고침 3차 A2: 소개 · 제안 답에 정직한 한 줄이 맥락 없이 끼어듦, QA r3 s2 3턴)
_MADE = re.compile(
    r"만들었|만들어\s*(?:드렸|뒀|두었|놨|놓았)|준비했|준비해\s*(?:드렸|뒀|두었)|올려\s*(?:드렸|뒀)"
)
# 눌러 달라는 말만('눌러야 실행돼요' · '누르기 전에는 …' 같은 설명, '이미 눌러 주셨어요' 같은 지난 일은 아니다)
_PRESS = re.compile(
    r"눌러\s*(?:주(?:세요|시면|시고|시기|십시오|실래요|시겠어요|셔야|셔도)|줘|"
    r"보(?:세요|시면|시고|실래요|셔도))|누르세요|누르시(?:면|고|기|겠)|누르셔야|클릭해\s*주(?:세요|시면)"
)
# 승인 카드가 아닌 것을 누르라는 말(채팅 열기 · 조사 링크 · 사진)은 카드 말이 아니다
_NOT_CARD = re.compile(r"채팅\s*열기|링크|사진|파일|지도")
_LABEL = re.compile(r"\[[^\]]{1,20}\]")  # 단추 이름('[맞아요, 저장]')
# 말이 가리키는 행동 종류(카드 이름 낱말). 없으면 종류를 가리지 않는다
KIND_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("home_info", re.compile(r"집\s*정보|면적|평형|평수|철거\s*범위|방\s*개수")),
    # '실측 요청을 취소하는 카드'는 실측 요청 카드가 아니라 취소 카드다
    ("visit_request", re.compile(r"실측\s*요청(?!\S{0,3}\s*취소)")),
    ("visit_cancel", re.compile(r"취소")),
    ("visit_slot", re.compile(r"실측\s*(?:시간|날짜|일정)|반나절|시간\s*(?:카드|고르기)")),
    (
        "vendor_confirm",
        re.compile(r"확정\s*(?:카드|승인|단추|버튼)|업체\s*확정|(?:으로|로)\s*확정"),
    ),
    ("dates_accept", re.compile(r"수락")),
    ("delay_accept", re.compile(r"수락")),
    ("date_change", re.compile(r"날짜\s*바꾸기|바꾸기\s*요청|연기\s*요청|미루기")),
    ("window_answer", re.compile(r"기간\s*답|답하기")),
    ("decline", re.compile(r"못\s*받아요")),
    ("dates", re.compile(r"(?:공사\s*)?날짜\s*보내기")),
)
# 단추로 승인 카드를 만드는 화면 카드 → 그 단추가 만드는 행동 종류. 이 턴에 보인 카드의 그 단추를 이름으로 누르라는
# 말('카드에서 수락을 눌러 주세요')은 맞다. 집 정보 카드 단추(철거 범위)는 면적 · 방 고치기 카드가 아니라 넣지 않는다
BUTTONS: dict[str, frozenset[str]] = {
    "vendor_picks": frozenset({"visit_request"}),
    "visit_slots": frozenset({"visit_request", "visit_slot"}),
    "quote_compare": frozenset({"vendor_confirm"}),
    "schedule": frozenset({"dates_accept", "delay_accept"}),
    "vendor_brief": frozenset({"window_answer", "decline"}),
    # [합지로 바꾸기] · [실크로 바꾸기] → 집 정보(벽지) 승인 카드
    "grade_compare": frozenset({"home_info"}),
}


def buttons_of(kind: str, data: dict) -> frozenset[str]:
    """화면 카드 단추가 만드는 행동 종류. 공사 날짜 카드는 수락 단추(proposal_ref)가 있을 때만, 벽지 견주기 카드는
    벽지를 바꿀 수 있을 때(can_change)만."""
    if kind == "schedule" and not data.get("proposal_ref"):
        return frozenset()
    if kind == "grade_compare" and not data.get("can_change"):
        return frozenset()
    return BUTTONS.get(kind, frozenset())


def card_claim(text: str) -> tuple[str, set[str]] | None:
    """승인 카드를 두고 한 말인지: ("made" · "press", 말이 가리키는 행동 종류) 또는 None. 이 턴에 만들었다 · 만들어
    뒀다(made)와 카드 · 단추를 눌러 달라(press)는 말만 본다(고정 선 5: 하지 않은 일을 한 것처럼, 없는 카드를 있는
    것처럼). 채팅 열기 · 링크 · 사진을 누르라는 말은 승인 카드 말이 아니다."""
    t = (text or "").strip()
    kinds = {k for k, rx in KIND_WORDS if rx.search(t)}
    if _MADE.search(t) and _CARD.search(t):
        return "made", kinds
    if (
        _PRESS.search(t)
        and (_CARD.search(t) or _LABEL.search(t) or kinds)
        and not _NOT_CARD.search(t)
    ):
        return "press", kinds
    return None


def claim_ok(
    claim: tuple[str, set[str]],
    made: Collection[str],
    opened: Collection[str],
    buttons: Collection[str] = (),
) -> bool:
    """그 말을 그대로 둘지(확실히 틀릴 때만 False): 만들었다는 말은 이 턴에 만든 승인 카드(made)가 하나라도 있으면
    둔다(종류 낱말이 어긋나도 카드는 화면에 있다). 눌러 달라는 말은 누를 것(이 턴에 만든 · 열린 승인 카드, 이 턴에
    보인 화면 카드 단추)이 하나라도 있으면 둔다."""
    what, _kinds = claim
    if what == "made":
        return bool(made)
    return bool({*made, *opened, *buttons})


def honest(claim: tuple[str, set[str]], opened: set[str]) -> str:
    """확실히 틀린 카드 말 대신 보낼 한 줄(정해 둔 글)."""
    what, kinds = claim
    there = bool(kinds & opened) if kinds else bool(opened)
    if what == "made":
        return CARD_ALREADY if there else CARD_NOT_MADE
    return NO_CARD


# ---- 말 길이 · 되풀이 (말투 · 길이는 모델에 맡기고, 코드는 아주 긴 답 · 지난 턴 안내 되풀이만, 08-rules) ----

TALK_LEAD = 6  # 바로 보내는 문장 수(지시문은 두세 문장: 이보다 긴 답만 줄인다)
TALK_CHARS = 500  # 바로 보낸 글이 이만큼 되면 뒤 문장은 모은다
# 대화 첫 답(소개 · 첫인사) · 업체 소개 · 견적 비교 카드를 보인 턴: 카드를 풀어 말해 길 수 있지만 끝은 있다(고침 3차 A2
# 결정 1, QA r3 c4 #1 525자 · c5 첫 답 14문장)
LONG_LEAD = 8
LONG_CHARS = 700
LIST_FIRST = 8  # 답 자체가 목록(묶음이 첫 문장)이면 상한을 넘어도 보내는 목록 줄 수
REPEAT_TURNS = 3  # 안내 되풀이를 견줄 지난 비서 턴 수
# 업체 소개 · 견적 비교 카드: 이 카드를 보인 턴은 LONG_LEAD까지
LONG_CARDS = frozenset({"vendor_picks", "quote_compare"})
# '다음 할 일' 문장: 누를 카드 · 단추 · 승인 · 고르기 · 채팅
NEXT_STEP = re.compile(
    r"카드|단추|버튼|승인|눌러|누르|수락|골라|고르|채팅|다음\s*할\s*일|할\s*차례"
)
# 고객에게 묻거나 부탁하는 말(넘친 문장 중 마지막 하나는 턴 끝에 보낸다: 빠지면 고객이 무엇을 답할지 모른다)
ASKS = re.compile(r"[?？]\s*$|알려\s*주|말씀해\s*주|정해\s*주|확인해\s*주")
# 권유 · 해 보라는 말('…물어보세요' · '…잘 맞아요' · '권해요')
SUGGEST = re.compile(r"세요[.!~]*\s*$|잘\s*맞아요|권해요|추천해요")
_PLAIN = re.compile(r"[\s.,!?~·:;'\"“”‘’()\[\]<>-]+")
_WORD = re.compile(r"[가-힣A-Za-z0-9]+")
# 뜻을 뒤집는 낱말: 한 낱말 차이여도 다른 말이다('들어 있어요' ≠ '안 들어 있어요')
_FLIP = frozenset(
    {"안", "못", "아니", "아니요", "아니에요", "않아요", "없어요", "말고", "불가능해요"}
)
# 앞으로 가리키는 문장(뒤 목록 · 문장과 한 묶음): ':'로 끝남 · '이래요' · '다음과 같아요' · '아래를' · '이렇게 …세요'
# (고침 3차 A2 결정 3, QA r3 c1 13 · 21턴 · c4 #20 · #35 · c5 11턴). 뒤에 가리킨 것이 없으면 이 문장도 뺀다
POINTER = re.compile(
    r"[:：]\s*$"
    r"|(?:이래요|이렇습니다|다음과\s*같(?:아요|습니다))[.!]?\s*$"
    r"|아래(?:와\s*같|를|처럼|\s*(?:내용|항목))"
    r"|이렇게\s+(?:\S+\s+){0,2}\S*(?:세요|가요)[.!]?\s*$|이렇게\s+보시면\s*돼요"
)
# 수를 말하는 가리킴('이유는 두 가지예요.'): 뒤와 한 묶음이지만, 뒤에 아무것도 없으면 앞 말을 줄인 끝 문장일 수 있어 둔다
COUNTED = re.compile(r"(?:가지|단계)(?:예요|이에요|가\s*있어요|입니다)[.!]?\s*$")


def pointer(text: str) -> bool:
    """앞으로 가리키는 문장인지(뒤 목록 · 문장과 한 묶음)."""
    t = (text or "").strip()
    return bool(POINTER.search(t) or COUNTED.search(t))


# 목록 줄의 머리(기호 · 번호 · 따옴표 예문). 이 머리는 문장으로 세지 않는다(runtime.SENT_END가 '1. '에서 자르지 않음)
LIST_MARK = re.compile(r"^\s*(?:[-•*·▪◦]\s|\d{1,2}[.)]\s|[①-⑳]\s?|[\"“‘'])")
# 앞 문장이 빠져 첫 문장이 된 문장의 첫머리 접속 말(고침 3차 A2 결정 5, QA r3 c4 #33 '다만 …')
LEAD_LINK = re.compile(
    r"^(?:다만|대신|그래서|그리고|또한|또|그런데|하지만|그러나|그러니까|그러니)\s*[,，]?\s+"
)
_DIGIT = re.compile(r"\d")


def next_step(text: str) -> bool:
    """다음 할 일(카드 · 단추 · 승인 · 고르기 · 채팅)을 말하는 문장인지."""
    return bool(NEXT_STEP.search(text or ""))


def asks(text: str) -> bool:
    """고객에게 묻거나(…편하세요?) 부탁하는(알려 주세요) 문장인지."""
    return bool(ASKS.search((text or "").strip()))


def guide(text: str) -> bool:
    """되풀이를 볼 안내 · 권유 · 묻는 말인지(다음 할 일 · 물음 · 해 보라는 말). 숫자가 든 문장은 사실 답이라 아니다."""
    t = (text or "").strip()
    return bool(t) and not _DIGIT.search(t) and (next_step(t) or asks(t) or bool(SUGGEST.search(t)))


def same_line(a: str, b: str) -> bool:
    """두 문장이 완전히 같은지(띄움 · 문장부호만 다름). 한 글자라도 다르면 다른 말이다('포함' ≠ '불포함')."""
    x, y = _PLAIN.sub("", a or ""), _PLAIN.sub("", b or "")
    return bool(x) and x == y


def near_same(a: str, b: str) -> bool:
    """거의 같은 문장인지: 완전히 같거나 낱말 하나만 더하거나 뺀 것('이어서' · '도배'). 바꾼 낱말 · 숫자 낱말 · 뜻을
    뒤집는 낱말('안' · '못')이 다르면 다른 말이다."""
    if same_line(a, b):
        return True
    x, y = _WORD.findall(a or ""), _WORD.findall(b or "")
    if len(x) < len(y):
        x, y = y, x
    if len(x) != len(y) + 1 or len(y) < 2:
        return False
    for i, w in enumerate(x):
        if x[:i] + x[i + 1 :] == y:
            return w not in _FLIP and not _DIGIT.search(w)
    return False


def strip_lead(text: str) -> str:
    """첫머리 접속 말('다만 · 대신 · 그래서 …')을 뗀 글(남는 글이 없으면 그대로)."""
    t = LEAD_LINK.sub("", text or "", count=1)
    return t if t.strip() else text


# ---- 안쪽 말(모델에만 주는 이름표 · 도구 · 칸 이름 · 도구 오류 hint)은 고객 답에 내지 않는다 ----

# 이름표(v7 · s1 · m2 …, 도구 · 카드가 모델에 준 짧은 이름). '84 m2' 같은 면적 꼴은 아니다
REF_LIKE = re.compile(r"(?<![A-Za-z0-9_])(?<!\d\s)[vmrswdpnx]\d{1,3}(?![A-Za-z0-9_])")
# 영어 snake_case 도구 · 칸 이름(propose_visit_request · vendor_ref · area_m2)
SNAKE = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*_[a-z0-9_]*[a-z0-9](?![A-Za-z0-9_])")
QUOTE_RUN = 8  # 도구 hint 글과 이만큼(띄움 · 부호를 뺀 글자) 이어서 같으면 옮긴 문장이다
# 도구 · 서버가 실패했다는 안쪽 사정('도구가 실패해서' · '도구 오류', QA r3 c4 #34). 연장 '도구'('준비할 도구는 …')는 아니다
INNER_FAIL = re.compile(
    r"도구\s*(?:가|를|의|에서|는)?\s*(?:\S+\s+){0,2}?\S*(?:실패|오류|에러)"
    r"|(?:서버|시스템)\s*(?:가|에서|의)?\s*(?:오류|에러|실패)"
)


def inside(text: str) -> str | None:
    """고객 답에 나오면 안 되는 안쪽 말이 든 문장인지: 까닭('이름표' · '안쪽 이름' · '안쪽 말') 또는 None."""
    t = text or ""
    if "이름표" in t or REF_LIKE.search(t):
        return "이름표"
    if SNAKE.search(t):
        return "안쪽 이름"
    if INNER_FAIL.search(t):
        return "안쪽 말"
    return None


def quotes(text: str, source: str, n: int = QUOTE_RUN) -> bool:
    """text가 source(도구 hint)의 n글자 이상을 그대로 옮겼는지(띄움 · 문장부호는 보지 않는다)."""
    t, s = _PLAIN.sub("", text or ""), _PLAIN.sub("", source or "")
    return len(s) >= n and any(t[i : i + n] in s for i in range(len(t) - n + 1))


# ---- 인사 · 맞장구 ----

# 인사 · 고마움만 한 말(LLM 턴은 도구를 부르지 못하게 tool_choice none, 무료 모드는 한 문장). '네 · 좋아요'처럼
# 앞 물음에 답하는 말은 넣지 않는다(카드를 만들어 달라는 대답일 수 있다)
_SOFT = r"(?:(?:네|넵|예|아|오|와|알겠어요|알겠습니다|알았어요)\s*[,.!~]*\s*)?"
_TAIL = r"[\s,.!~♡^ㅎㅋ]*"
SMALL_TALK = re.compile(
    rf"^{_SOFT}(?:고마워요?|고맙습니다|감사(?:해요|합니다|드려요)?|안녕(?:하세요|하십니까)?|반가워요|"
    rf"수고(?:하세요|하셨어요|하셨습니다|많으셨어요))"
    rf"{_TAIL}(?:(?:고마워요?|감사(?:해요|합니다)?|좋은\s*하루\s*(?:보내세요|되세요)){_TAIL})?$"
)
# 무료 모드만: 맞장구('네 · 알겠어요 · 좋아요')도 한 문장으로 받는다(무료 모드는 말로 제안을 만들지 않는다)
ACK = re.compile(
    rf"^(?:네|넵|예|응|알겠어요|알겠습니다|알았어요|좋아요|그래요|오케이|ㅇㅋ){_TAIL}$"
)


def small_talk(text: str) -> bool:
    return bool(SMALL_TALK.match((text or "").strip()))


def ack(text: str) -> bool:
    return bool(ACK.match((text or "").strip()))


Over = Literal["tools", "llm", "time", "cost"]


@dataclass
class TurnBudget:
    """턴 상한. 시각은 부르는 쪽이 넣는다(time.monotonic). cap_micros = LLM_CAP_TURN_USD × 1e6."""

    started: float
    cap_micros: int
    tools: int = 0
    llm: int = 0
    spent_micros: int = 0

    def elapsed(self, now: float) -> float:
        return max(now - self.started, 0.0)

    def over(self, now: float) -> Over | None:
        """새 LLM 호출 전에 본다: 넘은 상한 이름(없으면 None). 도구 상한은 도구를 더 부르려 할 때 본다."""
        if self.llm >= LLM_MAX - 1:
            return "llm"  # 마지막 한 번은 '지금까지로 답해요' 몫
        if self.elapsed(now) >= TURN_SECONDS:
            return "time"
        if self.spent_micros >= self.cap_micros:
            return "cost"
        return None

    def tool_ok(self) -> bool:
        return self.tools < TOOL_MAX

    def can_call(self) -> bool:
        return self.llm < LLM_MAX

    def left(self, now: float, wrap: bool) -> float:
        """이번 LLM 호출에 줄 시간(초). 마무리 한 번은 WRAP_GRACE를 더 준다."""
        base = TURN_SECONDS + (WRAP_GRACE if wrap else 0.0)
        return max(base - self.elapsed(now), 1.0)


Reason = Literal["ok", "off", "budget", "breaker"]


def mode_for(
    *, available: bool, budget_ok: bool, breaker: bool
) -> tuple[Literal["llm", "free"], Reason]:
    """턴 모드: 차단기 → 꺼짐 → 상한 순으로 본다. LLM이면 ("llm", "ok")."""
    if breaker:
        return "free", "breaker"
    if not available:
        return "free", "off"
    if not budget_ok:
        return "free", "budget"
    return "llm", "ok"


# ---- 먼저 말 걸기 규칙 (계약서 6장) ----

Verdict = Literal["send", "defer", "hold", "quiet"]


@dataclass(frozen=True)
class Dismissal:
    """닫은 제안 하나(트리거 · 닫은 때 · 대상). 규칙은 이것만 본다."""

    trigger: str
    at: datetime
    ref: object | None = None  # 닫은 줄의 대상 id(새 소식은 같은 대상을 닫았을 때만 쉰다)


@dataclass(frozen=True)
class RuleOut:
    verdict: Verdict
    reason: str | None = None  # hold · defer · quiet 까닭: snooze · mute · night · cap
    until: datetime | None = None  # defer면 다시 볼 때


@dataclass(frozen=True)
class NudgeRules:
    """알림(notify)은 사람을 부르니 상한 · 밤 · 멈춤을 보고, 대화 기록(feed)은 쉬기만 본다(밤에도 쌓는다)."""

    cap_customer: int = 2  # 하루 알림 수(서울 날짜)
    cap_vendor: int = 3
    night_from: int = 21  # 21시부터
    night_to: int = 9  # 9시까지는 9시로 미룬다
    snooze: timedelta = timedelta(days=3)  # 닫으면 같은 trigger를 쉬는 기간
    mute_window: timedelta = timedelta(days=7)  # 이 안에 두 번 닫으면
    mute_for: timedelta = timedelta(days=7)  # 알림을 멈추는 기간

    def cap(self, surface: str) -> int:
        return self.cap_vendor if surface == "vendor" else self.cap_customer

    def night(self, now: datetime) -> bool:
        h = now.astimezone(SEOUL).hour
        return h >= self.night_from or h < self.night_to

    def morning(self, now: datetime) -> datetime:
        """다음 아침 night_to시(서울). 지금이 그 시각 전이면 오늘 아침."""
        local = now.astimezone(SEOUL)
        day = local.date() if local.hour < self.night_to else local.date() + timedelta(days=1)
        return datetime.combine(day, time(self.night_to), SEOUL)

    def snoozed(
        self, trigger: str, dismissals: list[Dismissal], now: datetime, ref: object | None = None
    ) -> bool:
        """같은 trigger를 snooze 안에 닫았으면 쉰다. ref를 주면(새 소식) 같은 대상을 닫았을 때만."""
        return any(
            d.trigger == trigger and (ref is None or d.ref == ref) and now - d.at < self.snooze
            for d in dismissals
        )

    def muted_until(self, dismissals: list[Dismissal]) -> datetime | None:
        """mute_window 안에 이어 닫은 두 번이 있으면 뒤의 것 + mute_for까지 알림을 멈춘다."""
        at = sorted(d.at for d in dismissals)
        ends = [b + self.mute_for for a, b in itertools.pairwise(at) if b - a <= self.mute_window]
        return max(ends) if ends else None

    def check(
        self,
        *,
        trigger: str,
        channel: str,
        surface: str,
        now: datetime,
        sent_today: int,
        dismissals: list[Dismissal],
        due: datetime | None = None,
        snooze_ref: object | None = None,
    ) -> RuleOut:
        """보낼지(send) · 미룰지(defer, until) · 기록만 할지(hold) · 알림 대신 조용한 대화 줄로 지금 보낼지(quiet).
        sent_today는 오늘(서울) 보낸 알림 수. due는 할 일의 기한(공사 시작일 등): 밤 · 상한으로 미루면 그 기한이
        지나는 알림은 미루지 않고 대화 줄(feed, 종 알림 없음)로 보낸다(미룬 공사 전날 알림이 시작일에 닫혀 안 가던 것).
        snooze_ref를 주면(새 소식, proactive.fresh_event) 같은 대상을 닫았을 때만 쉰다. 멈춤은 그대로."""
        if self.snoozed(trigger, dismissals, now, snooze_ref):
            return RuleOut("hold", "snooze")
        if channel != "notify":
            return RuleOut("send")
        muted = self.muted_until(dismissals)
        if muted is not None and now < muted:
            return RuleOut("hold", "mute")
        if self.night(now):
            reason = "night"
        elif sent_today >= self.cap(surface):  # 낮(9~21시)이라 다음 아침은 내일 9시
            reason = "cap"
        else:
            return RuleOut("send")
        until = self.morning(now)
        if due is not None and until >= due:
            return RuleOut("quiet", reason)
        return RuleOut("defer", reason, until)
