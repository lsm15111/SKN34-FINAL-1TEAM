"""AI 답 출력 검사 (화면 guard.ts를 서버로 옮긴 것). 고객에게 보내기 전에 문장마다 본다.

- 계산 결과 · 자료 · 고객이 쓴 글에 없는 숫자가 든 문장은 뺀다.
- 공사 기간(일 · 주 · 개월)은 계산 엔진 결과에 있는 숫자만 허용한다.
- 한글로 쓴 금액 · 면적, 쓰면 안 되는 표현이 든 문장도 뺀다.
- 개인정보는 가린다(shared/pii.mask, v3 check와 같은 규칙 하나).
- v4 비서 대화(runtime.SentenceGate)만 어림 · 파생 · 날짜를 더 읽는다(ground · loose, 아래 'v4 대화 숫자' 절).
  v2 · v3 답 파이프라인 안쪽 검사(check · _bad_number)는 그대로다.
- 전각 · 다른 문자 숫자는 ASCII로 바꿔 읽고(norm), NUM_MAX를 넘는 수는 근거로 쓰지 않으며 문장에 있으면 근거 없는
  숫자다(점검 R6 B1 · B5: 309자리 넘는 숫자 줄은 float이 inf가 되어 반올림이 OverflowError를 냈다).
"""

import json
import math
import re
import unicodedata
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.shared.pii import mask

NUM = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(만\s*원|천\s*원|억\s*원|억|만|원|%|퍼센트|㎡|m²|평|일|개월|개|롤|cm|mm|m|배|시간|주|층|장|짝|명|인|품)?",
    re.ASCII,
)
NUM_MAX = 10**15
_WIDE = str.maketrans("，．％～", ",.%~")
_UDIGIT = re.compile(r"(?![0-9])\d")  # ASCII가 아닌 10진 숫자(전각 ３ 등)
COUNT_WORDS = re.compile(r"^\s*(가지|번|단계|번째|곳|군데|가지씩)")
# 한글 수: 자리 말(십 · 백 · 천)이 있는 수('이십오' · '삼백오십' · '3백'), 낱말 첫머리 한 자리 수 + 만 · 억('오만' ·
# '일억'). '공사만 원하시면' · '원래'는 금액이 아니다
_KD = "[일이삼사오육칠팔구]"
_KN = rf"(?:{_KD}?[십백천])+{_KD}?"
HANGUL_MONEY = re.compile(rf"(?:{_KN}\s*(?:만|억)?|(?<![가-힣]){_KD}\s?(?:만|억))\s*원(?![하래])")
HANGUL_AREA = re.compile(rf"{_KN}\s*평")
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


def norm(text: str) -> str:
    """전각 · 다른 문자 10진 숫자와 전각 쉼표 · 점 · % · 물결을 ASCII로(글자 수 그대로). NUM은 ASCII 숫자만 읽는다."""
    if text.isascii():
        return text
    return _UDIGIT.sub(lambda m: str(unicodedata.decimal(m.group())), text).translate(_WIDE)


def _val(raw: str, unit: str | None) -> float | None:
    """숫자 글 → 값. NUM_MAX를 넘으면 None(근거로 쓰지 않고, 문장 검사는 근거 없는 숫자로 본다)."""
    try:
        v = float(raw.replace(",", "")) * MULT.get((unit or "").replace(" ", ""), 1)
    except ValueError:
        return None
    return v if v <= NUM_MAX else None


