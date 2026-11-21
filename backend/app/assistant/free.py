"""무료 모드 코드 길잡이 (계약서 4장 9, 2026-11-21 보강). 키 없음 · 상한 · 차단기일 때 LLM 없이
말 → 의도(고객: 학습한 의도 모델 intent_v4, 업체: 낱말 규칙) → 도구 함수(카드) → 정해 둔 글로 답한다.

- 고객: 업체 추천 → vendor_picks · 실측 시간 → visit_slots(요청 전 희망 기간, 업체 답 뒤 반나절) · 견적서 비교 ·
  공정표 · 표준견적서 · 오늘 할 일 · 집 정보. 그 밖(지식 · 공통)은 answer_only로 답하고 공사 단계 · 보던 카드에 맞는
  화면(view)을 넘긴다. 목공만 물으면 목공 담당(button)으로 보낸다.
- 업체: 못 받아요 → decline 제안 하나 · 기간 답하기 → window_answer 제안 하나(같은 대상에 열린 제안이 있으면 그것,
  actions.propose) · 견적서 체크리스트 · 오늘 할 일. 그 밖은 요청 브리핑(새 제안 없음) + answer_only.
- 업체 연결(추천 · 실측 · 견적 비교 · 확정)은 아직 도배만이다. 목공 · 다른 공사로 물으면 policy.DOBAE_ONLY를 말하고
  도배 쪽 오늘 할 일을 보여 준다. 목공 지식 · 표준견적서는 그대로 답한다. 공종은 이 대화 · 공사에 나온 업체 이름을
  뺀 뒤 찾는다('마루와벽'의 '마루'는 바닥이 아니다).
- 비서가 기억한 것을 어디서 보고 지우는지 물으면 정해 둔 안내(내 정보 → 비서가 기억한 것)로 답한다.
- 고객 제안(승인 카드)은 사람이 카드 단추를 누른 턴(choice 'visit_request:v1,v2' …)에 choices.apply가 만든다.
  예외 하나: '공사 미루고 싶어요'처럼 공사 날짜를 바꾸고 싶다는 말은 날짜 바꾸기 요청 승인 카드
  (propose_date_change, 며칠 뒤 · 이날부터는 말에서 코드가 읽고 없으면 일주일 뒤)로 안내한다. 바라는 말이 없으면
  ('미루면 어떻게 돼요?') 안내 글만. 업체가 낸 날짜에 답하는 말 · 업체가 미루자는 말 · 실측 날짜는 여기로 오지 않는다.
- 글이 카드를 말하면 같은 턴에 그 카드가 있어야 한다(fit_cards): 없으면 만들고, 못 만들면 그 문장을 뺀다.
- 업체를 확정한 뒤 견적 비교를 물으면 확정한 업체 · 견적서 판을 말한다(확정 단추 안내를 하지 않는다).
"""

import re
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal

from app.assistant import policy
from app.assistant.schemas import CardOut, TodayData
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards
from app.assistant.tools import aftercare as aftercare_tools
from app.assistant.tools import diy as diy_tools
from app.db import SessionLocal
from app.shared.errors import AppError

Handler = Callable[[ToolCtx, str, list[str]], Awaitable[tuple[str, ToolOut] | None]]

# ---- 의도 (위에서부터 처음 맞는 것) ----
CUSTOMER: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("compare", re.compile(
        r"견적\S{0,2}\s{0,2}(?:비교|견줘|견주|차이|중에)|어느\s*견적|받은\s*견적|견적서\s*(?:왔|봐|보여|어때)|"
        r"업체\s*확정|확정\s*(?:할|하고|해|하려)"
    )),
    ("slots", re.compile(
        r"실측\S{0,3}\s{0,3}(?:언제|날짜|시간|일정|잡|가능|몇\s*시|날)|언제\s*(?:실측|와|오|올)|"
        r"방문\s*(?:언제|날짜|일정)|반나절"
    )),
    ("vendors", re.compile(
        r"업체\s*(?:추천|알려|소개|골라|찾아|보여|어디|목록|좀)|어느\s*업체|어떤\s*업체|(?:업체|곳)\s*추천|"
        r"추천\s*(?:해|좀)|맡길\s*(?:곳|업체)"
    )),
    ("schedule", re.compile(
        r"공정표|공사\s*(?:날짜|일정|시작일?|언제|며칠)|언제\s*(?:시작|공사)|날짜\s*(?:수락|확인)|"
        r"일정\s*(?:확인|보여|어떻게)"
    )),
    ("standard", re.compile(
        r"표준\s*견적|견적\s*(?:얼마|금액|보여)|얼마\s*(?:나와|들어|정도|예요|일까|해요)|비용\s*(?:얼마|알려|보여)|"
        r"총\s*(?:비용|금액)"
    )),
    ("home", re.compile(r"집\s*정보|우리\s*집\s*(?:정보|조건)|평수\s*(?:확인|보여)")),
    ("today", re.compile(  # '오늘'만으로는 잡지 않는다('오늘 점심 뭐 먹지?'는 잡담)
        r"오늘\s*(?:할|정할|해야|뭐\s*(?:하|해|할))|할\s*일|뭐\s*(?:하면|해야|할까)|다음\s*(?:단계|할|은|엔|에)|"
        r"지금\s*(?:뭐|무엇|어디)|진행\s*(?:상황|중)|어디까지"
    )),
)  # fmt: skip
VENDOR: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("decline", re.compile(
        r"거절|못\s*(?:받|가|해|하|간)|안\s*(?:받|할|해|갈)|사양|어렵|힘들|패스|안\s*될"
    )),
    ("window", re.compile(
        r"기간|답(?:하|해|할|장)|언제\s*(?:가|갈)|가능한\s*(?:날|때|시간)|빈\s*(?:시간|날|반나절|칸)|"
        r"일정\s*(?:보내|답)|수락|받을게|받을래|갈게"
    )),
    ("checklist", re.compile(r"견적서|체크|항목|빠진|빠뜨|확인할\s*것")),
    ("brief", re.compile(r"브리핑|요약해|정리해\s*줘")),
    ("today", re.compile(r"오늘|할\s*일|새\s*요청|공사\s*날짜|일정\s*(?:확인|보여)|작업함")),
)  # fmt: skip
# 업체 말의 '수락'이 업체가 받는다는 뜻이 아닌 꼴: 고객이 수락 · 수락 안 함('고객이 아직 수락 안 했는데 …')
NOT_ACCEPT = re.compile(r"고객\S{0,2}\s+(?:\S+\s+){0,2}?수락|수락\s*(?:안|않|못|을\s*안)|수락하지")
DECLINE_CODE = (
    ("full", re.compile(r"일정|바빠|바쁘|꽉|여유|시간이\s*없")),
    ("out_of_area", re.compile(r"지역|멀|거리|구역|동네")),
)
LINKED = ("compare", "slots", "vendors")  # 업체 연결 흐름: 아직 도배만

