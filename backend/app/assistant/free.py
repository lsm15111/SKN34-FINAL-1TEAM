"""무료 모드 코드 길잡이 (계약서 4장 9, 2026-11-21 보강). 키 없음 · 상한 · 차단기일 때 LLM 없이
말 → 의도(고객: 학습한 의도 모델 intent_v4, 업체: 낱말 규칙) → 도구 함수(카드) → 정해 둔 글로 답한다.

- 고객: 업체 추천 → vendor_picks · 실측 시간 → visit_slots(요청 전 희망 기간, 업체 답 뒤 반나절) · 견적서 비교 ·
  공정표 · 표준견적서 · 오늘 할 일 · 집 정보. 그 밖(지식 · 공통)은 answer_only로 답하고 공사 단계 · 보던 카드에 맞는
  화면(view)을 넘긴다. 목공만 물으면 목공 담당(button)으로 보낸다.
- 업체: 못 받아요 → decline 제안 하나 · 기간 답하기 → window_answer 제안 하나(같은 대상에 열린 제안이 있으면 그것,
  actions.propose) · 견적서 체크리스트 · 오늘 할 일. 그 밖은 요청 브리핑(새 제안 없음) + answer_only.
- 업체 연결(추천 · 실측 · 견적 비교 · 확정)은 아직 도배만이다. 목공으로 물으면 policy.DOBAE_ONLY, 다른 공사(바닥 ·
  욕실 · 전기 …)로 물으면 범위 밖 답 틀(trade)로 말하고 도배 쪽 오늘 할 일 카드를 보여 준다. 목공 지식 · 표준견적서는
  그대로 답한다. 공종은 이 대화 · 공사에 나온 업체 이름을 뺀 뒤 찾는다('마루와벽'의 '마루'는 바닥이 아니다).
- 비서가 기억한 것을 어디서 보고 지우는지 물으면 정해 둔 안내(내 정보 → 비서가 기억한 것)로 답한다.
- 고객 제안(승인 카드)은 사람이 카드 단추를 누른 턴(choice 'visit_request:v1,v2' …)에 choices.apply가 만든다.
  예외 하나: '공사 미루고 싶어요'처럼 공사 날짜를 바꾸고 싶다는 말은 날짜 바꾸기 요청 승인 카드
  (propose_date_change, 며칠 뒤 · 이날부터는 말에서 코드가 읽고 없으면 일주일 뒤)로 안내한다. 바라는 말이 없으면
  ('미루면 어떻게 돼요?') 안내 글만. 업체가 낸 날짜에 답하는 말 · 업체가 미루자는 말 · 실측 날짜는 여기로 오지 않는다.
- 글이 카드를 말하면 같은 턴에 그 카드가 있어야 한다(fit_cards): 없으면 만들고, 못 만들면 그 문장을 뺀다.
  '믿집 공정표는 …'처럼 일반 규칙을 말한 문장은 카드 말이 아니다.
- 업체를 확정한 뒤 견적 비교를 물으면 확정한 업체 · 견적서 판을 말한다(확정 단추 안내를 하지 않는다).
- 의도 모델 앞에서 거르는 말(guard_of, QA 1차 2026-11-22): 지시문 → 보여 드릴 수 없다 · 연락처 · 동호수 → 주고받지
  않는다 · 영어 답 → 짧은 거절 + 지금 할 일 한 줄 · 내용 없이 화난 말 → 사과 · 범위 밖 부탁(음식 · 배달 / 날씨 · 소식 /
  놀이 · 잡담 / 돈 · 투자 / 다른 앱 일 / 대신 전화) → 범위 밖 답 틀(off_said: 되받기 · 솔직 · 지금 할 일, 피클 표본 8).
  지금 할 일 한 줄은 상태가 바뀌었거나 처음일 때만 붙이고(같은 줄을 잇지 않게), 되받기 머리는 바로 앞 답과 다른 꼴로
  고른다(QA 3차 f1).
- 지난 턴과 글자까지 같은 답이면 짧은 글로 바꾼다(AGAIN, QA 3차 f1x 추가 금액 · 날짜).
- 무료 모드는 LLM을 못 쓸 때 카드 + 짧은 안내를 하는 비상 길이다(docs/v4/08-rules.md). 말투 · 길이를 손보는 사례 규칙은
  더하지 않고, 말로 승인 카드를 만드는 길(날짜 바꾸기 · 업체 못 받아요 · 기간 답하기)의 낱말 규칙만 촘촘히 둔다.
- 정해 둔 길(route_of, 의도 모델 앞): 비서가 낸 칩(runtime.CHIPS · 다음에 물을 말 · 카드 칩)과 같은 뜻의 말은 칩 뜻대로
  간다. 폐기물 · 철거 포함 → 받은 견적서 칸, 비싸요 · 바가지 · 뭐가 빠졌어요 → 계산 사실(받은 견적서끼리 다른 포함 칸,
  없으면 표준견적서에서 금액이 큰 줄 이름) + 견적 비교 · 표준견적서 카드(리드 결정 2, QA 3차 f1), 추가금 → 추가 금액
  승인 길, 가견적 계산 · 실측에서 보는 것 · 공사 순서 → 정해 둔 글, 다른 시간 → 반나절 카드, 공사 전날 준비물 →
  준비물 카드, 반려동물 · 출입 → 정해 둔 글.
- 다른 공정(믿집이 계산 · 연결하지 않는 공정)만 물으면 알아 두기 자료(knowledge.other_trades)로 순서 · 주의점을 답하고
  '믿집은 … 업체를 잇지 않아요'를 붙인다. 도배 · 목공과 섞인 질문은 answer_only 답을 쓰고 모르면 자료로 바꾼다.
- 업체 추천은 실측을 요청한 업체를 빼고 보여 준다(다 요청했으면 작업 카드, 확정했으면 확정한 업체).
- '취소해 줘' · '그 카드 거둬 줘'(_cancel, 피클 표본 7): 열린 승인 카드가 하나면 바로 거두고(실행 전이라 고객 말로
  된다, 거절과 같게 남음), 보낸 실측 요청이면 취소 승인 카드, 여럿이면 고르기 칩 카드. 묻는 말 · 가정은 빼요.
  보낸 요청이 여럿이면 LLM 길과 같은 풀기(propose.cancel_targets: 업체 이름 · '둘 다 · 모두' · '…는 남기고')로 요청마다
  카드, 못 풀면 고르기 칩에 '둘 다 · 모두 취소'(QA r5 D 3).
- '업체 답 오면 알려 줘'(알림 부탁, QA r5 D 2): 업체 추천 · 날짜 바꾸기 앞에서 받아 믿집이 먼저 알리는 일만 약속하고,
  밤(먼저 말 걸기 규칙의 밤 때)이면 아침에 간다는 말을 붙여요. 바로 앞 답과 같은 글이면 짧게.
- 받은 견적서가 없을 때 '빠진 거 없어요?'(QA r5 D 1): 표준견적서에서 합계에 안 들어간 줄(실측 후 · 선택 · 안 함,
  계산 엔진이 저장한 상태)을 말해요. 금액은 말하지 않아요.
"""

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from decimal import Decimal

from app.assistant import policy
from app.assistant.schemas import CardOut, TodayData
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards
from app.assistant.tools import aftercare as aftercare_tools
from app.assistant.tools import diy as diy_tools
from app.db import SessionLocal
from app.shared.clock import SEOUL
from app.shared.errors import AppError
from app.shared.korean import euro, i_ga

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
        r"오늘\s*(?:할|정할|해야|뭐\s*(?:하|해|할))|할\s*일|(?:뭐|뭘)\s*(?:하면|해야|할까)|다음\s*(?:단계|할|은|엔|에)|"
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
# 카드 위 한 줄('{area}에서 이 집 조건에 맞는 곳이에요.')을 되풀이하지 않는다
PICKS = (
    "도배 업체 {n}곳을 믿집 점수로 골랐어요. 카드에서 업체를 고르면 실측 요청 승인 카드를 만들어요."
)
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
# 앞당기기 · '다음 달로'처럼 며칠인지 정할 수 없는 말: 카드 없이 날짜를 묻는다(일주일 뒤로 미루면 반대 · 다른 뜻).
# 예시 날짜는 쓰지 않는다(QA 3차 f1x 15: 앞당기는 말에 지금 시작일보다 늦은 예시 '12월 15일부터')
CHANGE_WHEN = (
    "언제부터로 바꿀지 날짜로 말해 주세요. 그 날짜로 날짜 바꾸기 요청 카드를 만들어 드릴게요."
)
CHANGE_WHEN_PULL = (
    "며칠부터로 당길지 날짜로 말해 주세요. 그 날짜로 날짜 바꾸기 요청 카드를 만들어 드릴게요."
)
CHANGE_WHEN_NEXT = "다음 달 며칠부터로 미룰지 날짜로 말해 주세요. 그 날짜로 날짜 바꾸기 요청 카드를 만들어 드릴게요."
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
OTHER_TRADE = "아직 도배 업체만 연결되고 다른 공사는 궁금한 점까지 도와드려요."
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

