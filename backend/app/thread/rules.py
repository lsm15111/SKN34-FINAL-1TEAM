"""채팅 글 규칙 (순수 함수, AI를 부르지 않는다 · 유료 0).

- 주의 줄(D05 A): 업체 글이 믿집 밖 거래를 권하는 꼴이면 `offsite`. 고객 화면에만 한 줄을 붙이고 막지 않는다.
  낱말 목록은 security-01 · dev-05 규칙(현금 · 계좌 · 입금 · 선입금 · 따로 계약 · 직거래 · 수수료 없이 ·
  카톡 아이디 · 오픈채팅 · 외부 링크 · 은행 이름 근처 10~14자리 숫자)이다.
- 동 · 호 꼴(I7 B): 고객 글에 '101동 1203호' 꼴이 있으면 전날 알림이 '동 · 호를 보냈어요'로 본다.
- 번호 · 주소는 가리지 않는다(D05 A). 결과는 참 · 거짓만 쓰고 원문을 로그에 남기지 않는다.
"""

import re

# 은행 이름 (계좌 꼴은 이 이름 근처의 숫자 10~14자리). 흔한 말과 같은 이름('우리 팀장' · '제일 빠른 날' ·
# '하나만')은 '은행'이 붙을 때만 봐요(전화번호를 계좌로 본 오탐, 점검 R4#9)
_BANKS = "국민|신한|농협|카카오뱅크|카뱅|토스|케이뱅크|새마을|우체국|수협|신협|씨티|SC제일"
_BANKS_WORD = "우리|하나|기업|제일|부산|대구|경남|광주|전북|제주|산업"
_ACCOUNT = re.compile(
    rf"(?:(?:{_BANKS})(?:은행)?|(?:{_BANKS_WORD})\s?은행)\D{{0,8}}((?:\d[\s-]?){{10,14}})"
)
OFFSITE_WORDS = (
    r"현금",
    r"계좌",
    r"선?입금",
    r"직거래",
    r"계약\s*은?\s*따로",
    r"따로\s*(?:계약|거래|진행|하시|해\s*드|하면)",
    r"수수료\s*(?:없이|빼|아끼|안\s*나가)",
    r"카톡\s*(?:아이디|id)",
    r"카카오\s*톡?\s*(?:아이디|id)",
    r"오픈\s*채팅",
    r"open\.kakao",
    r"텔레그램",
    r"https?://",
    r"www\.",
)
_OFFSITE = re.compile("|".join(OFFSITE_WORDS), re.IGNORECASE)
# '101동 1203호' · '101 동 1203 호' (전각 숫자도 \d에 든다)
_ADDRESS = re.compile(r"\d{1,4}\s*동\s*\d{1,5}\s*호")


def offsite(text: str | None) -> bool:
    """믿집 밖 거래를 권하는 꼴인지 (업체 글에만 쓴다)"""
    if not text:
        return False
    return bool(_OFFSITE.search(text) or _ACCOUNT.search(text))


def has_address(text: str | None) -> bool:
    """'○○동 ○○호' 꼴이 있는지 (고객 글에만 쓴다)"""
    return bool(text and _ADDRESS.search(text))
