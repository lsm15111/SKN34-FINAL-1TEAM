"""점검 R6 B2: /v2 상담 대화를 chats.kind 'v2'로 나눈다(v3 AI 칸 목록 · 이어 보기에 섞이지 않게).

Revision ID: 0058_v4_audit_agent
Revises: 0057_v4_audit_platform
Create Date: 2026-11-24

- 이미 쌓인 v2 대화는 ai로 남는다(v3 대화와 가를 표시가 없다). v3 관문은 v3 담당이 아닌 waiting 라벨을 버린다.
- 되돌리면 v2 대화를 ai로 돌리고 옛 CHECK로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0058_v4_audit_agent"
down_revision: str | Sequence[str] | None = "0057_v4_audit_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "kind in ('ai', 'assistant')"
NEW_KINDS = "kind in ('ai', 'assistant', 'v2')"


def _swap(sql: str) -> None:
    op.drop_constraint(op.f("ck_chats_kind"), "chats", type_="check")
    op.create_check_constraint(op.f("ck_chats_kind"), "chats", sql)


def upgrade() -> None:
    _swap(NEW_KINDS)


def downgrade() -> None:
    op.execute("update chats set kind = 'ai' where kind = 'v2'")
    _swap(OLD_KINDS)