NO_PICKS = "아직 이 집 조건에 맞춰 단가를 확인한 업체가 없어요. 업체 고르기 화면에서 새로 들어오는 업체를 볼 수 있어요."
PICKS = "{area}에서 이 집 조건에 맞는 도배 업체 {n}곳을 믿집 점수로 골랐어요. 카드에서 업체를 고르면 실측 요청 승인 카드를 만들어요."
WISHES = (
    "공사 시작 희망일에 맞춘 실측 희망 기간 후보예요. 업체를 골라 실측 요청을 보내면 업체가 그 안에서 갈 수 있는 "
    "기간을 답해요."
)
NO_WISHES = "희망 기간 후보를 찾지 못했어요. 업체를 골라 실측 요청을 보내면 업체가 갈 수 있는 기간을 답해요."
HALVES = (
    "업체가 답한 기간에서 고르기 좋은 반나절이에요. 카드에서 시간을 고르면 승인 카드를 만들어요."
)
VISITS = "실측 진행은 작업 카드에서 볼 수 있어요. 업체가 기간을 답하면 반나절 후보를 보여 드릴게요."
VISITS_WAIT = "고른 시간을 업체가 수락하면 실측 날짜가 정해져요. 진행은 작업 카드에서 볼 수 있어요."
VISITS_BOOKED = "실측 날짜가 정해졌어요. 날짜는 작업 카드에서 볼 수 있어요."
VISITS_DONE = "실측은 끝났어요. 받은 견적서는 견적서 비교에서 볼 수 있어요."
# 카드 위 한 줄('실측 견적서가 2곳 왔어요.')을 되풀이하지 않는다
QUOTES = "합계 · 포함 항목 · 기간 · 유효기간을 카드에서 견줘 보세요. 확정할 업체를 카드에서 고르면 승인 카드를 만들어요."
CONFIRMED = "{vendor} 견적서 {version}판으로 확정했어요. 받은 견적서는 카드에서 다시 볼 수 있어요."
NO_QUOTES = "아직 받은 실측 견적서가 없어요. 업체가 실측하고 견적서를 보내면 여기서 견줄 수 있어요."
NO_DATES = "아직 확정한 업체의 공사 날짜가 없어요. 업체를 확정하면 업체가 공사 날짜를 올려요."
DATES = "카드에서 수락을 누르면 승인 카드를 만들어요."
DATES_OPEN = "수락 승인 카드가 열려 있어요. 그 카드를 확인하고 눌러 주세요."
PLAN = "날짜별 작업은 카드에서 볼 수 있어요."  # 카드 위 한 줄이 '확정 공정표예요.'

