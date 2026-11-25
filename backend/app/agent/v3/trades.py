"""공종 설정(TradeSpec) 13개: 12공종 + 공통. 공종 에이전트 코드는 한 벌이고 설정만 바꿔 낀다 (ADR agent-03).

- 깊이: 도배 · 목공은 'deep'(브리프 칸 되묻기 · 계산 엔진 연결), 나머지 10공종은 'knowledge'(지식 답).
- 낱말(words)은 관문 · 오케스트레이터 · 평가가 같이 읽는다. 처음 나온 순서대로 공종을 고른다.
  evaluation/v3/trades_v3.py에서 옮겨 왔고, 고칠 때는 dev 세트(E1)로만 고른다.
- 정해 둔 글(주의 · 순서 문장)에는 숫자를 쓰지 않는다. 공정 순서는 v2 GUIDE(팀이 쓴 순서)를 따른다.
- tags: 지식 조각의 공정 표시(16가지 낱말) → 이 공종. 검색 무게에 쓴다.
"""

import re
from dataclasses import dataclass, field

from app.agent.v3.schemas import TradeCode


@dataclass(frozen=True)
class Slot:
    """도배 · 목공 브리프 칸 하나. 고객이 버튼으로 고르면 기능 service가 저장한다(에이전트는 안 씀)."""

    key: str  # 예: dobae.grade
    question: str
    options: tuple[str, ...]
    fact: str = ""  # ProjectFacts에서 이 칸을 채우는 필드(있으면 되묻지 않음)


@dataclass(frozen=True)
class TradeSpec:
    code: TradeCode
    ko: str
    depth: str  # deep | knowledge
    words: str
    tags: tuple[str, ...]
    order: int  # 공정 순서(작을수록 먼저). 공통은 0
    cautions: tuple[str, ...] = ()
    survey: tuple[str, ...] = ()  # 실측 때 업체가 정하는 것
    prep: tuple[str, ...] = ()  # 고객 준비
    slots: tuple[Slot, ...] = ()
    calc: bool = False  # 믿집 계산 엔진이 금액 · 기간을 내는 공종
    risky_diy: bool = False  # 셀프 방법 대신 전문 업체를 권하는 공종(L24)
    check_where: str = "실측 때 업체"  # 모를 때 확인할 곳
    pattern: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pattern", re.compile(self.words, re.IGNORECASE))


