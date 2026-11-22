"""비서 턴 런타임 (계약서 4장): Claude 도구 루프 · 문장 검사(SentenceGate) · 짧은 이름표(RefTable).

- DB 세션을 쥐지 않는다. 도구는 저마다 짧은 세션을 열고, 턴 저장은 service.finish_turn이 한다.
- 메시지 순서: 지난 턴 글 → 이번 글(가림, 카드에서 고른 ref) → role:system 턴 사실(코드 값만).
  도구 · 지시문은 고정(이름순 · 판 번호)이라 앞부분 캐시가 턴마다 맞는다. 턴 안에서는 덧붙이기만 한다.
- stop_reason: tool_use → 도구, pause_turn → 다시 보냄(2회), refusal → 무료 모드, max_tokens → 끊긴 문장 버림.
- 상한: 도구 6 · LLM 8 · 45초 · 턴 $0.06. 넘으면 '지금까지로 답해요'로 한 번 더(tool_choice none), 그래도 넘으면
  카드만으로 끝낸다(stopped). 같은 (도구, 오류 코드)가 두 번이면 멈추고 실패 카드. Claude가 두 번 실패하면
  무료 모드 + 5분 차단기. 요청 자체가 틀린 거절(400 · 413 · 422, llm.LLMRejected)은 다시 보내지 않고 이 턴만
  무료 모드다(차단기에 세지 않는다). 빈 말은 LLM에 보내지 않는다(빈 글 블록은 400).
- 모델 글은 문장마다 check.sentence_ok(허용 숫자 = 이번 턴 도구 결과 · 사실 · 고객 글)를 지난 것만 token으로 보낸다.
  숫자는 근거 값 그대로에 더해 어림 · 차액 · 합계 · 평당 · 날짜 꼴을 읽고(guard.loose), 누출은 지시문의 규칙 절과만
  견준다(prompts.rules). 말투 · 길이는 모델에 맡기고(docs/v4/08-rules.md) 아주 긴 답만 줄인다: 넘친 문장은
  묻는 말 · 다음 할 일만 턴 끝에 보낸다. 끝 안내가 지난 두 비서 턴의 끝 문장과 완전히 같으면 뺀다(policy.TALK_* ·
  REPEAT_TURNS).
"""

import asyncio
import json
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import ClassVar

from app import queue
from app.agent import llm
from app.agent.v3 import check
from app.agent.v3.schemas import Sentence
from app.assistant import choices, policy, prompts
from app.assistant import tools as tools_mod
from app.assistant.schemas import AnswerData, CardOut
from app.assistant.tools import ToolCtx, ToolError
from app.auth.models import User
from app.config import settings
from app.shared.errors import AppError
from app.usage.service import REDIS_ERRORS
from app.v2 import guard

log = logging.getLogger(__name__)

Emit = Callable[[str, dict], Awaitable[None]]