# 공사 날짜 바꾸기(날짜 바꾸기 요청 승인 카드)
CHANGE_NONE = "아직 날짜를 바꿀 공사가 없어요. 업체가 공사 날짜를 올리면 바꾸기를 요청할 수 있어요."
CHANGE_HOW = (
    "공사 날짜는 날짜 바꾸기 요청으로 바꿔요. '2주 미뤄 주세요'처럼 말해 주시면 요청 승인 카드를 만들어 드릴게요. "
    "업체가 새 날짜를 올리고 수락하기 전까지 지금 날짜는 그대로예요."
)
CHANGE_MADE = "날짜 바꾸기 요청 승인 카드를 만들었어요. 카드를 확인하고 눌러야 업체에 요청이 가요."
CHANGE_SAME = "같은 날짜 바꾸기 요청 카드가 이미 있어요. 그 카드를 확인하고 눌러 주세요."
CHANGE_REJECTED = "앞에서 거절한 날짜 바꾸기 요청과 같아요. 다른 날짜를 말해 주시면 새로 만들어요."
CHANGE_HOW_EARLY = "공사 날짜는 업체를 확정한 뒤 업체가 올려요. 그 뒤에 바꿔야 하면 날짜 바꾸기 요청으로 새 날짜를 부탁할 수 있어요."
STANDARD = "이 집 표준견적서는 부가세 포함 {won}원이에요. 공공 기준 단가로 믿집이 계산한 참고 금액이고 업체 견적은 아니에요."
STANDARD_DAYS = "이 집 표준견적서로는 {who} 예상 {days}일이에요. 업체 공사 기간은 실측 견적서에서 확인해 주세요."
STANDARD_NO_TOTAL = (
    "공공 기준 단가로 믿집이 계산한 표준견적서예요. 업체 견적이 아니라 참고 금액이에요."
)
TODAY = "오늘 정할 일이에요."
TODAY_NONE = "오늘 정할 일은 없어요. 기다리는 일은 카드에서 볼 수 있어요."
HOME = "집 정보예요. 고칠 칸이 있으면 말해 주세요."
OTHER_TRADE = "아직 도배 업체만 연결돼요. 다른 공사는 궁금한 점까지 도와드려요."
MEMORY_GUIDE = (
    "비서가 기억한 것은 내 정보 → 비서가 기억한 것에서 보고 지울 수 있어요. "
    "지우면 다음 대화부터 쓰지 않아요."
)
# '기억해: 내 예산은 …'(기억은 코드가 고객 말에서 따로 골라 저장하고 금액 · 건강 · 연락처는 버린다. 약속하지 않는다)
MEMORY_SAY = (
    "예산 같은 금액 · 건강 · 연락처는 비서가 기억하지 않아요. "
    "공사 금액은 표준견적서와 견적서 카드에서 확인해 주세요."
)
SMALL_TALK_HI = "안녕하세요. 공사에서 궁금한 게 있으면 물어봐 주세요."
SMALL_TALK = "네, 궁금한 게 생기면 언제든 물어봐 주세요."
LEGAL = (
    "내용증명 · 소송 같은 법률 문제는 믿집이 판단하거나 대신 써 드리지 않아요. "
    "소비자상담센터나 법률 상담을 받아 보세요."
)
PREFS = "알려 주셔서 고마워요. 실측 시간을 고르거나 업체에 요청할 때 이 조건을 같이 봐 주세요."
# 업체
NO_VISIT = "어느 요청인지 몰라요. 요청을 열고 다시 말해 주세요."
DECLINED = "못 받아요 승인 카드를 만들었어요. 카드에서 눌러야 고객에게 알려져요."
DECLINE_REJECTED = (
    "앞에서 거절한 못 받아요 카드와 같아요. 다시 하려면 요청 카드의 단추로 직접 골라 주세요."
)
WINDOW = "답하기 좋은 기간으로 승인 카드를 만들었어요. 카드에서 눌러야 고객에게 보내져요."
WINDOW_REJECTED = "앞에서 거절한 기간 답하기 카드와 같아요. 다른 기간은 요청 카드에서 골라 주세요."
NO_WINDOW = "지금은 이 요청에 바로 답할 빈 기간을 찾지 못했어요. 요청 화면에서 기간을 골라 주세요."
# 공정 · 지역이 맞지 않는 요청: 기간 답하기 카드를 만들지 않는다({what}은 '지역이' 꼴)
NO_FIT = "{what} 우리 업체와 맞지 않아 기간 답하기 카드는 만들지 않았어요. 받기 어려우면 못 받아요로 답해 주세요."
ANSWERED = "이미 답했거나 닫힌 요청이에요. 진행은 요청 화면에서 볼 수 있어요."
CHECKLIST = "견적서를 낼 때 확인할 것이에요. 낼 금액 · 부가세 방식 · 공사 기간 · 유효기간은 칸에 적어 주세요."
VENDOR_TODAY = "오늘 할 일이에요."
BRIEF = "요청 브리핑이에요. 맞는 조건과 답할 기간을 카드에서 확인해 주세요."
ACCEPT_RULE = (
    "공사 날짜는 업체가 올리고 고객이 수락해야 확정돼요. 수락 전에는 비서도 대신 확정할 수 없어요."
)

# 보던 카드 · 공사 단계 → v3 화면 이름(answer_only view)
CARD_VIEW = {
    "home": "home", "standard": "standard", "picks": "vendors", "wish": "visit_request",
    "slots": "pick", "compare": "quotes", "dates": "schedule", "plan": "plan",
}  # fmt: skip
PHASE_VIEW = {"estimate": "vendors", "progress": "visits", "work": "schedule", "done": "plan"}
# '몰딩 교체는 언제 해요?'처럼 공종 일을 언제 하는지 물으면 공사 순서 질문이다. 무료 모드 낱말 검색이 순서 자료를
# 찾도록 answer_only에 보내는 글 끝에 '순서'를 붙인다(대화에 남기는 글은 그대로)
WHEN_WORK = re.compile(
    r"언제\s*(?:해|하|바꿔|바꾸|교체|시공|들어가|진행|붙)|(?:먼저|나중에?)\s*(?:해|하)"
)
SENT = re.compile(r"(?<=[.!?。])\s+|\n+")
HELLO = re.compile(r"안녕|처음\s*뵙|반가워")
# 기억해 달라는 말('기억해: …' · '… 기억해 줘')
MEMORY_SAY_RX = re.compile(
    r"^\s*기억(?:해|하세요|해\s*줘|해\s*둬|해\s*두세요)\s*[:：,.]?|기억해\s*(?:줘|주세요|둬|두세요)"
)
LEGAL_RX = re.compile(r"내용증명|소송|고소|변호사|손해배상\s*청구|법적으로\s*(?:어떻게|대응|문제)")


def prefs_said(text: str) -> bool:
    """조건 · 사정(요일 · 반려동물 · 사는 방식 …)을 알려 준 말이고 묻는 말이 아닌지."""
    from app.assistant import memory

    return bool(memory.CUE.search(text) and not QUESTION.search(text) and not ASK_WORD.search(text))


def not_kept(text: str) -> bool:
    """기억으로 남기지 않는 말(금액 · 건강 · 연락처, memory.validate가 버리는 것)이 들었는지."""
    from app.assistant import memory

    return bool(
        memory.MONEY.search(text) or memory.HEALTH.search(text) or memory.CONTACT.search(text)
    )


# 비서가 기억한 것을 어디서 보고 지우는지 묻는 말(기억해 달라는 말은 아님): 정해 둔 안내로 답한다
MEMORY_WHERE = re.compile(
    r"기억(?:한|하는|해\s{0,2}둔|하고\s{0,2}있는|된)\s{0,2}(?:거|것|건|걸|내용|정보|목록)?.{0,15}?"
    r"(?:어디|지우|지울|지워|삭제|없애|보여|볼\s{0,2}수|보고|봐|확인)"
    r"|(?:어디|어떻게).{0,15}?기억(?:한|하는|된)"
)


def intent_of(text: str, surface: str) -> str | None:
    for name, rx in CUSTOMER if surface == "customer" else VENDOR:
        if rx.search(text or ""):
            return name
    return None


