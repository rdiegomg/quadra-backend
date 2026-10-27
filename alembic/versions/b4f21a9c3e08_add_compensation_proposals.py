"""add compensation proposals and acceptances

Revision ID: b4f21a9c3e08
Revises: 9d6dfe07ea52
Create Date: 2026-11-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4f21a9c3e08'
down_revision: Union[str, None] = '9d6dfe07ea52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compensation_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "EXECUTED", "REJECTED", name="proposalstatus"),
            nullable=False,
        ),
        sa.Column("company_ids", sa.JSON(), nullable=False),
        sa.Column("edge_payload", sa.JSON(), nullable=False),
        sa.Column("compensation", sa.Numeric(15, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("acta_number", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("key", name="uq_compensation_proposals_key"),
    )
    op.create_index(
        "ix_compensation_proposals_key", "compensation_proposals", ["key"]
    )
    op.create_index(
        "ix_compensation_proposals_status", "compensation_proposals", ["status"]
    )
    op.create_table(
        "proposal_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "ACCEPTED", "REJECTED", name="acceptancestatus"
            ),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["compensation_proposals.id"]
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.UniqueConstraint(
            "proposal_id", "company_id", name="uq_acceptance_company"
        ),
    )
    op.create_index(
        "ix_proposal_acceptances_proposal_id",
        "proposal_acceptances",
        ["proposal_id"],
    )
    op.create_index(
        "ix_proposal_acceptances_company_id",
        "proposal_acceptances",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_table("proposal_acceptances")
    op.drop_table("compensation_proposals")
    sa.Enum(name="acceptancestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="proposalstatus").drop(op.get_bind(), checkfirst=True)
