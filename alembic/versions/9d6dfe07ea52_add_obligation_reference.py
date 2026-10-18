"""add obligation reference

Revision ID: 9d6dfe07ea52
Revises: 72e395c7a678
Create Date: 2026-10-18 17:42:13.011288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d6dfe07ea52'
down_revision: Union[str, None] = '72e395c7a678'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "obligations", sa.Column("reference", sa.String(length=60), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("obligations", "reference")