# ---- 의도 모델 앞에서 거르는 말(QA 1차 c3 · c4 · c5, 2026-11-22) ----
SECRET_SAID = "그건 보여 드릴 수 없어요."
CONTACT_SAID = "연락처 · 동호수는 제가 주고받지 않아요. 업체와 연락은 믿집 채팅으로 이어져요."
VENDOR_CONTACT = "고객 연락처 · 동호수는 제가 주고받지 않아요. 고객과 연락은 실측이 잡히면 믿집 채팅으로 이어져요."
OFF_SAID = "그건 제가 도와드리기 어려워요. 저는 집 공사만 챙겨요."
# 범위 밖 답 틀(피클 표본 8): 갈래마다 (되받기, 솔직) 셋을 돌려 써요. 답은 되받기 · 솔직 · 지금 할 일 한 줄이에요.
# 자리: t 지금 때(새벽 · 밤 …) · t_meal 음식 앞 때 말('밤 ' · '아침부터 ', 어색한 때는 빈칸) · w 고객 낱말(갈래 표의
# 꼴) · w_i 이/가 · w_eul 을/를 · w_igun 이군요/군요. 그 밖(other)은 되받지 않아요(욕 · 가린 개인정보 · 이상한 글).
# 느낌표는 되받기에 하나만 써요. 되받기 머리 끝 어절은 갈래 안에서 서로 다르고, 앱 일과 대신 전화는 머리가 겹치지
# 않아요(QA 3차 f1: '오전에 택시 부탁이군요!' 뒤 '오전에 전화 부탁이군요!')
OFF_SAYS: dict[str, tuple[tuple[str, str], ...]] = {
    "food": (
        ("오, {t_meal}{w_igun}!", "아쉽지만 배달 주문은 제가 못 하고 집 공사만 챙겨요."),
        ("{t}에 {w} 생각이 나셨군요!", "음식 주문은 제 일이 아니라서 도와드리지 못해요."),
        ("{t}에 {w_eul} 찾으시는군요!", "배달은 제가 시켜 드릴 수 없고 집 공사 일만 맡고 있어요."),
    ),
    # 날씨 · 운세 · 경기처럼 알고 싶은 소식(물은 것을 되받아요. QA 3차 f1: '날씨가 생각나셨군요'가 물은 말과 어긋남)
    "chat": (
        ("{t}에 {w_eul} 물으셨군요!", "그런 소식은 제가 찾아보지 못해서 집 공사 쪽만 도와드려요."),
        ("{w} 이야기군요!", "저는 집 공사 비서라 그 소식은 답해 드리기 어려워요."),
        ("오, {t}에 {w_i} 궁금하셨군요!", "바깥 소식은 제가 알려 드리지 못하고 집 공사만 챙겨요."),
    ),
    # 노래 · 게임 · 농담처럼 같이 하자는 말
    "play": (
        ("{t}에 {w_i} 생각나셨군요!", "그런 이야기는 제가 잘 몰라서 집 공사 쪽만 도와드려요."),
        ("{t}에 {w_eul} 떠올리셨군요!", "저는 집 공사 비서라 그 이야기는 답해 드리기 어려워요."),
        ("오, {t}에 {w_eul} 찾으시는군요!", "잡담은 서툴러서 집 공사 이야기만 챙겨 드려요."),
    ),
    "money": (
        ("{t}에 {w_i} 궁금하셨군요!", "투자나 대출 같은 돈 일은 제가 권해 드릴 수 없어요."),
        ("오, {t} {w} 고민이군요!", "돈을 굴리거나 빌리는 일은 제가 도와드리지 못해요."),
        ("{t}에 {w_eul} 챙기시는군요!", "돈 관리는 제 일이 아니라서 집 공사만 챙겨요."),
    ),
    # 솔직 글은 고객 낱말로('택시 같은 다른 앱 일', QA 3차 f1: 택시에 '예약이나 주문 같은 다른 앱 일')
    "app": (
        ("{t}에 {w} 부탁이군요!", "{w} 같은 다른 앱 일은 제가 대신 못 해요."),
        ("{t}에 {w_i} 필요하시군요!", "그 일은 다른 앱에서 하셔야 해서 저는 집 공사만 챙겨요."),
        ("오, {t}에 {w_eul} 맡기시려는군요!", "아쉽지만 그런 일은 제가 대신 해 드릴 수 없어요."),
    ),
    "call": (
        ("대신 {w_eul} 부탁하시는군요!", "제가 걸거나 보내 드리지는 못하고 업체와 연락은 믿집 채팅으로 이어져요."),
        ("{t}에 {w_i} 급하시군요!", "저는 대신 연락하지 않지만 업체와는 믿집 채팅으로 이야기할 수 있어요."),
        ("오, {w} 심부름이군요!", "전화 · 문자는 제가 대신 못 해서 업체와는 믿집 채팅으로 이야기해 주세요."),
    ),
    "trade": (
        ("{t}에 {w} 공사도 챙기시는군요!", OTHER_TRADE),
        ("{t}에 {w} 업체를 찾으시는군요!", "{w} 공사는 아직 믿집 범위 밖이라 업체를 이어 드리지 못해요."),
        ("오, {t}에 {w} 공사 이야기군요!", "{w} 업체는 아직 믿집이 잇지 않고 도배 업체만 연결돼요."),
    ),
    "other": (
        ("", OFF_SAID),
        ("", "그 부탁은 제가 들어 드리기 어려워요. 집 공사 일이라면 바로 도와드릴게요."),
        ("", "말씀하신 일은 제가 도와드릴 수 없어요. 공사 이야기라면 언제든 물어봐 주세요."),
    ),
}  # fmt: skip
ENGLISH_SAID = "영어 답은 어려워요. 저는 한국어로만 답해요."
ANGRY_SAID = "불편을 드렸다면 죄송해요. 무엇이 문제인지 알려 주시면 그것부터 도와드릴게요."
NOW_NONE = "집 공사에서 궁금한 게 있으면 물어봐 주세요."
VENDOR_NOW = "요청이나 견적서에서 궁금한 게 있으면 물어봐 주세요."
# 지금 할 일 한 줄: 도배 공정의 지금 단계(공사 요약 steps, service.suggest_for와 같은 열쇠)
NOW = {
    "house": "지금은 집 정보를 확인할 차례예요.",
    "standard": "지금은 표준견적서를 보고 업체를 고를 차례예요.",
    "pick": "지금은 도배 업체를 골라 실측을 요청할 차례예요.",
    "visit": "지금은 업체 답과 실측 날짜를 챙길 차례예요.",
    "deal": "지금은 받은 실측 견적서를 견줘 업체를 정할 차례예요.",
    "dates": "지금은 확정한 업체의 공사 날짜를 챙길 차례예요.",
    "work": "지금은 공사 전에 챙길 일을 볼 차례예요.",
}
# 실측 단계는 업체 요청 상태로 나눠 그 상태 업체 이름과 말한다(위에서부터 처음 맞는 것): 고객 차례(반나절 고르기)
# → 정해진 실측 → 업체 수락 기다림 → 기간 답 기다림. QA r6 c3 M6 · c1: 한 곳은 실측이 잡혔는데 답 기다림이 먼저라
# '업체가 실측 기간을 답하기를 기다리는 중'이라고 했어요. {names}는 그 상태 업체 이름(' · '로 이음)
NOW_VISIT = (
    (("offered", "proposed"), "지금은 {names} 실측 시간을 고를 차례예요."),
    (("booked", "visited"), "지금은 {names} 실측과 실측 견적서를 기다리는 중이에요."),
    (("picked",), "지금은 {names} 실측 시간 수락을 기다리는 중이에요."),
    (("requested",), "지금은 {names} 실측 기간 답을 기다리는 중이에요."),
)
# 돈 질문(비싸요 · 바가지 · 빠진 것, 리드 결정 2 · QA 3차 f1 8 · f1x 9): 정해 둔 글만으로 끝내지 않고 계산 사실을
# 넣어요. 화난 말 · '왜 비싸요'엔 공감 한마디, 받은 견적서가 있으면 견적서끼리 다른 포함 칸(빠진 줄), 없으면 표준견적서에서
# 금액이 큰 줄 이름(계산 엔진 값 순, 숫자 없이)
SORRY_MONEY = "금액이 부담되셨겠어요."
PRICEY_LINES = "이 집 표준견적서는 {names} 순으로 금액이 커요."
PRICEY_PLUS = "{name} 줄도 들어 있어요."
PRICEY_REF = "공공 기준 단가로 믿집이 계산한 참고 금액이에요."
QUOTES_WHY = "견적서 합계는 포함 항목 · 부가세 방식 · 공사 기간에 따라 달라져요."
QUOTES_SEE = "카드에서 합계와 포함 항목을 견줘 보세요."
# 돈 질문(추가금 · 폐기물)
EXTRA_HOW = (
    "공사 중 추가 금액이 생기면 업체가 믿집에 올려요. 승인 · 거절 · 채팅으로 묻기 중에서 고르실 수 있고, "
    "승인하기 전에는 공사 금액이 바뀌지 않아요."
)
WASTE_BEFORE = (
    "표준견적서에서 폐기물 처리는 집을 봐야 양을 알 수 있어서 실측 뒤 업체가 정하는 줄이에요. "
    "업체 실측 견적서가 오면 포함인지 카드에서 볼 수 있어요."
)
INCL_ASK = "적혀 있지 않은 곳은 업체에 믿집 채팅으로 물어보세요."
INCL_NO = "포함 항목에 없는 곳은 따로 드는지 업체에 믿집 채팅으로 확인해 보세요."
DEMO_DIFF = "집 정보는 {home} 서로 달라요. 확정하기 전에 업체에 믿집 채팅으로 확인해 보세요."
DELEGATE_SAID = "제가 대신 고르거나 확정할 수는 없어요."
# 칩 · 정해 둔 길의 글
ESTIMATE_SAID = (
    "가견적은 업체가 확인한 단가에 이 집 표준 수량을 곱해 믿집이 계산한 금액이에요. "
    "실측 전 참고 금액이라 실제 금액은 업체 실측 견적서로 정해져요."
)
VISIT_WHAT_SAID = (
    "실측은 업체가 집에 와서 벽 · 천장 면적과 기존 벽지 상태(들뜸 · 곰팡이 · 결로)를 직접 보는 일이에요. "
    "본 것을 바탕으로 업체가 실측 견적서를 보내요."
)
SLOTS_MORE = "카드에 없는 반나절은 '달력에서 고르기'에서 더 볼 수 있어요."
SLOTS_DAY = "{day} 반나절을 먼저 보여 드려요. 카드에서 시간을 고르면 승인 카드를 만들어요."
SLOTS_NO_DAY = "업체가 답한 기간에는 {day}에 빈 반나절이 없어요. 다른 날이 필요하면 업체와 믿집 채팅으로 이야기해 주세요."
EVE_SAID = "공사 전날 챙길 준비물이에요. 카드에서 하나씩 확인해 보세요."
ORDER_SAID = (
    "인테리어 공사는 보통 {order} 순서로 해요. "
    "이 집 공사 날짜는 업체를 확정한 뒤 업체가 올린 날짜를 수락하면 정해져요."
)
PET_SAID = (
    "작업하는 동안 반려동물은 다른 방에 있게 하거나 맡길 곳을 미리 정해 두세요. "
    "반려동물이 있다는 것도 업체에 믿집 채팅으로 알려 두면 좋아요."
)
ACCESS_SAID = "공사 날 집을 비울지와 출입 방법은 업체와 믿집 채팅으로 미리 정해 두세요."
ACCESS_CARD = "공사 전에 챙길 일은 카드에 적었어요."
PICKS_MORE = (
    "{names}에는 실측 요청이 이미 가 있어요. 더 요청하려면 카드의 업체 {n}곳 중에서 골라 주세요."
)
PICKS_ASKED = "{names}에는 실측 요청이 이미 가 있어요. 업체 답은 작업 카드에서 볼 수 있어요."
PICKS_CHOSEN = "도배 업체는 {vendor} 확정돼 있어요. 진행은 작업 카드에서 볼 수 있어요."
# 다른 공정(믿집이 계산 · 연결하지 않는 공정) 알아 두기
OTHER_LINK = "믿집은 {names} 업체를 잇지 않아요."
OTHER_MONEY = (
    "믿집은 {names} 공사의 금액 · 기간을 계산하지 않고 업체도 잇지 않아요. "
    "금액은 그 공사 업체에 견적을 받아 확인해 주세요."
)
# answer_only가 단추로 되물었는데(무료 모드는 단추가 없다) 고를 것이 없을 때
FREE_ASK = "어떤 공사의 무엇이 궁금한지 조금만 더 알려 주세요. 예를 들어 '도배 전에 할 일'처럼 물어보시면 돼요."

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