def numbers(text: str) -> set[float]:
    """글에 나온 숫자. 10만 이상은 만 원 단위 반올림 · 버림 값도 허용한다 (3,364,291원 → 336만 원).

    10만 아래는 반올림하지 않는다: 1.6만 원이 2만 원으로 통과하지 않게.
    """
    out: set[float] = set()
    for m in NUM.finditer(norm(text or "")):
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
    sentence = norm(sentence)
    for m in NUM.finditer(sentence):
        v = _val(m.group(1), m.group(2))
        if v is None:
            return m.group(0).strip()  # NUM_MAX를 넘는 수
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
    s = norm(s)
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
# - 어림: 근거 금액 V(10만 이상)와 3% 안의 더 둥근 수 R(문장에 약 · 쯤 · 정도 · 안팎 · 가량), 'R만 원대'(R ≤ V < 다음 자리).
#   R은 V를 그 자리에서 반올림한 수여야 한다: R의 반올림 단위의 반 안(만 원 단위 ±5,000원 · 10만 원 단위 ±50,000원,
#   백만 자리 이상 '약 300만 원'은 3%만 본다, 고침 4차 G · QA r4 s5 7번). 범위의 아래 · 위 끝도 숫자마다 같은 규칙
# - 파생: 근거 금액(1만 이상) 둘의 합 · 차, 근거 금액(10만 이상) ÷ 근거 면적(평 · ㎡). 조합은 둘까지. 파생 값은 그대로
#   (원 단위 올림 · 내림) · 만 원 반올림 · 버림(10만 이상)으로 지나고, 1만 이상이면 위 어림 · 원대로도 지난다.
#   따로 근거(apart: 지난 고객 말 · 지난 비서 말 하나하나)는 숫자 그대로는 근거이고, 파생은 그 말 안 숫자끼리만 만든다
#   (QA r10 c2 T26: 희망 예산 250만 원 + 다른 턴 송금 부탁 50만 원 = '300만 원')
# - 고객 말의 한글 금액('삼백만 원' · '3백만' · '예산 200')은 부르는 쪽이 원 값 줄로 덧붙여 넘긴다(heard, 아래 절)
# - 금액 묶음: '301만 6,000원' · '1억 2,000만 원'은 한 금액으로 본다(묶음으로 안 맞으면 옛 검사처럼 나눠서)
# - 날짜: '12월 15일' · '12.15(화)' · '12/15' · ISO · '2027.1.4(월)'을 날짜로 읽고(소수 12.15로 읽지 않음) 근거 글에
#   같은 월 · 일이 날짜로 있으면 통과. 없으면 옛 검사처럼 월 · 일 숫자를 따로 본다. 요일 없는 '12.15'는 근거 날짜일 때만
# - 요일(점검 R1a B2): 문장 날짜에 쓴 요일('(화)' · ' 화요일', 달 없는 '15일(화)'도)은 근거의 같은 날짜 요일(쓴 요일 ·
#   연도 있는 날짜로 센 요일)과 같아야 한다. 근거에 그 날짜 요일이 없으면 턴 사실 '지금' · '올해' 줄의 오늘에 가장
#   가까운 해로 세고, 그 줄도 없으면 보지 않는다
# - 단위(점검 R1a B2): 기간 · 배수 · 비율(일 · 주 · 개월 · 시간 · 배 · %)은 근거에 같은 값 · 같은 단위가 있어야 한다
#   ('3일' 근거로 '3주' · '3배'는 안 됨). 근거 단위는 숫자 뒤 낱말과 JSON 칸 이름(days · work_days → 일, *_months →
#   개월 …)으로 읽고, '3~5일'의 3처럼 단위 없는 범위 앞 수는 뒤 수의 단위로 본다
# - 다른 공정 기간: 기간 숫자가 말하는 공정(앞에서 가장 가까운 공정 낱말. 철거는 도배 견적 칸이기도 해 건너뛰고, '결도배' ·
#   '마루와벽'처럼 다른 한글이 붙은 업체 이름은 공정 낱말이 아님)이 믿집이 계산하지 않는 공정이면, 근거에서 그 공정
#   낱말과 같은 줄에 있는 값만 지난다(08-rules '다른 공정 기간 금지')
# - 그대로: 근거 없는 돈 숫자, 그 밖 숫자(근거 값 그대로), 한글 금액(HANGUL_MONEY), 표준 대비 %(부르는 쪽
#   policy.VS_STANDARD)
# - 금액 기준(고침 3차 A2): 근거 금액에 기준 꼬리표(basis)가 있으면 합 · 차는 같은 기준끼리만 다시 만든다. 공급가
#   (부가세 별도) ± 부가세 포함은 만들지 않고(QA r3 s5: 부가세 포함 합계 − 공급가 벽지 줄), 부가세 몫은 어느 쪽과도
#   된다(공급가 + 부가세 = 합계). 꼬리표가 없는 값(고객 말 · 턴 사실)은 지금처럼 어느 쪽과도 된다

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
# 끝 0이 이만큼(백만 자리) 넘는 어림은 반올림 단위를 보지 않고 3%만 본다('약 300만 원')
ROUND_FREE = 6
# 값과 단위가 같은 근거만 지나는 단위(퍼센트는 %로 읽음)와 그중 다른 공정 기간을 보는 단위
STRICT_UNITS = frozenset({"일", "주", "개월", "시간", "배", "%"})
PERIOD_UNITS_V4 = frozenset({"일", "주", "개월", "시간"})
# '3~5일'처럼 단위 없는 범위 앞 수 뒤의 '~5일'
UNIT_TAIL = re.compile(r"\s?[~∼〜\-–]\s?\d+(?:\.\d+)?\s?(일|주|개월|시간|배|%|퍼센트)")
# JSON 도구 결과의 칸 이름과 숫자 값: 칸 이름 낱말(_로 나눔)로 단위를 읽는다(work_days → 일)
UNIT_KEY = re.compile(r'"([A-Za-z_]+)"\s*:\s*(\d+(?:\.\d+)?)(?![\d.])')
KEY_UNITS = {"days": "일", "weeks": "주", "months": "개월", "hours": "시간", "pct": "%"}
# 믿집이 금액 · 기간을 내는 공정과 공정 낱말로 보지 않는 공정(도배 견적의 기존 벽지 철거)
OWN_TRADES = frozenset({"dobae", "mokgong"})
NEUTRAL_TRADES = frozenset({"demolition"})
# 문장의 공정 낱말 뒤에 붙어도 되는 말(공사 · 조사). 앞뒤에 다른 한글이 붙으면 업체 이름 같은 다른 낱말이다
# ('결도배' · '마루와벽' · 'QA벽지공방')
TRADE_TAIL = re.compile(
    r"(?:공사|작업|시공|쪽)?(?:은|는|이|가|을|를|도|만|과|와|랑|이랑|하고|의|에|에서|부터|까지|으로|로"
    r"|이나|나|보다|처럼|이면|면|이고|고|이요|요|이에요|예요|쯤)?(?![가-힣])"
)
WEEK = "월화수목금토일"
_WD = r"\s?\((?P<w>[월화수목금토일])\)"
_WD2 = r"\s?\((?P<w2>[월화수목금토일])\)"
_WDK = rf"(?:{_WD}|\s?(?P<wk>[월화수목금토일])요일)"  # 긴 꼴은 '12월 15일 화요일'도
_MO = r"1[0-2]|0?[1-9]"
_DA = r"3[01]|[12]\d|0?[1-9]"
DATE_KO = re.compile(
    rf"(?<!\d)(?:(?P<y>\d{{4}})\s?년\s?)?(?P<m>{_MO})\s?월\s?(?P<d>{_DA})\s?일{_WDK}?"
)
# '12월 1일(화)~4일(금)'의 뒤 날
DATE_KO_TAIL = re.compile(rf"\s?[~∼〜]\s?(?P<d>{_DA})\s?일{_WDK}?")
DATE_DOT = re.compile(
    rf"(?<![\d.,])(?:(?P<y>\d{{4}})\.)?(?P<m>{_MO})\.(?P<d>{_DA})"
    rf"(?:{_WD}|(?=\s\d{{1,2}}:\d{{2}}))"
)
DATE_DOT_RANGE = re.compile(
    rf"(?<![\d.,])(?:(?P<y>\d{{4}})\.)?(?P<m>{_MO})\.(?P<d>{_DA})(?:{_WD})?\s?[~∼〜]\s?"
    rf"(?:(?P<y2>\d{{4}})\.)?(?P<m2>{_MO})\.(?P<d2>{_DA})(?![\d.,])(?:{_WD2})?"
)
DATE_SLASH = re.compile(
    rf"(?<![\d/])(?:(?P<y>\d{{4}})/)?(?P<m>{_MO})/(?P<d>{_DA})(?![\d/])(?:{_WD})?"
)
DATE_ISO = re.compile(r"(?<!\d)(?P<y>\d{4})-(?P<m>1[0-2]|0[1-9])-(?P<d>3[01]|[12]\d|0[1-9])(?!\d)")
DATE_BARE = re.compile(rf"(?<![\d.,])(?P<m>{_MO})\.(?P<d>{_DA})(?![\d.,])")  # 요일 없는 '12.15'
DATE_DAY = re.compile(rf"(?<![\d.,월])(?<!월\s)(?P<d>{_DA})\s?일{_WD}")  # 달 없는 '15일(화)'
# 턴 사실 시각 줄(assistant.service.time_lines): '지금: 11월 24일(화) …' · '올해: 2026년'
NOW_LINE = re.compile(rf"지금:\s?(?P<m>{_MO})월\s?(?P<d>{_DA})일")
YEAR_LINE = re.compile(r"올해:\s?(?P<y>\d{4})년")