# 고객 의도: 학습한 비서 의도 모델(intent_v4) 라벨 → handler. dev로 고른 길은 '모델만'이에요
# (규칙만 · 규칙 먼저 + 모델보다 카드 정답률이 높았어요, docs/v4/eval/intent.md 7절). 모델 파일이 없으면 낱말 규칙.
# guide는 오늘 할 일을 물을 때(낱말 규칙 today)만 _today, 그 밖(인사 · 서비스 안내)은 answer_only 글 + today 카드.
# 지식 · 범위 밖은 카드 없이 answer_only로 답해요.
LABEL_DO: dict[str, str] = {
    "home_info": "home", "standard_quote": "standard", "vendor_pick": "vendors", "visit": "slots",
    "quote_compare": "compare", "schedule": "schedule",
}  # fmt: skip
# 바람 · 진술 뒤에 순서 · 시기 · 방법을 묻는 말은 지식이에요(라벨 규칙 10: 배경 뒤 묻는 말이면 묻는 쪽).
# 모델이 이 꼴을 집 정보 · 표준견적서로 보는 일이 있어서, 낱말 규칙이 없고 이 꼴이면 지식 답으로 내려요
# (어려운 예 재학습보다 dev에서 나았어요, intent.md 8절). 돈 · 기간을 묻는 말은 표준견적서 그대로예요
HOW_LABELS = ("home_info", "standard_quote", "quote_compare")
MONEY_DAYS = re.compile(r"얼마|비용|금액|가격|시세|평당|단가|예산|며칠|몇\s*일|기간")
# 묻는 낱말(언제 · 어떻게 · 순서 …)은 그대로, 때 낱말(전에 · 후에 · 먼저 …)은 묻는 꼴 문장에서만 세요
ASK_WORD = re.compile(
    r"언제|어떻게|어떡|순서|뭐부터|무엇부터|뭘\s{0,2}먼저|뭐가\s{0,2}먼저|"
    r"해야\s{0,2}(?:하나요|하죠|할까요|되나요|될까요)|해도\s{0,2}(?:되나요|될까요|괜찮)"
)
ASK_TIME = re.compile(r"전에|후에|뒤에|다음에|먼저|나중")
QUESTION = re.compile(r"\?|나요|까요|가요|죠|는지|ㄹ지|할지|되요|돼요|해요\s{0,2}\?")
# '살면서 도배할 수 있어요?'처럼 되는지 묻는 말(고칠 · 바꿀 칸을 말하면 집 정보 카드 그대로)
CAN_ASK = re.compile(r"(?:할|될)\s*수\s*(?:있|없)")
EDIT_WORD = re.compile(r"고치|고칠|고쳐|바꾸|바꿀|바꿔|수정|입력|넣|저장")


def asks_how(text: str) -> bool:
    """순서 · 시기 · 방법 · 되는지를 묻는 말인지(돈 · 기간을 묻는 말은 빼요)."""
    t = text or ""
    if MONEY_DAYS.search(t):
        return False
    if CAN_ASK.search(t) and QUESTION.search(t) and not EDIT_WORD.search(t):
        return True
    return bool(ASK_WORD.search(t) or (ASK_TIME.search(t) and QUESTION.search(t)))


def customer_intent(text: str) -> tuple[str | None, str | None]:
    """고객 말 → (handler 이름, 지식 답에 붙일 단계 카드 길). 단계 카드 길: 'gate'(입구 관문 길) · 'guide'(오늘 할 일
    카드) · None(카드 없음)."""
    from app.assistant import intent_v4

    g = intent_v4.predict(text)
    rule = intent_of(text, "customer")
    if g is None:
        return rule, "gate"
    if g.label == "guide":
        return ("today", None) if rule == "today" else (None, "guide")
    if g.label in HOW_LABELS and rule is None and asks_how(text):
        return None, None  # 순서 · 시기 · 방법 질문: 카드 없이 지식 답
    return LABEL_DO.get(g.label), None


def trades_in(text: str) -> list[str]:
    from app.agent.v3 import trades

    return list(trades.trades_in(text or ""))


async def vendor_names(tc: ToolCtx) -> list[str]:
    """이 대화 · 공사에 나온 업체 이름(긴 것부터): 대화 이름표 표의 업체 · 이 공사의 실측 요청 · 확정 · 담은 업체.
    공종 낱말을 찾기 전에 뺀다('마루와벽으로 확정할게요'의 '마루'는 바닥 공사가 아니에요). 읽기 조인만 한다."""
    from sqlalchemy import select

    from app.schedule.models import Deal
    from app.vendor.models import Vendor
    from app.visit.models import Shortlist, Visit

    names = {
        str(it[k]) for it in tc.refs.items.values() for k in ("name", "vendor_name") if it.get(k)
    }
    pid = tc.project_id
    if pid is not None:
        async with SessionLocal() as s:
            names.update(await s.scalars(select(Visit.vendor_name).where(Visit.project_id == pid)))
            names.update(await s.scalars(select(Deal.vendor_name).where(Deal.project_id == pid)))
            names.update(
                await s.scalars(
                    select(Vendor.biz_name)
                    .join(Shortlist, Shortlist.vendor_id == Vendor.user_id)
                    .where(Shortlist.project_id == pid, Vendor.biz_name.is_not(None))
                )
            )
    return sorted((n for n in names if n and len(n.strip()) >= 2), key=len, reverse=True)


def without_names(text: str, names: list[str]) -> str:
    """업체 이름(붙여 쓴 꼴도)을 빈칸으로 바꾼다."""
    for n in names:
        for w in dict.fromkeys((n.strip(), n.replace(" ", ""))):
            if len(w) >= 2:
                text = text.replace(w, " ")
    return text


# ---- 고객 ----


