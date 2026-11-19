"""v3 방 개수 칸 · 작은방 3 · 4 공간 종류 (whole-house-area 방안 4)

Revision ID: 0036_v3_rooms
Revises: 0035_v3_vendor_stopped
Create Date: 2026-11-19

projects.rooms: 방 개수 1~5. 옛 행은 비워 두고 계산 엔진이 평형 기본값으로 센다.
project_spaces.kind: 방이 4 · 5개인 집의 작은방 3 · 4를 더한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_v3_rooms"
down_revision: str | Sequence[str] | None = "0035_v3_vendor_stopped"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "('living', 'kitchen', 'master', 'room1', 'room2', 'hall', 'entry', 'dress')"
NEW_KINDS = (
    "('living', 'kitchen', 'master', 'room1', 'room2', 'room3', 'room4', 'hall', 'entry', 'dress')"
)


def upgrade() -> None:
    op.add_column("projects", sa.Column("rooms", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_projects_rooms"), "projects", "rooms is null or rooms between 1 and 5"
    )
    op.drop_constraint(op.f("ck_project_spaces_kind"), "project_spaces", type_="check")
    op.create_check_constraint(
        op.f("ck_project_spaces_kind"), "project_spaces", f"kind is null or kind in {NEW_KINDS}"
    )


def downgrade() -> None:
    op.execute("update project_spaces set kind = null where kind in ('room3', 'room4')")
    op.drop_constraint(op.f("ck_project_spaces_kind"), "project_spaces", type_="check")
    op.create_check_constraint(
        op.f("ck_project_spaces_kind"), "project_spaces", f"kind is null or kind in {OLD_KINDS}"
    )
    op.drop_constraint(op.f("ck_projects_rooms"), "projects", type_="check")
    op.drop_column("projects", "rooms")