# (글 자리 시작, 끝, 월, 일, 요일 0~6 | None, 연도 | None)
Token = tuple[int, int, int, int, int | None, int | None]

# ---- 금액 기준 꼬리표(basis) ----
# 도구 결과의 돈은 부가세 포함이 기본이고(K 결정 2), 공급가 칸은 이름 · 글에 '공급가'를 붙인다. 읽는 곳:
# - JSON 도구 결과: 키 supply · '공급가' · *_supply는 공급가, vat · '부가세'는 부가세 몫. 같은 묶음의 label · name ·
#   line · title 글이 '공급가 · 부가세 별도'면 그 묶음 금액이 공급가, '부가세 포함'이면 포함. 그 밖 금액은 포함(기본)
# - 글(고객 말 · 턴 사실 · 요약 줄): '공급가 913,665원' · '913,665원(공급가)' · '부가세 22,000원' · '부가세 포함 …'
#   처럼 금액 바로 앞뒤의 낱말. 낱말이 없으면 기준 모름(어느 쪽과도 된다)
SUPPLY, INCL, VAT, ANY = "supply", "incl", "vat", "any"
_INCL_WORD = re.compile(r"부가세\s*포함|VAT\s*포함", re.IGNORECASE)
_SUPPLY_WORD = re.compile(r"공급가|부가세\s*(?:별도|제외)|VAT\s*별도", re.IGNORECASE)
_VAT_ONLY = re.compile(r"^\s*(?:부가세|VAT)(?:\s*(?:액|몫|금액))?\s*$", re.IGNORECASE)
# 금액 바로 앞(사이에 낱말 하나 · 조사까지): '부가세 포함 합계 1,947,460원' · '공급가 220,000원' · '부가세 22,000원'
_TAG_BEFORE = re.compile(
    r"(공급가|부가세\s*(?:별도|제외|포함)|부가세)\s*(?:[가-힣]{1,4}\s*)?(?:은|는|이|가|[:：])?\s*$"
)
# 금액 바로 뒤: '913,665원(공급가)' · '2,952,491원, 부가세 포함'(뒤에 다른 금액이 이어지면 아님)
_TAG_AFTER = re.compile(
    r"^\s*(?:\(\s*(공급가|부가세\s*(?:별도|제외|포함))\s*\)|[,·]?\s*(부가세\s*(?:별도|제외|포함))(?!\s*\d))"
)
# 묶음 기준을 읽는 글 칸(vat_way는 업체가 적은 방식이라 아님)
_TAG_KEYS = ("label", "name", "line", "title")