async def _vendors(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut]:
    async with SessionLocal() as s:
        card, model = await cards.vendor_picks(s, tc.user, tc.project_id, "dobae", tc.refs)  # type: ignore[arg-type]
    if not model["picks"]:
        return NO_PICKS, ToolOut(data={})
    return PICKS.format(area=model["area"], n=model["count"]), ToolOut(data={}, cards=[card])


async def _slots(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut]:
    """업체가 답한 요청이 있으면 반나절 후보, 요청 중이면 작업 카드, 요청 전이면 첫 추천 업체로 희망 기간 후보."""
    from app.assistant import memory
    from app.assistant import repository as repo
    from app.schedule import service as schedule_service

    pid = tc.project_id
    async with SessionLocal() as s:
        prefer, days = memory.prefs(await repo.memories(s, tc.user.id))
        o = await schedule_service.overview_for(s, tc.user, pid, tc.today)  # type: ignore[arg-type]
        pickable = [v for v in o.vendors if v.status in ("offered", "proposed")]
        got: list[CardOut] = []
        for v in pickable[:2]:
            card, model = await cards.visit_slots(
                s,
                tc.user,
                pid,
                v.visit_id,
                tc.now,
                tc.refs,
                prefer=prefer,
                days=days,
            )
            if model["candidates"]:
                got.append(card)
        if got:
            return HALVES, ToolOut(data={}, cards=got)
        live = {v.status for v in o.vendors if v.status not in cards.ENDED}
        if live:
            task = cards.visit_task(pid, o, tc.now)  # type: ignore[arg-type]
            return visits_text(live), ToolOut(data={}, task=task)
        picks, pm = await cards.vendor_picks(s, tc.user, pid, "dobae", tc.refs)  # type: ignore[arg-type]
        if not pm["picks"]:
            return NO_PICKS, ToolOut(data={})
        first = pm["picks"][0]["ref"]
        vend = {**tc.refs.get(first, "vendor"), "ref": first}
        wish, wm = await cards.wishes(
            s,
            tc.user,
            pid,
            vend,
            tc.today,
            tc.refs,
            prefer=prefer,
            days=days,
        )
    if not wm["wishes"]:
        return NO_WISHES, ToolOut(data={}, cards=[picks])
    return WISHES, ToolOut(data={}, cards=[picks, wish])


def visits_text(live: set[str]) -> str:
    """진행 중인 실측 요청 상태 → 단계에 맞는 글(견적서가 온 뒤에 '기간을 답하면 …'이라고 하지 않는다)."""
    if live & {"requested", "offered", "proposed"}:
        return VISITS
    if "picked" in live:
        return VISITS_WAIT
    if "booked" in live:
        return VISITS_BOOKED
    return VISITS_DONE


async def _confirmed(s, tc: ToolCtx, trade: str) -> dict | None:
    """그 공정에서 확정한 업체 · 견적서 판(확정 때 고정한 판, schedule service 값). 없으면 None."""
    from app.schedule import service as schedule_service

    sch = await schedule_service.schedule_for(s, tc.user, tc.project_id, tc.today)  # type: ignore[arg-type]
    d = next((t.deal for t in sch.trades if t.deal.trade == trade), None)
    return {"vendor": d.vendor_name, "version": d.quote.version} if d is not None else None


async def _compare(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut]:
    pid = tc.project_id
    async with SessionLocal() as s:
        card, model = await cards.compare(s, tc.user, pid, "dobae", tc.today, tc.refs)  # type: ignore[arg-type]
        task = await cards.visit_task_for(s, tc.user, pid, tc.today, tc.now)  # type: ignore[arg-type]
        chosen = any(c.get("status") == "chosen" for c in model["cols"])
        done = await _confirmed(s, tc, "dobae") if chosen else None
    n = sum(1 for c in model["cols"] if c.get("version"))
    if done is not None:  # 확정한 뒤: 확정 단추 대신 확정한 업체 · 견적서 판을 말한다
        return CONFIRMED.format(**done), ToolOut(data={}, cards=[card] if n else [], task=task)
    if not n:
        return NO_QUOTES, ToolOut(data={}, task=task)
    return QUOTES, ToolOut(data={}, cards=[card], task=task)


async def _schedule(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut]:
    async with SessionLocal() as s:
        card, _ = await cards.schedule(s, tc.user, tc.project_id, tc.today, tc.refs)  # type: ignore[arg-type]
    if card is None:
        return NO_DATES, ToolOut(data={})
    if card.data["phase"] != "dates":
        return PLAN, ToolOut(data={}, cards=[card])
    # 수락 승인 카드가 열려 있으면 카드 단추가 비어 있다(수락 단추는 승인 카드 하나). 카드 위 한 줄은 되풀이하지 않는다
    text = DATES_OPEN if card.data.get("action_id") else DATES
    return text, ToolOut(data={}, cards=[card])


DAYS_ASK = re.compile(r"며칠|몇\s*일|기간|얼마나\s*걸|오래\s*걸")


async def _standard(tc: ToolCtx, text: str, found: list[str]) -> tuple[str, ToolOut] | None:
    """표준견적서 카드. 목공만 물었는데 이 공사 표준견적서에 목공이 없으면 None(지식 답으로)."""
    trade = "mokgong" if found == ["mokgong"] else "dobae"
    async with SessionLocal() as s:
        card, model = await cards.standard(s, tc.user, tc.project_id, trade)  # type: ignore[arg-type]
    if trade == "mokgong" and not any(x.get("trade") == "mokgong" for x in model["lines"]):
        return None
    total = model.get("total")
    days = model.get("days")
    if DAYS_ASK.search(text) and days:  # 며칠 걸려요? → 금액이 아니라 예상 일수(공정 모두의 합)
        tr = model.get("days_for") or []
        who = (
            f"{tr[0]} 공사가"
            if len(tr) == 1
            else f"{' · '.join(tr)} 공사를 합쳐"
            if tr
            else "공사가"
        )
        said = STANDARD_DAYS.format(who=who, days=f"{Decimal(str(days)).normalize():f}")
        return said, ToolOut(data={}, cards=[card])
    text = STANDARD.format(won=f"{total:,}") if isinstance(total, int) else STANDARD_NO_TOTAL
    return text, ToolOut(data={}, cards=[card])


