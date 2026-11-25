"""AI 답 출력 검사 (화면 guard.ts를 서버로 옮긴 것). 고객에게 보내기 전에 문장마다 본다.

- 계산 결과 · 자료 · 고객이 쓴 글에 없는 숫자가 든 문장은 뺀다.
- 공사 기간(일 · 주 · 개월)은 계산 엔진 결과에 있는 숫자만 허용한다.
- 한글로 쓴 금액 · 면적, 쓰면 안 되는 표현이 든 문장도 뺀다.
- 전화번호 · 동호수는 가린다.
"""

import re
from dataclasses import dataclass, field

NUM = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(만\s*원|천\s*원|억\s*원|억|만|원|%|퍼센트|㎡|m²|평|일|개월|개|롤|cm|mm|m|배|시간|주|층|장|짝|명|인|품)?",
    re.ASCII,
)
COUNT_WORDS = re.compile(r"^\s*(가지|번|단계|번째|곳|군데|가지씩)")
HANGUL_MONEY = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천])+\s*(?:만|억)?\s*원")
HANGUL_AREA = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천])+\s*평")
PHONE = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}")
UNIT_NO = re.compile(r"\d{1,4}\s*동\s*\d{1,4}\s*호")
MULT = {"만원": 1e4, "만": 1e4, "천원": 1e3, "억원": 1e8, "억": 1e8}
BANNED = re.compile(
    r"사기꾼|바가지|양아치|업체가\s*속이|법적으로\s*(?:아무\s*)?문제(?:가)?\s*없|무조건\s*(?:승소|이겨)"
    r"|하자가\s*확실히\s*아니|(?:이|그)\s*금액으로\s*확정|금액을\s*보장|100\s*%\s*(?:보장|안전)"
)
PERIOD_UNITS = frozenset({"일", "주", "개월"})
RANGE_TO_PERIOD = re.compile(r"^\s*[~\-–]\s*\d+(?:\.\d+)?\s*(?:일|주|개월)")  # 3~5일의 3
DATE_BEFORE = re.compile(r"\d{1,2}\s*월\s*$")  # 12월 3일: 기간이 아니라 날짜
SENT = re.compile(r"(?<=[.!?。요])\s+")
CITE_ONLY = re.compile(r"^\[K\d+\]")


@dataclass
class Checked:
    text: str
    dropped: list[str] = field(default_factory=list)  # 뺀 이유 (문장 원문은 남기지 않음)


def _val(raw: str, unit: str | None) -> float | None:
    try:
        v = float(raw.replace(",", ""))
    except ValueError:
        return None
    return v * MULT.get((unit or "").replace(" ", ""), 1)


def numbers(text: str) -> set[float]:
    """글에 나온 숫자. 10만 이상은 만 원 단위 반올림 · 버림 값도 허용한다 (3,364,291원 → 336만 원).

    10만 아래는 반올림하지 않는다: 1.6만 원이 2만 원으로 통과하지 않게.
    """
    out: set[float] = set()
    for m in NUM.finditer(text or ""):
        v = _val(m.group(1), m.group(2))
        if v is None:
            continue
        out.add(round(v, 4))
        if v >= 100_000:
            out.add(round(v / 1e4) * 1e4)
            out.add((v // 1e4) * 1e4)
    return out


def mask(text: str) -> str:
    return UNIT_NO.sub("(동호수 가림)", PHONE.sub("(번호 가림)", text or ""))


def _small_count(v: float, unit: str | None, rest: str) -> bool:
    """'3가지', '2번째'처럼 단위 없는 작은 수는 센 수라서 허용한다."""
    if unit or v > 10 or not float(v).is_integer():
        return False
    return bool(COUNT_WORDS.match(rest)) or not rest.strip() or rest[0] in ".)"


def _is_period(sentence: str, m: re.Match) -> bool:
    unit = m.group(2)
    if unit in PERIOD_UNITS:
        return unit != "일" or not DATE_BEFORE.search(sentence[: m.start()])
    return unit is None and bool(RANGE_TO_PERIOD.match(sentence[m.end() :]))


def _bad_number(
    sentence: str, allowed: set[float], periods: set[float] | None = None
) -> str | None:
    for m in NUM.finditer(sentence):
        v = _val(m.group(1), m.group(2))
        if v is None:
            continue
        if periods is not None and _is_period(sentence, m):
            if round(v, 4) not in periods:
                return m.group(0).strip()  # 기간은 계산 결과에 있는 숫자만
            continue
        if round(v, 4) in allowed:
            continue
        if _small_count(v, m.group(2), sentence[m.end() :]):
            continue
        return m.group(0).strip()
    return None


def _why(s: str, allowed: set[float], periods: set[float] | None = None) -> str | None:
    if HANGUL_MONEY.search(s) or HANGUL_AREA.search(s):
        return "한글로 쓴 금액 · 면적"
    bad = _bad_number(s, allowed, periods)
    if bad:
        return f"계산 결과 · 자료에 없는 숫자({bad})"
    if BANNED.search(s):
        return "쓰면 안 되는 표현"
    return None


def check(text: str, allowed_text: str, calc_text: str | None = None) -> Checked:
    """text: AI 글, allowed_text: 계산 결과 · 자료 · 고객 글을 이은 글. 줄 바꿈은 그대로 둔다.

    calc_text를 주면 공사 기간(일 · 주 · 개월) 숫자는 그 글(계산 엔진 결과)에 있어야만 통과한다.
    """
    allowed = numbers(allowed_text)
    periods = None if calc_text is None else numbers(calc_text)
    out_lines: list[str] = []
    dropped: list[str] = []
    for line in mask(text).split("\n"):
        if not line.strip():
            out_lines.append("")
            continue
        parts: list[str] = []
        for s in (x.strip() for x in SENT.split(line)):
            if not s:
                continue
            if CITE_ONLY.match(s) and parts:
                parts[-1] += " " + s  # 근거 표시는 앞 문장에 붙인다
            else:
                parts.append(s)
        kept = []
        for s in parts:
            why = _why(s, allowed, periods)
            if why:
                dropped.append(why)
            else:
                kept.append(s)
        if kept:
            out_lines.append(" ".join(kept))
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    return Checked(text=body, dropped=dropped)