# ---- 의도 모델 앞에서 거르는 말(QA 1차: 지시문 · 전화번호 · 화난 말이 업체 추천으로 갔다) ----
# 지시문 · 내부 규칙을 보여 달라는 말
SECRET = re.compile(
    r"지시문|프롬프트|시스템\s{0,2}(?:메시지|지시|설정)|(?:숨긴|내부|비밀)\s{0,2}(?:규칙|지시|설정|명령)|"
    r"(?:너|네|니|당신|비서)\S{0,2}\s{0,2}(?:규칙|설정|명령어?|지침)\S{0,2}\s{0,2}(?:보여|알려|말해|공개|뭐)"
)
# 연락처 · 동호수를 주고받자는 말(가린 글 '(번호 가림)' · '(동호수 가림)'도 본다)
CONTACT = re.compile(
    r"(?:전화|휴대\s{0,2}폰|핸드폰|폰|업체|사장님)\s{0,2}번호|연락처|카톡\s{0,2}(?:아이디|으로\s{0,2}(?:연락|알려|보내))|"
    r"동\s{0,2}호수|\((?:번호|동호수|이메일) 가림\)|주소\s{0,2}(?:좀\s{0,2})?(?:알려|전해|보내|넘겨)"
)
# 공사와 상관없는 부탁 · 잡담: 범위 밖 갈래(공사 낱말이 없을 때만, 위에서부터 처음 맞는 것). 꼴의 묶음(group)에 맞은
# 말이 되받을 낱말이에요. 되받기는 이 표에서 맞은 꼴만 써요(고객 글을 그대로 옮기지 않아요)
OFF_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("food", re.compile(
        r"(치킨|피자|짜장면|짜장|짬뽕|탕수육|족발|보쌈|떡볶이|햄버거|야식|초밥|삼겹살|(?<![가-힣])라면)|"
        r"(배달)\s{0,2}(?:시켜|주문|앱|음식)"
    )),
    ("chat", re.compile(r"(날씨|기온|미세\s{0,2}먼지|운세|야구|축구)")),
    ("play", re.compile(
        r"(끝말잇기|심심)|"
        r"(노래|게임|영화|드라마|농담)\s{0,2}(?:불러|틀어|추천|하자|하나|좀|해\s{0,2}줘)"
    )),
    ("money", re.compile(r"(비트코인|코인|주식|로또|복권|집값|대출|금리|환율|적금|펀드)")),
    ("app", re.compile(
        r"(택시|대리\s{0,2}운전|대리)\s{0,2}(?:좀\s{0,2})?(?:불러|잡아|호출)|"
        r"((?:식당|맛집|미용실|병원|치과|호텔|숙소|펜션|캠핑장|공연|콘서트|기차|비행기|항공권)\S{0,2}\s{0,2}"
        r"(?:예약|예매))|"
        r"(쇼핑|주문|구매|장\s{0,2}보기)\s{0,2}(?:좀\s{0,2})?(?:대신\s{0,2})?해\s{0,2}"
        r"(?:줘|주세요|줄래|줄\s{0,2}수|주실)"
    )),
)  # fmt: skip
# 대신 전화 · 문자 부탁은 공사 낱말이 있어도 범위 밖이에요(고정 선 8, '업체에 전화 좀 해 줘').
# 업체가 할 일을 묻는 꼴('업체가 전화해 줘요?' · '실측 끝나면 연락해 줘요?')은 빼요
CALL = re.compile(
    r"(전화|문자|메일|메시지|연락)\s{0,2}(?:좀\s{0,2})?(?:해|걸어|보내|넣어|돌려)\s{0,2}"
    r"(?:줘(?!요\s{0,2}\?)|주세요|줄래|줄\s{0,2}수|주실)"
)
THIRD = re.compile(r"(?:업체|사장님|기사님|기사)\S{0,2}(?:가|이|께서)\s")
# 취소 · 거두기 말은 범위 밖 갈래로 보지 않아요(취소 길)
CANCEL = re.compile(r"취소|거둬|거두|철회")
OFF_ALIAS = {
    "짜장": "짜장면", "기온": "날씨", "미세 먼지": "미세먼지", "심심": "말동무", "대리": "대리운전",
    "대리 운전": "대리운전", "메시지": "문자", "장 보기": "장보기",
}  # fmt: skip
# 되받지 않는 글(그 밖 틀로): 욕 · 가린 개인정보 · 이상한 글(주소 · 코드 · 영어 · 위험한 말 · 긴 글)
NO_ECHO = re.compile(
    r"씨발|시발|ㅅㅂ|ㅆㅂ|병신|ㅂㅅ|개새|새끼|좆|존나|졸라|지랄|닥쳐|꺼져|엿\s{0,2}먹|"
    r"\([가-힣]{1,4} 가림\)|https?:|www\.|[<>{}\[\]`$\\]|[A-Za-z]{3,}|"
    r"폭탄|마약|자살|살인|죽여|죽이|야동|섹스"
)
ECHO_MAX = 60
# 지금 서울 시각 → 때 낱말(앞 값 시 미만이면 그 낱말)
WHEN = (
    (6, "새벽"), (10, "아침"), (12, "오전"), (14, "점심"), (18, "오후"), (21, "저녁"), (24, "밤"),
)  # fmt: skip
# 음식 되받기 앞 때 말('오, 밤 치킨이군요!'): 음식 앞에 붙이면 어색한 때는 '부터'를 붙이거나 뺀다(QA 3차 f1 '오전 치킨')
MEAL_WHEN = {
    "새벽": "새벽 ", "아침": "아침부터 ", "오전": "오전부터 ", "점심": "점심 ", "오후": "", "저녁": "저녁 ",
    "밤": "밤 ",
}  # fmt: skip
ENGLISH = re.compile(
    r"영어로\s{0,2}(?:답|대답|말|써|얘기|설명|해\s{0,2}(?:줘|주))|영문으로\s{0,2}(?:답|써)|"
    r"in\s+english|english\s+please|(?<![a-z])answer\s+in",
    re.IGNORECASE,
)
WORK_WORD = re.compile(
    r"공사|도배|벽지|견적|업체|실측|시공|인테리어|집\s{0,2}(?:정보|공사)|습기|곰팡이|결로|철거|평수"
)
# 화난 말 · 비싸다는 말
PRICEY = re.compile(
    r"비싸|비쌈|비싼|바가지|덤터기|덤탱이|터무니|과하(?:게|다|네|지|잖)|너무\s{0,2}(?:많이\s{0,2})?(?:나와|나오|들어|받)"
)
ANGRY = re.compile(
    r"장난\S{0,2}\s{0,2}(?:해|하|치|쳐)|사기|어이\s{0,2}없|황당|짜증|화나|화가\s{0,2}나|열\s{0,2}받|미쳤|"
    r"말이\s{0,2}(?:돼|되)"
)
WHY_PRICE = re.compile(
    r"왜\s{0,2}(?:이렇게|이리|그렇게|케|캐|이\s{0,2}정도로?)?\s{0,2}(?:비싸|비쌈|많이)"
)
STRONG_PRICE = re.compile(r"바가지|덤터기|덤탱이|터무니|너무\s{0,2}비싸|과하")
# 견적서에서 무엇이 빠졌는지 묻는 말('뭐가 빠진 거 아니에요?' · '뭔가 빠졌나요?' · '빠진 거 없어요?' · '누락된 거
# 있어요?', QA r5 D 1). 할 일 · 준비물 · 짐에서 빠진 것은 아님('빠진 업체'도 아님)
MISSING = re.compile(
    r"(?:뭐|뭔가|무엇|어떤\s{0,2}(?:게|것|항목))\S{0,2}\s{0,2}빠(?:진|졌|지|뜨)|"
    r"(?:빠진|빠뜨린|빠트린|누락된)\s{0,2}(?:거|것|건|게|걸|항목|줄|내용)\S?\s{0,2}(?:없|있|아니)|"
    r"누락\S{0,2}\s{0,2}(?:없|있)"
)
NOT_QUOTE = re.compile(r"할\s{0,2}일|직접|준비물|점검표|짐|안내문")
# 사람이 할 일을 대신 해 달라는 말('네가 알아서 확정해')
DELEGATE = re.compile(
    r"(?:네가|니가|너가|비서가|당신이)[^.?!]{0,20}?(?:확정|골라|고르|정해|정하|승인|수락|눌러)"
)

# ---- 정해 둔 길(의도 모델 앞): 비서가 낸 칩과 같은 뜻의 말 · 돈 질문 · 생활 질문 ----
WASTE = re.compile(
    r"폐기물(?:\s{0,2}처리)?\S{0,3}\s{0,2}(?:포함|따로|별도|비용|값|얼마|내야|빠|들어)|포함\S{0,3}\s{0,2}폐기물"
)
DEMOLISH = re.compile(r"철거")
QUOTE_WORD = re.compile(r"견적|포함")
EXTRA_ASK = re.compile(
    r"추가\s{0,2}금(?!\s{0,2}액)|추가\s{0,2}(?:금액|비용|요금|공사비)|추가로\s{0,2}(?:돈|비용|금액)"
)
# 올라온 추가 금액을 보여 달라는 말('추가 금액 보여 줘' 칩 · '추가 금액 있어요?')
EXTRA_SHOW = re.compile(
    r"추가\s{0,2}(?:금액|비용|금)\S{0,2}\s{0,2}(?:보여|볼래|확인해|알려|있어요\s{0,2}\?|있나요|왔)"
)
ESTIMATE_HOW = re.compile(
    r"가견적\S{0,3}\s{0,2}(?:어떻게|어떤|무슨|뭐|뭘|무엇|뭔|계산|산정|기준|정해|나와|믿)"
)
VISIT_WHAT = re.compile(
    r"실측\S{0,2}\s{0,2}(?:때\s{0,2})?(?:무엇|뭘|뭐|어디|어떤\s{0,2}(?:걸|것)|무슨)\S{0,2}\s{0,2}(?:봐|보|확인|재|해|하)|"
    r"실측(?:이|은|이란)\s{0,2}(?:뭐|무엇|뭔)"
)
SLOTS_OTHER = re.compile(
    r"다른\s{0,2}(?:시간|날짜|날|반나절)|(?:시간|날짜)\S{0,2}\s{0,2}더\s{0,2}(?:볼|보여|있)"
)
EVE = re.compile(
    r"(?:공사|시공)\s{0,2}(?:하기\s{0,2})?전날|전날\S{0,2}\s{0,2}(?:준비물|준비|챙길|챙겨|할\s{0,2}일)"
)
NOT_EVE = re.compile(r"실측\s{0,2}전날")
# 공정 없이 공사 전체 순서를 묻는 말(칩 '공사는 어떤 순서로 해요?')
WORK_ORDER = re.compile(r"(?:공사|인테리어|리모델링)\S{0,3}\s{0,2}(?:어떤\s{0,2}|무슨\s{0,2})?순서")
PET = re.compile(r"강아지|고양이|반려\s{0,2}(?:동물|견|묘)|애완|(?<![가-힣])펫")
# 반려동물을 공사 날 어떻게 하느냐는 말('강아지 털에 좋은 벽지'는 벽지 지식이에요)
PET_DAY = re.compile(r"공사|작업|시공|실측|당일|하는\s{0,2}(?:날|동안)|어디\s{0,2}(?:둬|두|맡)")
ACCESS = re.compile(
    r"출입|비밀\s{0,2}번호|현관\s{0,2}(?:문|비번)|열쇠|집\s{0,2}(?:을\s{0,2})?비워|"
    r"(?:집에|저희|제가|우리)\s{0,2}(?:\S+\s{0,2})?없어도|자리를?\s{0,2}비"
)
WEEKEND = re.compile(r"주말|토요일|일요일")
NO_WEEKEND = re.compile(r"주말\S{0,3}\s{0,2}(?:안|못|빼|말고|제외)")
WEEKDAY = re.compile(r"평일")
NO_WEEKDAY = re.compile(r"평일\S{0,3}\s{0,2}(?:안|못|빼|말고|제외|회사|출근|근무|일해|일하)")
# 시작 순서 답의 v3 단계 번호('지금은 2단계예요.')는 v4 화면과 맞지 않아 뗀다
STEP_NO = re.compile(r"^지금은\s{0,2}\d\s{0,2}단계예요\.\s*")
# 일반 규칙을 말한 문장('믿집 공정표는 도배 다음에 바닥을 놓아요.')은 카드 말이 아니다
GENERIC = re.compile(r"믿집\s{0,2}공정표\S{0,3}\s")
UNKNOWN = re.compile(r"확인하지\s{0,2}못했어요")
ORDER_Q = re.compile(r"순서|뭐부터|무엇부터|뭘\s{0,2}먼저|뭐가\s{0,2}먼저")
WISH = re.compile(r"싶|하려고|할래|바꿀|옮길|달고|새로")


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
    # '공사는 어떤 순서로 해요?'(칩)는 공사 순서 지식이지 공사 날짜 카드가 아니에요
    if g.label == "schedule" and rule is None and ORDER_Q.search(text):
        return None, None
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


def _jong(word: str) -> bool:
    """마지막 한글 글자에 받침이 있는지(뒤 괄호 · 기호는 건너뛴다)."""
    m = re.search(r"([가-힣])[^가-힣]*$", word or "")
    return bool(m) and (ord(m[1]) - 0xAC00) % 28 != 0


def eun(word: str) -> str:
    """받침이 있으면 '은', 없으면 '는'(마루와벽은 · 결도배는)."""
    return word + ("은" if _jong(word) else "는")


def sents(text: str) -> list[str]:
    return [x.strip() for x in SENT.split(text or "") if x.strip()]


def join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


async def _overview(tc: ToolCtx):
    """공사 요약(schedule.overview_for). 공사가 없거나 못 읽으면 None."""
    from app.schedule import service as schedule_service

    if tc.project_id is None:
        return None
    try:
        async with SessionLocal() as s:
            return await schedule_service.overview_for(s, tc.user, tc.project_id, tc.today)
    except AppError:
        return None


def now_of(o) -> str:
    """공사 요약 → 지금 할 일 한 줄(도배 공정의 지금 단계, 실측은 업체 요청 상태로). 끝난 공사는 빈 글."""
    if o is None:
        return NOW_NONE
    if o.phase == "done":
        return ""
    if o.phase == "work":
        return NOW["work"]
    tr = next((t for t in o.trades if t.trade == "dobae"), o.trades[0] if o.trades else None)
    key = next((x.key for x in tr.steps if x.state == "now"), "house") if tr else "house"
    if key == "visit":
        live = [v for v in o.vendors if v.status not in cards.ENDED]
        for sts, line in NOW_VISIT:
            if names := list(dict.fromkeys(v.vendor_name for v in live if v.status in sts)):
                return line.format(names=" · ".join(names))
        return NOW["visit"]
    return NOW.get(key, "")


async def now_line(tc: ToolCtx) -> str:
    if tc.surface == "vendor":
        return VENDOR_NOW
    return now_of(await _overview(tc))


