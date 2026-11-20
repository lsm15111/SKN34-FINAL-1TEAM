"""일반 설명 (LLM 모드, 지시문 general_v1). 믿집 자료가 없는 도배 · 목공의 '무엇 · 어떻게' 질문에만
널리 알려진 일반 상식으로 숫자 없는 짧은 설명을 써요. 화면에는 '일반 설명(믿집 자료 밖)'으로 보이고 확인할 곳이 붙어요.

- 부르는 때: 답 작성기까지 돌린 뒤에도 '확인하지 못했어요'만 남은 턴(turn.py). 무료 모드는 부르지 않아요.
- 빼는 질문(코드가 먼저 걸러요): 숫자(금액 · 기간 · 수량 · 치수), 업체 · 브랜드 · 제품, 하자 판정 · A/S · 환불 · 계약 · 법률,
  전기 · 가스 · 구조 · 방수 · 배관 같은 위험한 작업, '우리 집 봐 주세요', 도배 · 목공 밖 공종(관문이 고른 담당이 trade · 도배 · 목공일 때만).
- 출력 검사: 숫자(아라비아 숫자 · 하루 · 이틀 같은 말) · 업체 · 브랜드 · 하자 판정 · 법률 · 위험 작업 낱말이 든 문장과
  금지 표현 · 지시문 누출은 빼요(check.section, 허용 숫자 없음). 첫 문장이 빠지면 쓰지 않아요(모름 그대로).
"""

import re
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agent import llm
from app.agent.v3 import check, llm_mode
from app.agent.v3.schemas import Section, Sentence, TradeCode

PROMPTS = Path(__file__).with_name("prompts")
VERSION = "general_v1"
TRADES = ("dobae", "mokgong")
MAX_ITEMS = 4

# '무엇 · 어떻게' 질문(뜻 · 차이 · 종류 · 방법 · 순서 · 고르는 법 · 관리)
WHAT_HOW = re.compile(
    r"뭐(?:예요|에요|야|죠|지|가|를|인가요|인지|일까요|하는|해요)|무엇|무슨|뭔가요|뭔지|뭘|"
    r"어떤\s{0,2}(?:거|것|게|걸)|차이|종류|뜻|의미|(?:이|가)란|라는\s{0,2}게|"
    r"어떻게|어떡|방법|하는\s{0,2}법|요령|순서|과정|절차|팁|주의할|주의\s{0,2}사항|조심|관리|고르|골라|선택"
)
# 숫자를 묻는 말(금액 · 기간 · 때 · 수량 · 치수)
NUM_ASK = re.compile(
    r"얼마|비용|가격|금액|견적|단가|평당|시세|예산|며칠|몇|기간|언제|시간이|날짜|일정|"
    r"치수|사이즈|크기|두께|길이|높이|너비|폭이"
)
# 업체 · 제품, 하자 · 계약 · 법률, 위험한 작업(설명 · 우리 집 조건 질문에서도 빼요, explain.py)
RISK = re.compile(
    r"업체|시공사|회사|사장|기사님|브랜드|제품|모델|메이커|"
    r"하자|불량|책임|A\s{0,1}/\s{0,1}S|AS(?![A-Za-z])|보수|보증|환불|보상|배상|분쟁|위약금|계약|법적|소송|고소|변호사|"
    r"전기|배선|전선|콘센트|스위치|조명|전등|누전|감전|차단기|가스|보일러|구조|내력벽|기둥|철근|방수|누수|배관|석면|화재",
    re.IGNORECASE,
)
# + 우리 집을 봐 달라는 말
EXCLUDE = re.compile(RISK.pattern + r"|우리\s{0,2}집|저희\s{0,2}집|봐\s{0,2}주", re.IGNORECASE)
BLOCK_FLAGS = {
    "price", "period", "vendor_reco", "brand_reco", "defect_judgement", "legal_case", "safety", "my_house",
}  # fmt: skip
# 답 문장에 들면 빼는 말: 숫자 · 숫자 말, 업체 · 브랜드, 하자 판정 · 법률, 위험한 작업
OUT_NUM = re.compile(
    r"\d|하루|이틀|사흘|나흘|닷새|일주일|보름|한\s{0,2}달|반나절|절반|퍼센트|%|"
    r"(?:한|두|세|네|다섯|여섯)\s{0,2}(?:시간|겹|롤|장|평|개|배|군데)|(?:두|세|네|다섯)\s{0,2}번"
)
OUT_WORD = re.compile(
    r"업체를\s{0,2}(?:추천|고르)|브랜드|제품명|모델명|하자(?:예요|입니다|가\s{0,2}맞|로\s{0,2}봐|라고)|"
    r"법적|소송|위약금|배상|전기|배선|콘센트|스위치|누전|가스|내력벽|방수|배관|석면"
)
WHERE_DEFAULT = "실측 때 업체"


class General(BaseModel):
    ok: bool
    lead: str
    kind: Literal["body", "steps"]
    items: list[str]


@cache
def prompt() -> str:
    return (PROMPTS / f"{VERSION}.md").read_text(encoding="utf-8")


@cache
def rules() -> str:
    """누출 검사에 쓰는 지시문 앞부분(규칙). 예시 답은 뺀다."""
    return prompt().split("## 예시")[0]


def eligible(question: str, route: str, trades: list[str], policy: list[str]) -> bool:
    """일반 설명을 해도 되는 질문인지(코드 규칙, LLM 없음)."""
    if route != "trade" or not trades or any(t not in TRADES for t in trades):
        return False
    if set(policy) & BLOCK_FLAGS:
        return False
    q = question or ""
    return bool(WHAT_HOW.search(q)) and not NUM_ASK.search(q) and not EXCLUDE.search(q)


def to_sections(
    g: General, *, route: str, trade: TradeCode | None, dropped: list[str]
) -> list[Section]:
    """LLM 답 → 검사를 지난 Section들(첫 줄 묶음 + 본문 또는 단계 묶음). 첫 문장이 빠지면 []."""
    if not g.ok or not g.lead.strip():
        return []

    def keep(text: str) -> Sentence | None:
        t = text.strip()
        if not t:
            return None
        if OUT_NUM.search(t):
            dropped.append("일반 설명: 숫자")
            return None
        if OUT_WORD.search(t):
            dropped.append("일반 설명: 빼는 말")
            return None
        return Sentence(text=t)

    def checked(sents: list[Sentence], steps: bool = False) -> Section | None:
        if not sents:
            return None
        sec = Section(sentences=sents, source="general", route=route, trade=trade, steps=steps)
        kept, why = check.section(sec, "", calc_text=None, shown=None, prompt=rules())
        dropped.extend(why)
        return kept

    head = keep(g.lead)
    lead = checked([head]) if head else None
    if lead is None:
        return []
    body = [x for x in (keep(t) for t in g.items[:MAX_ITEMS]) if x is not None]
    rest = checked(body, steps=g.kind == "steps" and len(body) >= 2)
    return [lead, rest] if rest else [lead]


async def explain(
    question: str, *, route: str, trade: TradeCode | None, dropped: list[str]
) -> list[Section]:
    """일반 설명 한 번. 못 쓰면 [](부르는 쪽은 모름 그대로)."""
    messages = [
        ("system", prompt()),
        ("user", f"고객 질문: {llm_mode._data(check.mask(question))}"),
    ]
    try:
        g = await llm.structured("general", General, messages)
    except llm.LLMError:
        dropped.append("일반 설명 실패")
        return []
    if not g.ok:
        dropped.append("일반 설명: 답하지 않음")
        return []
    return to_sections(g, route=route, trade=trade, dropped=dropped)
