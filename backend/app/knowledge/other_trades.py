"""다른 공정 알아 두기: 믿집이 금액 · 기간을 계산하지 않고 업체도 잇지 않는 공정(철거 · 설비 · 창호 · 전기 · 욕실 · 타일 ·
필름 · 도장 · 바닥 · 주방 · 중문)의 일반 순서 · 주의점. 비서 answer_question이 다른 공정 질문에 근거로 돌려준다.
DB · HTTP를 모르는 순수 함수.

- 자료: `other_trades.json`(운영 이미지는 app만 복사해서 여기에 둔다). 글에는 숫자를 넣지 않는다(금액 · 기간 · 치수 없음).
- 출처는 공공 자료(법령 · 고시 · 표준시방서 · 공공기관 안내)를 먼저 두고, 칸마다 확인 날짜 · 확인 방법을 적는다.
  저장소 지식 조각에 같은 글이 있으면 refs(K번호)를 적는다.
- 순서 글: 이 자료의 공정 쌍 글 → v3 공종 쌍 순서 글(trades.ORDER_RULES) → 공정 순서 값(order)으로 만든 글.
  공정이 둘 이상이고 순서 · 같이 하기 · 하는 방법을 물었을 때만 붙인다(orchestrator.ORDER_ASK + '하면서 · 김에 · -려면').
- 공종은 v3 낱말(trades_in)로 찾는다. '중문'만 걸린 창호는 중문으로, '방수도'의 '수도'만 걸린 설비는 빼요.
  '화장실 스위치'처럼 자리 낱말(욕실 · 주방)이 다른 일의 자리일 뿐이면 그 자리 공종은 빼요(PLACE).
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from pathlib import Path

PATH = Path(__file__).resolve().parent / "other_trades.json"
# 믿집이 계산하는 공종: 이 자료에는 없고 순서 글에만 써요(일 이름, TradeSpec.order)
OWN = {"dobae": ("도배", 7.0), "mokgong": ("목공", 4.0)}
MIDDOOR = "중문"
WATERPROOF = re.compile(r"방수도")  # '방수도 다시'의 '수도'를 설비로 읽지 않게
# 자리 공종: 자리 낱말로만 걸렸고 함께 걸린 일이 이 공종의 공사가 아니면 뺀다(욕실 리모델링의 철거 · 배관 · 타일은 둔다)
# '주방 가구'는 자리가 아니라 주방 공종의 일 낱말이라 자리 낱말로 지우지 않는다(QA r1 D7)
PLACE = {
    "bath": (re.compile(r"욕실|화장실"), frozenset({"electric", "film", "paint", "mokgong"})),
    "kitchen": (
        re.compile(r"(?:주방|부엌)(?!\s*가구)"),
        frozenset({"electric", "film", "paint", "tile", "demolition"}),
    ),
}
MAX_LINES = 6
MAX_ORDER = 2  # 순서 글 줄 수
MAX_SOURCES = 4
# '도배하면서 콘센트도 옮겨요?' · '후드 바꾸고 벽 타일도 붙이려면요?'도 순서 · 같이 하기 질문이에요
ALONG = re.compile(r"하면서|김에|려면")


@dataclass(frozen=True)
class Note:
    kind: str  # order · caution · check
    text: str
    src: tuple[str, ...]
    when: re.Pattern | None = None  # 질문에 이 말이 있을 때만 고르는 글(없으면 늘 고를 수 있음)


@dataclass(frozen=True)
class Trade:
    ko: str
    work: str  # 순서 글에 쓰는 일 이름(주방 → 주방 가구)
    order: float  # 믿집 안내 공정 순서(작을수록 먼저)
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class Book:
    version: str
    sources: dict[str, dict]
    trades: dict[str, Trade]
    pairs: dict[tuple[str, str], Note]


@dataclass(frozen=True)
class Know:
    """한 질문의 알아 두기: 다른 공정 이름 · 글(숫자 없음) · 출처 이름(공공 먼저)."""

    names: tuple[str, ...]
    lines: tuple[str, ...]
    sources: tuple[str, ...]

    def data(self) -> dict:
        """도구 결과 칸(policy.ALLOWED 이름만)."""
        return {
            "label": "알아 두기(믿집이 계산 · 연결하지 않는 공정)",
            "trades": list(self.names),
            "lines": list(self.lines),
            "sources": list(self.sources),
            "note": f"믿집은 {' · '.join(self.names)} 공사의 금액 · 기간을 계산하지 않고 업체도 연결하지 않아요.",
        }


def _note(n: dict, kind: str | None = None) -> Note:
    when = re.compile(n["when"]) if n.get("when") else None
    return Note(kind or n["kind"], n["text"], tuple(n["src"]), when)


@cache
def book() -> Book:
    raw = json.loads(PATH.read_text(encoding="utf-8"))
    trades = {
        code: Trade(t["ko"], t["work"], float(t["order"]), tuple(_note(n) for n in t["notes"]))
        for code, t in raw["trades"].items()
    }
    pairs = {(p["before"], p["after"]): _note(p, "order") for p in raw["pairs"]}
    return Book(raw["version"], raw["sources"], trades, pairs)


def codes_of(question: str) -> list[str]:
    """질문에 걸린 공종(v3 낱말, 공통 빼고). 창호 낱말이 '중문'뿐이면 중문, 둘 다면 둘 다예요."""
    from app.agent.v3.trades import BY_CODE, trades_in

    codes = [c for c in trades_in(question) if c != "common"]
    if "plumbing" in codes and not BY_CODE["plumbing"].pattern.search(
        WATERPROOF.sub("방수 ", question)
    ):
        codes.remove("plumbing")
    for place, (words, works) in PLACE.items():
        if (
            place in codes
            and works & set(codes)
            and not BY_CODE[place].pattern.search(words.sub(" ", question))
        ):
            codes.remove(place)
    if "window" in codes and MIDDOOR in question:
        if BY_CODE["window"].pattern.search(question.replace(MIDDOOR, " ")):
            codes.append("middoor")
        else:
            codes[codes.index("window")] = "middoor"
    return list(dict.fromkeys(codes))


def _josa(word: str, yes: str, no: str) -> str:
    """마지막 한글 글자에 받침이 있으면 yes(을 · 은 · 과), 없으면 no(를 · 는 · 와)."""
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            return yes if (ord(ch) - 0xAC00) % 28 else no
    return no


def _order(code: str) -> float:
    b = book()
    return b.trades[code].order if code in b.trades else OWN[code][1]


def _work(code: str) -> str:
    b = book()
    return b.trades[code].work if code in b.trades else OWN[code][0]


def pair_line(a: str, b: str) -> Note:
    """두 공종 순서 글: 이 자료의 쌍 글 → v3 공종 쌍 순서 글 → 순서 값으로 만든 글."""
    from app.agent.v3.trades import ORDER_RULES

    bk = book()
    for k in ((a, b), (b, a)):
        if k in bk.pairs:
            return bk.pairs[k]
    for k in ((a, b), (b, a)):
        if k in ORDER_RULES:
            return Note("order", ORDER_RULES[k], ("mitjip-order",))
    wa, wb = _work(a), _work(b)
    if _order(a) == _order(b):
        text = f"{wa}{_josa(wa, '과', '와')} {wb}{_josa(wb, '은', '는')} 비슷한 때 하는 공사라 업체와 순서를 맞춰요."
    else:
        first, then = (wa, wb) if _order(a) < _order(b) else (wb, wa)
        text = f"{first}{_josa(first, '을', '를')} 먼저 하고 {then}{_josa(then, '은', '는')} 그다음에 해요."
    return Note("order", text, ("mitjip-order",))


def notes_for(question: str) -> Know | None:
    """질문에 다른 공정이 걸리면 알아 두기(순서 글 · 공정마다 고른 주의점), 아니면 None."""
    from app.agent.v3.orchestrator import ORDER_ASK

    bk = book()
    codes = [c for c in codes_of(question) if c in bk.trades or c in OWN]
    other = [c for c in codes if c in bk.trades]
    if not other:
        return None
    picked: list[Note] = []
    if len(codes) >= 2 and (ORDER_ASK.search(question) or ALONG.search(question)):
        ordered = sorted(codes, key=lambda c: (_order(c), codes.index(c)))
        picked += [pair_line(a, b) for a, b in pairwise(ordered)][:MAX_ORDER]
    # 공정마다 고를 글 수: 하나면 셋, 여럿이면 둘까지(남은 줄을 공정끼리 나눠요)
    left = (MAX_LINES - len(picked)) // len(other[:3])
    per = max(1, min(3 if len(other) == 1 else 2, left))
    for c in other[:3]:
        # 순서 글을 붙였으면 공정 하나의 자리 글(order)은 빼요(같은 말 두 번)
        notes = [n for n in bk.trades[c].notes if not (picked and n.kind == "order")]
        hit = [n for n in notes if n.when is not None and n.when.search(question)]
        picked += (hit + [n for n in notes if n.when is None])[:per]
    lines = list(dict.fromkeys(n.text for n in picked))[:MAX_LINES]
    used = dict.fromkeys(k for n in picked if n.text in lines for k in n.src)
    srcs = sorted(
        used, key=lambda k: not bk.sources[k]["public"]
    )  # 공공 자료 먼저(같은 쪽은 나온 순서)
    titles = tuple(bk.sources[k]["title"] for k in srcs)[:MAX_SOURCES]
    return Know(tuple(bk.trades[c].ko for c in other), tuple(lines), titles)