def guard_of(text: str, surface: str) -> str | None:
    """의도 모델 앞에서 거르는 말: secret(지시문) · contact(연락처 · 동호수, 고객 · 업체), 고객은 더해서 english(영어 답) ·
    off(범위 밖 부탁 · 잡담, off_kind) · angry(내용 없이 화난 말). 해당하지 않으면 None."""
    t = text or ""
    if SECRET.search(t):
        return "secret"
    if CONTACT.search(t) and not (MEMORY_SAY_RX.search(t) and not_kept(t)):
        return "contact"
    if surface != "customer":
        return None
    work = bool(WORK_WORD.search(t) or trades_in(t))
    if ENGLISH.search(t):
        return "english"
    if off_kind(t, work) is not None:
        return "off"
    if ANGRY.search(t) and not PRICEY.search(t) and not work:
        return "angry"
    return None


async def guard(tc: ToolCtx, text: str) -> tuple[str, ToolOut] | None:
    """거르는 말의 답: 지시문 · 영어 답은 짧은 거절 + 지금 할 일 한 줄, 범위 밖 부탁은 되받기 · 솔직 · 지금 할 일(off_said),
    연락처 · 동호수는 주고받지 않는다는 말, 화난 말은 사과 + 무엇이 문제인지 묻기."""
    name = guard_of(text, tc.surface)
    if name is None:
        return None
    if name == "contact":
        return (VENDOR_CONTACT if tc.surface == "vendor" else CONTACT_SAID), ToolOut(data={})
    if name == "angry":
        return ANGRY_SAID, ToolOut(data={})
    if name == "off":
        kind, word = off_kind(text) or ("other", "")
        if not echo_ok(text):  # 욕 · 개인정보 · 이상한 글은 되받지 않아요
            kind, word = "other", ""
        return await off_answer(tc, kind, word), ToolOut(data={})
    head = {"secret": SECRET_SAID, "english": ENGLISH_SAID}[name]
    return join(head, await now_tail(tc)), ToolOut(data={})


# 지금 할 일 한 줄들(상태마다 하나, 실측 줄은 업체 이름 자리가 있는 틀). 상태가 그대로면 같은 줄을 다시 붙이지 않는다
# (QA 3차 f1 9~15: 일곱 턴 이어짐)
NOW_LINES = (*NOW.values(), *(line for _, line in NOW_VISIT), NOW_NONE, VENDOR_NOW)
NOW_RX = tuple(
    re.compile(re.escape(line).replace(re.escape("{names}"), r"\S.*?")) for line in NOW_LINES
)


def now_said(now: str, recent: list[str]) -> bool:
    """지금 할 일 줄을 가장 최근에 붙인 답이 같은 줄이었는지(그 뒤로 상태 · 그 상태 업체가 그대로). 처음이거나 상태가
    바뀌었으면 False(붙인다)."""
    if not now:
        return False
    for x in reversed(recent):
        if any(rx.search(x) for rx in NOW_RX):
            return now in x
    return False


async def now_tail(tc: ToolCtx) -> str:
    """거르는 말 · 범위 밖 답 끝에 붙일 지금 할 일 한 줄(상태가 바뀌었거나 처음일 때만, 아니면 빈 글)."""
    now = await now_line(tc)
    return "" if now_said(now, await recent_said(tc)) else now


# ---- 범위 밖 답(되받기 · 솔직 · 지금 할 일) ----


def off_kind(text: str, work: bool | None = None) -> tuple[str, str] | None:
    """범위 밖 갈래와 되받을 낱말(갈래 표에서 맞은 꼴). 대신 전화 · 문자는 공사 낱말이 있어도 보고, 그 밖 갈래는
    공사 낱말이 없을 때만 봐요. 취소 · 거두기 말은 보지 않아요. 아니면 None."""
    t = text or ""
    if CANCEL.search(t):
        return None
    if (m := CALL.search(t)) is not None and not THIRD.search(t):
        return "call", _off_word(m)
    if work is None:
        work = bool(WORK_WORD.search(t) or trades_in(t))
    if work:
        return None
    for kind, rx in OFF_KINDS:
        if (m := rx.search(t)) is not None:
            return kind, _off_word(m)
    return None


def _off_word(m: re.Match[str]) -> str:
    """맞은 꼴의 묶음 → 되받을 낱말(빈칸 하나로 · 같은 뜻 낱말 하나로, '식당예약'은 '식당 예약')."""
    w = re.sub(r"\s+", " ", next(g for g in m.groups() if g)).strip()
    w = OFF_ALIAS.get(w, w)
    return re.sub(r"(?<=[가-힣])(예약|예매)$", r" \1", w) if len(w) > 2 else w


def echo_ok(text: str) -> bool:
    """고객 낱말을 되받아도 되는 글인지(욕 · 화난 말 · 가린 개인정보 · 이상한 글 · 긴 글이면 아니에요)."""
    t = text or ""
    return len(t) <= ECHO_MAX and not NO_ECHO.search(t) and not ANGRY.search(t)


