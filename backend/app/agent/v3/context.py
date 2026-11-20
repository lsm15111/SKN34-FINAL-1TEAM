"""대화 상태(맥락 L1, docs/v3/agent-context.md 3절). 코드만 쓰고 LLM은 쓰지 않아요.

- 이어 묻기: 이어 묻기 신호가 있고 지금 질문에 공종 · 질문 꼴이 빠졌으면 앞 턴의 것을 물려받아 '독립 질문'을 만들어요.
  예) '실크벽지 평당 얼마예요?' 다음 '합지는요?' → '도배 합지는요 비용은 얼마예요'
- 새 공종 낱말이 있으면 공종은 물려받지 않아요. '도 · 같이 · 랑 · 까지'로 더하면 앞 공종과 합쳐요.
- 지금 질문에 꼴 낱말(비용 · 기간 · 순서 · 방법 · 뜻 · 비교 · 원인 · 예아니요 · 의문사)이 있으면 꼴은 물려받지 않아요.
- 상태에는 공종 · 꼴 · 담당 · 독립 질문(가린 글 80자)만 둬요. 금액 · 날짜 같은 숫자 값은 두지 않아요(계산 엔진이 늘 다시 세요).
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.agent.v3 import brief, policy
from app.agent.v3.templates import josa
from app.agent.v3.trades import BY_CODE, trades_in

Q_MAX = 80
SHORT = 14  # 띄어쓰기를 뺀 글자 수. 이보다 짧고 끝말이 이어 묻기 꼴이면 이어 묻기로 봐요

# 앞말 이어 묻기: '그럼 · 그건 · 이건 · 거기 · 또 …'로 시작
HEAD = re.compile(
    r"^\s*(?:그럼|그러면|그렇다면|그건|그거|그것|그게|이건|이거|이게|저건|저거|거기|그리고|아니면|또는|또|그래서|그때)"
)
# 끝말 이어 묻기: '합지는요? · 천장도? · 목공도 같이 하면요?'
TAIL = re.compile(
    r"(?:은|는|도|이랑|랑|하고|이면|면|라면|이라면|에는|엔|까지)\s*요?\s*[?？.!]*\s*$"
)
# 공종을 더하는 말: '목공도 같이 · 합지도요 · 천장까지'('도배'의 '도'는 아니에요)
ADD = re.compile(r"같이|함께|(?:도|까지|이랑|랑|하고)(?=\s|요|[?？]|$)")
# 물려받는 꼴 → 독립 질문 뒤에 붙일 말. 붙인 말이 다시 같은 꼴로 읽혀요(관문 정책 표시 · brief.form_of)
FORM_PHRASE = {
    "price": "비용은 얼마예요",
    "period": "기간은 며칠 걸려요",
    "order": "순서는 어떻게 돼요",
    "howto": "어떻게 해요",
    "define": "뭐예요",
    "compare": "어느 쪽이 나아요",
    "cause": "왜 그래요",
}
# 추천 · 하자 · 법률 꼴은 물려받지 않아요(정해 둔 글로 답하는 질문이라 잘못 물려받으면 엉뚱한 거절 글이 붙어요)
FORMS = (
    ("order", brief.ORDER_Q),
    ("cause", brief.CAUSE_Q),
    ("define", brief.DEFINE_Q),
    ("compare", brief.COMPARE_Q),
    ("howto", brief.HOWTO_Q),
    ("yesno", brief.YESNO_Q),
)


class SaidArea(BaseModel):
    """고객이 대화에서 말한 집 크기(질문 속 평수 · ㎡). 금액 · 기간은 늘 계산 엔진이 이 값으로 다시 세요."""

    m2: float
    basis: Literal["supply", "exclusive"] = "supply"
    label: str  # '32평' · '전용 84㎡'


class ChatState(BaseModel):
    """대화방 하나의 맥락. chats.state(JSONB)에 저장해요."""

    trades: list[str] = []
    form: str = "other"
    route: str = ""
    q: str = ""  # 앞 턴의 독립 질문(가린 글, Q_MAX자)
    turn: int = 0
    # 앞 턴에서 말한 집 크기 · 시작 날짜. 공사 없는 대화에서 그 값이 없는 다음 질문이 이어받아요
    area: SaidArea | None = None
    start: date | None = None


def load(raw: dict | None) -> ChatState | None:
    """저장된 상태를 읽어요. 모양이 안 맞으면(옛 행 · 깨진 값) 없는 것으로 봐요."""
    if not raw:
        return None
    try:
        return ChatState.model_validate(raw)
    except ValueError:
        return None


def explicit_form(text: str) -> str | None:
    """질문에 직접 들어 있는 꼴. 꼴 낱말이 없으면 None(물려받을 수 있음)."""
    t = text or ""
    if set(policy.policy_of(t)) & {
        "price", "period", "vendor_reco", "brand_reco", "defect_judgement", "legal_case",
    }:  # fmt: skip
        return brief.form_of(t)
    for form, pat in FORMS:
        if pat.search(t):
            return form
    return "other" if brief.WH.search(t) else None


def follow_up(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if HEAD.search(t):
        return True
    return len(re.sub(r"\s+", "", t)) <= SHORT and bool(TAIL.search(t))


def _name(code: str) -> str:
    spec = BY_CODE.get(code)  # type: ignore[call-overload]
    return spec.ko.split(" · ")[0] if spec and code != "common" else ""


def resolve(text: str, state: ChatState | None) -> tuple[str, bool]:
    """(독립 질문, 물려받았는지). 물려받을 게 없으면 질문 그대로예요."""
    t = (text or "").strip()
    if state is None or not state.q or not follow_up(t):
        return t, False
    now = trades_in(t)
    pre: list[str] = []
    if not now:
        pre = [_name(c) for c in state.trades[:2]]
    elif ADD.search(t):
        pre = [_name(c) for c in state.trades[:2] if c not in now]
    pre = [p for p in pre if p]
    post = FORM_PHRASE.get(state.form, "") if explicit_form(t) is None else ""
    if not pre and not post:
        return t, False
    core = re.sub(r"[?？.!\s]+$", "", t)
    if pre and (now or len(pre) > 1):
        # 공종 낱말은 '랑'으로 이어요. 띄어 쓰기만 하면 관문이 한 공종 질문으로 읽어 앞 공종만 답해요
        last = len(pre) if now else len(pre) - 1
        pre = [josa(p, "이랑", "랑") if i < last else p for i, p in enumerate(pre)]
    return " ".join(x for x in (*pre, core, post) if x), True


def next_state(
    prev: ChatState | None,
    question: str,
    *,
    route: str,
    trades: list[str],
    turn: int,
    area: SaidArea | None = None,
    start: date | None = None,
) -> ChatState | None:
    """이 턴 뒤의 상태. 범위 밖 · 되묻기 후보 턴은 앞 상태를 그대로 둬요(잡담이 맥락을 지우지 않게).
    area · start: 이번 질문에서 말한 집 크기 · 시작 날짜. 없으면 앞 턴 값을 그대로 둬요(새로 말하면 바꿔요)."""
    if route in ("out_of_scope", "ask_back"):
        return prev
    return ChatState(
        trades=[c for c in trades if c != "common"] or (prev.trades if prev else []),
        form=explicit_form(question) or "other",
        route=route,
        q=(question or "")[:Q_MAX],
        turn=turn,
        area=area or (prev.area if prev else None),
        start=start or (prev.start if prev else None),
    )
