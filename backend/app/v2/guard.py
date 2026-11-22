"""AI 답 출력 검사 (화면 guard.ts를 서버로 옮긴 것). 고객에게 보내기 전에 문장마다 본다.

- 계산 결과 · 자료 · 고객이 쓴 글에 없는 숫자가 든 문장은 뺀다.
- 공사 기간(일 · 주 · 개월)은 계산 엔진 결과에 있는 숫자만 허용한다.
- 한글로 쓴 금액 · 면적, 쓰면 안 되는 표현이 든 문장도 뺀다.
- 개인정보는 가린다(shared/pii.mask, v3 check와 같은 규칙 하나).
- v4 비서 대화(runtime.SentenceGate)만 어림 · 파생 · 날짜를 더 읽는다(ground · loose, 아래 'v4 대화 숫자' 절).
  v2 · v3 답 파이프라인 안쪽 검사(check · _bad_number)는 그대로다.
"""

import math
import re
from bisect import bisect_left
from dataclasses import dataclass, field

from app.shared.pii import mask

NUM = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(만\s*원|천\s*원|억\s*원|억|만|원|%|퍼센트|㎡|m²|평|일|개월|개|롤|cm|mm|m|배|시간|주|층|장|짝|명|인|품)?",
    re.ASCII,
)
COUNT_WORDS = re.compile(r"^\s*(가지|번|단계|번째|곳|군데|가지씩)")
HANGUL_MONEY = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천])+\s*(?:만|억)?\s*원")
HANGUL_AREA = re.compile(r"(?:[일이삼사오육칠팔구]?[십백천])+\s*평")
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


# ---- v4 대화 숫자(runtime.SentenceGate 길만, docs/v4/08-rules.md 숫자 절) ----
# 근거(허용 글: 이번 턴 도구 결과 · 턴 사실 · 고객 말)에서 다시 만들어지는 숫자만 보낸다. 옛 검사(numbers ·
# _small_count)를 지나는 숫자는 그대로 지나고, 그 밖에 아래만 더 읽는다.
# - 어림: 근거 금액 V(10만 이상)와 3% 안의 더 둥근 수 R(문장에 약 · 쯤 · 정도 · 안팎 · 가량), 'R만 원대'(R ≤ V < 다음 자리)
# - 파생: 근거 금액(1만 이상) 둘의 합 · 차, 근거 금액(10만 이상) ÷ 근거 면적(평 · ㎡). 조합은 둘까지. 파생 값은 그대로
#   (원 단위 올림 · 내림) · 만 원 반올림 · 버림(10만 이상)으로 지나고, 1만 이상이면 위 어림 · 원대로도 지난다
# - 금액 묶음: '301만 6,000원' · '1억 2,000만 원'은 한 금액으로 본다(묶음으로 안 맞으면 옛 검사처럼 나눠서)
# - 날짜: '12월 15일' · '12.15(화)' · '12/15' · ISO · '2027.1.4(월)'을 날짜로 읽고(소수 12.15로 읽지 않음) 근거 글에
#   같은 월 · 일이 날짜로 있으면 통과. 없으면 옛 검사처럼 월 · 일 숫자를 따로 본다. 요일 없는 '12.15'는 근거 날짜일 때만
# - 그대로: 근거 없는 돈 숫자, 기간(일 · 주 · 개월) · % 같은 그 밖 숫자(근거 값 그대로), 한글 금액(HANGUL_MONEY),
#   표준 대비 %(부르는 쪽 policy.VS_STANDARD)