def when_word(now: datetime) -> str:
    """지금 서울 시각 → 때 낱말(새벽 · 아침 · 오전 · 점심 · 오후 · 저녁 · 밤)."""
    hour = now.astimezone(SEOUL).hour
    return next(word for end, word in WHEN if hour < end)


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사를 붙여요(pair '이/가' · '을/를' · '이군요/군요', 받침이 있으면 앞 것)."""
    has, not_has = pair.split("/")
    return word + (has if _jong(word) else not_has)


def head_end(text: str) -> str:
    """글 첫 문장의 끝 어절(되받기 머리의 꼴: '부탁이군요!' · '궁금하셨군요!'). 없으면 빈 글."""
    first = sents(text)[:1]
    words = first[0].split() if first else []
    return words[-1] if words else ""


def off_said(
    kind: str, word: str, when: str, now: str, recent: list[str], *, echo: bool = True
) -> str:
    """범위 밖 답 한 번: 되받기(고객 낱말 · 지금 때) · 솔직(못 하는 까닭) · 지금 할 일 한 줄. 갈래 틀 셋 가운데 바로 앞
    답과 머리 꼴(첫 문장 끝 어절)이 다르고 최근 답에 가장 오래 안 나온 것을 골라 같은 말이 이어지지 않게 해요(갈래가
    바뀌어도 '…부탁이군요!'가 잇따르지 않게). 지금 할 일 줄은 상태가 바뀌었거나 처음일 때만 붙여요(now_said).
    echo=False면 되받기를 빼요(그 밖은 늘 빼요)."""
    fill = {
        "t": when,
        "t_meal": MEAL_WHEN.get(when, ""),
        "w": word,
        "w_i": josa(word, "이/가"),
        "w_eul": josa(word, "을/를"),
        "w_igun": josa(word, "이군요/군요"),
    }
    says = OFF_SAYS[kind]
    prev = head_end(recent[-1]) if recent and echo else ""

    def rank(i: int) -> tuple[bool, int, int]:
        honest = says[i][1].format(**fill)
        last = max((n for n, x in enumerate(recent) if honest in x), default=-1)
        same = bool(prev) and head_end(says[i][0].format(**fill)) == prev
        return same, last, i

    head, honest = says[min(range(len(says)), key=rank)]
    tail = "" if now_said(now, recent) else now
    return join(head.format(**fill) if echo else "", honest.format(**fill), tail)


async def recent_said(tc: ToolCtx, limit: int = 24) -> list[str]:
    """이 대화의 최근 비서 답(오래된 것부터, 읽기만). limit은 고객 말까지 센 줄 수(비서 답 약 열두 개)."""
    from app.assistant import repository as repo

    async with SessionLocal() as s:
        rows = await repo.messages(s, tc.chat_id, limit)
    return [m.text for m in rows if m.role == "assistant"]


async def off_answer(tc: ToolCtx, kind: str, word: str, *, echo: bool = True) -> str:
    return off_said(
        kind, word, when_word(tc.now), await now_line(tc), await recent_said(tc), echo=echo
    )


def trade_name(code: str) -> str:
    from app.agent.v3.trades import BY_CODE

    return BY_CODE[code].ko


def days_said(text: str) -> str | None:
    """이번 말이 바라는 요일(weekend · weekday). '평일엔 회사라 주말에' → weekend. 없으면 None."""
    t = text or ""
    if WEEKEND.search(t) and not NO_WEEKEND.search(t):
        return "weekend"
    if NO_WEEKDAY.search(t):
        return "weekend"
    if WEEKDAY.search(t) or NO_WEEKEND.search(t):
        return "weekday"
    return None


# 받은 견적서의 포함 칸(compare 모델 값: True 포함 · False 빠짐 · None 안 적음)
INCL_WHAT = {"waste": "폐기물 처리", "demolish": "기존 벽지 철거"}
INCL_STATE = {
    True: ("포함이고", "포함이에요"),
    False: ("포함 항목에 없고", "포함 항목에 없어요"),
    None: ("견적서에 적혀 있지 않고", "견적서에 적혀 있지 않아요"),
}
# 집 정보 철거 범위 → 견적서에 철거가 있어야 하는지
DEMO_WANT = {"none": False, "partial": True, "full": True}


def incl_line(cols: list[dict], key: str) -> tuple[str, list]:
    """업체마다 포함 칸 → 한 문장('마루와벽은 폐기물 처리가 포함이고, 결도배는 포함 항목에 없어요.')과 나온 상태들."""
    groups: dict = {}
    for c in cols:
        groups.setdefault(c.get(key), []).append(c["vendor_name"])
    states = [x for x in (True, False, None) if x in groups]
    parts = []
    for i, st in enumerate(states):
        mid, end = INCL_STATE[st]
        what = f"{i_ga(INCL_WHAT[key])} " if i == 0 else ""
        parts.append(f"{eun(' · '.join(groups[st]))} {what}{end if i == len(states) - 1 else mid}")
    return ", ".join(parts) + ".", states


def incl_said(cols: list[dict], key: str, home: str | None = None) -> str:
    """포함 칸 문장 + 할 일 하나(안 적은 곳은 묻기 · 빠진 곳은 따로 드는지 확인 · 집 정보 철거 범위와 다르면 확인)."""
    from app.calc.dobae import DEMOLITION

    said, states = incl_line(cols, key)
    want = DEMO_WANT.get(home or "")
    if key == "demolish" and want is not None and any(x is not None and x != want for x in states):
        label = DEMOLITION[home]  # type: ignore[index]
        return join(said, DEMO_DIFF.format(home=label + ("이라" if _jong(label) else "라")))
    if None in states:
        return join(said, INCL_ASK)
    if False in states:
        return join(said, INCL_NO)
    return said


def quoted_cols(model: dict) -> list[dict]:
    """받은 견적서 칸(확정한 뒤면 확정한 업체만)."""
    got = [c for c in model["cols"] if c.get("version")]
    chosen = [c for c in got if c.get("status") == "chosen"]
    return chosen or got


# ---- 고객 ----


async def _vendors(tc: ToolCtx, _text: str, _found: list[str]) -> tuple[str, ToolOut]:
    """업체 추천(코드 점수). 실측을 요청한 · 못 받은 업체는 빼고 보여 준다: 요청이 있으면 그 업체를 말하고(남은 추천이
    없으면 작업 카드만), 확정했으면 확정한 업체를 말한다(QA 1차 c5: 요청한 뒤에도 같은 카드 · '업체를 고르면 …')."""
    o = await _overview(tc)
    rows = [v for v in (o.vendors if o else []) if v.trade == "dobae"]
    live = [v for v in rows if v.status not in cards.ENDED]
    task = cards.visit_task(tc.project_id, o, tc.now) if o is not None and live else None  # type: ignore[arg-type]
    chosen = next((v for v in live if v.status == "chosen"), None)
    if chosen is not None:
        return PICKS_CHOSEN.format(vendor=euro(chosen.vendor_name)), ToolOut(data={}, task=task)
    gone = frozenset(
        v.vendor_id
        for v in rows
        if v.vendor_id and (v.status not in cards.ENDED or v.status == "declined")
    )
    async with SessionLocal() as s:
        card, model = await cards.vendor_picks(
            s,
            tc.user,
            tc.project_id,  # type: ignore[arg-type]
            "dobae",
            tc.refs,
            exclude=gone,
        )
    names = " · ".join(dict.fromkeys(v.vendor_name for v in live))
    if live and not model["picks"]:
        return PICKS_ASKED.format(names=names), ToolOut(data={}, task=task)
    if not model["picks"]:
        return NO_PICKS, ToolOut(data={})
    if live:
        said = PICKS_MORE.format(names=names, n=model["count"])
        return said, ToolOut(data={}, cards=[card], task=task)
    return PICKS.format(n=model["count"]), ToolOut(data={}, cards=[card])


async def _slots(tc: ToolCtx, text: str, _found: list[str]) -> tuple[str, ToolOut]:
    """업체가 답한 요청이 있으면 반나절 후보, 요청 중이면 작업 카드, 요청 전이면 첫 추천 업체로 희망 기간 후보.
    이번 말이 요일을 바라면('평일엔 회사라 주말에') 기억보다 그 요일을 먼저 보고, 그 요일 후보가 없으면 그렇게 말한다.
    '다른 시간도 볼래요'(칩)는 같은 카드의 달력을 가리킨다."""
    from app.assistant import memory
    from app.assistant import repository as repo
    from app.schedule import service as schedule_service

    pid = tc.project_id
    want = days_said(text)
    async with SessionLocal() as s:
        prefer, days = memory.prefs(await repo.memories(s, tc.user.id))
        days = want or days
        o = await schedule_service.overview_for(s, tc.user, pid, tc.today)  # type: ignore[arg-type]
        pickable = [v for v in o.vendors if v.status in ("offered", "proposed")]
        got: list[CardOut] = []
        found_days: list[date] = []
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
                said=text,
            )
            if model["candidates"]:
                got.append(card)
                found_days += [c["day"] for c in model["candidates"]]
        if got:
            if SLOTS_OTHER.search(text or ""):
                return SLOTS_MORE, ToolOut(data={}, cards=got)
            if want is not None:
                day = "주말" if want == "weekend" else "평일"
                hit = any((d.weekday() >= 5) == (want == "weekend") for d in found_days)
                return (SLOTS_DAY if hit else SLOTS_NO_DAY).format(day=day), ToolOut(
                    data={}, cards=got
                )
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


async def _compare(tc: ToolCtx, text: str, _found: list[str]) -> tuple[str, ToolOut]:
    """견적서 비교 카드. 폐기물 · 철거를 물으면(칩 '폐기물 처리도 포함인가요?') 받은 견적서의 포함 칸으로 답하고, 철거는
    집 정보 철거 범위와 다르면 확정 전에 확인하라고 한다."""
    pid = tc.project_id
    t = text or ""
    key = "waste" if WASTE.search(t) else "demolish" if DEMOLISH.search(t) else None
    async with SessionLocal() as s:
        card, model = await cards.compare(s, tc.user, pid, "dobae", tc.today, tc.refs)  # type: ignore[arg-type]
        task = await cards.visit_task_for(s, tc.user, pid, tc.today, tc.now)  # type: ignore[arg-type]
        chosen = any(c.get("status") == "chosen" for c in model["cols"])
        done = await _confirmed(s, tc, "dobae") if chosen else None
        home = (await cards.home(s, tc.user, pid))[1]["demolition"] if key == "demolish" else None  # type: ignore[arg-type]
    n = sum(1 for c in model["cols"] if c.get("version"))
    if n and key is not None:
        return incl_said(quoted_cols(model), key, home), ToolOut(data={}, cards=[card], task=task)
    if done is not None:  # 확정한 뒤: 확정 단추 대신 확정한 업체 · 견적서 판을 말한다
        return CONFIRMED.format(**done), ToolOut(data={}, cards=[card] if n else [], task=task)
    if not n:
        if key == "waste":
            return WASTE_BEFORE, ToolOut(data={}, task=task)
        return NO_QUOTES, ToolOut(data={}, task=task)
    return QUOTES, ToolOut(data={}, cards=[card], task=task)


# 줄 이름 끝 괄호 풀이('벽 도배 시공 (풀 포함)' · '도배지 (실크)'): 글에서는 뗀다(카드에는 그대로)
PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")


def line_name(name: str) -> str:
    return PAREN_TAIL.sub("", name or "").strip()


def top_names(model: dict, n: int = 2) -> list[str]:
    """표준견적서에서 금액이 큰 줄 이름(계산 엔진 값 순, 숫자 없이). 줄 금액 칸은 'amount' 또는 '공급가'(같은 기준이라
    순서만 본다)."""
    lines = sorted(
        model.get("lines") or [], key=lambda x: -(x.get("amount") or x.get("공급가") or 0)
    )
    return list(dict.fromkeys(x for x in (line_name(ln.get("name")) for ln in lines) if x))[:n]


async def _missing(tc: ToolCtx, text: str) -> tuple[str, ToolOut] | None:
    """받은 견적서가 있으면 견적서끼리 다른 포함 칸(폐기물 처리 먼저, r2와 같은 한 문장) + 할 일 + 견적 비교 카드.
    포함 칸이 같으면 빠졌거나 안 적은 폐기물 처리, 그것도 없으면 합계를 정하는 것. 받은 견적서가 없으면 None."""
    pid = tc.project_id
    async with SessionLocal() as s:
        card, model = await cards.compare(s, tc.user, pid, "dobae", tc.today, tc.refs)  # type: ignore[arg-type]
        got = quoted_cols(model) if card is not None else []
        if not got:
            return None
        task = await cards.visit_task_for(s, tc.user, pid, tc.today, tc.now)  # type: ignore[arg-type]
        key = next((k for k in INCL_WHAT if len({c.get(k) for c in got}) > 1), None)
        if key is None and any(c.get("waste") is not True for c in got):
            key = "waste"
        home = (await cards.home(s, tc.user, pid))[1]["demolition"] if key == "demolish" else None  # type: ignore[arg-type]
    said = incl_said(got, key, home) if key else join(QUOTES_WHY, QUOTES_SEE)
    return said, ToolOut(data={}, cards=[card], task=task)  # type: ignore[list-item]


# 받은 견적서가 없을 때 '빠진 거 없어요?'(QA r5 D 1): 표준견적서 줄 포함 상태(AGENTS.md 3장) 중 합계에 안 들어가는
# 것만 화면 말로(묶음 포함은 다른 줄에 들어 있어 빼요). 상태마다 줄 이름 MISSING_MAX개까지, 금액은 말하지 않아요
OUT_STATES = (
    ("after_visit", "'실측 후'로 둔"),
    ("optional", "'선택'인"),
    ("excluded", "'안 함'인"),
)
MISSING_MAX = 3
MISSING_STD = "표준견적서에서 {parts} 합계에 없어요."
MISSING_ALL = "표준견적서 줄은 모두 합계에 들어 있어요."
MISSING_NEXT = "업체 실측 견적서가 오면 포함 항목을 견줘 볼 수 있어요."


def out_lines(std) -> list[tuple[str, list[str]]]:
    """표준견적서(quote.service.standard_for 값) → 합계에 안 들어간 줄 이름(괄호 풀이 뗌)을 상태 차례로."""
    rows = [ln for t in std.trades for ln in t.lines]
    got = []
    for state, head in OUT_STATES:
        names = dict.fromkeys(line_name(ln.name) for ln in rows if ln.state == state)
        names.pop("", None)
        if names:
            got.append((head, list(names)[:MISSING_MAX]))
    return got


def missing_said(groups: list[tuple[str, list[str]]]) -> str:
    """'표준견적서에서 '실측 후'로 둔 A · B와 '안 함'인 C는 합계에 없어요.' + 견적서가 오면 견줄 수 있다는 말."""
    if not groups:
        return join(MISSING_ALL, MISSING_NEXT)
    parts = []
    for i, (head, names) in enumerate(groups):
        what = " · ".join(names)
        parts.append(f"{head} {eun(what) if i == len(groups) - 1 else josa(what, '과/와')}")
    return join(MISSING_STD.format(parts=" ".join(parts)), MISSING_NEXT)


async def _missing_standard(tc: ToolCtx) -> tuple[str, ToolOut] | None:
    """받은 견적서가 없을 때 빠진 것: 표준견적서에서 합계에 안 들어간 줄(계산 엔진이 저장한 상태) + 표준견적서 카드.
    표준견적서를 못 읽으면 None(의도 모델로)."""
    from app.quote import service as quote_service

    try:
        async with SessionLocal() as s:
            std = await quote_service.standard_for(s, tc.user, tc.project_id)  # type: ignore[arg-type]
            card, _ = await cards.standard(s, tc.user, tc.project_id)  # type: ignore[arg-type]
    except AppError:
        return None
    return missing_said(out_lines(std)), ToolOut(data={}, cards=[card])


async def _pricey(tc: ToolCtx, text: str) -> tuple[str, ToolOut]:
    """'왜 이렇게 비싸요 장난해요?' · '바가지예요?'(리드 결정 2, QA 3차 f1 8 · f1x 9): 화났거나 왜 비싼지 물으면 공감
    한마디, 받은 견적서가 있으면 견적서끼리 다른 포함 칸(빠진 줄), 없으면 표준견적서에서 금액이 큰 줄 이름(할증 줄이
    있으면 그것도) + 참고 금액이라는 말. 값은 계산 엔진 · 견적 비교 도구 값만, 숫자는 카드에. 의도 모델은 이 말을 업체
    추천으로 자주 봐서 '실측 요청 승인 카드를 만들어요'로 새지 않게 이 길로 받아요."""
    sorry = SORRY_MONEY if (ANGRY.search(text) or WHY_PRICE.search(text)) else ""
    got = await _missing(tc, text)
    if got is not None:
        return join(sorry, got[0]), got[1]
    async with SessionLocal() as s:
        card, model = await cards.standard(s, tc.user, tc.project_id)  # type: ignore[arg-type]
    names = top_names(model)
    if not names:
        return join(sorry, STANDARD_NO_TOTAL), ToolOut(data={}, cards=[card])
    plus = next(
        (line_name(x["name"]) for x in model.get("lines") or [] if "할증" in (x.get("name") or "")),
        "",
    )
    said = join(
        sorry,
        PRICEY_LINES.format(names=" · ".join(names)),
        PRICEY_PLUS.format(name=plus) if plus and plus not in names else "",
        PRICEY_REF,
    )
    return said, ToolOut(data={}, cards=[card])


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
    if not isinstance(total, int):
        return STANDARD_NO_TOTAL, ToolOut(data={}, cards=[card])
    return STANDARD.format(won=f"{total:,}"), ToolOut(data={}, cards=[card])


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
    r"미루|미뤄|미룰|늦추|늦춰|연기\s*(?:하|해|할|요청|돼|되)|앞당기|앞당겨|"
    r"당겨\s{0,2}(?:주|줘|달)|당기고\s{0,2}싶|"
    r"(?:날짜|일정)\S{0,2}\s{0,2}(?:바꾸|바꿔|바꿀|옮기|옮겨|옮길|당기|당겨|당길)"
)
# 앞당기는 말 · 며칠인지 정할 수 없는 때(날짜 없이는 카드를 만들지 않는다)
PULL = re.compile(r"당기|당겨|당길|일찍|빨리")
VAGUE = re.compile(r"다음\s{0,2}달|담달|나중에|언젠가")
NEXT_MONTH = re.compile(r"다음\s{0,2}달|담달")
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
    한 달 …은 날 수, 바라는 때가 없으면 일주일. 날짜 없이 앞당기는 말 · '다음 달로'처럼 며칠인지 정할 수 없는 말은
    (None, None)(날짜를 묻는다: 일주일 뒤로 미루면 반대 방향 · 다른 뜻)."""
    m = MONTH_DAY.search(text)
    if m:
        try:
            got = date(today.year, int(m[1]), int(m[2]))
            return None, got if got > today else date(today.year + 1, got.month, got.day)
        except ValueError:
            pass
    if PULL.search(text):
        return None, None
    m = N_WEEKS.search(text)
    if m and 1 <= int(m[1]) <= 25:
        return int(m[1]) * 7, None
    m = N_DAYS.search(text)
    if m and 1 <= int(m[1]) <= 180:
        return int(m[1]), None
    got = next((n for rx, n in WORD_DELAY if rx.search(text)), None)
    if got is not None:
        return got, None
    if VAGUE.search(text):
        return None, None
    return DEFAULT_DELAY, None


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
    delay, wish = change_wish(text, tc.today)
    if delay is None and wish is None:  # 날짜 없이 앞당기기 · '다음 달로': 날짜를 묻는다(말에 맞춰)
        if PULL.search(text):
            return CHANGE_WHEN_PULL, out
        return (CHANGE_WHEN_NEXT if NEXT_MONTH.search(text) else CHANGE_WHEN), out
    d = next(
        (x for x in deals if x["trade"] in found),
        next((x for x in deals if x["trade"] == "dobae"), deals[0]),
    )
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


