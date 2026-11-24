"""비서 턴 런타임 (계약서 4장): Claude 도구 루프 · 문장 검사(SentenceGate) · 짧은 이름표(RefTable).

- DB 세션을 쥐지 않는다. 도구는 저마다 짧은 세션을 열고, 턴 저장은 service.finish_turn이 한다.
- 메시지 순서: 지난 턴 글 → 이번 글(가림, 카드에서 고른 ref) → role:system 턴 사실(코드 값만).
  도구 · 지시문은 고정(이름순 · 판 번호)이라 앞부분 캐시가 턴마다 맞는다. 턴 안에서는 덧붙이기만 한다.
- stop_reason: tool_use → 도구, pause_turn → 다시 보냄(2회), refusal → 무료 모드, max_tokens → 끊긴 문장 버림.
- 상한: 도구 6 · LLM 8 · 45초 · 턴 $0.06. 넘으면 '지금까지로 답해요'로 한 번 더(tool_choice none), 그래도 넘으면
  카드만으로 끝낸다(stopped). 같은 (도구, 오류 코드)가 두 번이면 멈추고 실패 카드. Claude가 두 번 실패하면
  무료 모드 + 5분 차단기. 요청 자체가 틀린 거절(400 · 413 · 422, llm.LLMRejected)은 다시 보내지 않고 이 턴만
  무료 모드다(차단기에 세지 않는다). 빈 말은 LLM에 보내지 않는다(빈 글 블록은 400).
- 모델 글은 문장마다 check.sentence_ok(허용 숫자 = 이번 턴 도구 결과 · 이 턴에 만든 · 보인 카드 값 · 사실 · 고객
  글 · 지난 비서 말 두 개)를 지난 것만 token으로 보낸다. 숫자는 근거 값 그대로에 더해 어림 · 차액 · 합계 · 평당 · 날짜
  꼴을 읽고(guard.loose, 합 · 차는 같은 금액 기준끼리만), 누출은 지시문의 규칙 절과만 견준다(prompts.rules). 내용
  까닭(숫자 · 한 일처럼 말함 …)으로 뺀 문장 바로 뒤의 되가리키는 문장('이 값은 …')도 뺀다. 말투 · 길이는
  모델에 맡기고(docs/v4/08-rules.md) 아주 긴 답만 줄인다: 앞 문장부터 상한까지 보내고 넘친 문장은 마지막 묻는 말
  하나만 턴 끝에 보낸다. 앞으로 가리키는 문장과 뒤 목록은 묶음째 보내거나 뺀다(안 문장이 검사로 빠지면 가리키는 말이
  수를 말할 때만 묶음째, 아니면 그 문장만). 지난 세 비서 턴의 안내 · 권유 · 묻는 말 · 약속과 거의 같은 문장, 같은
  카드 · 채팅을 다시 가리키는 안내는 뺀다(policy.TALK_* · LONG_* · REPEAT_TURNS). 검사로 본문이 빠져 남은 글이 없거나
  가리키는 말뿐이면 정해 둔 정직한 한 줄(CUT_TEXT · 카드가 있으면 FAIL_TEXT)을 끝에 보낸다.
"""

import asyncio
import copy
import json
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import ClassVar

from app import queue
from app.agent import llm
from app.agent.v3 import check
from app.agent.v3.schemas import Sentence
from app.assistant import asks as asks_mod
from app.assistant import choices, policy, prompts
from app.assistant import tools as tools_mod
from app.assistant.schemas import AnswerData, CardOut
from app.assistant.tools import ToolCtx, ToolError
from app.assistant.tools import answer as answer_tools
from app.auth.models import User
from app.config import settings
from app.shared.errors import AppError
from app.usage.service import REDIS_ERRORS
from app.v2 import guard

log = logging.getLogger(__name__)

Emit = Callable[[str, dict], Awaitable[None]]

WRAP = "도구는 더 부르지 말고, 지금까지 얻은 결과로만 짧게 답해 주세요."
FAIL_TEXT = "설명을 만들지 못했어요. 카드와 버튼으로 이어서 진행해 주세요."
# 문장 검사로 답의 본문이 빠져 보낼 글이 없거나 가리키는 말뿐인 턴(카드 없음)의 끝 한 줄(고침 4차 G, QA r4 c2 15턴)
CUT_TEXT = "이번에는 답을 다 만들지 못했어요. 다시 말씀해 주시겠어요?"
# 버린 까닭 중 답의 본문이 빠진 것이 아닌 것(외국어 속말 · 한자): 남은 글을 보고 정직한 한 줄을 붙이지 않는다
NOISE = frozenset({"외국어 속말", "한글 없는 외국어 글", "한자 섞인 글"})
# 숫자 근거로 쓰는 지난 비서 말 수(가장 가까운 것부터, 이미 검사를 지나 보낸 글, 고침 5차 R1 · QA r5 C s5-4)
TOLD_TURNS = 2
# 앞 턴 승인 카드로 볼 때(시간): 이 안에 만든 카드를 두고 한 "만들었어요"는 반대 말로 바꾸지 않는다
BEFORE_HOURS = 2
# 앞 문장을 되가리키며 여는 말('이 값은 …' · '그 금액에 …' · '둘 다 …' · '그건 …' · '그중 …'). 내용 까닭으로 뺀 문장
# 바로 뒤에 오면 가리킬 말이 없어 같이 뺀다(고침 5차 R1, QA r5 C s5-4: 숫자 문장이 빠지고 '이 값은 벽지 값이 들어간
# 값이라, …'만 남음). '이중 도배' · '그 중간' · '둘 다른'은 아니다
BACK_REF = re.compile(
    r"(?:이|그)\s*(?:값|금액|범위)(?!어치)"
    r"|둘\s*다(?:요|(?![가-힣]))"
    r"|(?:이|그)(?:건|것은|것이|것도)(?:요|(?![가-힣]))"
    r"|그\s*중(?!간|요|심|순|대)|이\s+중(?!간|요|심|순|대)"
)
BACK_WHY = "앞 문장을 가리킴"
NUM_MARK = re.compile(r"^(\d{1,2})([.)])\s")  # 번호 목록 줄 머리('1. ')
TOOL_FAIL = "같은 문제가 두 번 나서 멈췄어요. 화면에서 직접 이어서 해 주세요."
EMPTY_TEXT = "말씀이 비어 있어요. 궁금한 것을 적어 주세요."
# 카드 종류 → 화면 이름(카드만 보낸 턴의 기록 글 · 먼저 말 건 줄 턴 사실). schemas.CardKind 모두(R1a B7)
CARD_NAME = {
    "home_info": "집 정보", "standard_quote": "표준견적서", "vendor_picks": "업체 추천",
    "visit_slots": "실측 일정", "quote_compare": "견적서 비교", "schedule": "공사 날짜",
    "knowledge": "자료", "answer": "답", "floorplan_links": "평면도 찾기", "today": "오늘 할 일",
    "vendor_brief": "요청 브리핑", "quote_checklist": "견적서 체크리스트",
    "extra": "추가 금액", "notice": "이웃 안내문", "grade_compare": "벽지 두 종류 비교",
    "market_range": "시세 범위", "options": "고르기", "research": "조사",
    "product_estimate": "벽지 금액",
}  # fmt: skip
CARDS_ONLY = "(카드를 보여 줬어요"  # 카드만 보낸 턴의 기록 글 머리(끝 문장으로 보지 않는다)
BREAKER_KEY = "assistant:breaker"
BREAKER_TTL = 300  # Claude가 한 턴에 두 번 실패하면 5분 동안 무료 모드
PAUSE_MAX = 2
# 이름표는 대화마다 7일(저장할 때마다 늘림). 지난 카드 · 먼저 말 걸기 카드(며칠 뒤 알림)의 단추도 같은 대상을 가리킨다.
# 지워져도 되는 값이다: 모르는 이름표 단추는 choices가 카드를 새로 불러온다
REF_TTL = 7 * 86400
REF_NUM_TTL = 30 * 86400  # 쓴 번호 · 버린 이름표 기록(표가 지워져도 번호를 다시 쓰지 않게)
REF_DEAD_MAX = 200
REF_SAVE_TRIES = 5
BEAT_EVERY = 10.0  # heartbeat를 이보다 자주 쓰지 않는다(초)
# 도구 하나에 주는 가장 짧은 시간(초). 그 밖에는 턴에 남은 시간(45초 안)까지만 기다린다
TOOL_MIN = 5.0
DROPPED_MAX = 12  # 흔적(trace)에 남기는 버린 문장 까닭 수
MADE_NOW = "이번 턴에 승인 카드를 만들었어요. 사람이 카드 버튼을 눌러야 실행돼요."
# 이 턴에 똑같이 보낸 카드를 도구가 다시 냈을 때 모델 값 note에 붙이는 말(카드는 다시 보내지 않는다)
SAME_CARD = "같은 카드를 이번 턴에 이미 보였어요(다시 보내지 않았어요)."
# 문장 끝: 마침표 · 물음표 · 느낌표 뒤 빈칸, 또는 줄 바꿈('필요 없어요'의 '요 '는 끝으로 보지 않는다). 목록 번호(줄
# 머리 · 빈칸 뒤 한두 자리 수 + 점, '1. ')는 문장 끝이 아니다(고침 3차 A2 결정 2, QA r3 c5 19턴 '2.'에서 끊김)
SENT_END = re.compile(r"(?<!\s\d\.)(?<!\s\d\d\.)(?<!^\d\.)(?<!^\d\d\.)(?<=[.!?。])[ \t]+|\n+")


def spacing(sep: str) -> str:
    """문장 사이 띄움: 빈 줄(말풍선 나눔, 줄 바꿈 둘 이상) · 줄 바꿈 · 빈칸. 화면은 빈 줄마다 말풍선을 나눈다."""
    n = sep.count("\n")
    return "\n\n" if n >= 2 else "\n" if n else " "


# 승인이 있어야 하는 일을 한 것처럼 끝맺는 말('확정했어요' · '요청을 보냈어요' · '결제를 완료'). 비서는 실행하지 않는다.
# 실측 요청 취소(visit_cancel 0051)와 '해 놨어요 · 끝냈어요 · 잡아 뒀어요 · 보내 놨어요' 꼴도(R1a B1). '넣었어요'는
# 카드에 넣은 말이라 빼요
CLAIM = re.compile(
    r"(?:확정|수락|승인|거절|취소|결제|예약|저장|실행|처리|요청|신청|접수|전송)(?:을|를|으로|로)?\s*"
    r"(?:했어요|했습니다|했고|했으니|해\s*드렸|해\s*뒀|해\s*두었|해\s*놨|해\s*놓았|완료|바꿨|끝냈|마쳤|"
    r"잡아\s*(?:드렸|뒀|두었|놨|놓았))"
    r"|보냈어요|보냈습니다|보내\s*(?:드렸|뒀|두었|놨|놓았)"
)
SUBJECT = re.compile(r"([가-힣A-Za-z0-9]+?)(?:이|가|께서|에서(?:는|도)?)\s")
FIRST = frozenset({"제", "저", "저희", "AI", "비서", "믿집", "내"})
# '…에서'가 곳을 말하면(화면에서 · 카드에서) 주어가 아니다. 그 밖의 '…에서'는 하는 쪽이다(결도배에서 보냈어요)
PLACE = frozenset(
    {"화면", "카드", "단추", "버튼", "채팅", "대화", "앱", "여기", "거기", "이곳", "그곳", "페이지",
     "목록", "메뉴", "알림", "공정표", "견적서", "표준견적서", "집", "현장"}
)  # fmt: skip


def claims_done(text: str) -> bool:
    """비서가 승인 없이 한 것처럼 말하는지. 다른 사람이 주어면(업체가 보냈어요 · 결도배에서 보냈어요) 사실 전달로
    둔다."""
    if not CLAIM.search(text):
        return False
    subjects = [m.group(1) for m in SUBJECT.finditer(text) if m.group(1) not in PLACE]
    return not subjects or all(s in FIRST for s in subjects)


HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
LATIN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
FOREIGN_RATE = 0.6  # 글자 중 로마자가 이만큼이면 외국어 문장(한글이 섞여 있어도)
# 한자(CJK 통합 한자 · 확장 A · 호환 한자). 한국어 답에 섞이면 한 글자는 지우고 두 글자 넘게 이으면 문장을 뺀다
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")