def _word_tag(word: str) -> str | None:
    if _INCL_WORD.search(word):
        return INCL
    if _SUPPLY_WORD.search(word):
        return SUPPLY
    return VAT if _VAT_ONLY.match(word) else None


def _key_tag(key: str) -> str | None:
    k = key.lower()
    if "공급가" in k or k == "supply" or k.startswith("supply_") or k.endswith("_supply"):
        return SUPPLY
    if k == "vat" or k.startswith("vat_won") or ("부가세" in k and "포함" not in k):
        return VAT
    return INCL if "부가세" in k else None


def _put_tag(out: dict[float, set[str]], v: float, tag: str) -> None:
    out.setdefault(round(v, 4), set()).add(tag)


def _text_tags(text: str, inherited: str | None, default: str, strong: dict, weak: dict) -> None:
    """글의 금액마다 기준: 바로 앞뒤 낱말 → 물려받은 묶음 기준 → 기본(default, 약한 꼬리표)."""
    text = norm(text)
    for m in NUM.finditer(text):
        v = _val(m.group(1), m.group(2))
        unit = (m.group(2) or "").replace(" ", "")
        if v is None or v < PART_MIN or not (unit in MONEY_UNITS or not unit):
            continue
        before = _TAG_BEFORE.search(text[max(0, m.start() - 16) : m.start()])
        after = _TAG_AFTER.match(text[m.end() :])
        word = (before and before.group(1)) or (after and (after.group(1) or after.group(2)))
        tag = (_word_tag(word) if word else None) or inherited
        _put_tag(strong if tag else weak, v, tag or default)


def _json_tags(value, inherited: str | None, strong: dict, weak: dict) -> None:
    """JSON 도구 결과의 금액마다 기준(키 · 같은 묶음 글 칸 · 기본은 부가세 포함)."""
    if isinstance(value, dict):
        own = inherited
        for k in _TAG_KEYS:
            if isinstance(value.get(k), str) and (t := _word_tag(value[k])):
                own = t
                break
        for k, x in value.items():
            kt = _key_tag(str(k)) or own
            if isinstance(x, int | float) and not isinstance(x, bool):
                if PART_MIN <= x <= NUM_MAX:
                    _put_tag(strong if kt else weak, float(x), kt or INCL)
            else:
                _json_tags(x, kt, strong, weak)
    elif isinstance(value, list):
        for x in value:
            _json_tags(x, inherited, strong, weak)
    elif isinstance(value, str):
        _text_tags(value, inherited, INCL, strong, weak)


def basis(pieces: list[str]) -> dict[float, frozenset[str]]:
    """허용 글 조각들 → 금액마다 기준 꼬리표. JSON으로 읽히는 조각은 도구 결과(기본 부가세 포함), 그 밖은 글(기본 모름).
    같은 값에 낱말 · 키로 읽은 꼬리표(강함)가 있으면 기본값(약함)은 보지 않는다."""
    strong: dict[float, set[str]] = {}
    weak: dict[float, set[str]] = {}
    for piece in pieces:
        try:
            got = json.loads(piece)
        except (TypeError, ValueError):
            got = None
        if isinstance(got, dict | list):
            _json_tags(got, None, strong, weak)
        else:
            _text_tags(piece or "", None, ANY, strong, weak)
    return {v: frozenset(strong.get(v) or weak[v]) for v in {*strong, *weak}}


def mixable(a: frozenset[str], b: frozenset[str]) -> bool:
    """두 근거 금액을 더하거나 빼도 되는지: 공급가와 부가세 포함만 섞지 않는다(기준 모름 · 부가세 몫은 어느 쪽과도)."""
    return any({x, y} != {SUPPLY, INCL} for x in a for y in b)


