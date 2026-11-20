"""v3 대화 상태(맥락 L1): chats.state

Revision ID: 0037_v3_chat_state
Revises: 0036_v3_rooms
Create Date: 2026-11-20

chats.state: 이어 묻기를 풀려고 코드가 남기는 대화 맥락(공종 · 질문 꼴 · 담당 · 가린 독립 질문 80자 · 턴).
숫자 값 · 개인정보는 넣지 않는다. 옛 행은 비워 둔다(이어 묻기만 안 될 뿐 답은 같다).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_v3_chat_state"
down_revision: str | Sequence[str] | None = "0036_v3_rooms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("state", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "state")
