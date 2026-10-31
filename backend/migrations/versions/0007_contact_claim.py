"""대신 연락: 보내기 전 선점(sending) · 시험 발송(test_sent) · 멈춘 발송(stuck)

Revision ID: 0007_contact_claim
Revises: 0006_directory_keep_consent
Create Date: 2026-11-01

열(claimed_at)은 autogenerate로 확인했고, CHECK와 데이터 바로잡기는 손으로 썼다.
- 예전에 dry_run이 '보냄(sent)'으로 남긴 것은 시험 발송(test_sent)으로 바꾼다. 이력도 같이 바로잡는다.
- failed는 이제 선점 뒤에만 생긴다. 예전 실패에는 보낸 쪽(dry_run)과 선점한 때를 채운다.
되돌리기는 test_sent를 예전 모양(sent + dry_run)으로 돌린다. sending이나 'stuck' 이력이 남아 있으면
예전 CHECK를 만들지 못해 멈춘다 (기록을 지우지 않는다).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_contact_claim"
down_revision: str | Sequence[str] | None = "0006_directory_keep_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REQ, EVENTS = "contact_requests", "contact_request_events"
OLD = "('draft', 'queued', 'sent', 'failed', 'blocked')"
NEW = "('draft', 'queued', 'sending', 'sent', 'test_sent', 'failed', 'blocked')"
CLAIMED = "('sending', 'sent', 'test_sent', 'failed')"
OLD_REASONS = "('consent', 'opted_out', 'no_contact', 'closed', 'send_error')"
NEW_REASONS = "('consent', 'opted_out', 'no_contact', 'closed', 'send_error', 'stuck')"

OLD_CHECKS = {
    REQ: {
        "status": f"status in {OLD}",
        "sent": "(status = 'sent') = (sent_at is not null)",
        "sender": "(status = 'sent') = (sender is not null)",
    },
    EVENTS: {
        "from_status": f"from_status is null or from_status in {OLD}",
        "to_status": f"to_status in {OLD}",
        "reason": f"reason is null or reason in {OLD_REASONS}",
    },
}
NEW_CHECKS = {
    REQ: {
        "status": f"status in {NEW}",
        "sent": "(status in ('sent', 'test_sent')) = (sent_at is not null)",
        "sender": f"(status in {CLAIMED}) = (sender is not null)",
        "claimed": f"(status in {CLAIMED}) = (claimed_at is not null)",
        "test_sent": (
            "status not in ('sent', 'test_sent') or (status = 'test_sent') = (sender = 'dry_run')"
        ),
    },
    EVENTS: {
        "from_status": f"from_status is null or from_status in {NEW}",
        "to_status": f"to_status in {NEW}",
        "reason": f"reason is null or reason in {NEW_REASONS}",
    },
}


def _drop(checks: dict[str, dict[str, str]]) -> None:
    for table, named in checks.items():
        for name in named:
            op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")


def _create(checks: dict[str, dict[str, str]]) -> None:
    for table, named in checks.items():
        for name, sql in named.items():
            op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, sql)


def upgrade() -> None:
    op.add_column(REQ, sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    _drop(OLD_CHECKS)
    op.execute(
        f"update {REQ} set status = 'test_sent' where status = 'sent' and sender = 'dry_run'"
    )
    op.execute(
        f"update {EVENTS} e set to_status = 'test_sent' from {REQ} r"
        " where e.request_id = r.id and r.status = 'test_sent' and e.to_status = 'sent'"
    )
    op.execute(f"update {REQ} set sender = 'dry_run' where status = 'failed' and sender is null")
    op.execute(
        f"update {REQ} r set claimed_at = coalesce(r.sent_at,"
        f" (select max(e.at) from {EVENTS} e where e.request_id = r.id), r.created_at)"
        " where r.status in ('test_sent', 'failed')"
    )
    _create(NEW_CHECKS)


def downgrade() -> None:
    _drop(NEW_CHECKS)
    op.execute(f"update {EVENTS} set to_status = 'sent' where to_status = 'test_sent'")
    op.execute(f"update {REQ} set status = 'sent' where status = 'test_sent'")
    op.execute(f"update {REQ} set sender = null where status = 'failed'")
    _create(OLD_CHECKS)
    op.drop_column(REQ, "claimed_at")