@dataclass(frozen=True)
class Ground:
    """v4 대화 숫자 검사의 근거(허용 글에서 한 번 읽어 둔다)."""

    nums: frozenset[float]  # 옛 검사 값(numbers)
    exact: frozenset[int]  # 파생 값(원 단위 올림 · 내림, 10만 이상이면 만 원 반올림 · 버림)
    # 어림 · 원대에 견줄 값(근거 금액 10만 이상 + 파생 값 1만 이상, 오름차순)
    bases: tuple[float, ...]
    dates: frozenset[tuple[int, int]]  # 근거 날짜(월, 일)
    units: frozenset[tuple[float, str]] = frozenset()  # 근거 기간 · 배수 · 비율(값, 단위)
    weeks: frozenset[tuple[int, int, int]] = frozenset()  # 근거 날짜의 요일(월, 일, 0=월요일)
    today: date | None = None  # 턴 사실 '지금' · '올해' 줄의 오늘
    # 다른 공정 낱말과 같은 근거 줄에 있는 기간(공종, 값, 단위)
    other: frozenset[tuple[str, float, str]] = frozenset()


def _week(y: int, mo: int, da: int) -> int | None:
    """달력 요일(0=월요일). 없는 날짜면 None."""
    try:
        return date(y, mo, da).weekday()
    except ValueError:
        return None


def _wd(m: re.Match, *names: str) -> int | None:
    """맞은 날짜 글에 쓴 요일(0=월요일)."""
    got = m.groupdict()
    return next((WEEK.index(got[n]) for n in names if got.get(n)), None)


def _yr(m: re.Match, name: str = "y") -> int | None:
    y = m.groupdict().get(name)
    return int(y) if y else None


def _tokens(text: str) -> list[Token]:
    """글의 날짜(요일 없는 '12.15'는 빼고)와 거기 쓴 요일 · 연도."""
    out: list[Token] = []
    for m in DATE_KO.finditer(text):
        y = _yr(m)
        out.append((m.start(), m.end(), int(m["m"]), int(m["d"]), _wd(m, "w", "wk"), y))
        if tail := DATE_KO_TAIL.match(text, m.end()):
            w = _wd(tail, "w", "wk")
            out.append((tail.start(), tail.end(), int(m["m"]), int(tail["d"]), w, y))
    for rx in (DATE_DOT, DATE_SLASH, DATE_ISO):
        out += [
            (m.start(), m.end(), int(m["m"]), int(m["d"]), _wd(m, "w"), _yr(m))
            for m in rx.finditer(text)
        ]
    for m in DATE_DOT_RANGE.finditer(text):
        out.append((m.start(), m.end("d"), int(m["m"]), int(m["d"]), _wd(m, "w"), _yr(m)))
        y2 = _yr(m, "y2") or _yr(m)
        out.append((m.end("d"), m.end(), int(m["m2"]), int(m["d2"]), _wd(m, "w2"), y2))
    return out


def _unit(text: str, m: re.Match) -> str:
    """숫자의 단위(띄운 '만 원'은 붙임, 퍼센트는 %). 단위 없는 '3~5일'의 3은 뒤 수의 단위로 본다."""
    u = (m.group(2) or "").replace(" ", "")
    if not u and (tail := UNIT_TAIL.match(text, m.end())):
        u = tail.group(1)
    return "%" if u == "퍼센트" else u


def _units(text: str) -> set[tuple[float, str]]:
    """글의 기간 · 배수 · 비율(값, 단위): 숫자 뒤 단위와 JSON 칸 이름(work_days → 일, warranty_months → 개월 …)."""
    out: set[tuple[float, str]] = set()
    for m in NUM.finditer(text):
        v = _val(m.group(1), m.group(2))
        if v is not None and (u := _unit(text, m)) in STRICT_UNITS:
            out.add((round(v, 4), u))
    for key, raw in UNIT_KEY.findall(text):
        if (v := float(raw)) <= NUM_MAX:
            words = key.lower().split("_")
            out.update((round(v, 4), u) for k, u in KEY_UNITS.items() if k in words)
    return out


def _trade_spans(text: str) -> list[tuple[int, str]]:
    """글의 공정 낱말 자리(시작, 공종 코드), 자리 순. 공종은 다른 공정 알아 두기와 같은 풀이('욕실 문'은 목공),
    철거는 빼고, 앞뒤에 다른 한글이 붙은 낱말(업체 이름)도 뺀다(TRADE_TAIL)."""
    from app.agent.v3.trades import BY_CODE
    from app.knowledge.other_trades import codes_of

    out: list[tuple[int, str]] = []
    for c in codes_of(text):
        spec = BY_CODE.get("window" if c == "middoor" else c)
        if spec is None or c in NEUTRAL_TRADES:
            continue
        for x in spec.pattern.finditer(text):
            alone = not (x.start() and "가" <= text[x.start() - 1] <= "힣")
            if alone and TRADE_TAIL.match(text, x.end()):
                out.append((x.start(), c))
    return sorted(out)


