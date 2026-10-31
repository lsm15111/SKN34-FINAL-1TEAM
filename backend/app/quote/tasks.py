"""가견적 작업 (arq). worker.py가 functions에 한 줄씩 등록한다."""

from app.db import SessionLocal
from app.quote import service
from app.quote.sender import DryRunSender
from app.shared.clock import now_utc


async def dispatch_contact_requests(ctx: dict) -> dict:
    """queued 대신 연락을 선점하고 보낸다. 지금 보내는 쪽은 DryRunSender(기록만, test_sent)뿐이다.

    CONTACT_SEND_ENABLED가 false(기본)면 아무것도 하지 않는다. 작업이 겹쳐도 선점이 한 번만 되지만,
    손으로 넣을 때도 _job_id="dispatch_contact_requests"로 넣는다.
    """
    sender = ctx.get("sender") or DryRunSender()
    async with SessionLocal() as s:
        return await service.dispatch_contacts(s, sender, now=now_utc())


async def fail_stuck_contacts(ctx: dict) -> dict:
    """sending에 오래 멈춘 대신 연락을 failed(확인 필요)로 돌린다. 다시 보내지 않는다."""
    async with SessionLocal() as s:
        return await service.fail_stuck_contacts(s, now=now_utc())
