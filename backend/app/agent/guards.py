"""출력 검사: 숫자 슬롯 채우기 · 문장 숫자 검사 · 금지 표현 · 개인정보 가림. LLM 글이 화면에 가기 전 마지막 관문.

- LLM은 숫자 대신 ⟦키⟧를 쓴다. 키에 맞는 표시 글(계산 엔진 값)을 코드가 넣는다. 모르는 키가 든 문장은 버린다.
- 남은 숫자는 문장마다 뽑아 '허용 집합'과 대조한다. 허용 = 이번 턴 슬롯 값 ∪ 인용한 지식 조각 안의 숫자.
  한글로 쓴 금액(삼백만 원)은 늘 버린다. 세는 말(2가지 · 3번 · 1단계)처럼 단위 없는 작은 수는 허용한다.
- 검사기가 최종 권한이다. 버린 문장이 있으면 부르는 쪽이 1회 다시 만들게 하고, 그래도 안 되면 계산 결과만 보인다.
docs/agent/03-runtime.md 6절.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

SLOT = re.compile(r"⟦([a-z0-9_.:]+)⟧")
NUM = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(만\s*원|천\s*원|억\s*원|억|만|원|%|퍼센트|㎡|m²|평|일|개월|개|롤|cm|mm|m|배|시간|주|층|장|짝|명|인|품)?"
)
COUNT_WORDS = re.compile(r"^\s*(가지|번|단계|번째|곳|군데|가지씩)")
HANGUL_MONEY = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천])+\s*(?:만|억)?\s*원")
HANGUL_AREA = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천])+\s*평")
PHONE = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}")
UNIT_NO = re.compile(r"\d{1,4}\s*동\s*\d{1,4}\s*호")
SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n+")
MULT = {"만원": 10_000, "만": 10_000, "천원": 1_000, "억원": 100_000_000, "억": 100_000_000}
SMALL_COUNT = 10

# 업체 비방 · 법률/안전 단정 · 금액 보장. 팀이 eval을 보며 늘린다
BANNED = re.compile(
    r"사기꾼|바가지|양아치|업체가\s*속이|"
    r"법적으로\s*(?:아무\s*)?문제(?:가)?\s*없|무조건\s*(?:승소|이겨)|하자가\s*확실히\s*아니|"
    r"(?:이|그)\s*금액으로\s*확정|금액을\s*보장|100\s*%\s*(?:보장|안전)"
)


@dataclass(frozen=True)
class GuardResult:
    text: str  # 통과한 문장만 이은 글(개인정보는 가림)
    dropped: tuple[str, ...]  # 버린 문장
    reasons: tuple[str, ...]  # 버린 이유(로그용, 입력값은 넣지 않는다)
    unknown_slots: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.dropped


def _value(raw: str, unit: str | None) -> Decimal | None:
    try:
        v = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    u = (unit or "").replace(" ", "")
    return v * MULT[u] if u in MULT else v


def numbers(text: str) -> set[Decimal]:
    """글에 든 숫자(만 원 · 억 등은 원 단위로 바꿈). 허용 집합을 만들 때와 검사할 때 같은 규칙을 쓴다."""
    out: set[Decimal] = set()
    for m in NUM.finditer(text):
        v = _value(m.group(1), m.group(2))
        if v is not None:
            out.add(v)
    return out


def render(text: str, slots: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    """⟦키⟧를 표시 글로 바꾼다. 모르는 키는 그대로 두고 목록으로 돌려준다."""
    unknown: list[str] = []

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in slots:
            return slots[key]
        unknown.append(key)
        return m.group(0)

    return SLOT.sub(sub, text), tuple(dict.fromkeys(unknown))


def mask(text: str) -> str:
    """전화번호 · 동호수 가림(Jev로 보내는 문장, 화면에 나가는 글 모두)."""
    return UNIT_NO.sub("(동호수 가림)", PHONE.sub("(번호 가림)", text))


def _small_count(v: Decimal, unit: str | None, rest: str) -> bool:
    """단위 없는 작은 정수가 세는 말(2가지 · 3번) 앞이거나 목록 번호(1.)면 허용"""
    if unit is not None or v > SMALL_COUNT or v != v.to_integral_value():
        return False
    return bool(COUNT_WORDS.match(rest)) or not rest.strip() or rest[:1] in ".)"


def _bad_numbers(sentence: str, allowed: set[Decimal]) -> bool:
    for m in NUM.finditer(sentence):
        v = _value(m.group(1), m.group(2))
        if v is None or v in allowed or _small_count(v, m.group(2), sentence[m.end() :]):
            continue
        return True
    return False


def check(text: str, slots: Mapping[str, str], cited: Iterable[str] = ()) -> GuardResult:
    """LLM 글 → 슬롯을 채우고 문장마다 검사. 통과한 문장만 남긴다."""
    rendered, unknown = render(text, slots)
    allowed = numbers(" ".join(slots.values())) | numbers(" ".join(cited))
    kept: list[str] = []
    dropped: list[str] = []
    reasons: list[str] = []
    for s in (x.strip() for x in SENTENCE.split(rendered)):
        if not s:
            continue
        why = None
        if SLOT.search(s):
            why = "모르는 슬롯"
        elif HANGUL_MONEY.search(s) or HANGUL_AREA.search(s):
            why = "한글로 쓴 금액 · 면적"
        elif _bad_numbers(s, allowed):
            why = "계산 엔진 · 인용에 없는 숫자"
        elif BANNED.search(s):
            why = "금지 표현"
        if why:
            dropped.append(s)
            reasons.append(why)
        else:
            kept.append(mask(s))
    return GuardResult(" ".join(kept), tuple(dropped), tuple(reasons), unknown)


def money(won: int) -> str:
    """슬롯 표시 글: 만 원 단위로 떨어지면 '264만 원', 아니면 '3,166,556원'."""
    if won % 10_000 == 0 and won >= 10_000:
        return f"{won // 10_000:,}만 원"
    return f"{won:,}원"
