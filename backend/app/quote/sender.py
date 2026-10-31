"""대신 연락을 보내는 쪽 (외부 경계). 지금은 보내지 않고 기록만 하는 DryRunSender 하나뿐이다.

실제 문자 · 메일 발송사를 붙이려면 Sender를 따르는 클래스를 더하고, 그 전에 법무 검토 · 발신번호 사전등록 ·
전송자격인증(정보통신망법 제50조의3)을 마친다. models의 sender 제약(dry_run)도 migration으로 넓힌다.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outgoing:
    channel: str  # sms · email · form
    to: str
    text: str


class SendError(Exception):
    """보내지 못함. reason은 로그용 짧은 이름이다 (받는 곳 · 내용을 넣지 않는다)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Sender(Protocol):
    name: str  # contact_requests.sender에 남는 이름
    test: bool  # True면 실제로 보내지 않는다 (상태가 sent가 아니라 test_sent)

    async def send(self, msg: Outgoing, *, idempotency_key: str) -> None:
        """idempotency_key(요청 id)가 같으면 한 번만 보낸다. 실제 발송사에는 멱등 키로 넘긴다."""
        ...


class DryRunSender:
    """보내지 않는다. 보냈을 메시지를 메모리에만 두고, 로그에는 수단과 글자 수만 남긴다."""

    name = "dry_run"
    test = True

    def __init__(self) -> None:
        self.outbox: list[Outgoing] = []
        self.keys: list[str] = []

    async def send(self, msg: Outgoing, *, idempotency_key: str) -> None:
        if idempotency_key in self.keys:
            log.info("같은 요청이라 다시 기록하지 않았어요: %s", msg.channel)
            return
        self.keys.append(idempotency_key)
        self.outbox.append(msg)
        log.info("대신 연락을 기록만 했어요 (보내지 않음): %s, %d자", msg.channel, len(msg.text))