async def _today(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut]:
    pid = tc.project_id
    async with SessionLocal() as s:
        card, model = await cards.today(s, tc.user, pid, tc.today, tc.now, tc.refs)  # type: ignore[arg-type]
        task = await cards.visit_task_for(s, tc.user, pid, tc.today, tc.now)  # type: ignore[arg-type]
    return (TODAY if model["count"] else TODAY_NONE), ToolOut(data={}, cards=[card], task=task)


async def _home(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut] | None:
    """집 정보 카드. 실측을 요청해 집 정보가 잠긴 공사는 고칠 수 없어서 카드를 다시 띄우지 않는다(None → 답만)."""
    async with SessionLocal() as s:
        card, model = await cards.home(s, tc.user, tc.project_id)  # type: ignore[arg-type]
    if model["locked"]:
        return None
    return HOME, ToolOut(data={}, cards=[card])


# 공사 날짜를 바꾸고 싶다는 말(미루기 · 연기 · 늦추기 · 날짜 바꾸기 · 옮기기 · 당기기)
CHANGE = re.compile(
    r"미루|미뤄|미룰|늦추|늦춰|연기\s*(?:하|해|할|요청|돼|되)|"
    r"(?:날짜|일정)\S{0,2}\s{0,2}(?:바꾸|바꿔|바꿀|옮기|옮겨|옮길|당기|당겨|당길)"
)
# 바라는 말이 있어야 카드를 만든다. 없으면('미루면 어떻게 돼요?') 안내만 한다
CHANGE_WANT = re.compile(
    r"싶|원해|주세요|주실|줄\s*수|줄래|줘요|해\s*줘|려고|(?:룰|출|꿀|길|할)\s*(?:게|래)|"
    r"(?:미뤄|늦춰|바꿔|옮겨|당겨)\s*(?:주|줘|야(?!\s*(?:하면|되면|한다면)))"
)
# 고객의 날짜 바꾸기 요청이 아닌 말: 실측 날짜 · 업체가 낸 날짜에 답하기(수락 · 승인) · 업체가 미루자는 말
NOT_CHANGE = re.compile(r"실측|방문|수락|승인|받아들|업체\s*(?:가|에서|쪽)|자는|자고|대요")
MONTH_DAY = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
N_WEEKS = re.compile(r"(\d{1,2})\s*주")
N_DAYS = re.compile(r"(\d{1,3})\s*일\s*(?:정도|쯤|만|가량)?\s*(?:미루|미뤄|늦|뒤)")
WORD_DELAY = (
    (re.compile(r"한\s*달"), 30), (re.compile(r"보름"), 15), (re.compile(r"(?:두|이)\s*주"), 14),
    (re.compile(r"일주일|한\s*주"), 7), (re.compile(r"사흘"), 3), (re.compile(r"이틀"), 2),
    (re.compile(r"하루"), 1),
)  # fmt: skip
CHANGE_REASON_WORDS = (
    ("move", re.compile(r"이사|이삿|입주")),
    ("other_work", re.compile(r"다른\s*공사|목공|바닥|욕실|전기|타일|샷시|창호")),
    ("family", re.compile(r"집안|가족|사정|출장|여행|아이|병원|일이\s*생")),
)
DEFAULT_DELAY = 7  # 바라는 때를 말하지 않으면 일주일 뒤부터(카드에서 고객이 확인한다)


def change_wish(text: str, today: date) -> tuple[int | None, date | None]:
    """말 → (미룰 날 수, 시작해도 되는 첫날) 중 하나. 'M월 D일'은 오늘 뒤 가장 가까운 그날, 'n주' · 'n일' · 일주일 ·
    한 달 …은 날 수, 없으면 일주일."""
    m = MONTH_DAY.search(text)
    if m:
        try:
            got = date(today.year, int(m[1]), int(m[2]))
            return None, got if got > today else date(today.year + 1, got.month, got.day)
        except ValueError:
            pass
    m = N_WEEKS.search(text)
    if m and 1 <= int(m[1]) <= 25:
        return int(m[1]) * 7, None
    m = N_DAYS.search(text)
    if m and 1 <= int(m[1]) <= 180:
        return int(m[1]), None
    return next((n for rx, n in WORD_DELAY if rx.search(text)), DEFAULT_DELAY), None


def change_reason(text: str) -> str:
    return next((code for code, rx in CHANGE_REASON_WORDS if rx.search(text)), "other")


async def _change(tc: ToolCtx, text: str, found: list[str]) -> tuple[str, ToolOut]:
    """공사 날짜를 바꾸고 싶다는 말 → 날짜 바꾸기 요청 승인 카드(propose_date_change) + 공사 날짜 카드. 바라는 말이
    없으면 안내 글과 카드만. 바꿀 수 있는 확정(수락한 날짜 · 업체가 낸 날짜)이 없으면 그렇게 말한다."""
    from app.assistant.tools import propose

    async with SessionLocal() as s:
        card, model = await cards.schedule(s, tc.user, tc.project_id, tc.today, tc.refs)  # type: ignore[arg-type]
    out = ToolOut(data={}, cards=[card] if card is not None else [])
    deals = [
        d
        for d in model["deals"]
        if (d["status"] == "scheduled" and d.get("start_date"))
        or (d["status"] == "confirmed" and d.get("proposal"))
    ]
    # 묻는 말 · 가정: 안내만(업체가 날짜를 올리기 전이면 그 순서부터)
    if not CHANGE_WANT.search(text):
        return (CHANGE_HOW if deals else CHANGE_HOW_EARLY), out
    if not deals:
        return CHANGE_NONE, out
    d = next(
        (x for x in deals if x["trade"] in found),
        next((x for x in deals if x["trade"] == "dobae"), deals[0]),
    )
    delay, wish = change_wish(text, tc.today)
    try:
        got = await propose.propose_date_change(
            tc,
            propose.DateChangeIn(
                deal_ref=d["ref"],
                reason=change_reason(text),  # type: ignore[arg-type]
                delay_days=delay,
                wish_from=wish,
            ),
        )
    except ToolError as e:
        return e.message, out
    out.actions += got.actions
    out.closed += got.closed
    said = {"new": CHANGE_MADE, "same": CHANGE_SAME, "rejected": CHANGE_REJECTED}
    return said.get(str(got.data.get("state")), CHANGE_NONE), out


