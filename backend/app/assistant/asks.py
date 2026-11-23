"""요청 점검(2026-11-23 사용자: "사용자 요청에 최대한 맞춰야" · 부족한 점 중 '요청을 다 했는지 스스로 점검'부터).

고객 말에서 분명한 부탁만 코드가 뽑아요(LLM 없음). 잘못 잡으면 LLM을 한 번 더 부르니, 놓치는 쪽이 낫게 좁게 잡아요.
- count: 찾거나 골라 달라는 수('업체 5곳 찾아줘' · '세 가지 골라 줘'), 2~10. 수 바로 뒤(다음 수 앞, 같은 문장)에 부탁 말
  (찾 · 알려 · 추천 · 골라 · 조사 · 비교 …)이 있어야 해요('방 3개인데'는 부탁이 아니에요).
- price: 값을 알려 달라는 말(가격 · 얼마 · 판매가 · 값 · 시세 · 단가). 바로 뒤가 '말고 · 빼고 · 없이 · 됐 · 필요 없'이면
  아니에요. '얼마나'(얼마나 걸려)는 값이 아니에요.
- show: 보여 달라 · 바꾸겠다는 화면 카드(show_card 종류). 카드 이름 뒤 NEAR자 안에 보기 말(보여 · 볼래 · 열어 …)이,
  집 정보는 바꾸기 말(바꿀 · 변경 · 수정 …)도 와야 해요. 그 사이에 '말고 · 빼고 · 대신'이나 방법을 묻는 말(방법 ·
  어떻게 · 계산 · 기준 · 뜻 · 왜)이 있으면 아니에요.

쓰는 곳
- 턴 시작(runtime._Turn): 턴 사실 끝에 '이번 부탁' 줄(line)을 붙여 비서가 처음부터 맞추게 해요.
- 조사 맡기기(tools.research.start_research): 모델이 목표에서 뺀 찾을 수 · 판매가를 고객 말에서 붙여요(research_goal).
- 턴 끝(runtime._Turn): 보여 달라 · 바꾸겠다고 한 카드를 이 턴에 보이지도 부르지도 않았으면 한 번 더 기회(missing ·
  nudge). 조사 결과의 수 · 판매가는 worker가 끝 줄에서 견줘요(research.ended_line).
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

COUNT_MIN, COUNT_MAX = 2, 10
KO_NUM = {
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
_UNIT = r"(곳|군데|가지|개|종류|업체)(?!월)"  # '3개월'은 수가 아니에요
_COUNT = re.compile(
    rf"(?<![\d.,])(\d{{1,2}})\s*{_UNIT}|(?<![가-힣])(두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*{_UNIT}"
)
# 목표에 이미 찾을 수가 있는지(부탁 말 없이)
_HAS_COUNT = re.compile(
    r"(?<![\d.,])\d{1,2}\s*(?:곳|군데|가지|개|종류)(?!월)|"
    r"(?<![가-힣])(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:곳|군데|가지|개|종류)"
)
_ASK_VERB = re.compile(r"찾|알려|알아봐|추천|골라|고르|뽑|조사|정리|비교|가져|모아|보여|소개")
_UPTO = re.compile(r"\s*(?:까지|만|정도|쯤|씩)")  # 부탁 말 뒤에 온 수('조사해줘 5개까지')
_CLAUSE_END = re.compile(r"[.?!\n]")
# 값을 묻는 말. '비용 · 금액'은 이 집 견적(계산 엔진)을 묻는 말이라 넣지 않아요. '값싼'은 값을 묻는 말이 아니에요.
# '견적이랑 많이 차이나?'는 값 차이를 묻는 말이에요
_PRICE = re.compile(r"가격|얼마(?!나)|판매가|값(?![싸싼쌉쌌])|시세|단가|차이\s*(?:나|많이|커|크)")
# 값 말 바로 뒤: 빼 달라 · 됐다 · 들어 있는지(포함 여부를 묻는 말은 값을 묻는 말이 아님)
_NOT_AFTER = re.compile(
    r"\s*(?:은|는|도|이|가)?\s*(?:말고|빼고|없이|됐|필요\s*없|상관\s*없|안\s*궁금|들어가|들어\s*있|포함)"
)
_NOT_BETWEEN = re.compile(r"말고|빼고|대신|방법|어떻게|계산|기준|뜻|의미|왜")
_SEE = re.compile(
    r"보여|볼래|볼게|보자|보기(?![에엔])|봐야|봐\s*줘|열어|띄워|확인\s*(?:해|할|하고)"
)
_CHANGE = re.compile(r"바꾸|바꿀|바꿔|변경|수정|고칠|고쳐|고치")
# '견적서 비교해줘' · '업체 추천해 주세요'(이름에 할 일이 든 카드)
_DO = re.compile(r"^\s*(?:좀\s*)?해\s*(?:줘|주세요|줄래|주실래|봐)")
NEAR = 12  # 카드 이름과 보기 · 바꾸기 말 사이 글자 수

# show_card 종류 → 카드 이름 말. 집 정보만 '바꾸겠다'도 부탁으로 봐요(다른 카드는 바로 바꾸는 카드가 아님).
# 집 정보에는 평형('16평으로 바꿔줘') · 벽지 종류('합지로 바꿀래요')도 들어요(집 정보 카드 · propose_home_info 칸)
SHOW_NOUN: dict[str, re.Pattern[str]] = {
    "home_info": re.compile(
        r"집\s*(?:정보|조건)|(?:평수|평형|면적)(?!별|대)|방\s*개수|방\s+수(?![가-힣])|"
        r"\d{1,3}(?:\.\d)?\s*평(?:형)?으로|(?:합지|실크)(?:\s*벽지)?로"
    ),
    "standard_quote": re.compile(r"표준\s*견적서?"),
    "schedule": re.compile(r"공정표|일정표|공사\s*일정"),
    "quote_compare": re.compile(r"견적서?\s*비교|받은\s*견적서?|실측\s*견적서?"),
    "vendor_picks": re.compile(r"업체\s*(?:다시\s*)?추천"),
    "today": re.compile(r"오늘\s*(?:할|정할)\s*일"),
}
CHANGEABLE = frozenset({"home_info"})
DOABLE = frozenset({"quote_compare", "vendor_picks"})
CARD_NAME = {
    "home_info": "집 정보 카드",
    "standard_quote": "표준견적서 카드",
    "schedule": "공정표 카드",
    "quote_compare": "견적서 비교 카드",
    "vendor_picks": "업체 추천 카드",
    "today": "오늘 할 일 카드",
}
# 그 카드 종류를 보이거나 만드는 도구(부르면 '해 봄'으로 봐요. 받은 견적서가 없어 카드가 없을 때도 다시 부르지 않게)
CALL_KIND = {
    "get_home": "home_info",
    "propose_home_info": "home_info",
    "get_standard_quote": "standard_quote",
    "get_schedule": "schedule",
    "compare_quotes": "quote_compare",
    "recommend_vendors": "vendor_picks",
    "start_research": "vendor_picks",  # 믿집 업체가 없는 지역은 믿집 밖 조사로 이어요
    "today_tasks": "today",
}


@dataclass(frozen=True)
class Asks:
    count: int | None = None  # 부탁한 수(2~10)
    unit: str = ""  # 곳 · 가지 · 개 · 군데 · 종류
    price: bool = False
    show: tuple[str, ...] = ()  # 보일 카드 종류(show_card kind)

    def __bool__(self) -> bool:
        return bool(self.count or self.price or self.show)

    def keys(self) -> list[str]:
        """기록용 이름(글 없음): count · price · show:<종류>."""
        return [
            *(["count"] if self.count else []),
            *(["price"] if self.price else []),
            *(f"show:{k}" for k in self.show),
        ]


NONE = Asks()


def _asked_before(text: str, m: re.Match[str], start: int) -> bool:
    """'업체도 조사해줘봐 5개까지'처럼 부탁 말 뒤에 수가 오면 수 바로 뒤에 '까지 · 만 · 정도'가 있을 때만 부탁으로 봐요
    ('도배 추천해줘, 방 3개야'는 아님). 앞은 같은 문장의 앞 수 뒤부터."""
    if not _UPTO.match(text, m.end()):
        return False
    stops = list(_CLAUSE_END.finditer(text, start, m.start()))
    head = text[stops[-1].end() if stops else start : m.start()]
    return bool(_ASK_VERB.search(head))


def _count(text: str) -> tuple[int | None, str]:
    found = list(_COUNT.finditer(text))
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        stop = _CLAUSE_END.search(text, m.end(), end)
        tail = text[m.end() : stop.start() if stop else end]
        start = found[i - 1].end() if i else 0
        if not _ASK_VERB.search(tail) and not _asked_before(text, m, start):
            continue
        n = int(m.group(1)) if m.group(1) else KO_NUM[m.group(3)]
        unit = m.group(2) or m.group(4)
        if COUNT_MIN <= n <= COUNT_MAX:
            return n, ("곳" if unit == "업체" else unit)
    return None, ""


def _price(text: str) -> bool:
    return any(not _NOT_AFTER.match(text, m.end()) for m in _PRICE.finditer(text))


def _show(text: str) -> tuple[str, ...]:
    got: list[str] = []
    for kind, noun in SHOW_NOUN.items():
        for m in noun.finditer(text):
            stop = _CLAUSE_END.search(text, m.end())
            near = text[m.end() : min(m.end() + NEAR, stop.start() if stop else len(text))]
            if kind in DOABLE and _DO.match(near):
                got.append(kind)
                break
            verb = _SEE.search(near) or (_CHANGE.search(near) if kind in CHANGEABLE else None)
            if verb and not _NOT_BETWEEN.search(near[: verb.start()]):
                got.append(kind)
                break
    return tuple(got)


def extract(text: str | None) -> Asks:
    """고객 말(가린 글) → 분명한 부탁. 없으면 NONE."""
    t = " ".join((text or "").split())
    if not t:
        return NONE
    n, unit = _count(t)
    return Asks(count=n, unit=unit, price=_price(t), show=_show(t))


def asked_price(text: str | None) -> bool:
    """값을 묻는 말이 있는지(조사 목표 · 메모, 바로 뒤 '말고 · 빼고 …'는 아님)."""
    return _price(" ".join((text or "").split()))


def line(a: Asks) -> str:
    """턴 사실 끝에 붙이는 '이번 부탁' 줄(비어 있으면 ''). 실측(2026-11-23 r1 '업체도 조사해줘봐 5개까지'): '못 채우면
    못 한다고 말해요'만 두니 믿집 업체가 0곳일 때 밖 조사를 맡기지 않고 '못 채워요 · 찾아볼까요?'로 멈췄어요. 그래서
    한 길로 모자라면 다른 도구로 끝까지 채우고, 다 써도 못 채운 것만 말하게 해요."""
    if not a:
        return ""
    parts = [
        *([f"{a.count}{a.unit}"] if a.count else []),
        *(["값(가격)"] if a.price else []),
        *(CARD_NAME[k] for k in a.show),
    ]
    return (
        f"이번 부탁(고객 말에서 코드가 뽑음): {' · '.join(parts)}. "
        "되묻지 말고 도구로 끝까지 채워요(한 길로 모자라면 다른 도구로). 도구를 다 써도 못 채운 것만 그렇다고 한 "
        "문장으로 말해요."
    )


def tried(name: str, args: object) -> set[str]:
    """도구 하나가 보이거나 만들 카드 종류(show_card는 고른 종류)."""
    if name == "show_card" and isinstance(args, dict):
        kind = args.get("kind")
        return {kind} if isinstance(kind, str) else set()
    kind = CALL_KIND.get(name)
    return {kind} if kind else set()


def missing(a: Asks, done: Collection[str]) -> list[str]:
    """보여 달라 · 바꾸겠다고 한 카드 중 이 턴에 보이지도(카드 · 승인 카드) 부르지도 않은 종류."""
    return [k for k in a.show if k not in done]


def nudge(miss: list[str]) -> str:
    """턴 끝에 한 번만 보내는 점검 글(모델에만 가요. 답에 옮기면 문장 검사가 빼요)."""
    names = " · ".join(CARD_NAME[k] for k in miss)
    kinds = " · ".join(miss)
    return (
        f"(요청 점검: 고객이 {names}를 보거나 바꾸려 했는데 이번 답에 그 카드가 없어요. show_card({kinds})로 카드를 "
        "보여 주고, 카드에서 무엇을 하면 되는지 한 문장으로 말해요. 보일 수 없으면 까닭을 한 문장으로 말해요. 앞에서 한 "
        "말은 되풀이하지 마.)"
    )


def research_goal(goal: str, text: str | None, kind: str, limit: int) -> str:
    """조사 목표에 고객이 말한 찾을 수 · 판매가가 빠졌으면 끝에 붙여요(' · 5곳' · ' · 판매가'). 목표에 이미 있으면 그대로."""
    a = extract(text)
    add: list[str] = []
    if a.count and not _HAS_COUNT.search(goal):
        add.append(f"{a.count}{'곳' if kind == 'outside_vendors' else '가지'}")
    if a.price and kind == "materials" and not _PRICE.search(goal):
        add.append("판매가")
    if not add:
        return goal
    tail = " · " + " · ".join(add)
    if len(goal) + len(tail) > limit:
        return goal[: max(limit - len(tail), 0)].rstrip() + tail
    return goal + tail
