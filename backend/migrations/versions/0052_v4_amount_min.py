"""v4 실측 견적서 낼 금액 · 추가 금액 1원 이상 CHECK(새 행부터, NOT VALID)

Revision ID: 0052_v4_amount_min
Revises: 0050_v4_research
Create Date: 2026-11-22

- vendor_quotes.entered_amount · extra_charges.entered_amount >= 1을 DB CHECK로도 지킨다(입력 · 보내기 검사는 고침 2차 G).
- NOT VALID로 더한다: 입력 검사를 1원으로 바꾸기 전에 저장한 0원 행(임시 저장 견적서 · 추가 금액)이 있을 수 있어서,
  이미 있는 행은 검사하지 않고 새로 넣거나 고치는 행부터 막는다. 0원 행을 정리한 뒤
  `ALTER TABLE … VALIDATE CONSTRAINT …`로 굳힐 수 있다.
- 옛 CHECK(0 이상 · 범위)는 그대로 둔다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052_v4_amount_min"
down_revision: str | Sequence[str] | None = "0050_v4_research"  # 병합 때 리드가 0051로 맞춰요
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = (
    ("vendor_quotes", "ck_vendor_quotes_entered_amount_min"),
    ("extra_charges", "ck_extra_charges_entered_amount_min"),
)


def upgrade() -> None:
    for table, name in CHECKS:
        op.execute(
            f"alter table {table} add constraint {name} check (entered_amount >= 1) not valid"
        )


def downgrade() -> None:
    for table, name in reversed(CHECKS):
        op.drop_constraint(op.f(name), table, type_="check")
