"""대신 연락 규칙 (순수 함수): 야간 금지, 하루 경계(서울), 메시지 끝의 발신자 · 수신거부 표시.

정보통신망법 제50조: 오후 9시 ~ 다음 날 오전 8시에는 보내지 않고, 보낸 곳의 이름 · 연락처와 수신거부 방법을 밝힌다.
가견적 요청이 광고성 정보인지는 아직 법무 검토 전이라, 광고가 아니어도 같은 규칙을 지킨다.
"""

from datetime import datetime, time

from app.shared.clock import SEOUL

NIGHT_FROM, NIGHT_UNTIL = 21, 8


def is_night(now: datetime) -> bool:
    hour = now.astimezone(SEOUL).hour
    return hour >= NIGHT_FROM or hour < NIGHT_UNTIL


def day_start(now: datetime) -> datetime:
    """서울 날짜로 오늘 0시 (하루 한도를 셀 때)"""
    return datetime.combine(now.astimezone(SEOUL).date(), time(0), tzinfo=SEOUL)


def optout_url(web_url: str, token: str) -> str:
    return f"{web_url.rstrip('/')}/opt-out?t={token}"


def compose(body: str, *, sender_contact: str, optout_link: str) -> str:
    """고객이 동의한 글 + 발신자(믿집) 표시 + 수신거부 링크"""
    return (
        f"{body.strip()}\n\n"
        "[믿집] 믿집 고객의 가견적 요청을 대신 전해 드려요.\n"
        f"보낸 곳: 믿집 {sender_contact}\n"
        f"받지 않으려면: {optout_link}"
    )
