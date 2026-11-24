"""받은 견적서 견주기(순수 함수): 고객이 믿집 밖(동네 지업사 · 숨고 등)에서 받은 도배 견적서 줄 ↔ 이 집 도배 표준견적서 줄.

- 줄 맞추기(item_of · classify): 외부 줄 이름을 표준 항목(벽지 · 인건비 · 올퍼티 · 부분퍼티 · 초배지/부자재 · 폐기물 · 보양 ·
  철거 · 식대/운송 · 기타)에 낱말로 맞춘다. 벽지 · 인건비 · 부자재를 한 줄로 받은 '도배 일체' 줄은 묶음(bundle)으로,
  합계 · 부가세 줄은 빼고(skip), 음수 · 할인 줄은 할인으로 본다. 괄호 밖 이름을 먼저 보고, 못 맞추면 괄호까지 본다.
- 금액: 외부 줄 금액은 고객이 준 값 그대로다(수량 × 단가만 적힌 줄은 여기서 곱한다). 부가세 기준을 맞추고(별도면 더함,
  여부를 모르면 적힌 값 그대로) 합 · 차는 여기서만 센다(won 한 곳). 표준 줄은 공급가라 부가세를 붙여 견준다.
- 판정: 줄 · 합계마다 많음 · 적음(BAND 밖) · 비슷, 줄에는 빠짐(표준엔 합계에 드는데 외부에 없음) · 표준에 없음 · 할인 ·
  금액 없음(포함 · 따로라고만 적힌 줄)도 있다. 표준 합계 밖 줄(선택 · 실측 후 · 고객 구매)은 외부에 그 줄이 있을 때만
  같은 범위로 더해 견준다(added).
- 합계 둘: 같은 범위 합(outside_cmp)은 표준에 없는 줄(표준에 금액이 없는 항목 · 기타)을 빼고 표준 합과 견준다(차이 ·
  판정). 받은 줄 모두 합(outside_total)은 적힌 합계(빠진 줄 묻기) · 희망 예산과 견준다.
- 올퍼티(full_putty): 이 집 도배 유형 · 철거 범위 · 표준 퍼티 줄 상태로 권함 · 실측 때 확인 · 부분퍼티로 충분 + 근거 한 줄.
- 표준 대비 %는 내지 않는다(차이는 원 단위만, docs/v4/08-rules.md 숫자). 물을 말은 '-요' 틀 글이다.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

from app.calc.common import COUNTED, VAT_RATE, with_vat, won

VatWay = Literal["included", "excluded", "unknown"]  # 부가세 포함 · 별도 · 적혀 있지 않음
Item = Literal[
    "paper", "labor", "putty_full", "putty_part", "material", "waste", "cover", "removal",
    "meal_truck", "other", "bundle", "discount", "skip",
]  # fmt: skip
Group = Literal["paper", "labor", "material", "putty", "meal_truck", "removal", "waste", "cover"]
RowState = Literal["missing", "more", "same", "less", "extra", "discount", "noprice"]
Judge = Literal["more", "same", "less"]
PuttyNeed = Literal["need", "check", "no"]
PuttyFound = Literal["full", "part", "none"]
BudgetState = Literal["within", "over", "under"]

# 많음 · 적음 폭(받은 금액 ÷ 표준 금액): 시장 실견적 ÷ 시장 기준 가운데 50% 띠(refprice/market.py market-2026.11-v5.1,
# 2025~2026 실견적 806건 · 출처마다 같은 무게, 시험이 그 값과 맞춰 본다). 이 띠 밖이면 시장 견적 넷 중 하나보다 더
# 벗어난 값이에요. 도배 유형별(실크 basic · 합지 economy), 모르면 실크
BAND: dict[str, tuple[Decimal, Decimal]] = {
    "basic": (Decimal("0.89"), Decimal("1.27")),
    "economy": (Decimal("0.90"), Decimal("1.19")),
}
# 줄 차이가 이보다 작으면 띠 밖이어도 '비슷'(작은 줄의 몇 만 원으로 많음 · 적음을 내지 않게). 도배만 하는 공사 기준
# 운송 · 경비 한 줄 값(refprice/book.py DOBAE_MARKET_2026_11 truck 50,000원)
LINE_MIN_WON = 50_000
# 적힌 합계와 줄 합(부가세 맞춘 값)이 이만큼 넘게 다르면 물을 것으로 둬요(견적서는 만 원 아래를 끊어 적는 일이 많아요)
STATED_GAP_WON = 10_000
ASKS_MAX = 5

GROUPS: tuple[Group, ...] = (
    "paper", "labor", "material", "putty", "meal_truck", "removal", "waste", "cover",
)  # fmt: skip
GROUP_NAME: dict[str, str] = {
    "paper": "벽지", "labor": "인건비", "material": "초배지 · 부자재", "putty": "퍼티",
    "meal_truck": "식대 · 운송", "removal": "철거", "waste": "폐기물", "cover": "보양",
}  # fmt: skip
ITEM_NAME: dict[str, str] = {
    "paper": "벽지", "labor": "인건비", "putty_full": "올퍼티", "putty_part": "부분퍼티",
    "material": "초배지 · 부자재", "waste": "폐기물", "cover": "보양", "removal": "철거",
    "meal_truck": "식대 · 운송", "other": "기타",
}  # fmt: skip
GROUP_OF: dict[str, Group] = {
    "paper": "paper", "labor": "labor", "putty_full": "putty", "putty_part": "putty",
    "material": "material", "waste": "waste", "cover": "cover", "removal": "removal",
    "meal_truck": "meal_truck",
}  # fmt: skip
# 표준견적서 줄 키(calc.dobae 두 기준 · 옛 v3 줄) → 견줄 항목
STANDARD_GROUP: dict[str, Group] = {
    "paper": "paper", "wall": "labor", "ceiling": "labor", "occupied": "labor",
    "putty": "putty", "material": "material", "primer": "material", "meal": "meal_truck",
    "truck": "meal_truck", "removal": "removal", "waste": "waste", "moving": "cover",
}  # fmt: skip
BUNDLE_GROUPS: tuple[Group, ...] = ("paper", "labor", "material")
BUNDLE_NAME = "도배 일체(벽지 · 인건비 · 부자재)"
TOTAL_NAME = "견적서 합계"
# 외부에 없어도 빠짐이 아닌 줄(표준도 실측 때 정해요): 이 견적서에 들어 있는지만 물어요
AFTER_VISIT_GROUPS: tuple[Group, ...] = ("removal", "waste", "cover")
# 표준 줄이 합계 밖일 때 줄 아래 말
STD_NOTE = {
    "optional": "표준견적서에서는 선택 줄(합계 밖)이에요",
    "after_visit": "표준견적서에서는 실측 후 정하는 줄이에요",
    "excluded": "표준견적서에서는 합계 밖 줄이에요",
}
MENTION_NOTE = {
    "included": "견적서에 다른 줄에 포함이라고 적혀 있어요",
    "separate": "견적서에 따로 받는다고 적혀 있어요(금액 없음)",
}
# 많음 줄에서 그 업체에 물을 것(없으면 '무엇이 들었는지')
ASK_MORE = {
    "labor": "몇 명이 며칠 일하는 값인지",
    "paper": "벽지 제품 이름과 롤 수를",
    "material": "부자재에 무엇이 드는지",
    "putty": "퍼티를 어디까지(못 자국 · 벽 전체) 하는지",
    "bundle": "벽지 · 인건비 · 부자재를 줄마다 나눠 달라고",
}

# ---- 줄 맞추기 낱말(괄호 밖 이름 → 괄호까지, 위에서부터 처음 맞는 것) ----
_PAREN = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|（[^（）]*）")
_DISCOUNT = re.compile(
    r"할인|네고|에누리|(?<![a-z])d\s*/?\s*c(?![a-z])|단수\s*(?:정리|조정)|절사|차감", re.IGNORECASE
)
_SKIP = re.compile(
    r"소\s*계|합\s*계|총\s*(?:액|계|금액|합계)|공급\s*가\s*액|부\s*가\s*(?:가치)?\s*세|(?<![a-z])vat(?![a-z])",
    re.IGNORECASE,
)
_COVER = re.compile(r"보양|짐\s*(?:이동|정리|옮김|빼기)|가구\s*(?:이동|옮김)|이삿짐")
_OTHER = re.compile(
    r"곰팡이|결로|방수|단열|몰딩|걸레\s*받이|장판|마루|바닥재|타일|조명|전등|전기|콘센트|스위치|필름|시트지|페인트|도장"
    r"|욕실|싱크|창호|샷시|섀시|중문|커튼|블라인드|문짝|문틀|붙박이"
)
_SEP = r"\s*[+＋&,·/및와]\s*"
_BUNDLE = re.compile(
    rf"일체|일식|통\s*견적|전체\s*공사|공사\s*비|자재\s*비?\s*포함|자재\s*비?{_SEP}(?:시공|인건|공임|설치)"
    rf"|(?:시공|인건|공임|설치)\s*비?\s*포함|(?:시공|인건|공임|설치)\s*비?{_SEP}자재"
)
_PUTTY_FULL = re.compile(
    r"올\s*(?:퍼티|빠데|빠대)|(?:전체|전면)\s*(?:퍼티|빠데|빠대)|(?:퍼티|빠데|빠대)\s*(?:전체|전면)"
)
_PUTTY = re.compile(
    r"퍼티|빠데|빠대|핸디|메꿈|크랙|사전\s*작업|밑\s*작업|바탕\s*(?:작업|정리|처리)|면\s*(?:정리|처리)|샌딩"
)
_REMOVAL = re.compile(r"철거|제거|뜯|(?<![가-힣])떼|탈거|벗기")
_WASTE = re.compile(r"폐기물|폐자재|쓰레기|마대|반출|수거|처리\s*비")
_MEAL_TRUCK = re.compile(
    r"식대|식비|점심|밥값|운송|운반|차량|화물|트럭|용달|주차|출장|교통비|유류|경비"
)
_MATERIAL = re.compile(
    r"초배|부자재|부직포|네바리|운용지|본드|실리콘|부속|도배\s*풀|풀\s*값|(?<![가-힣])풀(?![가-힣])(?!\s*(?:포함|옵션|세트))"
)
_LABOR = re.compile(
    r"인건비|시공|노임|인부|기술자|기능공|도배\s*(?:공|사)(?![가-힣])|작업\s*비|공임|일당|인원|조공|기공"
    r"|(?<![가-힣\d])품(?![가-힣])|\d\s*품(?![가-힣])"
)
_PAPER_GOODS = re.compile(r"벽지|도배지|정배지|실크|합지|광폭|소폭|디아망|베스띠|테라피|지물")
_PAPER = re.compile(rf"{_PAPER_GOODS.pattern}|자재")
_JOB = re.compile(
    r"도배(?!\s*(?:지|풀|공(?!사)|사(?![가-힣])))"
)  # 일 전체를 말하는 '도배'(도배지 · 도배풀 · 도배공은 아님)
_NOT_PAPER = re.compile(r"(?:자재|벽지)\s*(?:는|은)?\s*별도")  # '자재 별도': 벽지는 이 줄에 없어요
_RULES: tuple[tuple[Item, re.Pattern[str]], ...] = (
    ("discount", _DISCOUNT),
    ("skip", _SKIP),
    ("cover", _COVER),
    ("other", _OTHER),
    ("bundle", _BUNDLE),
    ("putty_full", _PUTTY_FULL),
    ("putty_part", _PUTTY),
    ("removal", _REMOVAL),
    ("waste", _WASTE),
    ("meal_truck", _MEAL_TRUCK),
    ("material", _MATERIAL),
)


def _core(text: str) -> Item | None:
    """벽지 · 인건비 · 묶음: 일하는 말이 있으면 인건비, 벽지 이름 + '도배'면 묶음('실크 도배'), 벽지 이름이면 벽지,
    '도배'만 있으면 묶음('도배 32평')."""
    if _LABOR.search(text):
        return "labor"
    if _PAPER_GOODS.search(text) and _JOB.search(text):
        return "bundle"
    if _PAPER.search(text):
        return "paper"
    if _JOB.search(text):
        return "bundle"
    return None


def _match(text: str) -> Item | None:
    for item, rx in _RULES:
        if rx.search(text):
            return item
    return _core(text)


def item_of(name: str, amount: int | None = None) -> Item:
    """외부 줄 이름 → 표준 항목. 음수 금액은 할인, 못 맞추면 기타."""
    if amount is not None and amount < 0:
        return "discount"
    head = _PAREN.sub(" ", name or "")
    for text in (head, name or ""):
        got = _match(text)
        if got is not None:
            return got
    return "other"


@dataclass(frozen=True)
class OutsideLine:
    """외부 견적서 줄 하나(뽑은 값). 금액은 고객이 준 값(원, 할인은 음수)이고, 비면 수량 × 단가로 세거나 '포함 · 따로'만
    적힌 줄(note)이다. 수량 · 단위는 보이기만 하고, 단가가 있을 때만 곱한다."""

    name: str
    amount: int | None = None
    vat: VatWay = "unknown"
    qty: Decimal | None = None
    unit: str | None = None
    unit_price: int | None = None
    note: Literal["included", "separate"] | None = None


class StdLine(Protocol):
    """표준견적서 줄(calc.common.Line · quote.schemas.StandardLineOut): 키 · 이름 · 공급가 · 포함 상태만 쓴다."""

    @property
    def key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def amount(self) -> int | None: ...
    @property
    def state(self) -> str: ...


def amount_of(ln: OutsideLine) -> int | None:
    """줄 금액: 적힌 금액, 없으면 수량 × 단가(원 단위 반올림), 그것도 없으면 None."""
    if ln.amount is not None:
        return ln.amount
    if ln.qty is not None and ln.unit_price is not None:
        return won(ln.qty * ln.unit_price)
    return None


def classify(lines: Sequence[OutsideLine]) -> list[Item]:
    """줄마다 항목. 벽지 줄 · 묶음 줄이 따로 없으면 벽지 이름이 든 시공 줄('실크벽지 시공')은 묶음으로 본다
    ('자재 별도'라고 적힌 줄은 그대로 인건비)."""
    items = [item_of(ln.name, amount_of(ln)) for ln in lines]
    if "paper" in items or "bundle" in items:
        return items
    return [
        "bundle"
        if it == "labor" and _PAPER_GOODS.search(ln.name) and not _NOT_PAPER.search(ln.name)
        else it
        for it, ln in zip(items, lines, strict=True)
    ]


def vat_in(amount: int, vat: VatWay, rate: Decimal = VAT_RATE) -> int:
    """부가세 포함으로 맞춘 금액: 별도면 공급가로 보고 부가세를 더하고(할인은 음수 그대로), 포함 · 모름은 적힌 값."""
    if vat != "excluded":
        return amount
    got = with_vat(abs(amount), rate).total
    return got if amount >= 0 else -got


def judge(outside: int, standard: int, band: tuple[Decimal, Decimal], min_won: int = 0) -> Judge:
    """받은 금액 ÷ 표준 금액이 띠 위면 많음 · 아래면 적음, 안이면 비슷. 차이가 min_won보다 작으면 늘 비슷."""
    if standard <= 0:
        raise ValueError("표준 금액은 0보다 커야 해요")
    if abs(outside - standard) < min_won:
        return "same"
    lo, hi = band
    if Decimal(outside) > Decimal(standard) * hi:
        return "more"
    if Decimal(outside) < Decimal(standard) * lo:
        return "less"
    return "same"


# ---- 올퍼티 ----
# 근거(규칙 대신 이 집 조건 셋):
# - 계산 엔진의 퍼티 판단: 도배만 하는 공사 기준은 퍼티가 '선택'(넣은 견적 5~38%), 전체 철거 · 큰 목공이 든 리모델링
#   기준은 '포함'(서울 업체 실견적 235건 모두 퍼티 줄): refprice/book.py DOBAE_MARKET_2026_11 · DOBAE_REMODEL_2026_11
# - 실크는 얇아 이음매 · 굴곡이 비치고 합지는 두께가 있어 덜 비쳐요. 올퍼티는 벽 전체를 바르고 갈아 면을 고르게 해요
#   (assistant/prompts/expert_dobae_v2.md 퍼티 줄 · knowledge 표준품셈 줄퍼티 · 올퍼티 품)
PUTTY_LABEL = {
    "need": "올퍼티 권해요",
    "check": "실측 때 벽 보고 정해요",
    "no": "부분퍼티로 충분해요",
}
FOUND_LABEL = {"full": "올퍼티 있음", "part": "부분퍼티만 있음", "none": "퍼티 줄 없음"}


def full_putty(
    grade: str | None, demolition: str | None, putty_state: str | None
) -> tuple[PuttyNeed, str]:
    """이 집 올퍼티 판단 + 근거 한 줄. 합지는 부분퍼티로 충분, 실크 + 전체 철거는 권함, 그 밖의 실크는 실측 때 확인
    (리모델링 기준이라 표준에 퍼티가 들었으면 그 말로). 도배 유형을 모르면 실크로 본다."""
    if grade == "economy":
        return "no", (
            "합지는 두께가 있어 작은 굴곡 · 이음매가 덜 비쳐요. 못 자국 · 이음매만 메우는 부분퍼티로 충분한 경우가 "
            "많아요."
        )
    if demolition == "full":
        return "need", (
            "전체 철거 뒤 새로 마감한 벽에 실크를 바르면 이음매 · 굴곡이 그대로 비쳐요. 벽 전체를 바르고 가는 올퍼티를 "
            "권해요."
        )
    if putty_state in COUNTED:
        return "check", (
            "리모델링 기준이라 표준견적서에 퍼티가 들어 있어요. 벽 전체(올퍼티)까지 할지는 실측 때 벽 상태로 정해요."
        )
    return "check", (
        "철거 없이 기존 벽에 실크를 바르면 부분퍼티로 충분한 경우가 많아요. 벽이 많이 울퉁불퉁하면 실측 때 올퍼티를 "
        "권할 수 있어요."
    )


@dataclass(frozen=True)
class PuttyCheck:
    need: PuttyNeed
    why: str
    found: PuttyFound  # 외부 견적서에 있는 퍼티
    ask: str | None  # 그 업체에 물을 말(없으면 None)


def putty_check(
    grade: str | None, demolition: str | None, putty_state: str | None, found: PuttyFound
) -> PuttyCheck:
    need, why = full_putty(grade, demolition, putty_state)
    ask = None
    if need == "need" and found != "full":
        ask = (
            "이 집은 올퍼티를 권하는데 견적서에는 부분퍼티만 있어요. 올퍼티로 할지 물어보세요."
            if found == "part"
            else "이 집은 올퍼티를 권하는데 견적서에 퍼티 줄이 없어요. 넣을지 물어보세요."
        )
    elif need == "no" and found == "full":
        ask = "합지는 올퍼티가 꼭 필요하진 않아요. 올퍼티를 넣은 까닭을 물어보세요."
    elif need == "check" and found == "full":
        ask = "올퍼티를 넣은 까닭(벽 상태)을 물어보세요."
    return PuttyCheck(need, why, found, ask)


# ---- 희망 예산 ----


@dataclass(frozen=True)
class BudgetCheck:
    state: BudgetState
    gap: int | None  # 넘거나 모자란 금액(안이면 None)
    low: int | None
    high: int | None


def budget_check(total: int, low: int | None, high: int | None) -> BudgetCheck:
    """받은 견적서 합계(부가세 맞춘 값)와 희망 예산 범위: 위 한도보다 많으면 over, 아래 한도보다 적으면 under."""
    if (low is not None and low <= 0) or (high is not None and high <= 0):
        raise ValueError("예산은 0보다 커야 해요")
    if low is not None and high is not None and low > high:
        raise ValueError("예산 범위를 다시 확인해 주세요")
    if high is not None and total > high:
        return BudgetCheck("over", total - high, low, high)
    if low is not None and total < low:
        return BudgetCheck("under", low - total, low, high)
    return BudgetCheck("within", None, low, high)


# ---- 견주기 ----


@dataclass(frozen=True)
class Row:
    key: str  # 견줄 항목(GROUPS · bundle) 또는 other · discount
    name: str
    state: RowState
    outside: int | None  # 받은 금액(부가세 맞춘 값)
    standard: int | None  # 표준 금액(부가세 포함)
    diff: int | None  # outside − standard
    lines: tuple[str, ...] = ()  # 이 줄에 든 외부 줄 이름
    note: str | None = None


@dataclass(frozen=True)
class Compare:
    rows: list[Row]
    # 받은 줄 모두 합(부가세 맞춘 값, 표준에 없는 줄 · 할인 포함): 적힌 합계 · 희망 예산과 견줘요
    outside_total: int
    outside_cmp: int  # 같은 범위 받은 합(outside_total − extra_total, 할인은 남김)
    standard_cmp: int  # 같은 범위 표준 합(부가세 포함)
    diff: int  # outside_cmp − standard_cmp
    state: Judge  # outside_cmp ↔ standard_cmp
    added: tuple[str, ...]  # 표준 합계 밖인데 외부에 있어 더한 표준 줄
    extra_total: int  # 표준에 없는 줄 합(줄 상태 extra: 표준에 금액이 없는 항목 · 기타 줄)
    vat_unknown: bool  # 부가세 여부가 적혀 있지 않은 줄이 있어 적힌 값 그대로 견줌
    stated_gap: int | None  # 적힌 합계 − 받은 줄 모두 합(STATED_GAP_WON을 넘을 때만): 빠진 줄 묻기
    putty: PuttyCheck
    budget: BudgetCheck | None
    asks: tuple[str, ...]  # 그 업체에 물을 것
    skipped: tuple[str, ...] = ()  # 합계 · 부가세라 뺀 줄 이름
    total_only: bool = False  # 줄 없이 합계만 있는 견적서


@dataclass
class _Std:
    counted: int = 0
    other: int = 0
    states: list[str] = field(default_factory=list)

    def note(self) -> str | None:
        """합계에 드는 줄이 없을 때 표준 줄 상태 말(선택 · 실측 후 · 합계 밖)."""
        if any(s in COUNTED for s in self.states):
            return None
        return next((STD_NOTE[s] for s in self.states if s in STD_NOTE), None)


def _std_groups(lines: Sequence[StdLine]) -> dict[str, _Std]:
    out: dict[str, _Std] = {}
    for ln in lines:
        g = STANDARD_GROUP.get(ln.key)
        if g is None:
            continue
        st = out.setdefault(g, _Std())
        st.states.append(ln.state)
        if ln.amount is None or ln.amount <= 0:
            continue
        if ln.state in COUNTED:
            st.counted += ln.amount
        else:
            st.other += ln.amount
    return out


def _josa(word: str, pair: tuple[str, str]) -> str:
    """받침에 맞춘 조사('이', '가') · ('은', '는'). 끝이 한글이 아니면 받침 없음으로 본다."""
    last = word.rstrip()[-1:]
    has = bool(last) and "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return f"{word}{pair[0] if has else pair[1]}"


IGA, EUN = ("이", "가"), ("은", "는")


def compare(
    lines: Sequence[OutsideLine],
    standard: Sequence[StdLine],
    *,
    grade: str | None = None,
    demolition: str | None = None,
    stated_total: int | None = None,
    stated_vat: VatWay = "unknown",
    budget: tuple[int | None, int | None] | None = None,
    vat_rate: Decimal = VAT_RATE,
) -> Compare:
    """외부 견적서 줄 ↔ 표준견적서 줄(도배). 도배 줄(항목 · 묶음)이 하나도 없고 적힌 합계도 없으면 ValueError.
    줄 없이 합계만 있으면 합계 한 줄로 표준 합계와 견준다(total_only). budget = (아래, 위) 한도(원, 한쪽은 비워도 됨)."""
    band = BAND.get(grade or "basic", BAND["basic"])
    items = classify(lines)
    std = _std_groups(standard)
    putty_line = next((ln for ln in standard if ln.key == "putty"), None)
    priced: dict[str, list[tuple[OutsideLine, int]]] = {}
    mentioned: dict[str, list[OutsideLine]] = {}
    found: set[str] = set()
    skipped: list[str] = []
    for ln, it in zip(lines, items, strict=True):
        if it == "skip":
            skipped.append(ln.name)
            continue
        key = GROUP_OF.get(it, it)
        amt = amount_of(ln)
        if amt is None:
            if ln.note is None:
                continue
            mentioned.setdefault(key, []).append(ln)
        else:
            priced.setdefault(key, []).append((ln, vat_in(amt, ln.vat, vat_rate)))
        if it in ("putty_full", "putty_part"):
            found.add(it)
    dobae_keys = {*GROUPS, "bundle"}
    total_only = False
    if not any(k in dobae_keys for k in [*priced, *mentioned]):
        if stated_total is None or priced:
            raise ValueError("견적서에서 도배 줄을 찾지 못했어요")
        total_only = True
        whole = OutsideLine(TOTAL_NAME, stated_total, stated_vat)
        priced["bundle"] = [(whole, vat_in(stated_total, stated_vat, vat_rate))]
    kind: PuttyFound = (
        "full" if "putty_full" in found else "part" if "putty_part" in found else "none"
    )
    putty = putty_check(grade, demolition, putty_line.state if putty_line else None, kind)
    merged: tuple[Group, ...] = ()
    if total_only:
        merged = GROUPS
    elif "bundle" in priced or "bundle" in mentioned:
        merged = BUNDLE_GROUPS

    rows: list[Row] = []
    asks: list[str] = []  # 빠짐 · 따로 받음
    more: list[str] = []  # 많음
    added: list[str] = []
    std_total = 0
    after: list[str] = []
    order: list[str] = (["bundle"] if merged else []) + [g for g in GROUPS if g not in merged]
    for key in order:
        groups: tuple[str, ...] = merged if key == "bundle" else (key,)
        keys = ("bundle", *merged) if key == "bundle" else (key,)
        got = [x for k in keys for x in priced.get(k, [])]
        said = [ln for k in keys for ln in mentioned.get(k, [])]
        sts = [std[g] for g in groups if g in std]
        counted = sum(s.counted for s in sts)
        other = sum(s.other for s in sts)
        name = (TOTAL_NAME if total_only else BUNDLE_NAME) if key == "bundle" else GROUP_NAME[key]
        if key == "putty" and found:
            kinds = [ITEM_NAME[k] for k in ("putty_full", "putty_part") if k in found]
            name = f"퍼티({' · '.join(kinds)})"
        names = tuple([ln.name for ln, _ in got] + [ln.name for ln in said])
        has = bool(got or said)
        std_total += counted
        use = counted
        if not counted and has and other:
            use = other
            std_total += other
            added.append(GROUP_NAME.get(key, name))
        std_in = with_vat(use, vat_rate).total if use else None
        note = next((n for s in sts if (n := s.note()) is not None), None) if not counted else None
        if got:
            amount = sum(a for _, a in got)
            if std_in is None:
                rows.append(Row(key, name, "extra", amount, None, None, names, note))
                continue
            rs: RowState = judge(amount, std_in, band, LINE_MIN_WON)
            rows.append(Row(key, name, rs, amount, std_in, amount - std_in, names, note))
            if rs == "more":
                what = ASK_MORE.get(key, "무엇이 들었는지")
                more.append(
                    f"{_josa(name, IGA)} 표준보다 {amount - std_in:,}원 많아요. {what} 물어보세요."
                )
        elif said:
            way = "separate" if any(ln.note == "separate" for ln in said) else "included"
            rows.append(Row(key, name, "noprice", None, std_in, None, names, MENTION_NOTE[way]))
            if way == "separate":
                asks.append(f"{_josa(name, EUN)} 따로 받는다고 적혀 있어요. 얼마인지 물어보세요.")
        elif counted and not total_only:
            rows.append(Row(key, name, "missing", None, std_in, None, (), None))
            if not (key == "putty" and putty.ask):  # 퍼티는 올퍼티 판단이 물을 말을 낸다
                asks.append(
                    f"{_josa(name, IGA)} 견적서에 없어요. 다른 줄에 들어 있는지 물어보세요."
                )
        elif key in AFTER_VISIT_GROUPS and sts and not total_only:
            after.append(name)
    if total_only:
        asks.append(
            "줄마다 나눈 견적서를 받아 보세요. 무엇이 들어 있는지 알아야 줄마다 견줄 수 있어요."
        )
    for ln, amount in priced.get("other", []):
        rows.append(Row("other", ln.name, "extra", amount, None, None, (ln.name,)))
    for ln, amount in priced.get("discount", []):
        rows.append(Row("discount", ln.name, "discount", amount, None, None, (ln.name,)))

    outside_total = sum(a for k in priced for _, a in priced[k])  # 받은 줄 모두 합
    # 표준에 없는 줄: 표준에 금액이 없는 항목(폐기물 · 보양 등) · 기타. 줄로만 보이고 같은 범위 합에서 빼요
    extra_total = sum(r.outside or 0 for r in rows if r.state == "extra")
    outside_cmp = outside_total - extra_total
    standard_cmp = with_vat(std_total, vat_rate).total
    state: Judge = judge(outside_cmp, standard_cmp, band) if standard_cmp > 0 else "same"
    vat_unknown = any(ln.vat == "unknown" for k in priced for ln, _ in priced[k])
    stated_gap = None
    checks: list[str] = []  # 합계 · 부가세
    if stated_total is not None and not total_only:
        # 적힌 합계는 받은 줄 모두 합과 견줘요(같은 범위 합이 아니에요): 빠진 줄이 있는지 묻기
        gap = vat_in(stated_total, stated_vat, vat_rate) - outside_total
        if abs(gap) > STATED_GAP_WON:
            stated_gap = gap
            checks.append(
                f"견적서에 적힌 합계와 줄을 더한 값이 {abs(gap):,}원 달라요. 빠진 줄이 있는지 물어보세요."
            )
    if vat_unknown:
        checks.append(
            "견적서에 부가세 말이 없어 적힌 금액 그대로 견줬어요. 부가세를 따로 받는지 물어보세요."
        )
    if after:
        checks.append(
            f"{_josa(' · '.join(after), IGA)} 이 견적서에 들어 있는지 물어보세요(표준견적서도 실측 때 정해요)."
        )
    # 물을 말 차례: 올퍼티 → 빠짐 · 따로 받음 → 많음 → 합계 · 부가세 → 실측 후 줄(ASKS_MAX까지)
    asks = [*([putty.ask] if putty.ask else []), *asks, *more, *checks]
    # 희망 예산은 낼 돈(받은 줄 모두 합)과 견줘요
    got_budget = budget_check(outside_total, *budget) if budget is not None else None
    return Compare(
        rows=rows,
        outside_total=outside_total,
        outside_cmp=outside_cmp,
        standard_cmp=standard_cmp,
        diff=outside_cmp - standard_cmp,
        state=state,
        added=tuple(added),
        extra_total=extra_total,
        vat_unknown=vat_unknown,
        stated_gap=stated_gap,
        putty=putty,
        budget=got_budget,
        asks=tuple(dict.fromkeys(asks))[:ASKS_MAX],
        skipped=tuple(skipped),
        total_only=total_only,
    )