def foreign(text: str) -> bool:
    """고객 글이 아닌 외국어 속말인지: 한글이 하나도 없고 글자 · 숫자의 반 넘게가 다른 글자(QA r2 c3 'Direct tasks
    not saved; make a card.'), 또는 글자의 FOREIGN_RATE 넘게가 로마자이고 로마자 낱말이 셋 이상(소문자로 시작하는
    낱말 둘 이상)인 문장(QA r3 s4y "I'll go with 마루와벽."). 제품 이름 · 단위가 섞인 한국어 문장('LX하우시스 베스띠
    실크' · '84㎡')과 숫자 · 날짜만인 줄은 아니다."""
    letters = sum(ch.isalpha() for ch in text)
    if not HANGUL.search(text):
        return letters * 2 > sum(ch.isalnum() for ch in text)
    latin = sum(ch.isascii() and ch.isalpha() for ch in text)
    words = LATIN_WORD.findall(text)
    lower = [w for w in words if w[0].islower()]
    return latin >= FOREIGN_RATE * letters and len(words) >= 3 and len(lower) >= 2


def han_fix(text: str) -> str | None:
    """한자가 섞인 문장: 한 글자씩 떨어진 한자는 지운 글(QA r3 c6 T18 '一이 결과엔 …'), 두 글자 넘게 이어지면 None."""
    runs = HAN.findall(text)
    if not runs:
        return text
    if any(len(r) > 1 for r in runs):
        return None
    fixed = re.sub(r"[ \t]{2,}", " ", HAN.sub("", text)).strip()
    return fixed or None


# ---- 짧은 이름표 ----


def _json_dict(raw) -> dict:
    try:
        got = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


class RefTable:
    """도구 · 카드가 만든 짧은 이름(v1 · m1 · r1 · s1 · w1 · d1 · p1 · n1) → 실제 값(id · 날짜). 대화마다 Redis(REF_TTL).

    - 같은 대상은 같은 이름을 받는다(IDENT 칸이 같으면 값만 새로 쓴다). 모르는 이름 · 종류가 다른 이름은 unknown_ref.
    - 턴 · 먼저 말 걸기 · 업체 브리핑(REST)이 한 대화의 표를 같이 쓴다. 번호는 머리글자마다 쓴 가장 큰 번호(top,
      REF_NUM_TTL) 다음부터라 표가 지워지거나 오래된 것을 버려도 같은 이름이 다른 대상을 가리키지 않는다.
    - 저장은 Redis 표와 합친다(WATCH). 두 곳이 같은 번호를 다른 대상에 썼으면 그 이름을 버리고(dead) 다시 살리지
      않는다: 그 이름의 단추는 모르는 이름표가 되어 카드를 새로 불러온다(엉뚱한 대상으로 가지 않게).
    - Redis는 지워져도 되는 값이라 번호는 DB(assistant_ref_tops)에도 늘기만 하게 둔다. 표 · 번호 기록이 모두 지워진
      뒤 새로 만든 번호(fresh)가 DB 번호보다 크지 않으면 그 이름은 저장할 때 버린다(지난 카드의 같은 이름이 다른
      대상일 수 있다). 다음 표는 DB 번호 다음부터 매긴다."""

    PREFIX: ClassVar[dict[str, str]] = {
        "vendor": "v", "visit": "m", "wish": "r", "slot": "s", "window": "w",
        "deal": "d", "proposal": "p", "days": "n",
        "extra": "x",  # 07 추가 금액
    }  # fmt: skip
    IDENT: ClassVar[dict[str, tuple[str, ...]]] = {
        "vendor": ("id",), "visit": ("id",), "wish": ("start", "end"),
        "slot": ("visit_id", "day", "half"), "window": ("visit_id", "start", "end"),
        "deal": ("id",), "proposal": ("id",), "days": ("deal_id", "start"),
        "extra": ("id",),
    }  # fmt: skip
    MAX = 80

    def __init__(
        self,
        chat_id: uuid.UUID,
        items: dict[str, dict] | None = None,
        top: dict[str, int] | None = None,
        dead: set[str] | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.dead: set[str] = set(dead or ())
        self.items: dict[str, dict] = {
            r: it
            for r, it in (items or {}).items()
            if r not in self.dead and isinstance(it, dict) and it.get("kind") in self.IDENT
        }
        self.top: dict[str, int] = dict(top or {})  # 머리글자마다 쓴 가장 큰 번호
        self.touched: set[str] = set()  # 이 표에서 넣거나 고친 이름(저장할 때 우리 값이 이긴다)
        self.fresh: set[str] = set()  # 이 표가 새 번호로 만든 이름(저장할 때 DB 번호와 견준다)
        # 이 표가 DB 번호를 올린 머리글자 → 올리기 전 번호(_durable). 두 번 저장해도 이 표가 올린 번호를 '지난 번호'로
        # 보지 않게(R1a B4)
        self._raised: dict[str, int] = {}

    @classmethod
    def ident(cls, it: dict) -> tuple:
        kind = it.get("kind")
        return (kind, *(str(it.get(k)) for k in cls.IDENT.get(str(kind), ())))

    def put(self, kind: str, value: dict) -> str:
        want = self.ident({**value, "kind": kind})
        ref = next((r for r, it in self.items.items() if self.ident(it) == want), None)
        if ref is not None:
            # 다시 쓴 이름표는 뒤로: 표가 차면 오래 안 쓴 것부터 버린다(R1a B3)
            it = self.items.pop(ref)
            it.update({k: v for k, v in value.items() if k != "kind"})
            self.items[ref] = it
            self.touched.add(ref)
            return ref
        prefix = self.PREFIX[kind]
        used = [int(r[1:]) for r in self.items if r[0] == prefix and r[1:].isdigit()]
        n = max([*used, self.top.get(prefix, 0)]) + 1
        self.top[prefix] = n
        ref = f"{prefix}{n}"
        if len(self.items) >= self.MAX:  # 가장 오래 안 쓴 것부터 버린다(번호는 top이 기억한다)
            self.items.pop(next(iter(self.items)))
        self.items[ref] = {**value, "kind": kind}  # 값의 칸이 종류 이름을 덮지 않게
        self.touched.add(ref)
        self.fresh.add(ref)
        return ref

    def get(self, ref: str | None, kind: str) -> dict:
        it = self.items.get(ref or "")
        if it is None or it["kind"] != kind:
            raise ToolError(
                "unknown_ref",
                "지금 대화에서 찾을 수 없는 항목이에요. 카드를 다시 불러와 골라 주세요.",
                hint=f"이름표 '{ref}'는 이 대화에 없어요({kind} 이름표가 필요해요). 도구 결과에 나온 이름표만 넘겨요",
            )
        return it

    def known(self, ref: str) -> bool:
        return ref in self.items

    @staticmethod
    def _key(chat_id: uuid.UUID) -> str:
        return f"assistant:refs:{chat_id}"

    @staticmethod
    def _num_key(chat_id: uuid.UUID) -> str:
        return f"assistant:refs:{chat_id}:num"

    @classmethod
    async def load(cls, chat_id: uuid.UUID) -> "RefTable":
        try:
            raw, num = await queue.redis.mget(cls._key(chat_id), cls._num_key(chat_id))
        except REDIS_ERRORS:
            raw = num = None
        meta = _json_dict(num)
        return cls(chat_id, _json_dict(raw), meta.get("top") or {}, set(meta.get("dead") or ()))

    def merged(
        self, theirs: dict, meta: dict, durable: dict[str, int] | None = None
    ) -> tuple[dict, dict]:
        """Redis에 있는 표(theirs) · 번호 기록(meta)과 이 표를 합친다. (새 표, 새 번호 기록)
        durable(DB에 남은 번호, 이 표가 올리기 전)보다 크지 않은 새 번호가 Redis에 없으면 버린다(표가 지워진 뒤 다시
        쓴 번호). 이 표에서 넣거나 고친 이름은 뒤로 옮겨, 넘치면 오래 안 쓴 것부터 버린다(R1a B3)."""
        durable = durable or {}
        dead = set(meta.get("dead") or ()) | self.dead
        out = {
            r: it
            for r, it in theirs.items()
            if r not in dead and isinstance(it, dict) and it.get("kind") in self.IDENT
        }
        for ref, it in self.items.items():
            if ref in dead:
                continue
            old = out.get(ref)
            if old is not None and self.ident(old) != self.ident(it):
                out.pop(ref)  # 같은 번호를 다른 대상에 썼다(동시에 만든 표): 둘 다 모르는 이름표로
                dead.add(ref)
                continue
            if old is None and ref in self.fresh and int(ref[1:]) <= durable.get(ref[0], 0):
                dead.add(ref)  # 지난 카드의 같은 이름이 다른 대상일 수 있다: 모르는 이름표로
                continue
            if ref in self.touched:
                out.pop(ref, None)  # 이 표에서 쓴 이름표는 뒤로(가장 최근에 쓴 것)
                out[ref] = it
            elif old is None:
                out[ref] = it
        while len(out) > self.MAX:
            out.pop(next(iter(out)))
        top = {str(p): int(n) for p, n in (meta.get("top") or {}).items()}
        for p, n in [*self.top.items(), *durable.items()]:
            top[p] = max(top.get(p, 0), n)
        return out, {"top": top, "dead": sorted(dead)[-REF_DEAD_MAX:]}

    async def _durable(self) -> dict[str, int]:
        """DB에 남긴 번호(머리글자 → 가장 큰 번호)를 읽고 이 표의 번호로 올린다(늘기만). 돌려주는 값: 올리기 전 번호.
        이 표가 앞서 올린 머리글자는 처음 올리기 전 번호다(R1a B4: 턴마다 두 번 저장하는데 첫 저장의 Redis가 실패하면,
        둘째 저장이 이 표가 올린 번호를 '지난 번호'로 보고 이 턴의 새 이름표를 버렸다). DB를 못 쓰면 {}(Redis만으로
        합친다)."""
        from sqlalchemy import func, select
        from sqlalchemy.dialects.postgresql import insert

        from app.assistant.models import AssistantRefTop
        from app.db import SessionLocal

        try:
            async with SessionLocal() as s:
                rows = await s.execute(
                    select(AssistantRefTop.prefix, AssistantRefTop.top).where(
                        AssistantRefTop.chat_id == self.chat_id
                    )
                )
                before = {str(p): int(n) for p, n in rows.all()}
                want = [
                    {"chat_id": self.chat_id, "prefix": p, "top": n}
                    for p, n in self.top.items()
                    if n > before.get(p, 0)
                ]
                if want:
                    stmt = insert(AssistantRefTop).values(want)
                    await s.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["chat_id", "prefix"],
                            set_={"top": func.greatest(AssistantRefTop.top, stmt.excluded.top)},
                        )
                    )
                    await s.commit()
        except Exception as e:  # noqa: BLE001 - 번호 기록 실패는 Redis만으로 합친다(종류 이름만 로그)
            log.warning("비서 이름표 번호 저장 실패 (%s)", type(e).__name__)
            return {}
        # 이번에 올린 머리글자는 올리기 전 번호를 기억한다(처음 한 번)
        for p, n in self.top.items():
            if p not in self._raised and n > before.get(p, 0):
                self._raised[p] = before.get(p, 0)
        return {**before, **self._raised}

    async def save(self) -> None:
        """Redis 표와 합쳐 저장한다. 이 표가 새 번호를 썼으면 먼저 DB 번호를 올리고 그 앞 번호로 견준다(merged)."""
        from redis.exceptions import WatchError

        durable = await self._durable() if self.fresh else {}
        key, num_key = self._key(self.chat_id), self._num_key(self.chat_id)
        try:
            async with queue.redis.pipeline(transaction=True) as pipe:
                for _ in range(REF_SAVE_TRIES):
                    try:
                        await pipe.watch(key, num_key)
                        raw, num = await pipe.mget(key, num_key)
                        items, meta = self.merged(_json_dict(raw), _json_dict(num), durable)
                        pipe.multi()
                        pipe.set(key, json.dumps(items, ensure_ascii=False), ex=REF_TTL)
                        pipe.set(num_key, json.dumps(meta), ex=REF_NUM_TTL)
                        await pipe.execute()
                        self.fresh.clear()  # 저장했다: 다시 저장할 때는 Redis 값과 견준다
                        return
                    except WatchError:
                        continue  # 그사이 다른 곳이 저장했다: 다시 읽어 합친다
        except REDIS_ERRORS:
            return  # 지워져도 되는 값: 모르는 이름표 단추는 카드를 새로 불러온다


