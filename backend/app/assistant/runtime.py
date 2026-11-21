"""비서 턴 런타임 (계약서 4장): Claude 도구 루프 · 문장 검사(SentenceGate) · 짧은 이름표(RefTable).

- DB 세션을 쥐지 않는다. 도구는 저마다 짧은 세션을 열고, 턴 저장은 service.finish_turn이 한다.
- 메시지 순서: 지난 턴 글 → 이번 글(가림, 카드에서 고른 ref) → role:system 턴 사실(코드 값만).
  도구 · 지시문은 고정(이름순 · 판 번호)이라 앞부분 캐시가 턴마다 맞는다. 턴 안에서는 덧붙이기만 한다.
- stop_reason: tool_use → 도구, pause_turn → 다시 보냄(2회), refusal → 무료 모드, max_tokens → 끊긴 문장 버림.
- 상한: 도구 6 · LLM 8 · 45초 · 턴 $0.06. 넘으면 '지금까지로 답해요'로 한 번 더(tool_choice none), 그래도 넘으면
  카드만으로 끝낸다(stopped). 같은 (도구, 오류 코드)가 두 번이면 멈추고 실패 카드. Claude가 두 번 실패하면
  무료 모드 + 5분 차단기.
- 모델 글은 문장마다 check.sentence_ok(허용 숫자 = 이번 턴 도구 결과 · 사실 · 고객 글)를 지난 것만 token으로 보낸다.
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
# 문장 끝: 마침표 · 물음표 · 느낌표 뒤 빈칸, 또는 줄 바꿈('필요 없어요'의 '요 '는 끝으로 보지 않는다)
SENT_END = re.compile(r"(?<=[.!?。])[ \t]+|\n+")
# 승인이 있어야 하는 일을 한 것처럼 끝맺는 말('확정했어요' · '요청을 보냈어요' · '결제를 완료'). 비서는 실행하지 않는다
CLAIM = re.compile(
    r"(?:확정|수락|승인|거절|결제|예약|저장|실행|처리|요청|신청|접수|전송)(?:을|를|으로|로)?\s*"
    r"(?:했어요|했습니다|했고|했으니|해\s*드렸|해\s*뒀|완료|바꿨)"
    r"|보냈어요|보냈습니다|보내\s*드렸|보내\s*뒀"
)
SUBJECT = re.compile(r"([가-힣A-Za-z0-9]+?)(?:이|가|께서)\s")
FIRST = frozenset({"제", "저", "저희", "AI", "비서", "믿집", "내"})


def claims_done(text: str) -> bool:
    """비서가 승인 없이 한 것처럼 말하는지. 다른 사람이 주어면(업체가 보냈어요) 사실 전달로 둔다."""
    if not CLAIM.search(text):
        return False
    subjects = [m.group(1) for m in SUBJECT.finditer(text)]
    return not subjects or all(s in FIRST for s in subjects)


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
      않는다: 그 이름의 단추는 모르는 이름표가 되어 카드를 새로 불러온다(엉뚱한 대상으로 가지 않게)."""

    PREFIX: ClassVar[dict[str, str]] = {
        "vendor": "v", "visit": "m", "wish": "r", "slot": "s", "window": "w",
        "deal": "d", "proposal": "p", "days": "n",
    }  # fmt: skip
    IDENT: ClassVar[dict[str, tuple[str, ...]]] = {
        "vendor": ("id",), "visit": ("id",), "wish": ("start", "end"),
        "slot": ("visit_id", "day", "half"), "window": ("visit_id", "start", "end"),
        "deal": ("id",), "proposal": ("id",), "days": ("deal_id", "start"),
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

    def merged(self, theirs: dict, meta: dict) -> tuple[dict, dict]:
        """Redis에 있는 표(theirs) · 번호 기록(meta)과 이 표를 합친다. (새 표, 새 번호 기록)"""
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
            if old is None or ref in self.touched:
                out[ref] = it
        while len(out) > self.MAX:
            out.pop(next(iter(out)))
        top = {str(p): int(n) for p, n in (meta.get("top") or {}).items()}
        for p, n in self.top.items():
            top[p] = max(top.get(p, 0), n)
        return out, {"top": top, "dead": sorted(dead)[-REF_DEAD_MAX:]}

    async def save(self) -> None:
        from redis.exceptions import WatchError

        key, num_key = self._key(self.chat_id), self._num_key(self.chat_id)
        try:
            async with queue.redis.pipeline(transaction=True) as pipe:
                for _ in range(REF_SAVE_TRIES):
                    try:
                        await pipe.watch(key, num_key)
                        raw, num = await pipe.mget(key, num_key)
                        items, meta = self.merged(_json_dict(raw), _json_dict(num))
                        pipe.multi()
                        pipe.set(key, json.dumps(items, ensure_ascii=False), ex=REF_TTL)
                        pipe.set(num_key, json.dumps(meta), ex=REF_NUM_TTL)
                        await pipe.execute()
                        return
                    except WatchError:
                        continue  # 그사이 다른 곳이 저장했다: 다시 읽어 합친다
        except REDIS_ERRORS:
            return  # 지워져도 되는 값: 모르는 이름표 단추는 카드를 새로 불러온다


# ---- 문장 검사 ----


class SentenceGate:
    """모델 글 조각을 문장으로 모아 검사를 지난 문장만 token으로 보낸다(숫자 · AI가 한 일처럼 · 주소 · 누출).

    말과 행동 맞추기(policy.card_claim): 승인 카드를 만들었다 · 만들어 드린다 · 눌러 달라는 문장은 그 말이 맞을 때만
    보낸다(이 턴에 제안 도구가 카드를 만듦 · 그 카드가 열려 있음 · 눌러 달라는 말은 이 턴에 보인 화면 카드 단추도).
    아직 모르면 그 문장과 뒤 문장을 순서대로 붙잡아 두고, 카드가 오면 놓아준다(made · opened · buttons). 턴
    끝(settle)에도 맞지 않으면 첫 문장을 정직한 한 줄로 바꾸고 나머지 그런 문장은 뺀다."""

    def __init__(self, emit: Emit, prompt: str, allowed: str, made: Collection[str] = ()) -> None:
        self._emit = emit
        self._prompt = prompt
        self._allowed = [allowed]
        self._nums: set[float] | None = None
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

    @property
    def text(self) -> str:
        return "".join(self._out).strip()

    def allow(self, text: str) -> None:
        """이번 턴 도구 결과 글(허용 숫자)."""
        self._allowed.append(text)
        self._nums = None

    def _numbers(self) -> set[float]:
        if self._nums is None:
            self._nums = guard.numbers("\n".join(self._allowed))
        return self._nums

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
        self._sep = " " if self._out or self._held else ""

    def discard(self) -> None:
        self._buf = ""

    async def _one(self, text: str) -> None:
        if not text.strip():
            return
        ok, why = check.sentence_ok(
            Sentence(text=text.strip()), self._numbers(), None, None, self._prompt
        )
        if ok is not None and claims_done(ok.text):
            ok, why = None, "승인 없이 한 일처럼 말함"
        if ok is not None and policy.VS_STANDARD.search(ok.text):
            ok, why = None, "표준 대비 %"
        if ok is None:
            if why:
                self.dropped.append(why)
            return
        claim = policy.card_claim(ok.text)
        if self._held or (claim is not None and not self._true(claim)):
            self._held.append((self._sep, ok.text, claim))  # 순서를 지키려고 뒤 문장도 기다린다
            return
        await self._send(self._sep, ok.text)

    def _true(self, claim: tuple[str, set[str]]) -> bool:
        return policy.claim_ok(claim, self.made, self.opened, self.buttons)

    async def _send(self, sep: str, text: str) -> None:
        piece = (sep if self._out else "") + text
        self._out.append(piece)
        self.sent.append(text)
        await self._emit("token", {"text": piece})

    async def cards(self, kinds: Collection[str], *, fresh: bool) -> None:
        """제안 도구가 승인 카드를 만들었다(fresh) · 열린 같은 카드를 다시 썼다. 맞게 된 문장부터 놓아준다."""
        (self.made if fresh else self.opened).update(kinds)
        await self._release()

    async def shown(self, card: CardOut) -> None:
        """화면 카드를 보냈다: 그 카드 단추를 누르라는 말이 맞게 된다."""
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
        """턴 끝: 붙잡아 둔 문장을 보낸다. 끝까지 맞지 않은 카드 말은 첫 것만 정직한 한 줄로 바꾸고 나머지는 뺀다."""
        held, self._held = self._held, []
        for sep, text, claim in held:
            if claim is None or self._true(claim):
                await self._send(sep, text)
                continue
            self.dropped.append("카드 없이 카드를 말함")
            if not self._fixed:
                self._fixed = True
                await self._send(sep, policy.honest(claim, self.opened | self.made))


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

    def trace(self, rev: int, ms: int) -> dict:
        return {
            "rev": rev,
            "llm": self.llm_calls,
            "tools": self.tools,
            "actions": self.actions,
            "stop": self.stop,
            "reason": self.reason,
            "ms": ms,
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
        self.gate = SentenceGate(emit, self.system, f"{ctx.text}\n{ctx.facts}", made=res.made)
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
        )

    def _messages(self) -> list[dict]:
        text = self.ctx.text
        if self.ctx.choice:
            text += f"\n(카드에서 고름: {', '.join(choices.text_of(c) for c in self.ctx.choice)})"
        if self.note:
            text += f"\n({self.note})"
        return [
            *self.ctx.history,
            {"role": "user", "content": [{"type": "text", "text": text}]},
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
            except llm.LLMError:
                b.llm += 1
                fails += 1
                self.gate.discard()
                if fails >= 2:
                    await _trip()
                    raise _Fallback("breaker") from None
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
            out = await tools_mod.run(t, self.tc, args)
        except ToolError as e:
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            return self._error(cid, e.code, e.message, e.hint), e.code
        except AppError as e:  # 기능 service 오류(404 · 409 …): 코드와 정해 둔 문장만
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            return self._error(cid, e.code, e.message), e.code
        except Exception as e:  # noqa: BLE001 - 도구 하나의 실패는 is_error로 돌려준다(종류 이름만 로그)
            log.warning("비서 도구 실패 (%s, %s)", name, type(e).__name__)
            trace["ms"] = int((time.monotonic() - t0) * 1000)
            return self._error(cid, "tool_failed", "도구를 쓰지 못했어요."), "tool_failed"
        data = policy.to_model(out.data)
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
            fresh = out.data.get("state") == "new"
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
    if mode == "free" or ctx.stale:
        # 지난 카드 단추는 카드를 새로 불러와 정해 둔 한 줄로 답한다(LLM 모드도 부르지 않는다)
        await free_turn(ctx, emit, res, reason if mode == "free" else "reload", note)
    else:
        turn = _Turn(ctx, emit, res, note)
        try:
            await turn.run()
            await turn.gate.settle()  # 붙잡아 둔 카드 말을 정리한다(맞지 않으면 정직한 한 줄)
            res.text = turn.gate.text
            if not res.text and not res.cards:
                res.text = FAIL_TEXT
                await emit("token", {"text": FAIL_TEXT})
        except _Fallback as f:
            await turn.gate.settle()
            kept = turn.gate.text
            await free_turn(ctx, emit, res, f.reason, note)
            res.text = f"{kept}\n{res.text}".strip() if kept else res.text
    if not res.text:
        res.text = "(카드를 보여 줬어요: " + " · ".join(c["kind"] for c in res.cards) + ")"
    res.chips = chips_for(res.cards)
    return res