APPROX = re.compile(r"(?<![가-힣])약\s?\d|쯤|정도|안팎|가량")
BAND = re.compile(r"^대(?!신)")  # '300만 원대'의 대(띄어 쓴 '원 대신'은 아님)
MONEY_UNITS = frozenset({"만원", "천원", "억원", "억", "만", "원"})
AREA_UNITS = frozenset({"평", "㎡", "m²"})
AREA_KEY = re.compile(r'"(?:area_m2|area|pyeong)"\s*:\s*(\d+(?:\.\d+)?)')
# 금액 묶음의 단위 자리(큰 단위부터 이어 써야 한 금액)
RANK = {"억": 4, "억원": 4, "만": 3, "만원": 3, "천원": 2, "원": 1}
LOOSE_MIN = 100_000  # 어림 · 원대의 근거 금액
PART_MIN = 10_000  # 합 · 차에 쓰는 근거 금액, 어림 · 원대에 쓰는 파생 값
MONEY_MAX = 60  # 합 · 차에 쓰는 근거 금액 수(글에 나온 차례로)
AREA_MAX = 1000  # 나누는 면적(평 · ㎡)의 위 한도
APPROX_RATE = 0.03
_WD = r"\s?\([월화수목금토일]\)"
_MO = r"1[0-2]|0?[1-9]"
_DA = r"3[01]|[12]\d|0?[1-9]"
DATE_KO = re.compile(rf"(?<!\d)(?:\d{{4}}\s?년\s?)?(?P<m>{_MO})\s?월\s?(?P<d>{_DA})\s?일(?:{_WD})?")
# '12월 1일(화)~4일(금)'의 뒤 날
DATE_KO_TAIL = re.compile(rf"\s?[~∼〜]\s?(?P<d>{_DA})\s?일(?:{_WD})?")
DATE_DOT = re.compile(
    rf"(?<![\d.,])(?:\d{{4}}\.)?(?P<m>{_MO})\.(?P<d>{_DA})(?:{_WD}|(?=\s\d{{1,2}}:\d{{2}}))"
)
DATE_DOT_RANGE = re.compile(
    rf"(?<![\d.,])(?:\d{{4}}\.)?(?P<m>{_MO})\.(?P<d>{_DA})(?:{_WD})?\s?[~∼〜]\s?"
    rf"(?:\d{{4}}\.)?(?P<m2>{_MO})\.(?P<d2>{_DA})(?![\d.,])(?:{_WD})?"
)
DATE_SLASH = re.compile(rf"(?<![\d/])(?:\d{{4}}/)?(?P<m>{_MO})/(?P<d>{_DA})(?![\d/])(?:{_WD})?")
DATE_ISO = re.compile(r"(?<!\d)\d{4}-(?P<m>1[0-2]|0[1-9])-(?P<d>3[01]|[12]\d|0[1-9])(?!\d)")
DATE_BARE = re.compile(rf"(?<![\d.,])(?P<m>{_MO})\.(?P<d>{_DA})(?![\d.,])")  # 요일 없는 '12.15'

Token = tuple[int, int, int, int]  # (글 자리 시작, 끝, 월, 일)


@dataclass(frozen=True)
class Ground:
    """v4 대화 숫자 검사의 근거(허용 글에서 한 번 읽어 둔다)."""

    nums: frozenset[float]  # 옛 검사 값(numbers)
    exact: frozenset[int]  # 파생 값(원 단위 올림 · 내림, 10만 이상이면 만 원 반올림 · 버림)
    # 어림 · 원대에 견줄 값(근거 금액 10만 이상 + 파생 값 1만 이상, 오름차순)
    bases: tuple[float, ...]
    dates: frozenset[tuple[int, int]]  # 근거 날짜(월, 일)


def _tokens(text: str) -> list[Token]:
    """글의 날짜(요일 없는 '12.15'는 빼고)."""
    out: list[Token] = []
    for m in DATE_KO.finditer(text):
        out.append((m.start(), m.end(), int(m["m"]), int(m["d"])))
        if tail := DATE_KO_TAIL.match(text, m.end()):
            out.append((tail.start(), tail.end(), int(m["m"]), int(tail["d"])))
    for rx in (DATE_DOT, DATE_SLASH, DATE_ISO):
        out += [(m.start(), m.end(), int(m["m"]), int(m["d"])) for m in rx.finditer(text)]
    for m in DATE_DOT_RANGE.finditer(text):
        out.append((m.start(), m.end("d"), int(m["m"]), int(m["d"])))
        out.append((m.end("d"), m.end(), int(m["m2"]), int(m["d2"])))
    return out


def ground(text: str) -> Ground:
    """허용 글 → 근거(옛 검사 값 · 파생 값 · 어림 견줄 값 · 날짜)."""
    text = text or ""
    money: dict[float, None] = {}
    areas: set[float] = set()
    for m in NUM.finditer(text):
        v = _val(m.group(1), m.group(2))
        if v is None or v <= 0:
            continue
        unit = (m.group(2) or "").replace(" ", "")
        if unit in AREA_UNITS:
            areas.add(v)
        elif (unit in MONEY_UNITS or not unit) and v >= PART_MIN and float(v).is_integer():
            money.setdefault(v)
    areas.update(float(x) for x in AREA_KEY.findall(text))
    parts = list(money)[:MONEY_MAX]
    derived: set[float] = set()
    for i, a in enumerate(parts):
        for b in parts[i + 1 :]:
            derived.update((a + b, abs(a - b)))
    for a in parts:
        if a >= LOOSE_MIN:
            derived.update(a / p for p in areas if 0 < p <= AREA_MAX)
    exact: set[int] = set()
    for d in derived:
        exact.update((math.floor(d), math.ceil(d)))
        if d >= LOOSE_MIN:
            exact.update((round(d / 1e4) * 10_000, math.floor(d / 1e4) * 10_000))
    bases = sorted({v for v in money if v >= LOOSE_MIN} | {d for d in derived if d >= PART_MIN})
    dates = frozenset((mo, da) for _, _, mo, da in _tokens(text))
    return Ground(frozenset(numbers(text)), frozenset(exact), tuple(bases), dates)