# ---- 문장 검사 ----


def recent_said(history: list[dict], turns: int = policy.REPEAT_TURNS) -> list[str]:
    """지난 비서 답 turns개(가장 가까운 것부터 셈)의 문장들(되풀이 견주기). 카드만 보낸 턴의 기록 글은 뺀다."""
    out: list[str] = []
    said = [m.get("content") for m in history if m.get("role") == "assistant"][-turns:]
    for text in said:
        if not isinstance(text, str) or not text.strip() or text.startswith(CARDS_ONLY):
            continue
        out += [p.strip() for p in SENT_END.split(text.strip()) if p.strip()]
    return out


# 되풀이로 빠질 다음 할 일 문장을 살리는 한도: 같은 안내가 바로 앞 두 답에 다 있었으면(세 번째 연속) 살리지 않는다
# (QA r4 c5 9~12턴 '열린 카드 안내 네 턴 연속'과 QA r6 c3 t19 '다음 할 일 없이 끝남'을 같이 지킴)
SPARE_RUN = 2


def said_turns(history: list[dict], turns: int = SPARE_RUN) -> list[list[str]]:
    """지난 비서 답 turns개의 문장들(답마다, 가장 가까운 답부터). 카드만 보낸 턴은 빈 목록."""
    said = [m.get("content") for m in history if m.get("role") == "assistant"][-turns:]
    return [recent_said([{"role": "assistant", "content": t}], 1) for t in reversed(said)]


def told_before(history: list[dict], turns: int = TOLD_TURNS) -> str:
    """지난 비서 말 turns개(가장 가까운 것부터 셈)의 글: 이미 검사를 지나 보낸 글이라 숫자 근거다(앞 턴에 말한 가견적을
    '만 원 단위로'처럼 다시 말할 수 있게, QA r5 C s5-4). 카드만 보낸 턴의 기록 글은 세기만 한다. 대화 기록은 최근
    service.HISTORY_FULL줄을 자르지 않아 이 글은 앞부분만 남긴 옛 비서 말(HISTORY_CUT자)이 아니다."""
    said = [m.get("content") for m in history if m.get("role") == "assistant"][-turns:]
    return "\n".join(
        t for t in said if isinstance(t, str) and t.strip() and not t.startswith(CARDS_ONLY)
    )


def back_ref(text: str) -> bool:
    """앞 문장을 되가리키며 여는 문장인지(BACK_REF, 첫머리 접속 말 '다만 · 그래서 …'은 떼고 본다)."""
    return bool(BACK_REF.match(policy.strip_lead((text or "").strip())))


def ref_names(refs: RefTable) -> set[str]:
    """이 대화 이름표 표의 업체 이름(업체 · 실측 요청 이름표에 든 것). 같은 카드 · 채팅을 가리키는지 가릴 때 쓴다."""
    out = set()
    for it in refs.items.values():
        name = it.get("name") or it.get("vendor_name")
        if it.get("kind") in ("vendor", "visit") and isinstance(name, str) and name.strip():
            out.add(name.strip())
    return out


FACT_VENDORS = re.compile(r"^업체:\s*(.+)$", re.MULTILINE)  # 턴 사실 '업체:' 줄(업체마다 ' / ')
NAME_HEAD = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def fact_names(facts: str) -> set[str]:
    """턴 사실 '업체:' 줄의 업체 이름(항목마다 첫 낱말, 뒤에 붙은 상태 말은 보지 않는다)."""
    out = set()
    for m in FACT_VENDORS.finditer(facts or ""):
        for item in m.group(1).split(" / "):
            if head := NAME_HEAD.match(item.strip()):
                out.add(head.group(0))
    return out


def card_vendors(summary: dict | None) -> set[str]:
    """승인 카드 요약의 '업체' 줄 값(고객 카드)."""
    rows = (summary or {}).get("rows") or []
    return {
        str(r["value"]).strip()
        for r in rows
        if isinstance(r, dict) and r.get("label") == "업체" and str(r.get("value") or "").strip()
    }


def card_ground(data: dict) -> str:
    """화면 카드 값 → 숫자 근거 글(모델에 보내는 칸만: id · 링크 · 표준 대비 % 없음, policy.to_model)."""
    return json.dumps(policy.to_model(data or {}), ensure_ascii=False, default=str)


def summary_ground(summary: dict) -> str:
    """승인 카드 요약 → 숫자 근거 글: 제목 · 금액(부가세 포함) · 금액 줄 · 차액 · 줄(이름 · 값) · 메모(QA r3 s2 9턴:
    카드엔 12월 14일이 있는데 글의 날짜 문장이 '자료에 없는 숫자'로 빠짐)."""
    s = summary or {}
    lines = [str(s.get("title") or ""), str(s.get("note") or "")]
    if s.get("amount_won") is not None:
        lines.append(f"부가세 포함 {s['amount_won']}원")
    lines += [f"{r.get('label', '')} {r.get('won')}원" for r in s.get("amounts") or []]
    if d := s.get("diff"):
        won = (d.get("from_won"), d.get("to_won"), d.get("diff_won"))
        lines.append(f"{d.get('label', '')} " + " ".join(f"{w}원" for w in won if w is not None))
    lines += [
        f"{r.get('label', '')}: {r.get('value', '')} {r.get('sub') or ''}"
        for r in s.get("rows") or []
    ]
    return "\n".join(x for x in lines if x.strip())


@dataclass
class _Piece:
    """검사를 지난 문장 하나: 앞 띄움 · 글 · 카드 말 · 목록 줄에 든 문장인지(item) · 목록 줄을 여는지(row)."""

    sep: str
    text: str
    claim: tuple[str, set[str]] | None = None
    item: bool = False
    row: bool = False
    member: bool = False  # 묶음째 보내는 문장(되풀이로 하나만 빼지 않는다)


@dataclass
class _Group:
    """앞으로 가리키는 문장(머리, policy.pointer)과 뒤 목록 줄 · 이어진 문장의 묶음(고침 3차 A2 결정 3). 머리가 없으면
    목록 줄만의 묶음이다. 통째로 보내거나 뺀다(가리키는 문장만 남기지 않는다). 안 문장이 검사로 빠지면 가리키는 말이
    수를 말할 때(counted)만 묶음째 빼고, 아니면 빠진 문장만 뺀다(고침 4차 G, QA r4 c2 15턴: 업체에 보낼 초안 중 한
    문장이 숫자 검사에 걸려 초안이 통째로 사라짐)."""

    head: bool
    members: list[_Piece] = field(default_factory=list)
    bad: bool = False  # 검사로 빠진 문장이 있다
    inline: bool = False  # 머리 줄에 이어 쓴 문장이 있다(가리킨 것이 같은 줄에 있다)
    broke: bool = False  # 머리 뒤 새 줄이 왔다
    # 가리키는 말(머리, 머리가 없으면 바로 앞에 보낸 문장)이 뒤 줄의 수를 말한다('세 가지예요'): 한 줄이 빠지면 묶음째
    counted: bool = False
    # 검사로 빠진 문장이 줄을 열었다: (앞 띄움, 목록 기호 · 닫지 않은 여는 따옴표). 같은 줄 다음 문장이 이어받는다
    orphan: tuple[str, str] | None = None

    def takes(self, newline: bool, row: bool) -> bool:
        """이 조각이 묶음에 드는지: 같은 줄 · 목록 줄, 머리 줄이 끝난 바로 뒤 한 줄(가리킨 것)."""
        if not newline:
            if self.head and not self.broke:
                self.inline = True
            return True
        if row or (self.head and not self.inline and not self.broke):
            self.broke = True
            return True
        return False

    def lose(self, raw: str, sep: str, newline: bool, row: bool) -> None:
        """검사로 빠진 문장 하나. 줄을 열었으면 띄움과 목록 기호(닫지 않은 따옴표)를 같은 줄 다음 문장에 넘기고, 앞에서 연
        따옴표를 닫았으면 닫는 따옴표를 같은 줄 앞 문장에 붙인다."""
        self.bad = True
        if newline:
            mark = ""
            if row and (m := policy.LIST_MARK.match(raw)):
                mark = m.group(0)
                if mark.strip() in policy.QUOTES and not policy.quote_left(raw):
                    mark = ""  # 한 문장으로 닫힌 따옴표 줄(넘길 따옴표가 없다)
            self.orphan = (sep, mark)
            return
        close = policy.quote_right(raw)
        if close and self.members and self.members[-1].item:
            last = self.members[-1]
            self.members[-1] = replace(last, text=last.text + close)

    def add(self, p: _Piece, newline: bool) -> None:
        """검사를 지난 문장을 묶음에 넣는다. 같은 줄 앞 문장이 빠져 줄 머리가 비었으면 그 띄움 · 기호를 이어받는다."""
        if self.orphan is not None:
            sep, mark = self.orphan
            self.orphan = None
            if not newline:
                p = replace(p, sep=sep, text=mark + p.text, row=p.row or bool(mark))
        self.members.append(p)


def renumber(members: list[_Piece]) -> None:
    """빠진 번호 목록 줄 뒤 번호를 다시 매긴다('1. · 3.' → '1. · 2.')."""
    n: int | None = None
    for i, p in enumerate(members):
        m = NUM_MARK.match(p.text) if p.row else None
        if m is None:
            continue
        n = int(m.group(1)) if n is None else n + 1
        if int(m.group(1)) != n:
            members[i] = replace(p, text=f"{n}{m.group(2)}{p.text[m.end(2) :]}")