SPECS: tuple[TradeSpec, ...] = (
    TradeSpec(
        "dobae",
        "도배",
        "deep",
        r"도배|벽지|초배|정배|합지|실크|도배풀|풀자국|퍼티|빠데|광폭|소폭|띠벽지|덧방\s*도배",
        ("도배",),
        7,
        cautions=(
            "천장 평탄화 · 몰딩 같은 목공이 끝난 뒤에 도배해요.",
            "곰팡이 · 습기가 있는 벽은 벽지보다 바탕부터 손봐요.",
        ),
        survey=("벽 · 천장 면적", "기존 벽지 상태(들뜸 · 곰팡이 · 결로)"),
        prep=("벽 앞 가구 옮기기", "벽에 건 액자 · 선반 떼기"),
        slots=(
            Slot(
                "dobae.grade",
                "오래 사실 집인가요, 세 놓을 집인가요?",
                ("오래 살 집", "세 놓을 집", "아직 몰라요"),
                fact="grade",
            ),
            Slot(
                "dobae.ceiling",
                "천장도 같이 도배하실 건가요?",
                ("천장도 해요", "벽만 해요", "아직 몰라요"),
            ),
            Slot(
                "dobae.living",
                "공사하는 동안 그 집에 사세요?",
                ("살면서 해요", "빈 집이에요", "아직 몰라요"),
                fact="living",
            ),
            Slot(
                "dobae.mold", "벽에 곰팡이나 물자국이 있나요?", ("있어요", "없어요", "아직 몰라요")
            ),
            Slot(
                "dobae.area_basis",
                "넣으신 면적이 공급면적인가요, 전용면적인가요?",
                ("공급면적이에요", "전용면적이에요", "아직 몰라요"),
                fact="area_basis",
            ),
        ),
        calc=True,
    ),
    TradeSpec(
        "mokgong",
        "목공",
        "deep",
        r"목공|목수|목재|몰딩|걸레받이|굽도리|문틀|문선|(?<!사전)(?<!실측 )방문(?!판매)|문짝|경첩|석고|"
        r"도어(?!락|록)|다루끼|각재|가벽|칸막이|천장틀|평탄화|단내림|커튼박스|단열|웨인스코팅|템바보드|분리대",
        ("목공",),
        4,
        cautions=("목공을 도배 · 필름보다 먼저 끝내요.",),
        survey=("몰딩 · 걸레받이 길이", "방문 개수 · 크기", "천장 · 벽 상태"),
        prep=("바꿀 방문 고르기",),
        slots=(
            Slot(
                "mokgong.molding", "몰딩도 바꾸실 건가요?", ("바꿔요", "그대로 둬요", "아직 몰라요")
            ),
            Slot(
                "mokgong.molding_scope",
                "이번 공사는 어디까지 하세요?",
                ("벽 · 천장까지 새로", "도배만 새로", "몰딩 색만 바꾸기"),
            ),
            Slot(
                "mokgong.doors",
                "방문은 문짝만 바꾸세요, 문틀까지 바꾸세요?",
                ("문짝만", "문틀까지", "아직 몰라요"),
            ),
            Slot(
                "mokgong.ceiling",
                "천장을 평평하게 잡는 공사도 생각하세요?",
                ("네", "아니요", "아직 몰라요"),
            ),
        ),
        calc=True,
    ),
    TradeSpec(
        "floor",
        "바닥",
        "knowledge",
        r"바닥재|강마루|강화마루|원목마루|마루|장판|데코타일|폴리싱|층간소음|바닥(?!\s*타일)",
        ("바닥재",),
        8,
        cautions=("바닥재는 도배가 끝난 뒤에 깔아요.",),
        survey=("바닥 수평 · 들뜸", "문턱 · 걸레받이 높이"),
        prep=("바닥에 둔 짐 옮기기",),
    ),
    TradeSpec(
        "tile",
        "타일",
        "knowledge",
        r"타일|줄눈|메지|포세린",
        ("타일",),
        5,
        cautions=("타일 덧방은 바탕 상태를 보고 정해요.",),
        survey=("바탕 벽 · 바닥 상태", "물 빠짐 기울기"),
    ),
    TradeSpec(
        "bath",
        "욕실",
        "knowledge",
        r"욕실|화장실|욕조|샤워|세면대|변기|비데|수전|방수|욕실장|환풍기",
        ("욕실",),
        5,
        cautions=("방수를 하면 마른 뒤에 타일을 붙여요.",),
        survey=("방수 상태", "배수구 · 배관 위치"),
        prep=("욕실 쓰지 못하는 동안 지낼 곳 정하기",),
        risky_diy=True,
    ),
    TradeSpec(
        "kitchen",
        "주방",
        "knowledge",
        r"주방|부엌|싱크대|씽크대|상판|상부장|하부장|후드|인덕션|아일랜드|붙박이장|신발장|주방\s*가구",
        ("주방", "가구"),
        9,
        cautions=("주방 가구는 바닥재를 깐 뒤에 설치해요.",),
        survey=("벽 길이 · 배관 · 콘센트 위치",),
    ),
    TradeSpec(
        "paint",
        "도장",
        "knowledge",
        r"도장(?!\s*(?:찍|을\s*찍|날인))|페인트|탄성코트|벽칠|도색|젯소|칠(?:하|을|해|이|은)",
        ("도장",),
        6,
        cautions=("칠하기 전에 바탕을 고르고 환기해요.",),
    ),
    TradeSpec(
        "film",
        "필름",
        "knowledge",
        r"필름|시트지|랩핑",
        ("필름",),
        6,
        cautions=("필름은 목공이 끝난 뒤, 도배 전에 붙여요.",),
    ),
    TradeSpec(
        "electric",
        "전기 · 조명",
        "knowledge",
        r"전기|조명|콘센트|스위치|누전|차단기|LED|등기구|매입등|다운라이트|배선|전등|방등|분전반|실링팬|"
        r"무드등|간접등|센서등|회로|두꺼비집|멀티탭|형광등|전구",
        ("조명", "전기"),
        3,
        cautions=("배선 · 차단기 작업은 전기 공사 자격이 있는 업체에 맡겨요.",),
        risky_diy=True,
        check_where="전기 공사 업체",
    ),
    TradeSpec(
        "window",
        "창호",
        "knowledge",
        # '창문 열기 · 닫기 · 환기'는 창호 공사가 아니라 다른 공종의 건조 · 환기 질문이에요
        r"창호|샷시|섀시|새시|창문(?![^.?!]{0,12}(?:열어|열고|열면|열기|열\s*수|열지|닫아|닫고|닫으|닫기|닫지|환기))|"
        r"창틀|방충망|이중창|시스템창|유리창|강화유리|중문|발코니\s*확장",
        ("창호", "중문", "확장"),
        2,
        cautions=("창을 바꾸면 창 둘레 마감을 한 뒤 도배해요.",),
        survey=("창 크기 · 틀 상태",),
    ),
    TradeSpec(
        "demolition",
        "철거",
        "knowledge",
        r"철거|뜯어|뜯고|폐기물|원상복구|깨고|부수|석면|헐어|헐고",
        ("철거",),
        1,
        cautions=("철거는 가장 먼저 해요. 철거 뒤 바탕 상태를 보고 다음 공사를 정해요.",),
        check_where="관리사무소 · 실측 때 업체",
    ),
    TradeSpec(
        "plumbing",
        "설비",
        "knowledge",
        r"설비|배관|보일러|난방|분배기|수도|누수|하수구|배수|급수|에어컨|온수|역류|가스|물이\s*새|물이\s*샌",
        ("설비",),
        2,
        cautions=("배관 · 가스 작업은 전문 업체에 맡겨요.",),
        risky_diy=True,
        check_where="설비 업체 · 관리사무소",
    ),
    TradeSpec(
        "common",
        "공통",
        "knowledge",
        r"(?!x)x",
        ("전체", "공통", "마감"),
        0,
        check_where="관리사무소 · 1372 소비자상담센터",
    ),
)
BY_CODE: dict[str, TradeSpec] = {s.code: s for s in SPECS}
TRADE_CODES: tuple[str, ...] = tuple(s.code for s in SPECS if s.code != "common")
TAG_TO_CODE: dict[str, str] = {t: s.code for s in SPECS for t in s.tags}

