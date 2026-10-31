"""가견적 작업 (arq). worker.py가 functions에 한 줄씩 등록한다."""

from app.db import SessionLocal
from app.quote import service
from app.quote.sender import DryRunSender
from app.shared.clock import now_utc


async def dispatch_contact_requests(ctx: dict) -> dict:
    """queued 대신 연락을 보낸다. 지금 보내는 쪽은 DryRunSender(기록만)뿐이다.

    CONTACT_SEND_ENABLED가 false(기본)면 아무것도 하지 않는다. 같은 작업이 겹치지 않게
    _job_id="dispatch_contact_requests"로 넣는다.
    """
    sender = ctx.get("sender") or DryRunSender()
    async with SessionLocal() as s:
        return await service.dispatch_contacts(s, sender, now=now_utc())