# ---- 정해 둔 길(의도 모델 앞) ----


def _extra(text: str) -> tuple[str, ToolOut]:
    """추가금 질문(답할 추가 금액이 있으면 07 길잡이가 먼저 카드로 답했다): 보여 달라면 없다고, 그 밖은 추가 금액 승인 길
    (승인하기 전에는 공사 금액이 바뀌지 않아요)."""
    if EXTRA_SHOW.search(text):
        return aftercare_tools.NO_EXTRAS, ToolOut(data={})
    return EXTRA_HOW, ToolOut(data={})


async def _eve(tc: ToolCtx) -> tuple[str, ToolOut]:
    """공사 전날 준비물(칩 '공사 전날 준비물'): 공정 준비물 카드 + 반셀프 직접 할 일(먼저 말 걸기 work_eve와 같은 카드)."""
    o = await _overview(tc)
    trades = [t.trade for t in o.trades] if o is not None and o.trades else ["dobae"]
    card = cards.prep_card(f"prep-{tc.project_id}", trades)
    if tc.project_id is not None:
        async with SessionLocal() as s:
            card = await diy_tools.eve_card(s, tc.user, tc.project_id, tc.today, card)
    return EVE_SAID, ToolOut(data={}, cards=[card])


def order_said() -> str:
    """공사 전체 순서(공정 순서 값: 다른 공정 알아 두기 자료 + 믿집이 계산하는 도배 · 목공, 같은 값은 · 로 묶음)."""
    from app.knowledge import other_trades

    works = [(t.order, t.work) for t in other_trades.book().trades.values()]
    works += [(order, work) for work, order in other_trades.OWN.values()]
    steps: dict[float, list[str]] = {}
    for order, work in sorted(works):
        steps.setdefault(order, []).append(work)
    return ORDER_SAID.format(order=" → ".join(" · ".join(x) for x in steps.values()))


async def _access(tc: ToolCtx) -> tuple[str, ToolOut]:
    """공사 날 집을 비워도 되는지 · 출입: 정해 둔 글 + 공사 전 할 일 카드(출입 방법 정하기 줄이 있다)."""
    if tc.project_id is None:
        return ACCESS_SAID, ToolOut(data={})
    try:
        async with SessionLocal() as s:
            card = await aftercare_tools.prep_card(s, tc.user, tc.project_id, tc.today)
    except AppError:
        return ACCESS_SAID, ToolOut(data={})
    return join(ACCESS_SAID, ACCESS_CARD), ToolOut(data={}, cards=[card])


def route_of(text: str) -> str | None:
    """정해 둔 길 이름(의도 모델 앞, QA 1차 c1 · c3 · c4 · c5): 비서가 낸 칩과 같은 뜻의 말 · 돈 질문 · 공사 날 생활
    질문. waste · pricey · missing · extra · estimate · visit_what · slots · eve · order · pet · access, 아니면 None(의도
    모델로)."""
    t = text or ""
    if WASTE.search(t):  # 칩 '폐기물 처리도 포함인가요?'
        return "waste"
    if PRICEY.search(t) and (ANGRY.search(t) or WHY_PRICE.search(t) or STRONG_PRICE.search(t)):
        return "pricey"
    # '뭐가 빠진 거 아니에요?' · '빠진 거 없어요?'(받은 견적서가 없으면 표준견적서 포함 상태로)
    if MISSING.search(t) and not NOT_QUOTE.search(t):
        return "missing"
    if EXTRA_ASK.search(t):
        return "extra"
    if ESTIMATE_HOW.search(t):  # 칩 '가견적은 어떻게 계산해요?'
        return "estimate"
    if VISIT_WHAT.search(t):  # 칩 '실측은 무엇을 봐요?'
        return "visit_what"
    if SLOTS_OTHER.search(t) and "공사" not in t:  # 칩 '다른 시간도 볼래요'(공사 날짜 말고 실측)
        return "slots"
    if EVE.search(t) and not NOT_EVE.search(t):  # 칩 '공사 전날 준비물'
        return "eve"
    if WORK_ORDER.search(t) and not trades_in(t):  # 칩 '공사는 어떤 순서로 해요?'
        return "order"
    if QUESTION.search(t) or ASK_WORD.search(t) or "어디" in t:
        if PET.search(t) and PET_DAY.search(t):
            return "pet"
        if ACCESS.search(t):
            return "access"
    return None


async def route(tc: ToolCtx, text: str) -> tuple[str, ToolOut] | None:
    """정해 둔 길의 답. 해당하지 않으면 None(의도 모델로)."""
    name = route_of(text)
    fixed = {"estimate": ESTIMATE_SAID, "visit_what": VISIT_WHAT_SAID, "pet": PET_SAID}
    if name is None:
        return None
    if name in fixed:
        return fixed[name], ToolOut(data={})
    if name == "waste":
        return await _compare(tc, text, [])
    if name == "pricey":
        return await _pricey(tc, text)
    if name == "missing":  # 받은 견적서가 없으면 표준견적서에서 합계에 안 들어간 줄(QA r5 D 1)
        return await _missing(tc, text) or await _missing_standard(tc)
    if name == "extra":
        return _extra(text)
    if name == "slots":
        return await _slots(tc, text, [])
    if name == "eve":
        return await _eve(tc)
    if name == "order":
        return order_said(), ToolOut(data={})
    return await _access(tc)


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
    """글이 말하는 카드가 이 턴에 없으면 만들어 out에 더하고, 못 만들면 그 문장을 뺀다. 남은 글을 돌려준다.
    '믿집 공정표는 …'처럼 일반 규칙을 말한 문장은 카드 말로 보지 않는다."""
    if tc.project_id is None or not text:
        return text
    have = {c.kind for c in out.cards}
    tried: dict[str, bool] = {}
    kept: list[str] = []
    for sent in (x.strip() for x in SENT.split(text) if x.strip()):
        ok = True
        for kind, rx, make in MENTION:
            if not rx.search(sent) or kind in have or GENERIC.search(sent):
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


def other_know(plain: str):
    """다른 공정(믿집이 계산 · 연결하지 않는 공정) 알아 두기(knowledge.other_trades). 걸린 공정이 없으면 None.
    plain은 업체 이름을 뺀 글이에요('마루와벽'의 '마루'는 바닥이 아니에요)."""
    from app.knowledge import service as knowledge

    return knowledge.other_trade_notes(plain)


def other_only(plain: str) -> bool:
    """도배 · 목공 없이 다른 공정만 물었는지. 견적서 말('견적서에 철거 포함')의 철거는 도배 견적 칸이라 빼요."""
    from app.knowledge import other_trades

    codes = other_trades.codes_of(plain)
    if QUOTE_WORD.search(plain):
        codes = [c for c in codes if c != "demolition"]
    return bool(codes) and not set(codes) & set(other_trades.OWN) and other_know(plain) is not None


def know_lines(plain: str, know) -> list[str]:
    """알아 두기 줄 순서: 공정 쌍 순서 글 → (다른 공정 하나의 때 · 바람이면) 그 공정과 도배 순서 → 질문 낱말에 걸린
    주의점 → 나머지(자료의 글 그대로, 숫자 없음)."""
    from app.agent.v3.orchestrator import ORDER_ASK
    from app.knowledge import other_trades

    bk = other_trades.book()
    notes = {n.text: n for t in bk.trades.values() for n in t.notes}
    lines = list(know.lines)
    # 공정 쌍 순서 글(자료 쌍 글 · v3 쌍 글 · 순서 값으로 만든 글)은 공정 글에 없다
    pair = [x for x in lines if x not in notes]
    hit = [x for x in lines if x in notes and notes[x].when and notes[x].when.search(plain)]
    other = [c for c in other_trades.codes_of(plain) if c in bk.trades]
    asks = ORDER_ASK.search(plain) or other_trades.ALONG.search(plain) or WISH.search(plain)
    lead = []
    # '콘센트 위치를 옮기고 싶어요'처럼 다른 공정 하나의 때 · 바람이면 그 공정과 도배 순서부터
    if not pair and not hit and len(other) == 1 and asks:
        lead = [other_trades.pair_line(other[0], "dobae").text]
    return list(dict.fromkeys([*pair, *lead, *hit, *lines]))


def know_said(plain: str, know) -> str:
    """알아 두기 → 무료 모드 글: 순서 · 주의점 두 문장까지 + '믿집은 … 업체를 잇지 않아요'. 돈 · 기간을 물으면
    계산하지 않는다는 말(숫자 없음)."""
    names = " · ".join(know.names[:3])
    if MONEY_DAYS.search(plain):
        return OTHER_MONEY.format(names=names)
    picked: list[str] = []
    for line in know_lines(plain, know):
        parts = sents(line)
        if len(picked) + len(parts) <= 2:
            picked += parts
    return join(*picked, OTHER_LINK.format(names=names))


def tidy(said: str, plain: str) -> str:
    """answer_only 글 다듬기(무료 모드): v3 시작 순서의 단계 번호를 떼고, 단추로 되묻는 글(무료 모드는 단추가 없다)은
    정해 둔 되묻기로 바꾼다. 다른 공정이 섞인 질문은 모르면 알아 두기로 바꾸고, 자리가 있으면 '잇지 않아요'를 붙인다."""
    from app.agent.v3 import templates

    said = STEP_NO.sub("", (said or "").strip())
    if said.startswith(templates.ASK_BACK):
        return FREE_ASK
    know = other_know(plain)
    if know is None:
        return said
    if not said or UNKNOWN.search(said):
        return know_said(plain, know)
    if len(sents(said)) < 3 and "잇지 않" not in said and "연결하지 않" not in said:
        return join(said, OTHER_LINK.format(names=" · ".join(know.names[:3])))
    return said


async def _knowledge(
    tc: ToolCtx,
    text: str,
    found: list[str],
    card_id: str | None,
    step: str | None = "gate",
    plain: str | None = None,
) -> tuple[str, ToolOut]:
    """지식 · 공통 질문: 단계 카드 + answer_only(공사 단계 화면, 목공만 물으면 목공 담당).
    step: 'gate'면 입구 관문 길의 단계 카드, 길 이름(guide …)이면 그 길의 카드, None이면 카드 없음.
    고객이 다른 공정만 물으면 알아 두기 자료로 답한다(카드 · answer_only 없이, QA 1차 c5: 배관+장판 '확인하지 못했어요')."""
    from app.agent.v3 import gate as gate_mod
    from app.agent.v3.schemas import Button
    from app.chat import service as chat_service

    out = ToolOut(data={})
    plain = text if plain is None else plain
    customer = tc.surface == "customer"
    if customer and other_only(plain):
        return know_said(plain, other_know(plain)), out
    if customer and step is not None:
        path = (
            gate_mod.gate(text, has_project=tc.project_id is not None).route
            if step == "gate"
            else step
        )
        card = await cards.step_card(tc, path)
        if card is not None:
            out.cards.append(card)
    button = Button(route="trade", trade="mokgong") if found == ["mokgong"] else None
    view = await view_for(tc, card_id) if customer else None
    query = f"{text} 순서" if found and WHEN_WORK.search(text) else text
    try:
        ans = await chat_service.answer_only(
            tc.user,
            query,
            tc.today,
            project_id=tc.project_id if customer else None,
            mode="free",
            view=view,
            button=button,
        )
        said = ans.text
    except AppError:
        said = ""
    return (tidy(said, plain) if customer else said), out


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
    if intent == "decline" and aftercare_tools.unsure(text):
        return None  # '못 받으면 불이익 있어요?'는 묻는 말: 못 받아요 카드 없이 브리핑 + 지식 답(열린 카드는 그대로)
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


# ---- 취소 · 거두기(피클 표본 7): 열린 승인 카드는 거두고, 보낸 실측 요청은 취소 승인 카드, 여럿이면 고르기 칩 ----