# 앞뒤 공종 쌍의 순서 문장(오케스트레이터가 합칠 때 덧붙인다). 숫자 없음
ORDER_RULES: dict[tuple[str, str], str] = {
    ("demolition", "bath"): "철거가 먼저예요. 철거 뒤 방수 · 타일 순서로 욕실 공사를 해요.",
    ("plumbing", "bath"): "배관 · 방수를 먼저 하고 그다음 욕실 타일을 붙여요.",
    ("electric", "mokgong"): "전기 배선 자리를 먼저 정하고 목공으로 천장 · 벽을 막아요.",
    ("mokgong", "dobae"): "목공이 끝난 뒤 도배해요.",
    ("mokgong", "film"): "목공이 끝난 뒤 문 · 몰딩에 필름을 붙여요.",
    ("mokgong", "paint"): "목공이 끝난 뒤 칠해요.",
    ("film", "dobae"): "필름을 먼저 붙이고 도배해요.",
    ("paint", "dobae"): "칠을 먼저 하고 도배해요.",
    ("tile", "dobae"): "욕실 · 타일 공사가 끝난 뒤 도배해요.",
    ("bath", "dobae"): "욕실 공사가 끝난 뒤 도배해요.",
    ("window", "dobae"): "창을 바꾼 뒤 도배해요.",
    (
        "dobae",
        "floor",
    ): "믿집 공정표는 도배 다음에 바닥을 놓아요. 다만 마루는 도배 전에, 장판은 도배 뒤에 까는 경우가 많아서 실측 때 업체와 순서를 정해요.",
    ("floor", "kitchen"): "바닥재를 깐 뒤 주방 가구를 설치해요.",
    ("demolition", "floor"): "철거 뒤 바닥 상태를 보고 바닥재를 정해요.",
}
# 순서 문장의 근거: 계산 엔진 공정표 순서(rule:plan-order, calc/v2_plan.PLAN_ORDER) + 그 순서를 말하는 지식 조각
ORDER_CITES: dict[tuple[str, str], tuple[str, ...]] = {
    ("demolition", "bath"): ("K372",),
    ("plumbing", "bath"): ("K157", "K372"),
    ("electric", "mokgong"): ("K157", "K167"),
    ("mokgong", "dobae"): ("rule:plan-order", "K1360"),
    ("mokgong", "film"): ("rule:plan-order", "K1360"),
    ("mokgong", "paint"): ("rule:plan-order", "K157"),
    ("film", "dobae"): ("rule:plan-order", "K1362"),
    ("paint", "dobae"): ("rule:plan-order", "K1362"),
    ("tile", "dobae"): ("rule:plan-order", "K1360"),
    ("bath", "dobae"): ("rule:plan-order",),
    ("window", "dobae"): ("rule:plan-order",),
    ("dobae", "floor"): ("rule:plan-order", "K840"),
    ("floor", "kitchen"): ("rule:plan-order", "K1360"),
    ("demolition", "floor"): ("K778",),
}
PLAN_KO = {
    "window": "창호", "carpentry": "목공", "bath": "욕실", "tile": "타일", "film": "필름", "paint": "도장",
    "wallpaper": "도배", "floor": "바닥", "furniture": "가구", "middoor": "중문", "light": "조명", "finish": "마감",
}  # fmt: skip


