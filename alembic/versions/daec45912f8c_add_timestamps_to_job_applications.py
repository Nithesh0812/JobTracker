"""add timestamps to job applications

Revision ID: daec45912f8c
Revises: d84ad76fa0c7
Create Date: 2026-07-20 21:14:44.190867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'daec45912f8c'
down_revision: Union[str, Sequence[str], None] = 'd84ad76fa0c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add columns while allowing NULL temporarily
    op.add_column(
        "job_application",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "job_application",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    # Step 2: Give all existing rows timestamp values
    op.execute(
        sa.text(
            """
            UPDATE job_application
            SET created_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
               OR updated_at IS NULL
            """
        )
    )

    # Step 3: Make the columns required
    with op.batch_alter_table("job_application", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False
        )

        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False
        )
def downgrade() -> None:
    with op.batch_alter_table("job_application", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")