CUSTOMER_DO: dict[str, Handler] = {
    "vendors": _vendors, "slots": _slots, "compare": _compare, "schedule": _schedule,
    "standard": _standard, "today": _today, "home": _home,
}  # fmt: skip
# 글이 말하는 카드 → 그 카드를 만드는 길(fit_cards)
MENTION: tuple[tuple[str, re.Pattern[str], Handler], ...] = (
    ("visit_slots", re.compile(
        r"희망\s*기간|실측\s*(?:날짜|시간|일정|희망)|반나절\s*후보|날짜\s*후보|시간\s*후보"
    ), _slots),
    ("vendor_picks", re.compile(r"업체\s*\d\s*곳|추천\s*업체|맞는\s*업체|업체를?\s*골라\s*봤"), _vendors),
    ("quote_compare", re.compile(r"견적서\s*(?:비교|견줘|견주)|받은\s*(?:실측\s*)?견적서"), _compare),
    ("schedule", re.compile(r"공정표|공사\s*날짜"), _schedule),
    ("standard_quote", re.compile(r"표준\s*견적서"), _standard),
)  # fmt: skip


async def fit_cards(tc: ToolCtx, text: str, out: ToolOut) -> str:
    """글이 말하는 카드가 이 턴에 없으면 만들어 out에 더하고, 못 만들면 그 문장을 뺀다. 남은 글을 돌려준다."""
    if tc.project_id is None or not text:
        return text
    have = {c.kind for c in out.cards}
    tried: dict[str, bool] = {}
    kept: list[str] = []
    for sent in (x.strip() for x in SENT.split(text) if x.strip()):
        ok = True
        for kind, rx, make in MENTION:
            if not rx.search(sent) or kind in have:
                continue
            if kind not in tried:
                try:
                    got = await make(tc, "", [])
                except (ToolError, AppError):
                    got = None
                new = [c for c in (got[1].cards if got else []) if c.kind not in have]
                out.cards.extend(new)
                have |= {c.kind for c in new}
                if got is not None and got[1].task is not None and out.task is None:
                    out.task = got[1].task
                tried[kind] = kind in have
            ok = ok and tried[kind]
        if ok:
            kept.append(sent)
    return " ".join(kept)


async def view_for(tc: ToolCtx, card_id: str | None) -> str | None:
    """answer_only에 넘길 화면: 보던 카드가 있으면 그 화면, 없으면 공사 단계(공사 요약 phase)에 맞는 화면."""
    from app.schedule import service as schedule_service

    if card_id:
        got = CARD_VIEW.get(card_id.split("-", 1)[0])
        if got:
            return got
    if tc.project_id is None:
        return None
    try:
        async with SessionLocal() as s:
            o = await schedule_service.overview_for(s, tc.user, tc.project_id, tc.today)
    except AppError:
        return None
    return PHASE_VIEW.get(o.phase)


async def _knowledge(
    tc: ToolCtx, text: str, found: list[str], card_id: str | None, step: str | None = "gate"
) -> tuple[str, ToolOut]:
    """지식 · 공통 질문: 단계 카드 + answer_only(공사 단계 화면, 목공만 물으면 목공 담당).
    step: 'gate'면 입구 관문 길의 단계 카드, 길 이름(guide …)이면 그 길의 카드, None이면 카드 없음."""
    from app.agent.v3 import gate as gate_mod
    from app.agent.v3.schemas import Button
    from app.chat import service as chat_service

    out = ToolOut(data={})
    if tc.surface == "customer" and step is not None:
        route = (
            gate_mod.gate(text, has_project=tc.project_id is not None).route
            if step == "gate"
            else step
        )
        card = await cards.step_card(tc, route)
        if card is not None:
            out.cards.append(card)
    button = Button(route="trade", trade="mokgong") if found == ["mokgong"] else None
    view = await view_for(tc, card_id) if tc.surface == "customer" else None
    query = f"{text} 순서" if found and WHEN_WORK.search(text) else text
    try:
        ans = await chat_service.answer_only(
            tc.user,
            query,
            tc.today,
            project_id=tc.project_id if tc.surface == "customer" else None,
            mode="free",
            view=view,
            button=button,
        )
        said = ans.text
    except AppError:
        said = ""
    return said, out


# ---- 업체 ----


async def _brief(tc: ToolCtx, *, propose_window: bool) -> tuple[CardOut, dict, ToolOut]:
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        card, model, _data, made, closed = await vendor_tools.brief(
            s,
            tc.user,
            tc.visit_id,  # type: ignore[arg-type]
            tc.today,
            tc.now,
            tc.refs,
            tc.turn_id,
            propose_window=propose_window,
        )
    live = [a for a in made if a.status == "proposed"]
    # 업체가 거절한 같은 기간 제안이면 다시 만들지 않았다(actions.offer): 모델 값에 표시만 남긴다
    data = {"rejected": True} if any(a.status == "rejected" for a in made) else {}
    return card, model, ToolOut(data=data, cards=[card], actions=live, closed=closed)


