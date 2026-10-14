"""Add user relationship to job applications

Revision ID: d84ad76fa0c7
Revises: 91704cc92819
Create Date: 2026-07-10 12:45:45.855771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd84ad76fa0c7'
down_revision: Union[str, Sequence[str], None] = '91704cc92819'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("job_application", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("user_id", sa.Integer(), nullable=False)
        )

        batch_op.create_foreign_key(
            "fk_job_application_user_id",
            "users",
            ["user_id"],
            ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("job_application", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_job_application_user_id",
            type_="foreignkey"
        )

        batch_op.drop_column("user_id")