class SentenceGate:
    """모델 글 조각을 문장으로 모아 검사를 지난 문장만 token으로 보낸다(숫자 · AI가 한 일처럼 · 주소 · 누출 · 안쪽 말 ·
    외국어 · 한자).

    말과 행동 맞추기(policy.card_claim · 고정 선 5): 이 턴에 승인 카드를 만들었다 · 눌러 달라는 문장은 확실히 틀릴 때만
    바꾼다(policy.claim_ok: 만들었다는 말은 이 턴에 만든 카드가 하나도 없을 때, 눌러 달라는 말은 누를 것이 하나도 없을
    때). 아직 모르면 그 문장과 뒤 문장을 순서대로 붙잡아 두고, 카드가 오면 놓아준다(made · opened · buttons). 턴
    끝(settle)에도 틀리면 첫 문장을 정직한 한 줄로 바꾸고 나머지 그런 문장은 뺀다.

    길이(policy.TALK_* · LONG_*): 아주 긴 답만 줄인다. 앞 문장부터 상한(보통 6문장 · 500자, 대화 첫 답 · 업체 소개 ·
    견적 비교 카드를 보인 턴은 8문장 · 700자)까지 보내고, 넘친 뒤 문장은 모두 모았다가 턴 끝에 마지막 묻는 말 하나만
    보낸다(이미 물었으면 없음). 앞으로 가리키는 문장과 뒤 목록 줄은 한 묶음(_Group): 상한 안이면 같이 보내고 넘으면
    통째로 뺀다. 묶음이 답의 첫 문장이면(답 자체가 목록) 목록 줄 LIST_FIRST개까지 보낸다. 묶음 안 문장이 검사로 빠지면
    가리키는 말이 수를 말할 때만 묶음째 빼고, 아니면 그 문장만 뺀다(줄 머리 기호 · 따옴표는 이웃 문장이 이어받고 번호는
    다시 매긴다). 가리킨 말이 없는 머리는 뺀다. 앞 문장이 빠져 첫 문장이 되면 첫머리 접속 말을 뗀다. 내용 까닭으로 뺀
    문장 · 묶음째 뺀 목록 바로 뒤의 되가리키는 문장(back_ref, '이 값은 …' · '그중 …')도 뺀다(외국어 속말 · 한자로 뺀
    문장은 사이로 보지 않는다).
    되풀이: 이 턴에 보낸 문장과 같은 문장은 빼고, 지난 비서 턴(said, REPEAT_TURNS)에 보낸 문장과 거의 같은 안내 ·
    권유 · 묻는 말 · 약속(policy.guide · near_same), 같은 카드 · 채팅 · 약속을 새 대상 없이 다시 가리키는 안내
    (policy.same_aim, 대상 이름은 names)는 뺀다. 첫 문장 · 이 턴에 만든 카드와 보인 카드 단추를 가리키는 말 · 지난 일 ·
    묶음 안 문장은 두고, 그 문장뿐이면 둔다. 고객이 금액 · 날짜를 물은 턴(asked 'fact')은 숫자가 든 사실 답을, 카드 ·
    할 일을 물은 턴('how')은 같은 카드 안내도 둔다. 되풀이로 뺀 다음 할 일 문장(policy.points: 카드 · 채팅 · 누를 것)은
    한 문장만 남겨 뒀다가, 턴 끝에 답에 다른 다음 할 일 · 묻는 말이 없고 이 턴에 만든 · 보인 카드 단추도 없으면 끝에
    살린다(QA r6 c3 t19: [채팅] 안내가 '지난 턴과 같은 안내'로 빠져 상태 문장만 남음).
    본문이 빠짐: 검사 · 묶음으로 답의 본문이 빠져 보낸 글이 없거나 가리키는 말뿐이면 턴 끝(mend)에 정직한 한 줄을 보낸다."""

    def __init__(
        self,
        emit: Emit,
        prompt: str,
        allowed: str,
        made: Collection[str] = (),
        said: Collection[str] = (),
        long_ok: bool = False,
        names: Collection[str] = (),
        asked: Collection[str] = (),
        turns: Sequence[Collection[str]] | None = None,
    ) -> None:
        self._emit = emit
        self._prompt = prompt  # 누출 견주기 글(prompts.rules: 지시문의 규칙 절만)
        self._allowed = [allowed]
        self._ground: guard.Ground | None = None
        self._buf = ""
        self._sep = ""  # 다음 문장 앞에 붙일 띄움(빈칸 · 줄 바꿈)
        self.sent: list[str] = []
        self.dropped: list[str] = []
        self._out: list[str] = []
        self.made: set[str] = set(made)  # 이 턴에 새로 만든 승인 카드 종류
        self.opened: set[str] = set()  # 열려 있는 승인 카드 종류(턴 앞 · 이 턴에 다시 쓴 카드)
        # 앞 턴에 만들어 이제 닫힌(승인 · 거절 · 만료) 승인 카드 종류(BEFORE_HOURS 안): 그 카드를 두고 '만들었어요'라고
        # 하면 이 턴 기준으로는 틀려도 '아직 만들지 않았어요'로 바꾸지 않고 뺀다(QA r7 c1 9턴: 방금 승인한 카드에 반대 말)
        self.before: set[str] = set()
        self.buttons: set[str] = set()  # 이 턴에 보인 화면 카드 단추가 만드는 행동 종류
        self._held: list[_Piece] = []  # 카드 말이 맞게 될 때까지 붙잡아 둔 문장(뒤 문장도 순서대로)
        self._fixed = False  # 정직한 한 줄을 이미 썼다
        self.said = [s for s in said if s and s.strip()]  # 지난 비서 턴에 보낸 문장
        self._extra: list[_Piece] = []  # 길이 상한을 넘은 뒤 문장
        self._group: _Group | None = None  # 모으는 중인 묶음
        self._over = False  # 길이 상한으로 자르기 시작했다(뒤 문장은 모두 넘친 문장)
        self._lost = False  # 첫 문장 전에 빠진 문장이 있다(첫머리 접속 말을 뗀다)
        self._newline = True  # 다음 조각이 새 줄에서 시작한다(첫 조각 · 모델 글 블록의 첫 조각)
        self._row = False  # 지금 줄이 목록 줄이다
        self._last_row = False  # 마지막으로 보낸 조각이 목록 줄에 있다
        self.cut = 0  # 길이 · 되풀이 · 묶음으로 뺀 문장 수(흔적)
        # 길게 둬도 되는 턴(LONG_* 상한): 대화 첫 답(소개 · 첫인사) · 업체 소개 · 견적 비교 카드를 보인 턴
        self.long_ok = long_ok
        self._hints: list[str] = []  # 이번 턴 도구 오류의 hint(모델에만 주는 글)
        # 업체 이름(같은 카드 · 채팅인지 가리는 대상)
        self.names: set[str] = {n for n in names if n}
        self.asked = frozenset(asked)  # 이 턴 고객 말이 묻는 것(policy.asked: fact · how)
        self._gone = 0  # 검사 · 묶음으로 빠진 본문 문장 수(외국어 속말 · 한자는 세지 않는다)
        self._back = False  # 바로 앞 문장이 내용 까닭으로 빠졌다(되가리키는 다음 문장도 뺀다)
        # 되풀이로 뺀 다음 할 일 문장(마지막 하나): 답에 다른 다음 할 일이 없으면 턴 끝에 살린다(settle)
        self._spare: _Piece | None = None
        # 지난 턴과 같은 지금 단계 문장을 뺐다(_same_state): 상태가 그대로라 지금 할 일 줄도 붙이지 않아요(next_step)
        self.state_cut = False
        # 바로 앞 비서 답들의 문장(답마다, 가까운 것부터, SPARE_RUN개). 주지 않으면 said 하나를 바로 앞 답으로 본다
        self.turns = [list(t) for t in turns] if turns is not None else [self.said]

    @property
    def text(self) -> str:
        return "".join(self._out).strip()

    def allow(self, text: str) -> None:
        """숫자 근거 글을 더한다(도구 결과 · 이 턴에 만든 · 보인 카드 값 · 지난 비서 말)."""
        self._allowed.append(text)
        self._ground = None

    def hint(self, text: str) -> None:
        """이번 턴 도구 오류의 hint(모델에만 주는 고칠 방법). 이 글을 옮긴 문장은 고객에게 보내지 않는다."""
        if text and text.strip():
            self._hints.append(text)

    def _grounds(self) -> guard.Ground:
        """허용 글의 숫자 근거(옛 검사 값 · 어림 · 파생 · 날짜, 금액 기준 꼬리표). 근거가 더해지면 다시 읽는다."""
        if self._ground is None:
            self._ground = guard.ground("\n".join(self._allowed), guard.basis(self._allowed))
        return self._ground

    async def feed(self, chunk: str) -> None:
        self._buf += chunk
        parts = SENT_END.split(self._buf)
        seps = SENT_END.findall(self._buf)
        if len(parts) <= 1:
            return
        self._buf = parts[-1]
        for text, sep in zip(parts[:-1], seps, strict=True):
            if text.strip():
                await self._one(text)
                self._sep = spacing(sep)
            else:  # 띄움만 이어졌다(글 조각 경계에서 빈 줄이 나뉨): 앞 띄움에 더한다
                self._sep = spacing(self._sep + sep)

    async def flush(self, drop_tail: bool = False) -> None:
        """모델 글 블록이 끝났다. drop_tail이면(max_tokens) 끊긴 마지막 문장을 버린다(묶음 안이면 묶음째)."""
        tail, self._buf = self._buf, ""
        if tail.strip() and not drop_tail:
            await self._one(tail)
        elif tail.strip():
            self.dropped.append("끊긴 문장")
            self._gone += 1
            if self._group is not None:
                self._group.bad = True
        busy = self._out or self._held or self._group or self._extra
        # 도구 뒤 글은 새 말풍선으로 연다(카드 앞뒤로 말풍선을 나눈다)
        self._sep = "\n\n" if busy else ""
        # 다음 블록(도구 뒤 글)은 새 줄로 본다(가리킨 목록이 도구 뒤에 와도 묶음에 든다)
        self._newline = True

    def discard(self) -> None:
        self._buf = ""

    def mark(self) -> tuple:
        """LLM 한 번을 부르기 전 상태(그 호출이 실패하면 undo로 그 시도의 글을 거둔다)."""
        keep = (
            self._sep,
            copy.deepcopy(self._held),
            copy.deepcopy(self._extra),
            copy.deepcopy(self._group),
            self._over,
            self._lost,
            self._newline,
            self._row,
            self._last_row,
            self._gone,
            self._back,
            self._spare,
            self.state_cut,
        )
        return len(self._out), keep, len(self.dropped), self.cut

    def undo(self, mark: tuple) -> bool:
        """실패한 LLM 시도의 글을 거둔다(끊긴 조각 · 붙잡은 · 넘친 · 모으던 문장). 그 시도에서 이미 보낸 글이 있으면
        (화면에 나갔다) 끊긴 조각만 버리고 False: 같은 요청을 다시 보내면 앞 글과 겹친다."""
        self._buf = ""
        out, keep, dropped, cut = mark
        if len(self._out) != out:
            return False
        (
            self._sep,
            self._held,
            self._extra,
            self._group,
            self._over,
            self._lost,
            self._newline,
            self._row,
            self._last_row,
            self._gone,
            self._back,
            self._spare,
            self.state_cut,
        ) = keep
        del self.dropped[dropped:]
        self.cut = cut
        return True

    def _check(self, raw: str) -> tuple[str | None, str | None]:
        """문장 하나의 검사: (보낼 글 | None, 버린 까닭)."""
        # 고객 글이 아닌 속말(도구 앞 영어 메모 · 영어 문장): 보내지도 기록하지도 않고 까닭만 흔적에
        if foreign(raw):
            return None, "외국어 속말" if HANGUL.search(raw) else "한글 없는 외국어 글"
        fixed = han_fix(raw)
        if fixed is None:
            return None, "한자 섞인 글"
        if fixed != raw:
            self.dropped.append("한자 지움")
            raw = fixed
        # 숫자: 근거 값 그대로에 더해 어림 · 파생 · 날짜를 읽는다(guard.loose, 08-rules 숫자 절). 통과한 값만 허용에 더해
        # 아래 검사(한글 금액 · 쓰면 안 되는 표현 · 한 일처럼 · 주소 · 누출)를 같이 지나게 한다
        g = self._grounds()
        bad, fine = guard.loose(check.mask(raw), g)
        ok, why = check.sentence_ok(
            Sentence(text=raw), set(g.nums) | fine, None, None, self._prompt
        )
        # 같은 값이 다른 자리(날짜 · 금액 묶음)에서 지나 위 검사가 놓친 숫자
        if ok is not None and bad is not None:
            ok, why = None, f"계산 결과 · 자료에 없는 숫자({bad})"
        if ok is not None and claims_done(ok.text):
            ok, why = None, "승인 없이 한 일처럼 말함"
        if ok is not None and policy.VS_STANDARD.search(ok.text):
            ok, why = None, "표준 대비 %"
        # 이름표 · 도구 · 칸 이름 · 도구 실패 같은 안쪽 말
        if ok is not None and (inner := policy.inside(ok.text)):
            ok, why = None, inner
        if ok is not None and any(policy.quotes(ok.text, h) for h in self._hints):
            ok, why = None, "도구 안내 글"  # 모델에만 준 hint를 옮긴 문장
        return (ok.text if ok is not None else None), why

    async def _one(self, text: str) -> None:
        if not text.strip():
            return
        sep, newline = self._sep, self._newline or "\n" in self._sep
        self._newline = False
        raw = text.strip()
        if newline:
            self._row = bool(policy.LIST_MARK.match(raw))
        row = newline and self._row  # 목록 줄을 여는 조각
        g = self._group
        if g is not None and not g.takes(newline, row):
            await self._close()
            g = None
        if g is None and row and not self._over:  # 머리 없는 목록 줄 묶음(앞 문장이 가리킴)
            counted = bool(self.sent) and policy.counted(self.sent[-1])
            g = self._group = _Group(head=False, counted=counted)
        ok, why = self._check(raw)
        if ok is not None and self._back and back_ref(ok):  # 가리킬 앞 문장이 빠졌다(고침 5차 R1)
            ok, why = None, BACK_WHY
        if ok is None:
            if why:
                self.dropped.append(why)
            if why not in NOISE:
                self._gone += 1
                self._back = True
            if g is not None:
                g.lose(raw, sep, newline, row)
            if not self._out:
                self._lost = True
            return
        self._back = False
        p = _Piece(sep, ok, policy.card_claim(ok), item=self._row, row=row)
        if g is not None:
            g.add(p, newline)
        elif self._over:
            self._extra.append(p)
        elif policy.pointer(ok):  # 앞으로 가리키는 문장: 가리킨 것을 볼 때까지 모은다
            self._group = _Group(head=True, members=[p], counted=policy.counted(ok))
        else:
            await self._admit(p)

    def _limits(self) -> tuple[int, int]:
        if self.long_ok:
            return policy.LONG_LEAD, policy.LONG_CHARS
        return policy.TALK_LEAD, policy.TALK_CHARS

    def _lead(self) -> tuple[int, int]:
        """바로 보낸 몫(보냄 · 붙잡음): (문장 수, 글자 수)."""
        texts = [*self.sent, *(p.text for p in self._held)]
        return len(texts), sum(map(len, texts))

    def _full(self, n: int, chars: int, whole: bool = False) -> bool:
        """n문장(chars자)을 더하면 상한을 넘는지. 문장 하나는 앞 몫이 상한 글자 수 전이면 되고(whole=False), 묶음은
        묶음 전체가 상한 안에 들어야 한다."""
        lead, size = self._limits()
        count, used = self._lead()
        if whole:
            return count + n > lead or used + chars > size
        return count + n > lead or used >= size

    async def _admit(self, p: _Piece) -> None:
        """묶음 밖 문장 하나: 상한 안이면 보내고, 넘치면 그 뒤 문장은 모두 넘친 문장이다(앞 답부터 남긴다)."""
        if self._full(1, len(p.text)):
            self._over = True
            self._extra.append(p)
            return
        await self._pass(p)

    async def _pass(self, p: _Piece) -> None:
        if self._held or (p.claim is not None and not self._true(p.claim)):
            self._held.append(p)  # 순서를 지키려고 뒤 문장도 기다린다
            return
        await self._send(p)

    async def _close(self) -> None:
        """모은 묶음을 정리한다: 안 문장이 검사로 빠졌으면 가리키는 말이 수를 말할 때만 묶음째 빼고, 아니면 빠진 문장만 뺀
        채(번호는 다시 매김) 둔다. 가리킨 것이 없는 머리는 뺀다. 상한 안이면 같이 보내고, 넘치면 통째로 뺀다(답 자체가
        목록이면 목록 줄 여덟까지)."""
        g, self._group = self._group, None
        if g is None:
            return
        if g.bad and g.counted:  # '세 가지예요' 뒤 한 줄이 빠지면 수가 틀린다
            self._gone += len(g.members)
            self._cut(g.members, "묶음째 뺌")
            self._back = True  # 뒤 '그중 …'이 가리킬 목록이 빠졌다(고침 5차 R1)
            return
        if g.bad:
            renumber(g.members)
        if not g.members:
            return
        if g.head and len(g.members) == 1:  # 뒤에 가리킨 것이 없다(다 빠졌거나 처음부터 없다)
            head = g.members[0]
            if policy.POINTER.search(head.text):
                self._gone += 1
                self._cut(g.members, "가리킨 말 없음")
            else:  # '…두 가지예요.'는 앞 말을 줄인 끝 문장일 수 있다
                await self._admit(head)
            return
        members = [replace(p, member=True) for p in g.members]
        if not self._full(len(members), sum(len(p.text) for p in members), whole=True):
            for p in members:
                await self._pass(p)
            return
        self._over = True
        if self._lead()[0]:
            self._cut(members, "길이 상한")
            return
        rows, keep = 0, 0
        for p in members:
            rows += p.row
            if rows > policy.LIST_FIRST:
                break
            keep += 1
        for p in members[:keep]:
            await self._pass(p)
        self._cut(members[keep:], "길이 상한")

    def _cut(self, pieces: list[_Piece], why: str) -> None:
        if not pieces:
            return
        self.cut += len(pieces)
        self.dropped.append(why)
        if not self._out:
            self._lost = True

    def _true(self, claim: tuple[str, set[str]]) -> bool:
        return policy.claim_ok(claim, self.made, self.opened, self.buttons)

    def _fresh(self, text: str) -> bool:
        """이 턴에 만든 카드 · 보인 카드 단추를 가리키는 말(같은 글이어도 새 안내다)."""
        new = self.made | self.buttons
        if not new:
            return False
        claim = policy.card_claim(text)
        if claim is not None:
            return bool(claim[1] & new) if claim[1] else True
        # 카드 종류를 읽을 수 있는 안내('실측 시간 카드가 열려 있어요')
        return bool(policy.aims(text) & new)

    def _repeat(self, text: str, said: Collection[str] | None = None) -> bool:
        """지난 비서 턴에 보낸 안내 · 권유 · 묻는 말 · 약속과 거의 같은 문장, 같은 카드 · 채팅 · 약속을 새 대상 없이 다시
        가리키는 안내(고침 4차 G, QA r4 c5 9~12턴 · c1 8~10턴). 새 안내(이 턴 카드) · 지난 일 · 새 소식은 아니고, 고객이
        금액 · 날짜를 물은 턴은 숫자가 든 사실 답을, 카드 · 할 일을 물은 턴은 같은 카드 안내를 둔다. said를 주면 그
        문장들과만 견준다(답 하나)."""
        said = self.said if said is None else said
        if self._fresh(text) or not policy.guide(text, numbers=not self.asked):
            return False
        if any(policy.near_same(text, x) for x in said):
            return True
        return (
            "how" not in self.asked
            and not policy.past(text)
            and any(policy.same_aim(text, x, self.names) and not policy.past(x) for x in said)
        )

    def _twice(self, text: str) -> bool:
        """같은 안내가 바로 앞 두 답(SPARE_RUN)에 다 있었다: 살리면 세 번째 연속이다."""
        last = self.turns[:SPARE_RUN]
        return len(last) >= SPARE_RUN and all(self._repeat(text, t) for t in last)

    def _same_state(self, text: str) -> bool:
        """지금 단계 문장(policy.now_state)이 지난 비서 턴(said)의 지금 단계 문장과 같은 업체 · 날짜 · 반나절만 말하는지
        (새 대상 없음, QA r7 c1 20~23턴: '우리집벽지 실측 내일 오전' 끝맺음 네 턴). 업체 이름이 없는 문장 · 고객이 금액 ·
        날짜 · 할 일을 물은 턴은 보지 않아요."""
        if self.asked or not policy.now_state(text):
            return False
        mine = policy.targets(text, self.names)
        if not mine[2]:
            return False
        return any(
            policy.now_state(x)
            and all(a <= b for a, b in zip(mine, policy.targets(x, self.names), strict=True))
            for x in self.said
        )

    async def _send(self, p: _Piece) -> None:
        """검사를 지난 문장 하나를 보낸다. 이 턴에 보낸 문장과 같으면 빼고, 첫 문장이 아닌 지난 턴 안내 되풀이도 뺀다
        (묶음 안 문장은 목록이 비지 않게 둔다)."""
        if any(policy.same_line(p.text, x) for x in self.sent):
            self.dropped.append("같은 문장")
            self.cut += 1
            return
        # 지난 턴과 같은 지금 단계(상태가 그대로)면 다시 말하지 않아요
        if self._out and not p.member and self._same_state(p.text):
            self.state_cut = True
            self.dropped.append("지난 턴과 같은 지금 단계")
            self.cut += 1
            return
        if self._out and not p.member and self._repeat(p.text):
            if policy.points(
                p.text
            ):  # 가리키는 다음 할 일(카드 · 채팅 · 누를 것): 다른 게 없으면 끝에 살린다(settle)
                self._spare = p
                return
            self.dropped.append("지난 턴과 같은 안내")
            self.cut += 1
            return
        await self._put(p.sep, p.text, p.item)

    def _needs_next(self) -> bool:
        """보낸 답에 다음 걸음(policy.leads: 가리키는 말 · 묻는 말 · 고르기 · 누르기 같은 할 일을 하라는 말)이 없고, 이 턴에
        만든 승인 카드 · 보인 카드 단추 · 열려 있는 승인 카드도 없다. 열린 승인 카드가 있으면 그 카드가 화면의 다음 걸음이라 '눌러 주세요'
        되풀이는 살리지 않는다(QA r2 · r4 c5: 같은 재촉이 턴마다 끝에 붙음). '고르지 않거나'처럼 낱말만 닮은 문장은 다음
        할 일로 보지 않는다."""
        if self.made or self.buttons or self.opened:
            return False
        return not any(policy.leads(s) for s in self.sent)

    async def _put(self, sep: str, text: str, item: bool = False) -> None:
        if not self._out and self._lost:  # 앞 문장이 빠져 첫 문장이 됐다: '다만 · 대신 …'을 뗀다
            text = policy.strip_lead(text)
        if self._out and self._last_row and not item and "\n" not in sep:
            sep = "\n"  # 목록 줄 끝에 다른 문장을 잇지 않는다(넘친 묻는 말 · 빠진 문장 뒤)
        piece = (sep if self._out else "") + text
        self._out.append(piece)
        self.sent.append(text)
        self._last_row = item
        await self._emit("token", {"text": piece})

    async def cards(self, kinds: Collection[str], *, fresh: bool) -> None:
        """제안 도구가 승인 카드를 만들었다(fresh) · 열린 같은 카드를 다시 썼다. 맞게 된 문장부터 놓아준다."""
        (self.made if fresh else self.opened).update(kinds)
        await self._release()

    async def shown(self, card: CardOut) -> None:
        """화면 카드를 보냈다: 그 카드 단추를 누르라는 말이 맞게 되고, 업체 소개 · 견적 비교 카드면 길게 둔다."""
        if card.kind in policy.LONG_CARDS:
            self.long_ok = True
        got = policy.buttons_of(card.kind, card.data)
        if got:
            self.buttons |= got
            await self._release()

    async def _release(self) -> None:
        while self._held:
            p = self._held[0]
            if p.claim is not None and not self._true(p.claim):
                return
            self._held.pop(0)
            await self._send(p)

    async def settle(self) -> None:
        """턴 끝: 모으던 묶음을 정리하고 붙잡아 둔 문장을 보낸다. 끝까지 틀린 카드 말은 첫 것만 정직한 한 줄로 바꾸고
        나머지는 뺀다. 넘친 문장은 마지막 묻는 말 하나만 끝에 보낸다."""
        await self._close()
        held, self._held = self._held, []
        for p in held:
            if p.claim is None or self._true(p.claim):
                await self._send(p)
                continue
            self.dropped.append("카드 없이 카드를 말함")
            if p.claim[0] == "made" and self.before:
                continue
            if not self._fixed:
                self._fixed = True
                await self._send(_Piece(p.sep, policy.honest(p.claim, self.opened | self.made)))
        last = self._tail()
        if last is not None:
            await self._put(last.sep, last.text)
        # 다음 할 일이 되풀이로 뺀 이 문장뿐이면 남긴다(QA r6 c3 t19). 바로 앞 두 답에도 있었으면 세 번째라 뺀다
        spare, self._spare = self._spare, None
        if spare is not None and self._needs_next() and not self._twice(spare.text):
            await self._put(spare.sep, spare.text, spare.item)
        elif spare is not None:
            self.dropped.append("지난 턴과 같은 안내")
            self.cut += 1

    async def mend(self, cards: bool) -> None:
        """LLM 턴 끝(settle 뒤): 검사 · 묶음으로 답의 본문이 빠져 보낸 글이 없거나 가리키는 말(카드 · 단추 · 채팅 · 앞으로
        가리키는 문장)뿐이면 정해 둔 정직한 한 줄을 끝에 보낸다(고침 4차 G, QA r4 c2 15턴: 초안이 빠지고 없는 카드 단추를
        가리키는 한 줄만 남음). 이 턴에 카드가 있으면 FAIL_TEXT, 없으면 CUT_TEXT. 카드 말 정직한 한 줄을 이미 썼으면 없다."""
        if not self._gone or self._fixed or any(not policy.points(s) for s in self.sent):
            return
        await self._put("\n\n", FAIL_TEXT if cards else CUT_TEXT)  # 정직한 한 줄은 따로 한 말풍선

    def _tail(self) -> _Piece | None:
        """넘친 문장 중 끝에 보낼 마지막 묻는 말 하나(목록 줄 · 가리키는 문장 · 맞지 않는 카드 말 · 이 턴과 같은 말 ·
        지난 턴 되풀이는 아님). 이미 보낸 글에 묻는 말이 있으면 없다. 나머지는 뺀다."""
        extra, self._extra = self._extra, []
        pick = None
        asks = [
            p for p in extra if policy.asks(p.text) and not p.item and not policy.pointer(p.text)
        ]
        if asks and not any(policy.asks(s) for s in self.sent):
            p = asks[-1]
            fine = p.claim is None or self._true(p.claim)
            seen = any(policy.same_line(p.text, x) for x in self.sent)
            if fine and not seen and not (self._out and self._repeat(p.text)):
                pick = p
        self._cut([p for p in extra if p is not pick], "길이 상한")
        return pick