def _other(text: str) -> set[tuple[str, float, str]]:
    """근거 줄마다 다른 공정 낱말과 같은 줄에 있는 기간(공종, 값, 단위). 기간이 있는 줄만 공종을 읽는다."""
    from app.knowledge.other_trades import codes_of

    out: set[tuple[str, float, str]] = set()
    for line in text.split("\n"):
        got = [(v, u) for v, u in _units(line) if u in PERIOD_UNITS_V4]
        if got:
            codes = set(codes_of(line)) - OWN_TRADES - NEUTRAL_TRADES
            out.update((c, v, u) for c in codes for v, u in got)
    return out


def _today(text: str) -> date | None:
    """턴 사실 '지금: 11월 24일(화)' · '올해: 2026년' 줄 → 오늘. 둘 중 하나라도 없으면 None."""
    now, year = NOW_LINE.search(text), YEAR_LINE.search(text)
    if now is None or year is None:
        return None
    try:
        return date(int(year["y"]), int(now["m"]), int(now["d"]))
    except ValueError:
        return None


# ---- 고객 말의 금액(QA r10 c2 T10 · T16 · T20: 되받는 비서 문장이 '자료에 없는 숫자'로 빠짐) ----
# 고객은 '삼백만 원' · '3백만' · '2천5백만' · '이백오십만'처럼 한글 수 · 자리 말을 섞어 말해요. 부르는 쪽(runtime)이 고객
# 말에만 원 값 줄을 덧붙여(heard) 숫자 근거로 넘겨요. 비서 글의 한글 금액은 그대로 막아요(HANGUL_MONEY).
# - 한글 한 자리 수 + 만 · 억('이만' · '오만' · '일만')은 다른 낱말과 겹쳐 뒤에 '원'이 있을 때만 읽어요
# - 금액 뒤는 띄움 · 끝 · 원 · 조사만('천만에요' · '천만다행'은 금액이 아니에요)
# - 예산 · 금액 바로 뒤의 단위 없는 수('예산 200으로' · '예산은 삼백이에요')는 만 원으로 읽어요(1~9,999, 뒤가 단위가
#   아닐 때만). 그 밖의 단위 없는 수('도배지 200 정도')는 그대로 둬요
_KO_DIGIT = "일이삼사오육칠팔구"
_KO_VAL = {c: i for i, c in enumerate(_KO_DIGIT, 1)} | {"십": 10, "백": 100, "천": 1000}
_KO_BIG = {"만": 10**4, "억": 10**8}
_KD1 = rf"(?:\d{{1,4}}|[{_KO_DIGIT}])"  # 자리 하나의 수(아라비아 숫자 · 한글 한 자리)
_KSEC = rf"(?:{_KD1}?[십백천])+{_KD1}?"  # 자리 말이 든 만 아래 수('삼백오십' · '2천5백' · '백')
_SEC = rf"(?:{_KSEC}|{_KD1})"
_MONEY_END = (
    r"(?=\s|$|[.,!?~)·]|원|이|인|으|은|을|과|도|만|에(?!요)"
    r"|정도|쯤|뿐|밖에|까지|가량|안팎|내외|선|대|짜리|하고)"
)
KO_MONEY = re.compile(
    rf"(?<![가-힣\d.,])(?P<n>{_SEC}\s?억(?:\s?{_SEC}\s?만)?|{_SEC}\s?만){_MONEY_END}(?P<won>\s?원)?"
)
# 한글 수는 자리 말로 끝나야 해요('삼백이에요'의 '이'는 조사)
KO_BUDGET = re.compile(
    rf"(?:예산|금액)(?:은|는|이|가|을|를|도|:)?(?:\s*(?P<d>\d{{1,4}})|\s+(?P<k>(?:{_KD1}?[십백천])+))"
    r"(?![\d,.]|\s?[만억천백십원])(?=\s|$|[.,!?~)]|으로|이|인|요|정도|쯤|까지|선|에|은|을|도)"
)
_KO_TOKEN = re.compile(rf"\d+|[{_KO_DIGIT}십백천만억]")


def _ko_value(s: str) -> int:
    """한글 · 섞은 수 글('삼백만' · '2천5백만' · '1억 2천만' · '이백') → 값."""
    total = sec = 0
    num: int | None = None
    for tok in _KO_TOKEN.findall(s):
        if tok.isdigit():
            num = int(tok)
        elif tok in _KO_BIG:
            total += (sec + (num or 0) or 1) * _KO_BIG[tok]
            sec, num = 0, None
        elif _KO_VAL[tok] >= 10:  # 십 · 백 · 천
            sec += (1 if num is None else num) * _KO_VAL[tok]
            num = None
        else:
            num = _KO_VAL[tok]
    return total + sec + (num or 0)