WRAP = "도구는 더 부르지 말고, 지금까지 얻은 결과로만 짧게 답해 주세요."
FAIL_TEXT = "설명을 만들지 못했어요. 카드와 버튼으로 이어서 진행해 주세요."
TOOL_FAIL = "같은 문제가 두 번 나서 멈췄어요. 화면에서 직접 이어서 해 주세요."
EMPTY_TEXT = "말씀이 비어 있어요. 궁금한 것을 적어 주세요."
# 카드 종류 → 화면 이름(카드만 보낸 턴의 기록 글)
CARD_NAME = {
    "home_info": "집 정보", "standard_quote": "표준견적서", "vendor_picks": "업체 추천",
    "visit_slots": "실측 시간", "quote_compare": "견적서 비교", "schedule": "공사 날짜",
    "knowledge": "자료", "answer": "답", "floorplan_links": "평면도 찾기", "today": "오늘 할 일",
    "vendor_brief": "요청 브리핑", "quote_checklist": "견적서 체크리스트",
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
# 문장 끝: 마침표 · 물음표 · 느낌표 뒤 빈칸, 또는 줄 바꿈('필요 없어요'의 '요 '는 끝으로 보지 않는다)
SENT_END = re.compile(r"(?<=[.!?。])[ \t]+|\n+")
# 승인이 있어야 하는 일을 한 것처럼 끝맺는 말('확정했어요' · '요청을 보냈어요' · '결제를 완료'). 비서는 실행하지 않는다
CLAIM = re.compile(
    r"(?:확정|수락|승인|거절|결제|예약|저장|실행|처리|요청|신청|접수|전송)(?:을|를|으로|로)?\s*"
    r"(?:했어요|했습니다|했고|했으니|해\s*드렸|해\s*뒀|완료|바꿨)"
    r"|보냈어요|보냈습니다|보내\s*드렸|보내\s*뒀"
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


def foreign(text: str) -> bool:
    """한글이 하나도 없고 글자 · 숫자의 반 넘게가 다른 글자(로마자 등)인 문장: 도구 앞에 쓴 영어 속말(QA r2 c3
    'Direct tasks not saved; make a card.'). 제품 이름 · 단위가 섞인 한국어 문장과 숫자 · 날짜만인 줄은 아니다."""
    if HANGUL.search(text):
        return False
    letters = sum(ch.isalpha() for ch in text)
    return letters * 2 > sum(ch.isalnum() for ch in text)


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

    @classmethod
    def ident(cls, it: dict) -> tuple:
        kind = it.get("kind")
        return (kind, *(str(it.get(k)) for k in cls.IDENT.get(str(kind), ())))

    def put(self, kind: str, value: dict) -> str:
        want = self.ident({**value, "kind": kind})
        for ref, it in self.items.items():
            if self.ident(it) == want:
                it.update({k: v for k, v in value.items() if k != "kind"})
                self.touched.add(ref)
                return ref
        prefix = self.PREFIX[kind]
        used = [int(r[1:]) for r in self.items if r[0] == prefix and r[1:].isdigit()]
        n = max([*used, self.top.get(prefix, 0)]) + 1
        self.top[prefix] = n
        ref = f"{prefix}{n}"
        if len(self.items) >= self.MAX:  # 가장 오래된 것부터 버린다(번호는 top이 기억한다)
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
        쓴 번호)."""
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
            if old is None or ref in self.touched:
                out[ref] = it
        while len(out) > self.MAX:
            out.pop(next(iter(out)))
        top = {str(p): int(n) for p, n in (meta.get("top") or {}).items()}
        for p, n in [*self.top.items(), *durable.items()]:
            top[p] = max(top.get(p, 0), n)
        return out, {"top": top, "dead": sorted(dead)[-REF_DEAD_MAX:]}

    async def _durable(self) -> dict[str, int]:
        """DB에 남긴 번호(머리글자 → 가장 큰 번호)를 읽고 이 표의 번호로 올린다(늘기만). 돌려주는 값: 올리기 전 번호.
        DB를 못 쓰면 {}(Redis만으로 합친다)."""
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
        return before

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


def recent_ends(history: list[dict], turns: int = policy.REPEAT_TURNS) -> list[str]:
    """지난 비서 답 turns개(가장 가까운 것부터 셈)의 끝 문장. 카드만 보낸 턴의 기록 글은 끝 문장이 없다."""
    out: list[str] = []
    said = [m.get("content") for m in history if m.get("role") == "assistant"][-turns:]
    for text in said:
        if not isinstance(text, str) or not text.strip() or text.startswith(CARDS_ONLY):
            continue
        parts = [p.strip() for p in SENT_END.split(text.strip()) if p.strip()]
        if parts:
            out.append(parts[-1])
    return out


class SentenceGate:
    """모델 글 조각을 문장으로 모아 검사를 지난 문장만 token으로 보낸다(숫자 · AI가 한 일처럼 · 주소 · 누출).

    말과 행동 맞추기(policy.card_claim · 고정 선 5): 승인 카드를 만들었다 · 만들어 드린다 · 눌러 달라는 문장은 확실히
    틀릴 때만 바꾼다(policy.claim_ok: 만들었다는 말은 이 턴에 만든 카드가 하나도 없을 때, 눌러 달라는 말은 누를 것이
    하나도 없을 때). 아직 모르면 그 문장과 뒤 문장을 순서대로 붙잡아 두고, 카드가 오면 놓아준다(made · opened ·
    buttons). 턴 끝(settle)에도 틀리면 첫 문장을 정직한 한 줄로 바꾸고 나머지 그런 문장은 뺀다.

    길이(policy.TALK_LEAD · TALK_CHARS): 아주 긴 답만 줄인다. 앞 몫까지 바로 보내고, 넘친 문장은 모아 두었다가 턴 끝에
    묻는 말 · 다음 할 일만 보낸다. 대화 첫 답(소개 · 첫인사, long_ok)과 업체 소개 · 견적 비교 카드
    (policy.LONG_CARDS)를 보인 턴은 줄이지 않는다.
    되풀이: 이 턴에 보낸 문장과 완전히 같은 문장은 빼고, 지난 비서 턴의 끝 문장(ends)과 완전히 같은 다음 할 일
    문장은 끝 문장인지 볼 때까지 기다렸다가 끝이면 뺀다(그 문장뿐이면 둔다). 이 턴에 만든 카드 · 보인 카드 단추를
    눌러 달라는 말은 새 안내라 되풀이로 보지 않는다."""

    def __init__(
        self,
        emit: Emit,
        prompt: str,
        allowed: str,
        made: Collection[str] = (),
        ends: Collection[str] = (),
        long_ok: bool = False,
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
        self.buttons: set[str] = set()  # 이 턴에 보인 화면 카드 단추가 만드는 행동 종류
        # 붙잡아 둔 문장: (앞 띄움, 글, 카드 말)
        self._held: list[tuple[str, str, tuple[str, set[str]] | None]] = []
        self._fixed = False  # 정직한 한 줄을 이미 썼다
        self.ends = [e for e in ends if e and e.strip()]  # 지난 비서 턴의 끝 문장
        self._extra: list[tuple[str, str, tuple[str, set[str]] | None]] = []  # 넘친 문장
        self._pending: tuple[str, str] | None = None  # 지난 턴 끝 문장과 같은 문장(끝인지 기다림)
        self.cut = 0  # 길이 · 되풀이로 뺀 문장 수(흔적)
        # 길이를 줄이지 않는 턴: 대화 첫 답(소개 · 첫인사) · 업체 소개 · 견적 비교 카드를 보인 턴
        self.long_ok = long_ok
        self._hints: list[str] = []  # 이번 턴 도구 오류의 hint(모델에만 주는 글)

    @property
    def text(self) -> str:
        return "".join(self._out).strip()

    def allow(self, text: str) -> None:
        """이번 턴 도구 결과 글(허용 숫자)."""
        self._allowed.append(text)
        self._ground = None

    def hint(self, text: str) -> None:
        """이번 턴 도구 오류의 hint(모델에만 주는 고칠 방법). 이 글을 옮긴 문장은 고객에게 보내지 않는다."""
        if text and text.strip():
            self._hints.append(text)

    def _grounds(self) -> guard.Ground:
        """허용 글의 숫자 근거(옛 검사 값 · 어림 · 파생 · 날짜). 도구 결과가 더해지면 다시 읽는다."""
        if self._ground is None:
            self._ground = guard.ground("\n".join(self._allowed))
        return self._ground

    async def feed(self, chunk: str) -> None:
        self._buf += chunk
        parts = SENT_END.split(self._buf)
        seps = SENT_END.findall(self._buf)
        if len(parts) <= 1:
            return
        self._buf = parts[-1]
        for text, sep in zip(parts[:-1], seps, strict=True):
            await self._one(text)
            self._sep = "\n" if "\n" in sep else " "

    async def flush(self, drop_tail: bool = False) -> None:
        """모델 글 블록이 끝났다. drop_tail이면(max_tokens) 끊긴 마지막 문장을 버린다."""
        tail, self._buf = self._buf, ""
        if tail.strip() and not drop_tail:
            await self._one(tail)
        elif tail.strip():
            self.dropped.append("끊긴 문장")
        self._sep = " " if self._out or self._held or self._pending else ""

    def discard(self) -> None:
        self._buf = ""

    def mark(self) -> tuple:
        """LLM 한 번을 부르기 전 상태(그 호출이 실패하면 undo로 그 시도의 글을 거둔다)."""
        held, extra = list(self._held), list(self._extra)
        return len(self._out), self._sep, held, extra, self._pending, len(self.dropped), self.cut

    def undo(self, mark: tuple) -> bool:
        """실패한 LLM 시도의 글을 거둔다(끊긴 조각 · 붙잡은 · 넘친 · 기다리는 문장). 그 시도에서 이미 보낸 글이
        있으면(화면에 나갔다) 끊긴 조각만 버리고 False: 같은 요청을 다시 보내면 앞 글과 겹친다."""
        self._buf = ""
        out, sep, held, extra, pending, dropped, cut = mark
        if len(self._out) != out:
            return False
        self._sep, self._held, self._extra, self._pending = sep, held, extra, pending
        del self.dropped[dropped:]
        self.cut = cut
        return True

    async def _one(self, text: str) -> None:
        if not text.strip():
            return
        # 고객 글이 아닌 속말(도구 앞 영어 메모): 보내지도 기록하지도 않고 까닭만 흔적에
        if foreign(text):
            self.dropped.append("한글 없는 외국어 글")
            return
        # 숫자: 근거 값 그대로에 더해 어림 · 파생 · 날짜를 읽는다(guard.loose, 08-rules 숫자 절). 통과한 값만 허용에 더해
        # 아래 검사(한글 금액 · 쓰면 안 되는 표현 · 한 일처럼 · 주소 · 누출)를 같이 지나게 한다
        g = self._grounds()
        bad, fine = guard.loose(check.mask(text.strip()), g)
        ok, why = check.sentence_ok(
            Sentence(text=text.strip()), set(g.nums) | fine, None, None, self._prompt
        )
        # 같은 값이 다른 자리(날짜 · 금액 묶음)에서 지나 위 검사가 놓친 숫자
        if ok is not None and bad is not None:
            ok, why = None, f"계산 결과 · 자료에 없는 숫자({bad})"
        if ok is not None and claims_done(ok.text):
            ok, why = None, "승인 없이 한 일처럼 말함"
        if ok is not None and policy.VS_STANDARD.search(ok.text):
            ok, why = None, "표준 대비 %"
        if ok is not None and (inner := policy.inside(ok.text)):  # 이름표 · 도구 · 칸 이름
            ok, why = None, inner
        if ok is not None and any(policy.quotes(ok.text, h) for h in self._hints):
            ok, why = None, "도구 안내 글"  # 모델에만 준 hint를 옮긴 문장
        if ok is None:
            if why:
                self.dropped.append(why)
            return
        claim = policy.card_claim(ok.text)
        if self._full():  # 길이 상한: 턴 끝에 묻는 말 · 다음 할 일만 고른다
            self._extra.append((self._sep, ok.text, claim))
            return
        if self._held or (claim is not None and not self._true(claim)):
            self._held.append((self._sep, ok.text, claim))  # 순서를 지키려고 뒤 문장도 기다린다
            return
        await self._send(self._sep, ok.text)

    def _true(self, claim: tuple[str, set[str]]) -> bool:
        return policy.claim_ok(claim, self.made, self.opened, self.buttons)

    def _full(self) -> bool:
        """바로 보낼 몫(보냄 · 붙잡음 · 기다림)이 찼는지: TALK_LEAD 문장 또는 TALK_CHARS 자(소개 · 비교 답은 늘 아님)."""
        if self.long_ok:
            return False
        lead = [*self.sent, *(t for _, t, _ in self._held)]
        if self._pending is not None:
            lead.append(self._pending[1])
        return len(lead) >= policy.TALK_LEAD or sum(map(len, lead)) >= policy.TALK_CHARS

    def _fresh(self, text: str) -> bool:
        """이 턴에 만든 카드 · 보인 카드 단추를 가리키는 카드 말(같은 글이어도 새 안내다)."""
        claim = policy.card_claim(text)
        if claim is None:
            return False
        new = self.made | self.buttons
        return bool(claim[1] & new) if claim[1] else bool(new)

    def _repeat(self, text: str) -> bool:
        """지난 비서 턴의 끝 안내와 완전히 같은 다음 할 일 문장(새 안내는 빼고). 다시 물은 답 · 사실 문장은 아니다."""
        return (
            policy.next_step(text)
            and any(policy.same_line(text, e) for e in self.ends)
            and not self._fresh(text)
        )

    async def _send(self, sep: str, text: str) -> None:
        """검사를 지난 문장 하나를 보낸다. 이 턴에 보낸 문장과 같으면 빼고, 지난 턴 끝 문장과 같으면 끝 문장인지 볼 때까지
        기다린다(다음 문장이 오면 먼저 보낸다)."""
        if any(policy.same_line(text, x) for x in self.sent) or (
            self._pending is not None and policy.same_line(text, self._pending[1])
        ):
            self.dropped.append("같은 문장")
            self.cut += 1
            return
        if self._pending is not None:
            wait, self._pending = self._pending, None
            await self._put(*wait)
        if self._repeat(text):
            self._pending = (sep, text)
            return
        await self._put(sep, text)

    async def _put(self, sep: str, text: str) -> None:
        piece = (sep if self._out else "") + text
        self._out.append(piece)
        self.sent.append(text)
        await self._emit("token", {"text": piece})

    async def cards(self, kinds: Collection[str], *, fresh: bool) -> None:
        """제안 도구가 승인 카드를 만들었다(fresh) · 열린 같은 카드를 다시 썼다. 맞게 된 문장부터 놓아준다."""
        (self.made if fresh else self.opened).update(kinds)
        await self._release()

    async def shown(self, card: CardOut) -> None:
        """화면 카드를 보냈다: 그 카드 단추를 누르라는 말이 맞게 되고, 업체 소개 · 견적 비교 카드면 길이를 줄이지 않는다."""
        if card.kind in policy.LONG_CARDS:
            self.long_ok = True
        got = policy.buttons_of(card.kind, card.data)
        if got:
            self.buttons |= got
            await self._release()

    async def _release(self) -> None:
        while self._held:
            sep, text, claim = self._held[0]
            if claim is not None and not self._true(claim):
                return
            self._held.pop(0)
            await self._send(sep, text)

    async def settle(self) -> None:
        """턴 끝: 붙잡아 둔 문장을 보낸다. 끝까지 틀린 카드 말은 첫 것만 정직한 한 줄로 바꾸고 나머지는 뺀다.
        넘친 문장에서는 묻는 말 · 다음 할 일만 끝에 보내고, 지난 턴 끝 안내와 같은 끝 문장은 뺀다(그 문장뿐이면 둔다)."""
        held, self._held = self._held, []
        for sep, text, claim in held:
            if claim is None or self._true(claim):
                await self._send(sep, text)
                continue
            self.dropped.append("카드 없이 카드를 말함")
            if not self._fixed:
                self._fixed = True
                await self._send(sep, policy.honest(claim, self.opened | self.made))
        tail = self._overflow()
        if self._pending is not None:
            wait, self._pending = self._pending, None
            if self.sent or tail:
                self.dropped.append("지난 턴과 같은 끝 문장")
                self.cut += 1
            else:
                await self._put(*wait)
        for piece in tail:
            await self._put(*piece)

    def _overflow(self) -> list[tuple[str, str]]:
        """넘친 문장 중 끝에 보낼 것(순서대로): 묻는 말 · 다음 할 일(소개 · 비교 답이면 모두). 카드 말이면 그대로 둘
        것, 이 턴에 보낸 말과 같지 않은 것, 지난 턴 끝 안내의 되풀이가 아닌 것. 나머지는 뺀다."""
        extra, self._extra = self._extra, []
        keep: list[tuple[str, str]] = []
        for sep, text, claim in extra:
            if not (self.long_ok or policy.asks(text) or policy.next_step(text)):
                continue
            if claim is not None and not self._true(claim):
                continue
            seen = [*self.sent, *(t for _, t in keep)]
            if any(policy.same_line(text, x) for x in seen) or self._repeat(text):
                continue
            keep.append((sep, text))
        if len(extra) > len(keep):
            self.dropped.append("길이 상한")
            self.cut += len(extra) - len(keep)
        return keep


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

    def trace(self, rev: int, ms: int) -> dict:
        return {
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
    "visit_slots": (("다른 시간도 볼래요", None), ("실측은 무엇을 봐요?", None)),
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
    def __init__(self, ctx: TurnCtx, emit: Emit, res: TurnResult, note: str | None = None) -> None:
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
            ends=recent_ends(ctx.history),
            # 대화 첫 답은 소개 · 첫인사라 길이를 줄이지 않는다(08-rules '소개 답은 예외')
            long_ok=not any(m.get("role") == "assistant" for m in ctx.history),
        )
        # 인사 · 고마움만 한 턴: 도구를 부르지 못하게(도구 정의는 그대로 보내 캐시를 지킨다)
        self.chat_only = policy.small_talk(ctx.text) and not ctx.choice and not ctx.stale
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
        return [
            *self.ctx.history,
            {"role": "user", "content": [{"type": "text", "text": said(self.ctx, self.note)}]},
            {"role": "system", "content": self.ctx.facts},
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

    async def _open_kinds(self) -> set[str]:
        """턴 앞에 열려 있는 승인 카드 종류(카드를 눌러 달라는 말이 맞는지 본다). 못 읽으면 빈 집합."""
        from app.assistant import repository as repo
        from app.db import SessionLocal

        try:
            async with SessionLocal() as s:
                rows = await repo.actions_of(
                    s,
                    self.ctx.user.id,
                    self.ctx.surface,
                    project_id=self.ctx.project_id,
                    status="proposed",
                    limit=20,
                )
        except Exception as e:  # noqa: BLE001 - 못 읽으면 열린 카드가 없는 것으로 본다(말이 더 정직해진다)
            log.warning("비서 열린 카드 읽기 실패 (%s)", type(e).__name__)
            return set()
        return {a.kind for a in rows if a.expires_at > self.ctx.now}

    async def run(self) -> None:
        self.gate.opened |= await self._open_kinds()
        with llm.call_ctx(self.ctx.user.id, self.ctx.turn_id, "assistant") as cc:
            try:
                await self._loop(cc)
            finally:  # 무료 모드로 넘어가도 쓴 비용 · 호출 수는 남긴다
                self.res.cost_micros = cc.spent_micros
                self.res.llm_calls = self.budget.llm
                self.res.tool_calls = self.budget.tools

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
        for a in out.closed:
            await self.emit("action", a.model_dump(mode="json"))
        for c in out.cards:
            await self.card(c)
        for a in out.actions:  # 행을 commit한 뒤에 보낸다(도구가 commit했다)
            if str(a.action_id) not in self.res.actions:
                self.res.actions.append(str(a.action_id))
            await self.emit("action", a.model_dump(mode="json"))
        if t.kind == "propose" and out.actions:  # 카드 말(만들었어요 · 눌러 주세요)을 놓아준다
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
    # 카드 단추로 고른 것(철거 범위 · 'visit_request:v1,v2' …)은 모드와 상관없이 코드가 승인 카드로 만든다
    note = await choices.apply(ctx, emit, res)
    answered = res.reason == choices.ANSWERED  # 잠긴 집의 칸 단추(QA r3 v1 M6)
    if mode == "free" or ctx.stale or answered:
        # 지난 카드 단추는 카드를 새로 불러와, 잠긴 집의 칸 단추는 까닭 한 줄로 답한다(LLM 모드도 부르지 않는다)
        why = reason if mode == "free" else "reload" if ctx.stale else choices.ANSWERED
        await free_turn(ctx, emit, res, why, note)
    elif not said(ctx, note):  # 가린 뒤 빈 말 · 고른 것 없음: 빈 글 블록을 보내지 않는다(400)
        await free_turn(ctx, emit, res, "empty", EMPTY_TEXT)
    else:
        turn = _Turn(ctx, emit, res, note)
        try:
            await turn.run()
            # 붙잡아 둔 카드 말 · 넘친 문장 · 지난 턴과 같은 끝 문장을 정리한다(맞지 않는 카드 말은 정직한 한 줄)
            await turn.gate.settle()
            res.text = turn.gate.text
            if not res.text and not res.cards:
                res.text = FAIL_TEXT
                await emit("token", {"text": FAIL_TEXT})
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