# ---- 턴 ----


@dataclass
class TurnCtx:
    """start_turn이 짧은 세션으로 채운 값(LLM 출력으로 바꾸지 않는다)."""

    turn_id: uuid.UUID
    chat_id: uuid.UUID
    user: User
    surface: str
    project_id: uuid.UUID | None
    visit_id: uuid.UUID | None
    today: date
    now: datetime
    text: str  # 가린 고객 글
    choice: list[str]  # 카드에서 고른 ref(아는 것만)
    history: list[dict]  # 지난 글(Claude 꼴, 오래된 것부터)
    facts: str  # 턴 사실(코드 값만)
    rev: int
    refs: RefTable
    client_key: str
    card_id: str | None = None
    # 지난 카드 단추(모르는 이름표 · 다른 대상): 카드를 새로 불러온다
    stale: list[str] = field(default_factory=list)
    # 카드 단추가 보낸 턴(context.choice가 있음): 글은 화면이 만든 말이라 기억을 뽑지 않는다
    pressed: bool = False


@dataclass
class TurnResult:
    mode: str = "llm"
    status: str = "done"  # done · stopped
    text: str = ""  # 대화에 남길 답 글(검사를 지난 것)
    cards: list[dict] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)  # 흔적: 이름 · 성공 · 크기 · 걸린 시간(글 없음)
    llm_calls: int = 0
    tool_calls: int = 0
    cost_micros: int = 0
    stop: str | None = None
    reason: str = "ok"
    chips: list[str] = field(default_factory=list)
    # 이 턴에 카드 단추 고르기로 새로 만든 승인 카드 종류(SentenceGate가 '만들었어요'를 맞다고 본다)
    made: set[str] = field(default_factory=set)
    # 이 턴에 새로 만든 승인 카드 id(단추 고르기 · 제안 도구). 같은 턴에 다시 제안하면 모델에도 '새로 만듦'으로 알린다
    made_ids: set[str] = field(default_factory=set)
    cut: int = 0  # 길이 상한 · 되풀이로 뺀 문장 수
    # 문장 검사가 버린 문장의 까닭(종류만, 글 없음)
    dropped: list[str] = field(default_factory=list)
    # 무료 모드로 넘어가기 전에 화면에 보낸 LLM 글의 길이(저장한 답 글 앞부분). 다시 열 때 AI 글로 보인다
    kept: int = 0
    # 요청 점검(asks.py): 고객 말에서 뽑은 부탁 이름 · 턴 끝에 못 채운 것 · 한 번 더 기회를 줬는지(글 없음)
    asks: list[str] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    asks_retry: bool = False

    def trace(self, rev: int, ms: int) -> dict:
        out = {
            "rev": rev,
            "llm": self.llm_calls,
            "tools": self.tools,
            "actions": self.actions,
            "stop": self.stop,
            "reason": self.reason,
            "ms": ms,
            "cut": self.cut,
            "dropped": self.dropped[:DROPPED_MAX],
            "kept": self.kept,
        }
        if self.asks:  # 부탁이 있던 턴만(요청 점검 평가가 읽는다)
            out["asks"] = {"want": self.asks, "unmet": self.unmet, "retry": self.asks_retry}
        return out