async def _vendor(tc: ToolCtx, text: str, intent: str | None) -> tuple[str, ToolOut] | None:
    """업체 의도 → 카드 · 제안 하나. 의도가 없으면 None(브리핑 + 지식 답)."""
    from app.assistant.tools import propose
    from app.assistant.tools import vendor as vendor_tools

    if intent == "today":
        async with SessionLocal() as s:  # 공사 날짜 줄 단추(dates:d#,n#)의 이름표는 이 턴의 표에
            rows = (await vendor_tools.vendor_today(s, tc.user, tc.today, tc.refs)).rows
        data = TodayData(date=tc.today, todo=rows, waiting=[], news=[])
        card = CardOut(card_id="today", kind="today", data=data.model_dump(mode="json"))
        return VENDOR_TODAY, ToolOut(data={}, cards=[card])
    # '고객이 아직 수락 안 했는데 …'는 기간 답하기가 아니다
    if intent == "window" and NOT_ACCEPT.search(text):
        out = (await _brief(tc, propose_window=False))[2] if tc.visit_id else ToolOut(data={})
        return ACCEPT_RULE, out
    if intent is None:
        return None
    if intent == "brief" and tc.visit_id is None:  # 보던 요청이 없으면 새 요청이 든 오늘 할 일
        return await _vendor(tc, text, "today")
    if tc.visit_id is None:
        return NO_VISIT, ToolOut(data={})
    if intent == "brief":
        _card, _model, out = await _brief(tc, propose_window=False)
        return BRIEF, out
    if intent == "checklist":
        async with SessionLocal() as s:
            card, *_ = await vendor_tools.checklist(s, tc.user, tc.visit_id, tc.today, tc.refs)
        return CHECKLIST, ToolOut(data={}, cards=[card])
    if intent == "window":
        _card, model, out = await _brief(tc, propose_window=True)
        if model["status"] != "requested":
            return ANSWERED, out
        if model["misfit"]:  # 공정 · 지역이 맞지 않음: 까닭만(못 받아요는 업체가 고른다)
            from app.shared.korean import i_ga

            return NO_FIT.format(what=i_ga(model["misfit"])), out
        if not out.actions and out.data.pop("rejected", False):
            return WINDOW_REJECTED, out
        return (WINDOW if out.actions else NO_WINDOW), out
    # decline: 브리핑(새 기간 제안 없이) + 못 받아요 제안 하나(같은 대상의 열린 제안은 이것으로 바뀐다)
    _card, model, out = await _brief(tc, propose_window=False)
    code = next((c for c, rx in DECLINE_CODE if rx.search(text)), "other")
    try:
        got = await propose.propose_decline(
            tc,
            propose.DeclineIn(visit_ref=model["ref"], code=code),  # type: ignore[arg-type]
        )
    except ToolError as e:
        return e.message, out
    out.actions += got.actions
    out.closed += got.closed
    if not got.actions:  # 거절한 같은 못 받아요 제안: 다시 만들지 않았다
        return DECLINE_REJECTED, out
    return DECLINED, out


# ---- 한 턴 ----


async def answer(tc: ToolCtx, text: str, card_id: str | None) -> tuple[str, ToolOut]:
    """무료 모드 답 한 번(글, 카드 · 행동 · 작업 카드). 글이 비면 부르는 쪽이 실패 문구를 쓴다."""
    if policy.small_talk(text) or policy.ack(text):  # 인사 · 맞장구만: 카드 · 지식 답 없이 한 문장
        return (SMALL_TALK_HI if HELLO.search(text) else SMALL_TALK), ToolOut(data={})
    if tc.surface == "vendor":
        got = await _vendor(tc, text, intent_of(text, "vendor"))
        if got is not None:
            return got
        said, out = await _knowledge(tc, text, trades_in(text), card_id)
        if tc.visit_id is not None:
            _card, _model, brief_out = await _brief(tc, propose_window=False)
            out.cards = [*brief_out.cards, *out.cards]
        return said, out
    if MEMORY_WHERE.search(text):
        return MEMORY_GUIDE, ToolOut(data={})
    if (more := await aftercare_tools.free_answer(tc, text)) is not None:  # 07 자동화 카드
        return more
    if MEMORY_SAY_RX.search(text) and not_kept(text):  # '기억해: 내 예산은 …' → 기억하지 않는 것
        return MEMORY_SAY, ToolOut(data={})
    if LEGAL_RX.search(text):  # 내용증명 · 소송: 법률 판단은 하지 않는다
        return LEGAL, ToolOut(data={})
    if (more := await diy_tools.free_answer(tc, text)) is not None:  # 반셀프 직접 할 일 카드
        return more
    # 업체 이름을 뺀 뒤 공종을 찾는다(업체 이름 속 '마루' · '목공'은 공종 말이 아니에요)
    found = trades_in(without_names(text, await vendor_names(tc)))
    if tc.project_id is None:
        return await _knowledge(tc, text, found, card_id)
    if CHANGE.search(text) and not NOT_CHANGE.search(text):  # 공사 날짜 바꾸기 요청 승인 카드로
        return await _change(tc, text, found)
    intent, step = customer_intent(text)
    if intent in LINKED and found and "dobae" not in found:  # 업체 연결은 아직 도배만
        said = policy.DOBAE_ONLY if "mokgong" in found else OTHER_TRADE
        _, out = await _today(tc, text, found)
        return f"{said} 도배 쪽 오늘 할 일을 보여 드릴게요.", out
    # 조건 · 사정을 알려 준 말('주말에만 시간이 되고 강아지가 있어요'): 고마움 + 오늘 할 일
    if intent is None and step == "guide" and prefs_said(text):
        _, out = await _today(tc, text, found)
        return PREFS, out
    handler = CUSTOMER_DO.get(intent or "")
    got = await handler(tc, text, found) if handler is not None else None
    if got is not None:
        return got
    # handler가 카드를 못 만들면: 잠긴 집 정보(home)는 카드 없이 답만, 그 밖(목공 표준견적서 없음 등)은
    # 지금처럼 입구 관문 길의 단계 카드
    if handler is not None:
        step = None if intent == "home" else "gate"
    said, out = await _knowledge(tc, text, found, card_id, step)
    return await fit_cards(tc, said, out), out