def _tz(n: int) -> int:
    """끝 0의 수(더 둥근 수 견주기)."""
    k = 0
    while n and n % 10 == 0:
        n //= 10
        k += 1
    return k


def _money_ok(n: float, rest: str, approx: bool, g: Ground) -> bool:
    """문장 금액 n(원)이 근거에서 다시 만들어지는지: 옛 값 · 파생 값 그대로, 'n만 원대', 어림(더 둥근 수 · 3% 안)."""
    k = round(n)
    if round(n, 4) in g.nums or k in g.exact:
        return True
    if k < PART_MIN:
        return False
    tz = _tz(k)
    if BAND.match(rest):  # n ≤ V < 다음 자리
        i = bisect_left(g.bases, k)
        if i < len(g.bases) and g.bases[i] < k + 10**tz:
            return True
    if approx:
        i = bisect_left(g.bases, k / (1 + APPROX_RATE))
        for v in g.bases[i:]:
            if v > k / (1 - APPROX_RATE):
                break
            if abs(k - v) <= APPROX_RATE * v and tz > _tz(round(v)):
                return True
    return False


def _runs(s: str, ms: list[re.Match]) -> dict[int, tuple[float, list[int], int]]:
    """큰 단위부터 이어 쓴 금액('301만 6,000원' · '1억 2,000만 원') → {첫 숫자: (합, 숫자 차례들, 끝 자리)}."""
    out: dict[int, tuple[float, list[int], int]] = {}
    i = 0
    while i < len(ms):
        unit = (ms[i].group(2) or "").replace(" ", "")
        if unit not in ("억", "만"):
            i += 1
            continue
        idx, rank, j = [i], RANK[unit], i
        while j + 1 < len(ms) and "원" not in unit:
            nxt = ms[j + 1]
            nu = (nxt.group(2) or "").replace(" ", "")
            gap = s[ms[j].end() : nxt.start()]
            if gap.strip() or len(gap) > 2 or RANK.get(nu, 99) >= rank:
                break
            j, unit, rank = j + 1, nu, RANK[nu]
            idx.append(j)
        if len(idx) > 1 and "원" in unit:
            total = sum(_val(ms[x].group(1), ms[x].group(2)) or 0 for x in idx)
            out[i] = (total, idx, ms[j].end())
        i = j + 1
    return out


def _date_ok(m: re.Match, v: float, hits: list[Token], s: str, g: Ground) -> bool:
    """날짜에 든 숫자: 근거 날짜(같은 월 · 일)면 통과. 아니면 옛 검사처럼 숫자마다 보고(옛 검사보다 좁히지 않는다),
    '12.15(화)'처럼 점으로 쓴 날짜는 소수가 아니라 월 · 일 둘로도 본다."""
    if any((mo, da) in g.dates for _, _, mo, da in hits):
        return True
    if round(v, 4) in g.nums or _small_count(v, m.group(2), s[m.end() :]):
        return True
    return "." in m.group(1) and any(mo in g.nums and da in g.nums for _, _, mo, da in hits)


def loose(sentence: str, g: Ground) -> tuple[str | None, set[float]]:
    """v4 대화 문장 하나의 숫자 검사. (처음 걸린 숫자 글 | None, 통과한 숫자 값). 문장은 가린 뒤 글이다."""
    ms = list(NUM.finditer(sentence))
    if not ms:
        return None, set()
    toks = _tokens(sentence)
    taken = [(a, b) for a, b, _, _ in toks]
    for m in DATE_BARE.finditer(sentence):
        day = (int(m["m"]), int(m["d"]))
        if day in g.dates and not any(m.start() < b and m.end() > a for a, b in taken):
            toks.append((m.start(), m.end(), *day))
    approx = bool(APPROX.search(sentence))
    runs = _runs(sentence, ms)
    fine: set[float] = set()
    skip: set[int] = set()
    for i, m in enumerate(ms):
        v = _val(m.group(1), m.group(2))
        if i in skip or v is None:
            continue
        key = round(v, 4)
        hits = [t for t in toks if m.start() < t[1] and m.end() > t[0]]
        if hits:
            if _date_ok(m, v, hits, sentence, g):
                fine.add(key)
                continue
            return m.group(0).strip(), fine
        if (run := runs.get(i)) is not None and _money_ok(run[0], sentence[run[2] :], approx, g):
            for x in run[1]:
                fine.add(round(_val(ms[x].group(1), ms[x].group(2)) or 0, 4))
                skip.add(x)
            continue
        unit = (m.group(2) or "").replace(" ", "")
        rest = sentence[m.end() :]
        if key in g.nums or _small_count(v, m.group(2), rest):
            fine.add(key)
            continue
        money = unit in MONEY_UNITS or (not unit and v >= PART_MIN)
        if money and _money_ok(v, rest, approx, g):
            fine.add(key)
            continue
        return m.group(0).strip(), fine
    return None, fine