class _Fallback(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def breaker_open() -> bool:
    try:
        return bool(await queue.redis.exists(BREAKER_KEY))
    except REDIS_ERRORS:
        return False


async def _trip() -> None:
    try:
        await queue.redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL, nx=True)
    except REDIS_ERRORS:
        return


# 카드 종류 → 빠른 답 칩(정해 둔 글, 그 칩이 맞는 단계 사실). 사실(service.chip_facts, 코드 값):
# visits 실측을 요청함 · quote 받은 실측 견적서가 있음 · dates 수락한 공사 날짜가 있음(고객),
# requested 답할 요청 · visited 견적서를 낼 요청(업체 브리핑의 요청). '!사실'은 그 사실이 없을 때만
CHIPS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "standard_quote": (("업체 추천해 줘", "!visits"), ("가견적은 어떻게 계산해요?", None)),
    "vendor_picks": (("가견적은 어떻게 계산해요?", None), ("실측은 무엇을 봐요?", None)),
    "visit_slots": (("다른 날짜도 볼래요", None), ("실측은 무엇을 봐요?", None)),
    "quote_compare": (("폐기물 처리도 포함인가요?", "quote"), ("표준견적서 다시 보기", None)),
    "schedule": (("공사 전날 준비물", "dates"), ("공정표 보기", None)),
    "today": (("견적서 비교 보기", "quote"), ("오늘 할 일 다시 보기", None)),
    "vendor_brief": (("빈 시간 보여 줘", "requested"), ("견적서 체크리스트", "visited")),
}


def _chip_ok(need: str | None, facts: Collection[str]) -> bool:
    if need is None:
        return True
    return need[1:] not in facts if need.startswith("!") else need in facts


def chips_for(cards: list[dict], facts: Collection[str] = ()) -> list[str]:
    """마지막 카드 종류로 고른 빠른 답 칩(정해 둔 글) 중 지금 공사 단계 사실(facts)에 맞는 것만."""
    for c in reversed(cards):
        if c["kind"] in CHIPS:
            return [text for text, need in CHIPS[c["kind"]] if _chip_ok(need, facts)]
    return []


def off_topic(ctx: TurnCtx, note: str | None = None) -> bool:
    """인테리어와 상관없는 부탁 · 잡담(음식 · 날씨 · 놀이 · 돈 · 다른 앱 일)이면 LLM을 부르지 않고 막는다
    (2026-11-23 사용자: '치킨 먹고 싶다'에 맞장구). 판별은 무료 모드와 같은 코드(free.off_kind, 공사 낱말이 없을 때만
    맞음)예요. 대신 전화 · 문자 부탁은 비서가 앱 안 알림으로 도울 수 있어 빼고, 비서가 바로 앞에서 물었으면 그 답일 수
    있어('날씨 풀리면요') 막지 않아요."""
    from app.assistant import free

    if ctx.surface != "customer" or ctx.pressed or ctx.choice or note:
        return False
    got = free.off_kind(ctx.text)
    return got is not None and got[0] != "call" and not asked_last(ctx.history)


# 다음 일로 이끄는 카드(집 정보 · 업체 추천 · 실측 시간 · 견적서 비교 · 공사 날짜 · 오늘 할 일 …): 이 카드가 나온 턴에는 한
# 줄을 붙이지 않아요. 표준견적서 카드는 금액을 보여 줄 뿐 다음 할 일을 알려 주지 않아 빼요(2026-11-23 평가: 실측 · 공사
# 단계에서 표준견적서 카드가 다음 단계 줄을 막음). 카드 이름 표에 더한 07 · 고르기 · 조사 카드는 그대로 빼요(이름만
# 더했어요, R1a B7)
STEP_CARDS = frozenset(CARD_NAME) - {
    "knowledge", "answer", "standard_quote",
    "extra", "notice", "grade_compare", "market_range", "options", "research", "product_estimate",
}  # fmt: skip
# 지금 할 일 줄을 붙여도 답이 이 문장 수를 넘지 않을 때만 붙여요(지시문 '많아야 네 문장', QA r6 · FA2: 코드가 붙인 줄로
# 다섯 문장 넘는 답이 생김). 넘으면 이번 턴은 붙이지 않고 같은 단계의 다음 답에 붙어요(now_said는 붙인 줄만 셈)
STEP_ROOM = 4


async def next_step(turn: "_Turn", res: TurnResult) -> str:
    """다음 할 일 없이 끝난 답 뒤 지금 할 일 한 줄(2026-11-23 사용자: 쓰면서 다음 흐름으로 이끌기, 지식 답 40개 중 3개만
    다음 단계를 말함 · QA r6 c3 M8 · c1 M12: 막는 답 · 범위 밖 답 · '사람이야?' 답이 다음 할 일 없이 끝남). 답에 다음
    걸음(policy.leads: 가리키는 말 · 묻는 말 · 할 일을 하라는 말)이 없고, 다음 일 카드 · 승인 카드가 없을 때 코드가 지금
    할 일 줄(free.now_tail: 무료 · 범위 밖 답과 같은 줄)을 붙여요. 막는 답인지는 낱말로 가르지 않고 답 꼴로 봐요. 같은
    단계에서는 한 번만 나와요(상태가 바뀌었거나 처음일 때만). 인사 · 고마움만 한 턴(chat_only)은 붙이지 않아요.
    이 턴 전문가 답에 확인할 조건이 있으면(turn.ask) 지금 할 일 줄 대신 그 조건을 묻는 한 문장을 붙여요."""
    from app.assistant import free

    ctx = turn.ctx
    if ctx.surface != "customer" or ctx.pressed or ctx.choice or res.actions or turn.chat_only:
        return ""
    if STEP_CARDS & {c["kind"] for c in res.cards} or res.text.rstrip().endswith("?"):
        return ""
    if any(policy.leads(s) for s in turn.gate.sent):
        return ""
    if len(turn.gate.sent) >= STEP_ROOM:  # 붙이면 많아야 네 문장을 넘어요
        return ""
    # 전문가 답의 확인할 조건을 끝 물음으로(지금 할 일 줄보다 먼저, QA r7 c1 6 · 10 · 13 · 25턴)
    if turn.ask:
        asked, _why = turn.gate._check(turn.ask)  # 숫자 · 안쪽 말 검사(모델 문장과 같은 검사)
        if asked and asked not in res.text:
            return asked
    # 지금 단계는 한 답에 한 번: 모델이 이미 말했거나(QA r7 c1 19 · 27턴) 지난 턴과 같은 상태라 뺐으면 붙이지 않아요
    if turn.gate.state_cut or any(policy.now_state(s) for s in turn.gate.sent):
        return ""
    try:
        line = await free.now_tail(turn.tc)
    except Exception as e:  # noqa: BLE001 - 할 일 줄을 못 읽으면 붙이지 않아요(종류 이름만 로그)
        log.warning("다음 할 일 줄 실패 (%s)", type(e).__name__)
        return ""
    return line if line and line not in res.text else ""


async def first_card(ctx: TurnCtx, res: TurnResult, emit: Emit) -> None:
    """대화 첫 말에 한글이 없고(이모지 · 다른 말만) 첫 답에 카드가 없으면 오늘 정할 일 카드를 붙여요(QA r6 c3: 첫 말이
    '🏠🔨🤯❓'면 열린 질문만 하고 이끌 카드 · 칩이 없었어요. 지시문 예시 1 '처음 인사'와 같은 꼴). 뜻을 읽을 수 있는 첫
    말은 모델이 정해요. 정할 일 · 기다리는 일이 없으면 붙이지 않아요."""
    from app.assistant.tools import cards
    from app.db import SessionLocal

    if ctx.surface != "customer" or ctx.project_id is None or ctx.pressed or ctx.choice:
        return
    if (
        res.cards
        or HANGUL.search(ctx.text)
        or any(m.get("role") == "assistant" for m in ctx.history)
    ):
        return
    try:
        async with SessionLocal() as s:
            card, _ = await cards.today(s, ctx.user, ctx.project_id, ctx.today, ctx.now, ctx.refs)
    except Exception as e:  # noqa: BLE001 - 못 읽으면 붙이지 않아요(종류 이름만 로그)
        log.warning("첫 답 오늘 카드 실패 (%s)", type(e).__name__)
        return
    if any(card.data.get(k) for k in ("todo", "waiting", "know")):
        await send_card(res, emit, card)


