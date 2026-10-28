"""add STALE to proposal status enum

Revision ID: c7e2b1d94a10
Revises: b4f21a9c3e08
Create Date: 2026-10-28 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c7e2b1d94a10'
down_revision: Union[str, None] = 'b4f21a9c3e08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADD VALUE no puede correr dentro de una transaccion en Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE proposalstatus ADD VALUE 'STALE'")


def downgrade() -> None:
    # Postgres no permite quitar valores de un enum: se recrea el tipo.
    op.execute(
        "UPDATE compensation_proposals SET status='REJECTED' "
        "WHERE status='STALE'"
    )
    op.execute("ALTER TYPE proposalstatus RENAME TO proposalstatus_old")
    op.execute(
        "CREATE TYPE proposalstatus AS ENUM "
        "('PENDING', 'EXECUTED', 'REJECTED')"
    )
    op.execute(
        "ALTER TABLE compensation_proposals "
        "ALTER COLUMN status TYPE proposalstatus "
        "USING status::text::proposalstatus"
    )
    op.execute("DROP TYPE proposalstatus_old")