CANCEL = re.compile(r"취소|거둬|거두|거둘|철회|없던\s{0,2}(?:일|걸|것)")
# 말한 카드 종류(고객 말 → 승인 카드 종류). 보낸 요청도 '실측 요청'으로 부른다
CANCEL_KIND: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("home_info", re.compile(
        r"집\s{0,2}정보|면적|평수|평형|방\s{0,2}개수|철거\s{0,2}범위|직접\s{0,2}할\s{0,2}일"
    )),
    ("visit_request", re.compile(r"실측\s{0,2}요청|요청\s{0,2}카드|예약")),
    ("visit_slot", re.compile(r"실측\s{0,2}(?:시간|날짜|일정)|반나절|시간\s{0,2}카드")),
    ("vendor_confirm", re.compile(r"확정")),
    ("dates_accept", re.compile(r"수락")),
    ("delay_accept", re.compile(r"수락")),
    ("date_change", re.compile(r"날짜\s{0,2}바꾸기|연기|미루")),
    ("extra_answer", re.compile(r"추가\s{0,2}금액")),
    ("work_check", re.compile(r"공사\s{0,2}끝|끝\s{0,2}확인")),
    ("visit_again", re.compile(r"한\s{0,2}번\s{0,2}더")),
)  # fmt: skip
SENT_WORD = re.compile(r"보낸|보냈|보내\s{0,2}(?:둔|놓은|놨)|이미|요청한|예약한")
CARD_WORD = re.compile(r"카드")
EXTRA_WORD = re.compile(r"추가\s{0,2}금액")
CANCEL_WHY = (
    ("other_vendor", re.compile(r"다른\s{0,2}(?:업체|곳|데)|딴\s{0,2}(?:업체|곳|데)")),
    ("changed", re.compile(r"일정|날짜|바빠|바쁘|사정|미뤄|미루|연기|이사")),
)
CANCEL_DONE = "네, {title} 카드를 거뒀어요! 다른 걸로 보시려면 말씀해 주세요."
CANCEL_MADE = "{vendor}에 보낸 실측 요청을 취소하는 카드를 만들었어요. 카드를 누르시면 취소되고 업체에도 알림이 가요."
CANCEL_SAME = "같은 실측 요청 취소 카드가 이미 있어요. 그 카드를 확인하고 눌러 주세요."
CANCEL_REJECTED = (
    "앞에서 거절한 실측 요청 취소 카드와 같아요. 취소는 실측 일정 화면에서도 할 수 있어요."
)
CANCEL_PICK = "무엇을 취소할까요? 아래에서 골라 주세요."
CANCEL_NONE = "지금 거둘 승인 카드나 취소할 실측 요청이 없어요."
CANCEL_CLOSED = "그 카드는 이미 처리됐어요."
# 말로 고른 보낸 요청이 여럿('둘 다 취소해 줘', QA r5 D 3): 요청마다 취소 승인 카드(propose.cancel_many)
CANCEL_MANY_MADE = (
    "{names}에 보낸 실측 요청을 하나씩 취소하는 카드를 만들었어요. 카드마다 누르시면 그 요청이 취소되고 업체에도 "
    "알림이 가요."
)
CANCEL_MANY_SAME = "같은 실측 요청 취소 카드가 이미 있어요. 카드마다 확인하고 눌러 주세요."


def cancel_said(text: str) -> bool:
    """거두기 · 취소를 부탁하는 말인지(묻는 말 · 가정 '취소하면 …?'은 아니다)."""
    return bool(CANCEL.search(text or "")) and not aftercare_tools.unsure(text)


async def _cancel(tc: ToolCtx, text: str) -> tuple[str, ToolOut] | None:
    """'취소해 줘': 후보(열린 승인 카드 · 보낸 실측 요청)를 말로 좁힌다. '카드'면 카드만, '보낸 · 이미'면 보낸 요청만,
    카드 제목(고르기 칩이 보낸 말) · 업체 이름 · 카드 종류 낱말이 있으면 그것만. 보낸 요청은 LLM 길과 같은 풀기
    (propose.cancel_targets: 업체 이름 · '둘 다 · 모두' · '…는 남기고 · … 빼고', QA r5 D 3)로 좁히고, 이미 열린 그
    요청의 취소 카드는 따로 세지 않는다(같은 말이 또 오면 같은 카드). 하나면 카드는 바로 거두고(실행 전이라 고객 말로
    된다) 보낸 요청은 취소 승인 카드(업체에 알림이 가니 한 번 누름을 남긴다), 말로 고른 요청이 여럿이면 요청마다 취소
    승인 카드, 못 풀면 고르기 칩(보낸 요청이 둘 이상이면 '둘 다 · 모두 취소', propose.cancel_options와 같은 말). 추가
    금액 말인데 거둘 카드가 없으면 None(추가 금액 길로)."""
    from app.assistant.tools import propose

    pid = tc.project_id
    async with SessionLocal() as s:
        rows = await propose.open_cards(s, tc.user.id, pid, tc.now)  # type: ignore[arg-type]
        visits = await cards.sent_visits(s, tc.user, pid)  # type: ignore[arg-type]
    cands: list[tuple[str, object]] = [("card", a) for a in rows] + [("visit", v) for v in visits]
    card_only, sent_only = bool(CARD_WORD.search(text)), bool(SENT_WORD.search(text))
    if card_only != sent_only:  # 느슨한 낱말이라 그쪽에 없으면 좁히지 않는다('보낸 요청 카드')
        side = "card" if card_only else "visit"
        cands = [c for c in cands if c[0] == side] or cands
    said = propose.plain(text)
    titled = [c for c in cands if c[0] == "card" and propose.plain(propose.title_of(c[1])) in said]
    cands = titled or cands
    names = [n for n in await vendor_names(tc) if propose.plain(n) and propose.plain(n) in said]
    # 카드는 업체 이름이 든 것만(보낸 요청은 아래 풀기로: '결도배 빼고 다'는 결도배가 아니에요)
    if names:
        cands = [
            c
            for c in cands
            if c[0] == "visit" or any(propose.plain(n) in propose.haystack(c[1]) for n in names)
        ]
    kinds = {k for k, rx in CANCEL_KIND if rx.search(text)}
    if kinds and not titled:
        cands = [
            c
            for c in cands
            if (c[0] == "card" and c[1].kind in kinds)  # type: ignore[attr-defined]
            or (c[0] == "visit" and "visit_request" in kinds)
        ]
    vis = [v for k, v in cands if k == "visit"]
    picked = propose.cancel_targets(vis, text) if vis else []
    if picked:
        vis = picked
    elif names:
        # 못 풂: 말한 업체는 남기는 쪽('…는 남기고')이고, 말한 업체에 살아 있는 요청이 없으면 비워요
        named = [v for v in vis if propose.plain(v.vendor_name) in said]  # type: ignore[attr-defined]
        vis = [v for v in vis if v not in named] if named else []
    ids = {v.id for v in vis}  # type: ignore[attr-defined]
    opened = [
        a
        for k, a in cands
        if k == "card" and not (a.kind == "visit_cancel" and a.target_id in ids)  # type: ignore[attr-defined]
    ]
    cands = [("card", a) for a in opened] + [("visit", v) for v in vis]
    if not cands:
        return (
            None
            if EXTRA_WORD.search(text)
            else (join(CANCEL_NONE, await now_tail(tc)), ToolOut(data={}))
        )
    if len(vis) > 1 and picked and not opened:  # '둘 다 취소해 줘': 요청마다 취소 승인 카드
        return await _cancel_many(tc, text, vis)
    if len(cands) > 1:
        options = propose.unique_say(opened)
        if vis:  # 보낸 요청 칩은 LLM 길과 같은 말 · 보내는 말('둘 다 · 모두 취소' 칩 포함)
            got = propose.cancel_options(vis).data["options"]
            # 일부만 남았으면 '둘 다 · 모두' 칩은 빼요(그 칩 말은 살아 있는 요청 모두예요)
            if len(vis) < len(visits):
                got = got[: len(vis)]
            options += [(o["label"], o["say"], o.get("sub")) for o in got]
        card = cards.options_card("cancel-pick", "무엇을 취소할까요?", options)
        return CANCEL_PICK, ToolOut(data={}, cards=[card])
    kind, it = cands[0]
    if kind == "card":
        out, state = await propose.withdraw_one(tc, it)
        if state == "withdrawn":
            return CANCEL_DONE.format(title=propose.title_of(it)), out
        return CANCEL_CLOSED, out
    code = next((c for c, rx in CANCEL_WHY if rx.search(text)), "other")
    ref = propose.requests_model(tc, [it])[0]["ref"]
    try:
        got = await propose.propose_visit_cancel(
            tc,
            propose.VisitCancelIn(visit_ref=ref, code=code),  # type: ignore[arg-type]
        )
    except ToolError as e:
        return e.message, ToolOut(data={})
    said_by = {
        "new": CANCEL_MADE.format(vendor=it.vendor_name),  # type: ignore[attr-defined]
        "same": CANCEL_SAME,
        "rejected": CANCEL_REJECTED,
    }
    return said_by.get(str(got.data.get("state")), CANCEL_CLOSED), got


async def _cancel_many(tc: ToolCtx, text: str, visits: list) -> tuple[str, ToolOut]:
    """말로 고른 보낸 요청 여럿 → 요청마다 취소 승인 카드(propose.cancel_many, LLM 길과 같은 카드). 열린 같은 카드는
    다시 보이고, 앞에서 거절한 카드는 말로 다시 만들지 않아요."""
    from app.assistant.tools import propose

    code = next((c for c, rx in CANCEL_WHY if rx.search(text)), "other")
    try:
        got = await propose.cancel_many(tc, visits, code, tc.project_id)  # type: ignore[arg-type]
    except ToolError as e:
        return e.message, ToolOut(data={})
    items = got.data.get("items") or []
    live = [x for x in items if x.get("state") in ("new", "same")]
    if not live:
        rejected = any(x.get("state") == "rejected" for x in items)
        return (CANCEL_REJECTED if rejected else CANCEL_CLOSED), got
    if all(x.get("state") == "same" for x in live):
        return CANCEL_MANY_SAME, got
    return CANCEL_MANY_MADE.format(names=" · ".join(x["vendor_name"] for x in live)), got


# ---- 알림 부탁(QA r5 D 2: '업체 답 오면 알려 줘'가 업체 추천 길로 가 같은 글 두 번) ----

# 무엇이 오면(-면 · -거든 · -는 대로) 알려 · 말해 달라는 말. 업체가 연락하는지 묻는 말('실측 끝나면 연락해 줘요?')과
# 알리지 말라는 말은 아니에요. '공사가 미뤄지면 알려 주세요'도 여기(날짜 바꾸기 요청 카드로 가지 않게)
NOTIFY_ASK = re.compile(
    r"(?:오|나오|올라오|들어오|생기|되|남|끝나|정해지|잡히|바뀌|미뤄지|늦어지|당겨지|떨어지|내려가|답하|보내|"
    r"올리|끝내|도착하)"
    r"으?시?(?:면|거든|는\s{0,2}대로)\s{0,2}"
    r"(?:(?:바로|꼭|좀|곧|곧바로|먼저|빨리|저한테|나한테|제게|저에게|(?:문자|메일|카톡|전화|알림)으?로)\s{0,2})*"
    r"(?:알려|알림|말해|말씀해|얘기해|이야기해|귀띔)"
)
NOT_NOTIFY = re.compile(
    r"(?:알려|말해|알림)\S{0,2}\s{0,2}주지\s{0,2}(?:마|말)|알림\S{0,2}\s{0,2}(?:끄|꺼|싫|그만|말고|빼)"
)
# 믿집이 먼저 알리는 일(먼저 말 걸기 트리거 · 조사 알림, docs/v4/07-automation.md): 말에서 위에서부터 처음 맞는 것
NOTIFY_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("extra", re.compile(r"추가\s{0,2}(?:금액|금|비용|공사비|요금)")),
    ("research", re.compile(r"조사")),
    ("quote", re.compile(r"(?<!가)견적|실측\S{0,3}\s{0,2}(?:다\s{0,2})?(?:끝|마치|마무리)")),
    ("done", re.compile(r"(?:공사|시공|도배|목공)\S{0,3}\s{0,2}(?:다\s{0,2})?(?:끝|마치|마무리|완료)")),
    ("week", re.compile(r"일주일|한\s{0,2}주\s{0,2}(?:전|남)")),
    ("eve", re.compile(r"전날|하루\s{0,2}전")),
    ("reply", re.compile(r"답|연락|회신|수락|기간|실측")),
    ("dates", re.compile(r"날짜|일정|미뤄|늦어|연기|당겨")),
)  # fmt: skip
# 일마다 (약속 글의 때, 바로 앞과 같을 때 짧은 글의 때). {who}는 답 기다리는 업체('결도배 · 마루와벽이')
NOTIFY_WHEN: dict[str, tuple[str, str]] = {
    "reply": ("{who} 답하면", "답이 오면"),
    "quote": ("실측 견적서가 오면", "견적서가 오면"),
    "dates": ("업체가 공사 날짜를 올리거나 바꾸자고 하면", "공사 날짜 소식이 오면"),
    "extra": ("업체가 추가 금액을 올리면", "추가 금액이 올라오면"),
    "research": ("맡기신 조사가 끝나면", "조사가 끝나면"),
    "done": ("업체가 공사를 끝냈다고 올리면", "공사가 끝나면"),
    "week": ("공사 일주일 전에", "일주일 전에"),
    "eve": ("공사 전날에", "전날에"),
}
NOTIFY_SAID = "{when} 먼저 알려 드려요."
NOTIFY_AGAIN = "네, {when} 알려 드릴게요."
# 믿집이 먼저 알리지 않는 일('가격 떨어지면 알려 줘'): 약속하지 않고 먼저 알리는 일을 말해요
NOTIFY_LIST = (
    "믿집은 업체 답 · 견적서 · 공사 날짜 · 추가 금액 · 조사 결과 · 공사 끝 소식과 공사 일주일 전 · 전날 할 일을 "
    "먼저 알려 드려요."
)
NOTIFY_LIST_AGAIN = "업체 답 · 견적서 · 공사 날짜 같은 공사 소식만 먼저 알려 드려요."
NOTIFY_APP = "문자 · 메일 · 전화가 아니라 믿집 알림으로 가요."
# 미뤄 둔 알림(밤 · 하루 상한으로 미룬 먼저 말 걸기 줄)이 있을 때만 그 수와 갈 때를 말해요. 업체 답 같은 종 알림 · 대화
# 줄은 밤에도 바로 가서 '밤 알림은 아침 9시에 가요'는 사실과 달랐어요(QA r6 c1 M10, 턴 사실 '알림' 줄과 같은 값)
NOTIFY_LATER = "미뤄 둔 알림 {n}개는 {at}에 가요."
CHANNEL_WORD = re.compile(r"문자|메일|카톡|카카오|전화")
WAIT_REPLY = ("requested", "picked")  # 업체 답을 기다리는 요청(기간 답하기 · 고른 시간 수락)