def said_won(text: str) -> list[int]:
    """고객 말의 한글 · 섞은 금액과 예산 · 금액 뒤 단위 없는 수 → 원 값(나온 차례, 겹침 없이)."""
    t = norm(text or "")
    out: dict[int, None] = {}
    for m in KO_MONEY.finditer(t):
        if m["won"] or re.search(r"[\d십백천]", m["n"]):
            out.setdefault(_ko_value(m["n"]))
    for m in KO_BUDGET.finditer(t):
        out.setdefault((int(m["d"]) if m["d"] else _ko_value(m["k"])) * 10**4)
    return [v for v in out if 0 < v <= NUM_MAX]


def heard(text: str) -> str:
    """고객 말 → 숫자 근거 글: 말 그대로 + 다음 줄에 원 값(said_won, '3,000,000원 · 2,000,000원'). 없으면 그대로."""
    got = said_won(text)
    return f"{text}\n" + " · ".join(f"{v:,}원" for v in got) if got else text


def _money_areas(text: str) -> tuple[list[float], set[float]]:
    """글의 근거 금액(1만 이상 정수, 처음 나온 차례 · 겹침 없이)과 나눌 면적(평 · ㎡ · JSON 칸)."""
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
    return list(money), areas


def _derive(money: list[float], areas: set[float], tags: dict[float, frozenset[str]]) -> set[float]:
    """한 근거 묶음 안의 파생 값: 금액 둘의 합 · 차(같은 기준끼리) · 금액 ÷ 면적."""
    parts = money[:MONEY_MAX]
    anyway = frozenset({ANY})
    out: set[float] = set()
    for i, a in enumerate(parts):
        for b in parts[i + 1 :]:
            if mixable(tags.get(round(a, 4), anyway), tags.get(round(b, 4), anyway)):
                out.update((a + b, abs(a - b)))
    for a in parts:
        if a >= LOOSE_MIN:
            out.update(a / p for p in areas if 0 < p <= AREA_MAX)
    return out


def ground(
    text: str, tags: dict[float, frozenset[str]] | None = None, apart: Sequence[str] = ()
) -> Ground:
    """허용 글 → 근거(옛 검사 값 · 파생 값 · 어림 견줄 값 · 날짜 · 요일 · 단위). tags(basis)를 주면 합 · 차는 같은
    기준끼리만. apart(따로 근거 글 하나하나)는 숫자 그대로 근거이고, 파생은 그 글 안 숫자끼리만 만든다."""
    text = norm(text or "")
    tags = tags or {}
    pieces = [text, *(norm(x or "") for x in apart)]
    money: list[float] = []
    derived: set[float] = set()
    for piece in pieces:
        got, areas = _money_areas(piece)
        money += got
        derived |= _derive(got, areas, tags)
    text = "\n".join(pieces)
    exact: set[int] = set()
    for d in derived:
        exact.update((math.floor(d), math.ceil(d)))
        if d >= LOOSE_MIN:
            exact.update((round(d / 1e4) * 10_000, math.floor(d / 1e4) * 10_000))
    bases = sorted({v for v in money if v >= LOOSE_MIN} | {d for d in derived if d >= PART_MIN})
    toks = _tokens(text)
    weeks: set[tuple[int, int, int]] = set()
    for _, _, mo, da, w, y in toks:
        if w is not None:
            weeks.add((mo, da, w))
        if y is not None and (x := _week(y, mo, da)) is not None:
            weeks.add((mo, da, x))
    return Ground(
        frozenset(numbers(text)),
        frozenset(exact),
        tuple(bases),
        frozenset((t[2], t[3]) for t in toks),
        frozenset(_units(text)),
        frozenset(weeks),
        _today(text),
        frozenset(_other(text)),
    )


def _tz(n: int) -> int:
    """끝 0의 수(더 둥근 수 견주기)."""
    k = 0
    while n and n % 10 == 0:
        n //= 10
        k += 1
    return k


def _rounded(k: int, v: float, tz: int) -> bool:
    """어림 k(끝 0이 tz개)가 v를 그 자리에서 반올림한 수인지: 반올림 단위의 반 안(만 원 단위 ±5,000원). 백만 자리
    이상(ROUND_FREE)은 보지 않는다(3%만, QA r4 s5 7번: 3,045,900원을 '약 307만'으로)."""
    return tz >= ROUND_FREE or abs(k - v) * 2 <= 10**tz


def _money_ok(n: float, rest: str, approx: bool, g: Ground) -> bool:
    """문장 금액 n(원)이 근거에서 다시 만들어지는지: 옛 값 · 파생 값 그대로, 'n만 원대', 어림(더 둥근 수 · 3% 안 ·
    반올림 단위의 반 안)."""
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
            if abs(k - v) <= APPROX_RATE * v and tz > _tz(round(v)) and _rounded(k, v, tz):
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
        vals = [_val(ms[x].group(1), ms[x].group(2)) for x in idx]
        if len(idx) > 1 and "원" in unit and None not in vals:
            out[i] = (sum(v for v in vals if v is not None), idx, ms[j].end())
        i = j + 1
    return out