def asked_last(history: list[dict]) -> bool:
    """지난 글 중 마지막 비서 글이 물음표로 끝났는지."""
    for m in reversed(history):
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        blocks = c if isinstance(c, list) else []
        text = (
            c
            if isinstance(c, str)
            else " ".join(
                str(b.get("text") or "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            )
        )
        return text.rstrip().endswith("?")
    return False


def said(ctx: TurnCtx, note: str | None = None) -> str:
    """모델에 보낼 이번 고객 글: 가린 글 + 카드에서 고른 것 + 코드가 처리한 한 줄. 비면 ''(빈 글 블록은 보내지 않는다)."""
    text = ctx.text
    if ctx.choice:
        text += f"\n(카드에서 고름: {', '.join(choices.text_of(c) for c in ctx.choice)})"
    if note:
        text += f"\n({note})"
    return text.strip()


async def send_card(res: TurnResult, emit: Emit, card: CardOut) -> None:
    """카드 하나를 보내고 턴 결과에 남긴다(같은 card_id면 바꿔 끼운다)."""
    data = card.model_dump(mode="json")
    res.cards = [c for c in res.cards if c["card_id"] != card.card_id] + [data]
    await emit("card", data)


class _Turn:
    def __init__(
        self,
        ctx: TurnCtx,
        emit: Emit,
        res: TurnResult,
        note: str | None = None,
        seen: Collection[tuple[str, dict]] = (),
    ) -> None:
        self.ctx, self.emit, self.res = ctx, emit, res
        self.note = note  # 카드 고르기를 코드가 처리한 결과(모델에 알릴 한 줄)
        self.budget = policy.TurnBudget(
            started=time.monotonic(), cap_micros=round(settings.llm_cap_turn_usd * 1_000_000)
        )
        self.system = prompts.system(ctx.surface)
        self.defs = tools_mod.defs(ctx.surface)  # type: ignore[arg-type]
        # 허용 숫자: 이번 고객 글 · 턴 사실 + 대화 기록의 고객 말(앞 턴에 고객이 한 '7시'를 다시 말할 수 있게, 고정 선 2)
        said_before = "\n".join(
            m["content"]
            for m in ctx.history
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        )
        self.gate = SentenceGate(
            emit,
            # 누출은 규칙 절과만 견준다(성격 소개 · 좋은 예시 · 그대로 말해도 되는 말을 닮은 답은 버리지 않게)
            prompts.rules(ctx.surface),
            f"{ctx.text}\n{ctx.facts}\n{said_before}",
            made=res.made,
            said=recent_said(ctx.history),
            turns=said_turns(ctx.history),
            # 대화 첫 답은 소개 · 첫인사라 길게 둔다(08-rules '소개 답은 예외', 상한은 LONG_*)
            long_ok=not any(m.get("role") == "assistant" for m in ctx.history),
            # 같은 카드 · 채팅인지 가리는 업체 이름(턴 사실 업체 줄 · 이 대화 이름표 표, 열린 카드 업체는 run에서 더함)
            names=fact_names(ctx.facts) | ref_names(ctx.refs),
            asked=policy.asked(ctx.text),
        )
        # 지난 비서 말 두 개(이미 검사를 지나 보낸 글)도 숫자 근거다: 앞 턴에 말한 가견적을 '만 원 단위로'처럼 다시 말할
        # 수 있게(고침 5차 R1, QA r5 C s5-4). 그 말에 없는 숫자 · 반올림 단위의 반을 넘는 어림은 지금처럼 뺀다
        if told := told_before(ctx.history):
            self.gate.allow(told)
        # 카드 단추 고르기(choices)가 이 턴에 보낸 카드 · 승인 카드: 숫자 근거 · 누를 단추 · 길게 둘 카드
        if note:
            self.gate.allow(note)
        for name, data in seen:
            if name == "card":
                self.gate.allow(card_ground(data.get("data") or {}))
                self.gate.buttons |= policy.buttons_of(
                    str(data.get("kind")), data.get("data") or {}
                )
                self.gate.long_ok |= data.get("kind") in policy.LONG_CARDS
            elif name == "action" and data.get("status") == "proposed":
                self.gate.allow(summary_ground(data.get("summary") or {}))
        # 인사 · 고마움만 한 턴: 도구를 부르지 못하게(도구 정의는 그대로 보내 캐시를 지킨다)
        self.chat_only = policy.small_talk(ctx.text) and not ctx.choice and not ctx.stale
        # 요청 점검(asks.py): 고객 비서에서 고객이 직접 쓴 말만(카드 단추가 만든 말 · 인사는 아님)
        plain = ctx.surface == "customer" and not self.chat_only and not ctx.pressed
        self.asks = asks_mod.extract(ctx.text) if plain else asks_mod.NONE
        # 이 턴에 보인 카드 · 만든 승인 카드 · 부른 카드 도구의 카드 종류(요청 점검이 견준다)
        self.done: set[str] = {str(d.get("kind")) for _, d in seen if d.get("kind")}
        self.rechecked = False
        # 이 턴 전문가 답의 확인할 조건 끝 물음(answer.ask_tail): 답에 묻는 말 · 다음 걸음이 없으면 끝에 붙여요(next_step)
        self.ask: str | None = None
        self.errors: Counter[tuple[str, str]] = Counter()
        self.beat_at = time.monotonic()
        self.tc = ToolCtx(
            user=ctx.user,
            surface=ctx.surface,  # type: ignore[arg-type]
            turn_id=ctx.turn_id,
            chat_id=ctx.chat_id,
            project_id=ctx.project_id,
            visit_id=ctx.visit_id,
            today=ctx.today,
            now=ctx.now,
            refs=ctx.refs,
            text=ctx.text,
        )

    def _messages(self) -> list[dict]:
        facts = self.ctx.facts
        if want := asks_mod.line(self.asks):  # 요청 점검: 이번 부탁(코드가 고객 말에서 뽑음)
            facts = f"{facts}\n{want}" if facts else want
        return [
            *self.ctx.history,
            {"role": "user", "content": [{"type": "text", "text": said(self.ctx, self.note)}]},
            {"role": "system", "content": facts},
        ]

    async def _beat(self, force: bool = False) -> None:
        if not force and time.monotonic() - self.beat_at < BEAT_EVERY:
            return
        self.beat_at = time.monotonic()
        from app.assistant import repository as repo
        from app.db import SessionLocal
        from app.shared.clock import now_utc

        try:
            async with SessionLocal() as s:
                await repo.beat(s, self.ctx.turn_id, now_utc())
                await s.commit()
        except Exception as e:  # noqa: BLE001 - heartbeat는 지워져도 되는 표시(턴은 이어 간다)
            log.warning("비서 heartbeat 실패 (%s)", type(e).__name__)

    async def card(self, card: CardOut) -> None:
        await send_card(self.res, self.emit, card)
        await self.gate.shown(card)
        self.done.add(card.kind)

    def _sent_same(self, card: CardOut) -> bool:
        """이 턴에 같은 카드(같은 id · 같은 값)를 이미 보냈는지."""
        data = card.model_dump(mode="json")
        return any(c == data for c in self.res.cards if c.get("card_id") == card.card_id)

    async def _open_kinds(self) -> set[str]:
        """턴 앞에 열려 있는 승인 카드 종류(카드를 눌러 달라는 말이 맞는지 본다). 못 읽으면 빈 집합. 그 카드의 업체
        이름은 되풀이 거름의 대상 이름(gate.names)에 더한다."""
        from app.assistant import repository as repo
        from app.db import SessionLocal

        try:
            async with SessionLocal() as s:
                rows = await repo.actions_of(
                    s,
                    self.ctx.user.id,
                    self.ctx.surface,
                    project_id=self.ctx.project_id,
                    limit=20,
                )
        except Exception as e:  # noqa: BLE001 - 못 읽으면 열린 카드가 없는 것으로 본다(말이 더 정직해진다)
            log.warning("비서 열린 카드 읽기 실패 (%s)", type(e).__name__)
            return set()
        live = [a for a in rows if a.status == "proposed" and a.expires_at > self.ctx.now]
        for a in live:
            self.gate.names |= card_vendors(a.summary)
        since = self.ctx.now - timedelta(hours=BEFORE_HOURS)
        self.gate.before = {a.kind for a in rows if a not in live and a.created_at > since}
        return {a.kind for a in live}

    async def run(self) -> None:
        self.gate.opened |= await self._open_kinds()
        with llm.call_ctx(self.ctx.user.id, self.ctx.turn_id, "assistant") as cc:
            try:
                await self._loop(cc)
            finally:  # 무료 모드로 넘어가도 쓴 비용 · 호출 수는 남긴다
                self.res.cost_micros = cc.spent_micros
                self.res.llm_calls = self.budget.llm
                self.res.tool_calls = self.budget.tools
                self.res.asks = self.asks.keys()
                self.res.unmet = [f"show:{k}" for k in asks_mod.missing(self.asks, self.done)]
                self.res.asks_retry = self.rechecked

    def _recheck(self, messages: list[dict], wrap: bool) -> bool:
        """요청 점검: 모델이 도구 없이 답을 마쳤는데 보여 달라 · 바꾸겠다고 한 카드를 이 턴에 보이지도 부르지도 않았으면,
        상한 안에서 한 번만 점검 글을 붙여 다시 부른다(앞 글은 이미 보냈고 이어서 쓴다). 점검 글은 모델에만 간다."""
        if self.rechecked or wrap or self.chat_only:
            return False
        miss = asks_mod.missing(self.asks, self.done)
        if not miss or not self.budget.can_call() or not self.budget.tool_ok():
            return False
        self.rechecked = True
        text = asks_mod.nudge(miss)
        self.gate.hint(text)
        messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
        return True

    async def _loop(self, cc: llm.CallCtx) -> None:
        messages = self._messages()
        wrap = False
        pauses = fails = 0
        while True:
            b = self.budget
            b.spent_micros = cc.spent_micros
            over = b.over(time.monotonic())
            if over and not wrap:
                wrap, self.res.stop = True, over
                self._wrap(messages)
            if not b.can_call():
                self.res.status = "stopped"
                break
            mark = self.gate.mark()
            try:
                reply = await asyncio.wait_for(
                    llm.claude_stream(
                        self.system,
                        messages,
                        tools=self.defs,
                        on_text=self.gate.feed,
                        purpose="assistant",
                        tool_choice={"type": "none"} if wrap or self.chat_only else None,
                    ),
                    timeout=b.left(time.monotonic(), wrap),
                )
            except (llm.LLMOff, llm.OverBudget) as e:
                self.gate.discard()
                raise _Fallback("off" if isinstance(e, llm.LLMOff) else "budget") from None
            except TimeoutError:
                b.llm += 1
                self.gate.discard()
                self.res.status, self.res.stop = "stopped", "time"
                break
            except llm.LLMRejected:
                # 요청 자체가 틀렸다: 다시 보내도 같다(이 턴만 무료 모드, 차단기에 세지 않는다)
                b.llm += 1
                self.gate.undo(mark)
                raise _Fallback("rejected") from None
            except llm.LLMError:
                b.llm += 1
                fails += 1
                clean = self.gate.undo(mark)  # 실패한 시도의 글을 거둔다
                if fails >= 2:
                    await _trip()
                    raise _Fallback("breaker") from None
                if not clean:
                    # 이 시도에서 글을 이미 보냈다: 다시 쓰면 앞 글과 겹친다(무료 모드로 잇는다)
                    raise _Fallback("error") from None
                continue
            b.llm += 1
            b.spent_micros = cc.spent_micros
            await self._beat()
            if reply.stop == "refusal":
                self.gate.discard()
                raise _Fallback("refusal")
            if reply.stop == "max_tokens":
                await self.gate.flush(drop_tail=True)
                break
            await self.gate.flush()
            if reply.content:  # 빈 assistant 메시지는 보내지 않는다(400)
                messages.append({"role": "assistant", "content": reply.content})
            if reply.stop == "pause_turn":
                pauses += 1
                if pauses > PAUSE_MAX:
                    self.res.status, self.res.stop = "stopped", "pause"
                    break
                continue  # 서버 도구를 이어 가게 같은 요청을 다시 보낸다(새 말 없이)
            if reply.stop != "tool_use" or not reply.tool_calls:
                if self._recheck(messages, wrap):
                    continue
                break
            if wrap:  # 마무리 한 번에도 도구를 부르면 카드만으로 끝낸다
                self.res.status = "stopped"
                messages.pop()
                break
            results, failed = await self._tools(reply.tool_calls)
            messages.append({"role": "user", "content": results})
            if not self.budget.tool_ok() and not wrap and failed is None:
                wrap, self.res.stop = True, "tools"  # 도구를 다 썼다: 다음 한 번은 마무리
                self._wrap(messages)
            if failed is not None:
                await self.card(
                    CardOut(
                        card_id=f"fail-{self.ctx.turn_id}",
                        kind="answer",
                        data=AnswerData(text=TOOL_FAIL, src="guide").model_dump(mode="json"),
                    )
                )
                self.res.status, self.res.stop = "stopped", "tool_error"
                break

    def _wrap(self, messages: list[dict]) -> None:
        """'지금까지로 답해요'를 마지막 user 메시지 끝에 붙인다(도구 결과 블록 뒤)."""
        block = {"type": "text", "text": WRAP}
        last = messages[-1] if messages else None
        if last and last["role"] == "user" and isinstance(last["content"], list):
            last["content"] = [*last["content"], block]
        else:
            messages.append({"role": "user", "content": [block]})

    async def _tools(self, calls: list[dict]) -> tuple[list[dict], str | None]:
        results: list[dict] = []
        failed: str | None = None
        for call in calls:
            name, cid = str(call.get("name")), str(call.get("id"))
            if not self.budget.tool_ok():
                results.append(
                    self._error(cid, "tool_limit", "도구 상한이에요. 지금까지로 답해 주세요.")
                )
                continue
            self.budget.tools += 1
            block, code = await self._one(name, cid, call.get("input"))
            results.append(block)
            if code is not None and code != "tool_limit":
                self.errors[(name, code)] += 1
                if self.errors[(name, code)] >= 2 and failed is None:
                    failed = name
        return results, failed

    @staticmethod
    def _error(cid: str, code: str, message: str, hint: str | None = None) -> dict:
        got = {"error": code, "message": message, **({"hint": hint} if hint else {})}
        body = json.dumps(got, ensure_ascii=False)
        return {"type": "tool_result", "tool_use_id": cid, "content": body, "is_error": True}

    async def _one(self, name: str, cid: str, args) -> tuple[dict, str | None]:
        t0 = time.monotonic()
        trace = {"name": name, "ok": False, "size": 0, "ms": 0}
        self.res.tools.append(trace)
        # 요청 점검: 카드 도구를 불렀으면 '해 봄'(실패해도 다시 부르지 않게)
        self.done |= asks_mod.tried(name, args)
        try:
            t = tools_mod.get(name, self.ctx.surface)  # type: ignore[arg-type]
            await self.emit("status", {"text": t.status})
            await self._beat()  # 오래 걸리는 도구(도면 찾기 · 웹 검색) 앞에도 살아 있다고 남긴다
            # 도구도 턴 시간(45초) 안에서만 기다린다(정리 sweep이 멈춘 턴으로 닫고 다 만든 답을 버리지 않게)
            left = max(self.budget.left(time.monotonic(), wrap=False), TOOL_MIN)
            out = await asyncio.wait_for(tools_mod.run(t, self.tc, args), timeout=left)
        except ToolError as e:
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            if e.hint:  # 모델에만 주는 글: 답에 옮기면 문장 검사가 뺀다
                self.gate.hint(e.hint)
            return self._error(cid, e.code, e.message, e.hint), e.code
        except AppError as e:  # 기능 service 오류(404 · 409 …): 코드와 정해 둔 문장만
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            return self._error(cid, e.code, e.message), e.code
        except TimeoutError:
            log.warning("비서 도구 시간 넘음 (%s)", name)
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            return self._error(cid, "tool_timeout", "시간이 너무 걸려 멈췄어요."), "tool_timeout"
        except Exception as e:  # noqa: BLE001 - 도구 하나의 실패는 is_error로 돌려준다(종류 이름만 로그)
            log.warning("비서 도구 실패 (%s, %s)", name, type(e).__name__)
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            return self._error(cid, "tool_failed", "도구를 쓰지 못했어요."), "tool_failed"
        given = out.data
        if name == "answer_question" and (tail := answer_tools.ask_tail(given)):
            self.ask = tail
        # 이 턴에 똑같이 보낸 카드는 다시 보내지 않고 모델에 알린다(QA r6 c3 H1: 업체 추천 뒤 show_card로 같은 카드
        # 두 번). 값이 달라진 같은 카드(제안 도구가 바뀜 칸을 단 집 정보 카드)는 화면이 그 자리에서 바꿔 끼운다
        shown = [c for c in out.cards if not self._sent_same(c)]
        if len(shown) < len(out.cards):
            given = {**given, "note": " ".join(x for x in (given.get("note"), SAME_CARD) if x)}
        ids = {str(a.action_id) for a in out.actions}
        if t.kind == "propose" and ids:
            # 같은 턴에 단추 고르기 · 앞 제안이 이미 만든 카드면 도구는 'same'이지만 고객에게는 방금 만든 카드다
            if given.get("state") == "same" and ids <= self.res.made_ids:
                given = {**given, "state": "new", "note": MADE_NOW}
            if given.get("state") == "new":
                self.res.made_ids |= ids
        data = policy.to_model(given)
        body = json.dumps(data, ensure_ascii=False, default=str)
        self.gate.allow(body)
        # 이 턴에 만든 승인 카드 요약 · 보인 화면 카드의 값(날짜 · 금액)도 숫자 근거다(QA r3 s2 9턴)
        for c in out.cards:
            self.gate.allow(card_ground(c.data))
        for a in out.actions:
            self.gate.allow(summary_ground(a.summary.model_dump(mode="json")))
        for a in out.closed:
            await self.emit("action", a.model_dump(mode="json"))
        for c in shown:
            await self.card(c)
        for a in out.actions:  # 행을 commit한 뒤에 보낸다(도구가 commit했다)
            if str(a.action_id) not in self.res.actions:
                self.res.actions.append(str(a.action_id))
            self.done.add(a.kind)
            await self.emit("action", a.model_dump(mode="json"))
        # 카드 말(만들었어요 · 눌러 주세요)을 놓아준다. 승인 카드를 만드는 읽기 도구(업체 request_brief)도 같아요(점검 R2 B3)
        if out.actions:
            fresh = given.get("state") == "new"
            await self.gate.cards({a.kind for a in out.actions}, fresh=fresh)
        if out.task is not None:
            await self.emit(
                "status", {"text": out.task.title, "task": out.task.model_dump(mode="json")}
            )
        trace.update(ok=True, size=len(body), ms=int((time.monotonic() - t0) * 1000))
        await self._beat()
        return {"type": "tool_result", "tool_use_id": cid, "content": body}, None


async def free_turn(
    ctx: TurnCtx, emit: Emit, res: TurnResult, reason: str, note: str | None = None
) -> None:
    """무료 모드(계약서 4장 9): LLM 없이 코드 길잡이(free.answer)가 의도 → 도구 → 카드 + 정해 둔 글로 답한다.
    note(카드 고르기를 코드가 처리한 결과)가 있으면 그 한 줄로 답한다."""
    from app.assistant import free

    res.mode, res.reason = "free", reason
    text = note or ""
    if not note:
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
            mode="free",
            text=ctx.text,
        )
        try:
            text, out = await free.answer(tc, ctx.text, ctx.card_id)
        except (ToolError, AppError) as e:
            text, out = e.message, None
        except Exception as e:  # noqa: BLE001 - 길잡이 실패는 실패 문구로 끝낸다(종류 이름만 로그)
            log.warning("무료 모드 길잡이 실패 (%s)", type(e).__name__)
            text, out = "", None
        if out is not None:
            for a in out.closed:
                await emit("action", a.model_dump(mode="json"))
            for c in out.cards:
                await send_card(res, emit, c)
            for a in out.actions:
                if str(a.action_id) not in res.actions:
                    res.actions.append(str(a.action_id))
                await emit("action", a.model_dump(mode="json"))
            if out.task is not None:
                await emit(
                    "status", {"text": out.task.title, "task": out.task.model_dump(mode="json")}
                )
    text = text or FAIL_TEXT
    await send_card(
        res,
        emit,
        CardOut(
            card_id=f"answer-{ctx.turn_id}",
            kind="answer",
            data=AnswerData(text=text, src="guide").model_dump(mode="json"),
        ),
    )
    res.text = text


async def run_turn(ctx: TurnCtx, emit: Emit) -> TurnResult:
    """한 턴을 돌리고 결과(저장할 글 · 카드 · 행동 · 흔적)를 돌려준다. 저장은 service.finish_turn이 한다."""
    res = TurnResult()
    breaker = await breaker_open()
    ok = True if breaker else await llm.budget_ok(ctx.user.id, "assistant")
    # 꺼짐(키 없음 · LLM_LIVE=false)은 첫 호출의 LLMOff로 안다(시험 대본이 켜져 있으면 대본으로 돈다)
    mode, reason = policy.mode_for(available=True, budget_ok=ok, breaker=breaker)
    # 카드 단추로 고른 것(철거 범위 · 'visit_request:v1,v2' …)은 모드와 상관없이 코드가 승인 카드로 만든다. 그때 보낸
    # 카드 · 승인 카드는 LLM 턴 문장 검사의 근거 · 누를 단추로도 쓴다
    seen: list[tuple[str, dict]] = []

    async def tap(name: str, data: dict) -> None:
        if name in ("card", "action"):
            seen.append((name, data))
        await emit(name, data)

    note = await choices.apply(ctx, tap, res)
    answered = res.reason == choices.ANSWERED  # 잠긴 집의 칸 단추(QA r3 v1 M6)
    if mode == "free" or ctx.stale or answered:
        # 지난 카드 단추는 카드를 새로 불러와, 잠긴 집의 칸 단추는 까닭 한 줄로 답한다(LLM 모드도 부르지 않는다)
        why = reason if mode == "free" else "reload" if ctx.stale else choices.ANSWERED
        await free_turn(ctx, emit, res, why, note)
    elif not said(ctx, note):  # 가린 뒤 빈 말 · 고른 것 없음: 빈 글 블록을 보내지 않는다(400)
        await free_turn(ctx, emit, res, "empty", EMPTY_TEXT)
    elif off_topic(ctx, note):
        # 인테리어와 상관없는 말은 LLM 없이 막아요(무료 모드의 범위 밖 답 틀)
        await free_turn(ctx, emit, res, "off_topic")
    else:
        turn = _Turn(ctx, emit, res, note, seen)
        try:
            await turn.run()
            # 붙잡아 둔 카드 말 · 넘친 문장 · 지난 턴과 같은 끝 문장을 정리한다(맞지 않는 카드 말은 정직한 한 줄)
            await turn.gate.settle()
            # 검사로 본문이 빠져 남은 글이 없거나 가리키는 말뿐이면 정직한 한 줄(고침 4차 G)
            await turn.gate.mend(bool(res.cards))
            res.text = turn.gate.text
            if not res.text and not res.cards:
                res.text = FAIL_TEXT
                await emit("token", {"text": FAIL_TEXT})
            elif tail := await next_step(
                turn, res
            ):  # 다음 할 일 없는 답 뒤 지금 할 일 한 줄(코드 글)
                res.text = f"{res.text}\n\n{tail}"
                await emit("token", {"text": f"\n\n{tail}"})
            await first_card(ctx, res, emit)  # 대화 첫 답에 카드가 없으면 오늘 정할 일 카드
        except _Fallback as f:
            await turn.gate.settle()
            kept = turn.gate.text
            await free_turn(ctx, emit, res, f.reason, note)
            if kept:  # 화면에 이미 보낸 LLM 글은 답 글 앞에 남기고, 다시 열 때 AI 글로 보이게 길이를 적는다
                res.text, res.kept = f"{kept}\n{res.text}", len(kept)
        res.cut = turn.gate.cut
        res.dropped = [why.split("(")[0].strip() for why in turn.gate.dropped]  # 까닭 종류만
    # 카드만 보낸 턴의 기록 글(화면은 숨기고 다음 턴 LLM이 읽는다): 카드 화면 이름으로
    if not res.text:
        names = dict.fromkeys(CARD_NAME.get(c["kind"], "카드") for c in res.cards)
        res.text = f"{CARDS_ONLY}: " + " · ".join(names) + ")"
    res.chips = chips_for(res.cards)
    # 이 턴 카드의 이름표를 저장 전에 남긴다(턴 저장이 409로 실패해도 기록에 남는 카드 단추가 같은 대상을 가리키게)
    await ctx.refs.save()
    return res