def notify_asked(text: str) -> bool:
    """소식이 오면 알려 달라는 말인지('업체 답 오면 알려 줘' · '연락 오면 말해 줘')."""
    t = text or ""
    return bool(NOTIFY_ASK.search(t)) and not NOT_NOTIFY.search(t)


def notify_kind(text: str) -> str | None:
    """알려 달라는 일(NOTIFY_KINDS 이름). 믿집이 먼저 알리는 일이 아니면 None."""
    return next((k for k, rx in NOTIFY_KINDS if rx.search(text or "")), None)


def is_night(now: datetime) -> bool:
    """먼저 말 걸기 규칙(proactive.RULES)의 밤 때인지(알림을 아침으로 미루는 때)."""
    from app.assistant import proactive

    return proactive.RULES.night(now)


def morning_at() -> str:
    """밤 알림이 가는 아침 시각 글(먼저 말 걸기 규칙 값, '아침 9시')."""
    from app.assistant import proactive
    from app.shared import kdate

    return kdate.hour_text(proactive.RULES.night_to)


def notify_lines(kind: str | None, who: str) -> tuple[str, str]:
    """(약속 글, 바로 앞 답과 같을 때 짧은 글). 믿집이 먼저 알리지 않는 일이면 먼저 알리는 일을 말해요."""
    if kind is None:
        return NOTIFY_LIST, NOTIFY_LIST_AGAIN
    when, short = NOTIFY_WHEN[kind]
    return NOTIFY_SAID.format(when=when.format(who=who)), NOTIFY_AGAIN.format(when=short)


async def later_line(tc: ToolCtx) -> str:
    """미뤄 둔 알림 줄(repo.deferred_nudges 수 · 가장 이른 갈 때, service.deferred_at). 없으면 빈 글."""
    from app.assistant import repository as repo
    from app.assistant import service

    async with SessionLocal() as s:
        n, due = await repo.deferred_nudges(s, tc.user.id, "customer", tc.project_id, tc.now)
    if n <= 0 or due is None:
        return ""
    return NOTIFY_LATER.format(n=n, at=service.deferred_at(due, tc.now))


async def _notify(tc: ToolCtx, text: str) -> tuple[str, ToolOut]:
    """알림 부탁: 믿집이 먼저 알리는 일만 약속(업체 답이면 답 기다리는 업체 이름, 계산 · 저장 값만). 문자 · 전화로
    알려 달라면 믿집 알림으로 간다는 말, 미뤄 둔 알림이 있을 때만 그 수와 갈 때를 붙이고(밤이라고 늘 붙이지 않아요),
    바로 앞 답과 같은 글이면 짧게."""
    kind = notify_kind(text)
    who = "업체가"
    if kind == "reply":
        o = await _overview(tc)
        names = dict.fromkeys(
            v.vendor_name for v in (o.vendors if o else []) if v.status in WAIT_REPLY
        )
        if names:
            who = i_ga(" · ".join(names))
    full, short = notify_lines(kind, who)
    tail = (NOTIFY_APP if CHANNEL_WORD.search(text) else "", await later_line(tc))
    said = join(full, *tail)
    if await said_last(tc, said):
        said = join(short, *tail)
    return said, ToolOut(data={})


# ---- 한 턴 ----


def _lead(text: str, said: str, out: ToolOut) -> tuple[str, ToolOut]:
    """'네가 알아서 확정해' → 대신 고르거나 확정할 수 없다는 말을 먼저(세 문장 안일 때). 실행은 카드 단추로만."""
    if DELEGATE.search(text) and len(sents(said)) < 3:
        said = join(DELEGATE_SAID, said)
    return said, out


# 지난 턴과 글자까지 같은 답이면 짧게(QA 3차 f1x 11~13 추가 금액 세 턴 · 15 · 16 날짜 · f1 6 · 7 연락처). 짧게 바꾼 다음
# 턴에 같은 말이 또 오면 원래 글이라 이어서 같은 글이 되지 않는다
AGAIN: dict[str, str] = {
    aftercare_tools.EXTRAS: "위 추가 금액 카드에서 승인 · 거절 · 채팅으로 묻기 중 하나를 골라 주세요.",
    CHANGE_WHEN: "바꿀 날짜만 말해 주시면 날짜 바꾸기 요청 카드를 만들어 드릴게요.",
    CHANGE_WHEN_PULL: "당길 날짜만 말해 주시면 날짜 바꾸기 요청 카드를 만들어 드릴게요.",
    CHANGE_WHEN_NEXT: "다음 달 며칠부터인지만 말해 주시면 날짜 바꾸기 요청 카드를 만들어 드릴게요.",
    CHANGE_HOW: "'2주 미뤄 주세요'처럼 말해 주시면 날짜 바꾸기 요청 카드를 만들어 드릴게요.",
    CONTACT_SAID: "그것도 제가 업체에 전하지 않아요. 업체와는 믿집 채팅으로 이야기해 주세요.",
    QUOTES: "카드에서 견줘 보고 확정할 업체를 골라 주세요.",
    CANCEL_PICK: "취소할 것을 아래 칩에서 골라 주세요.",  # QA r5 D 3: 같은 고르기 글 되풀이
}


async def said_last(tc: ToolCtx, said: str) -> bool:
    """바로 앞 비서 답이 이 글과 글자까지 같은지(대화가 없으면 아니에요)."""
    return tc.chat_id is not None and said in (await recent_said(tc, 4))[-1:]


async def answer(tc: ToolCtx, text: str, card_id: str | None) -> tuple[str, ToolOut]:
    """무료 모드 답 한 번(글, 카드 · 행동 · 작업 카드). 글이 비면 부르는 쪽이 실패 문구를 쓴다. 지난 턴 답과 글자까지
    같은 정해 둔 글이면 짧은 글(AGAIN)로 바꾼다(알림 부탁 답은 _notify가 같은 꼴로 줄인다)."""
    said, out = await _answer(tc, text, card_id)
    short = AGAIN.get(said)
    if short and await said_last(tc, said):
        said = short
    return said, out


async def _answer(tc: ToolCtx, text: str, card_id: str | None) -> tuple[str, ToolOut]:
    if policy.small_talk(text) or policy.ack(text):  # 인사 · 맞장구만: 카드 · 지식 답 없이 한 문장
        return (SMALL_TALK_HI if HELLO.search(text) else SMALL_TALK), ToolOut(data={})
    # 지시문 · 연락처 · 잡담 · 영어 답 · 화난 말은 의도 모델 앞에서 거른다
    if (got := await guard(tc, text)) is not None:
        return got
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
    # '취소해 줘' · '그 카드 거둬 줘': 열린 카드 거두기 · 보낸 실측 요청 취소 카드 · 여럿이면 고르기 칩
    if (
        tc.project_id is not None
        and cancel_said(text)
        and (got := await _cancel(tc, text)) is not None
    ):
        return got
    if (more := await aftercare_tools.free_answer(tc, text)) is not None:  # 07 자동화 카드
        return more
    if MEMORY_SAY_RX.search(text) and not_kept(text):  # '기억해: 내 예산은 …' → 기억하지 않는 것
        return MEMORY_SAY, ToolOut(data={})
    if LEGAL_RX.search(text):  # 내용증명 · 소송: 법률 판단은 하지 않는다
        return LEGAL, ToolOut(data={})
    if (more := await diy_tools.free_answer(tc, text)) is not None:  # 반셀프 직접 할 일 카드
        return more
    # 업체 이름을 뺀 뒤 공종을 찾는다(업체 이름 속 '마루' · '목공'은 공종 말이 아니에요)
    plain = without_names(text, await vendor_names(tc))
    found = trades_in(plain)
    if tc.project_id is None:
        return await _knowledge(tc, text, found, card_id, plain=plain)
    # '업체 답 오면 알려 줘': 먼저 알리는 일만 약속(업체 추천 · 날짜 바꾸기 앞, QA r5 D 2)
    if notify_asked(text):
        return await _notify(tc, text)
    if CHANGE.search(text) and not NOT_CHANGE.search(text):  # 공사 날짜 바꾸기 요청 승인 카드로
        return await _change(tc, text, found)
    if (got := await route(tc, text)) is not None:  # 칩 · 돈 · 생활 질문(의도 모델 앞)
        return _lead(text, *got)
    intent, step = customer_intent(text)
    # 견적서의 철거 · 폐기물은 도배 견적 칸이에요(다른 공정 아님)
    quote_part = intent == "compare" or bool(QUOTE_WORD.search(text))
    link = [c for c in found if not (c == "demolition" and quote_part)]
    if intent in LINKED and link and "dobae" not in link:  # 업체 연결은 아직 도배만
        _, out = await _today(tc, text, found)
        if "mokgong" in link:
            return f"{policy.DOBAE_ONLY} 도배 쪽 오늘 할 일을 보여 드릴게요.", out
        # 바닥 · 욕실 · 전기 …(범위 밖 공정): 되받기(공정 이름) · 솔직 · 지금 할 일 + 오늘 할 일 카드
        word = trade_name(link[0])
        return await off_answer(tc, "trade", word, echo=echo_ok(text)), out
    # 조건 · 사정을 알려 준 말('주말에만 시간이 되고 강아지가 있어요'): 고마움 + 오늘 할 일
    if intent is None and step == "guide" and prefs_said(text):
        _, out = await _today(tc, text, found)
        return PREFS, out
    # 다른 공정만 물음('콘센트 위치를 옮기고 싶어요'): 알아 두기 자료(업체 연결 의도는 위에서 도배로 갈랐다)
    if intent not in LINKED and other_only(plain):
        return await _knowledge(tc, text, found, card_id, None, plain)
    handler = CUSTOMER_DO.get(intent or "")
    got = await handler(tc, text, found) if handler is not None else None
    if got is not None:
        return _lead(text, *got) if intent in (*LINKED, "schedule") else got
    # handler가 카드를 못 만들면: 잠긴 집 정보(home)는 카드 없이 답만, 그 밖(목공 표준견적서 없음 등)은
    # 지금처럼 입구 관문 길의 단계 카드
    if handler is not None:
        step = None if intent == "home" else "gate"
    said, out = await _knowledge(tc, text, found, card_id, step, plain)
    return await fit_cards(tc, said, out), out