def _date_ok(m: re.Match, v: float, hits: list[Token], s: str, g: Ground) -> bool:
    """날짜에 든 숫자: 근거 날짜(같은 월 · 일)면 통과. 아니면 옛 검사처럼 숫자마다 보고(옛 검사보다 좁히지 않는다),
    '12.15(화)'처럼 점으로 쓴 날짜는 소수가 아니라 월 · 일 둘로도 본다."""
    if any((t[2], t[3]) in g.dates for t in hits):
        return True
    if round(v, 4) in g.nums or _small_count(v, m.group(2), s[m.end() :]):
        return True
    return "." in m.group(1) and any(t[2] in g.nums and t[3] in g.nums for t in hits)


def _near(mo: int, da: int, today: date) -> int | None:
    """연도 없는 날짜의 요일: 오늘에 가장 가까운 해(앞뒤 한 해 안)의 그 날. 없는 날짜면 None."""
    days = [
        date(y, mo, da)
        for y in range(today.year - 1, today.year + 2)
        if _week(y, mo, da) is not None
    ]
    best = min(days, key=lambda d: abs((d - today).days), default=None)
    return best.weekday() if best else None


def _week_bad(s: str, toks: list[Token], g: Ground) -> str | None:
    """요일이 근거와 다른 첫 날짜 글 | None. 연도를 쓰면 달력, 근거에 그 날짜 요일이 있으면 그 요일, 없으면 근거의
    오늘(g.today)에 가장 가까운 해의 달력과 견준다(셀 길이 없으면 지난다). 달 없는 '15일(화)'는 근거에서 같은
    날(일)인 날짜의 요일과 견준다."""
    for a, b, mo, da, w, y in toks:
        if w is None:
            continue
        if y is not None:
            want = {_week(y, mo, da)}
        else:
            want = {x for m2, d2, x in g.weeks if (m2, d2) == (mo, da)}
            if not want and g.today is not None:
                want = {_near(mo, da, g.today)}
        want.discard(None)
        if want and w not in want:
            return s[a:b].strip()
    for m in DATE_DAY.finditer(s):
        if any(m.start() < b and m.end() > a for a, b, *_ in toks):
            continue
        known = {x for _, d2, x in g.weeks if d2 == int(m["d"])}
        if known and WEEK.index(m["w"]) not in known:
            return m.group(0).strip()
    return None


def _trade_at(spans: list[tuple[int, str]], at: int) -> str | None:
    """at 자리 숫자가 말하는 공정: 앞에서 가장 가까운 공정 낱말(없으면 None)."""
    before = [c for i, c in spans if i < at]
    return before[-1] if before else None


def loose(sentence: str, g: Ground) -> tuple[str | None, set[float]]:
    """v4 대화 문장 하나의 숫자 검사. (처음 걸린 숫자 글 | None, 통과한 숫자 값). 문장은 가린 뒤 글이다."""
    sentence = norm(sentence)
    ms = list(NUM.finditer(sentence))
    if not ms:
        return None, set()
    toks = _tokens(sentence)
    taken = [(t[0], t[1]) for t in toks]
    for m in DATE_BARE.finditer(sentence):
        day = (int(m["m"]), int(m["d"]))
        if day in g.dates and not any(m.start() < b and m.end() > a for a, b in taken):
            toks.append((m.start(), m.end(), *day, None, None))
    if (bad := _week_bad(sentence, toks, g)) is not None:
        return bad, set()
    approx = bool(APPROX.search(sentence))
    runs = _runs(sentence, ms)
    fine: set[float] = set()
    skip: set[int] = set()
    spans: list[tuple[int, str]] | None = None  # 공정 낱말 자리(기간 숫자를 볼 때 한 번 읽는다)
    for i, m in enumerate(ms):
        if i in skip:
            continue
        v = _val(m.group(1), m.group(2))
        if v is None:
            return m.group(0).strip(), fine  # NUM_MAX를 넘는 수
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
        unit = _unit(sentence, m)
        rest = sentence[m.end() :]
        if unit in STRICT_UNITS:  # 기간 · 배수 · 비율: 같은 값 · 같은 단위의 근거만
            if (key, unit) not in g.units:
                return m.group(0).strip(), fine
            if unit in PERIOD_UNITS_V4:  # 다른 공정 기간은 그 공정 낱말과 같은 근거 줄의 값만
                spans = _trade_spans(sentence) if spans is None else spans
                trade = _trade_at(spans, m.start())
                if trade not in (None, *OWN_TRADES) and (trade, key, unit) not in g.other:
                    return m.group(0).strip(), fine
            fine.add(key)
            continue
        if key in g.nums or _small_count(v, m.group(2), rest):
            fine.add(key)
            continue
        money = unit in MONEY_UNITS or (not unit and v >= PART_MIN)
        if money and _money_ok(v, rest, approx, g):
            fine.add(key)
            continue
        return m.group(0).strip(), fine
    return None, fine