def rules() -> dict[str, dict[str, str]]:
    """근거 종류 rule: 계산 엔진이 공정표를 놓는 순서. 답 · 채점 묶음에 근거로 붙인다(글은 계산 엔진 상수에서 만든다)."""
    from app.calc.v2_plan import PLAN_ORDER

    order = " → ".join(PLAN_KO.get(c, c) for c in PLAN_ORDER)
    return {
        "rule:plan-order": {
            "title": "믿집 공정표 계산 순서",
            "kind": "rule",
            "text": f"믿집 계산 엔진이 공정표를 놓는 순서: {order}. 뒤 공정은 앞 공정이 끝난 다음 일하는 날 시작해요.",
        }
    }


# 자리 · 물건 낱말 공종(욕실 · 주방 · 목공의 문 · 몰딩 · 창): 같은 문장에 '하는 일' 공종이 있으면 그쪽이 질문의 주인이다
# (예: '욕실 타일' → 타일, '붙박이장 필름' → 필름, '방문 칠' → 도장). E1 dev 질문 은행에서 고른 규칙(held-out 안 봄)
CONTEXT = {"bath": 2, "kitchen": 2, "mokgong": 1, "window": 1}
WORK_OVER = {
    "bath": ("tile", "electric", "plumbing", "demolition", "film", "paint"),
    "kitchen": ("film", "demolition", "electric", "tile", "paint"),
    "mokgong": ("paint", "film"),
    "window": ("film",),
}


def trades_in(text: str) -> list[TradeCode]:
    """걸린 공종: 질문의 주인 공종을 맨 앞에, 나머지는 문장에 처음 나온 순서로(공통 빼고)."""
    hits: list[tuple[int, str]] = []
    for s in SPECS:
        if s.code == "common":
            continue
        m = s.pattern.search(text or "")
        if m:
            hits.append((m.start(), s.code))
    order = [c for _, c in sorted(hits)]
    if len(order) >= 2 and order[0] in WORK_OVER:
        work = next((c for c in order[1:] if c in WORK_OVER[order[0]]), None)
        if work:
            order.remove(work)
            order.insert(0, work)
    return order  # type: ignore[return-value]


def mention_spans(text: str, codes: list[str]) -> list[tuple[int, int, str]]:
    """공종마다 처음 걸린 낱말 자리(시작 · 끝 · 공종), 문장 순서."""
    out = []
    for c in codes:
        m = BY_CODE[c].pattern.search(text or "")
        if m:
            out.append((m.start(), m.end(), c))
    return sorted(out)


def chunk_trades(tags: tuple[str, ...] | list[str]) -> frozenset[str]:
    """조각 공정 표시 → v3 공종 묶음. 표시가 없거나 전체 · 공통 · 마감뿐이면 공통."""
    got = {TAG_TO_CODE.get(t) for t in tags} - {None, "common"}
    return frozenset(got) if got else frozenset({"common"})  # type: ignore[arg-type]


def by_order(codes: list[str]) -> list[str]:
    return sorted(codes, key=lambda c: (BY_CODE[c].order, codes.index(c)))
