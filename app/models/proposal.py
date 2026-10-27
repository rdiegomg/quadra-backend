from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AcceptanceStatus, ProposalStatus

if TYPE_CHECKING:
    from app.models.company import Company


class CompensationProposal(Base):
    """Propuesta de compensacion multilateral persistida.

    Se materializa cuando una empresa consulta sus cadenas: el `key` es
    una firma del estado del grafo (empresas, obligaciones, montos), asi
    una misma cadena reutiliza la misma propuesta mientras el grafo no
    cambie. Cuando todos los participantes aceptan, se ejecuta la
    compensacion sobre las obligaciones reales y queda el acta.
    """

    __tablename__ = "compensation_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "cycle" | "chain"
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus), default=ProposalStatus.PENDING, index=True
    )
    company_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    # [{debtor_id, creditor_id, debtor_name, creditor_name, balance,
    #   cancelled, obligation_ids}]
    edge_payload: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    compensation: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BOB")
    acta_number: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)

    acceptances: Mapped[list["ProposalAcceptance"]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )


class ProposalAcceptance(Base):
    """Decision de cada empresa participante sobre la propuesta."""

    __tablename__ = "proposal_acceptances"
    __table_args__ = (
        UniqueConstraint("proposal_id", "company_id", name="uq_acceptance_company"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("compensation_proposals.id"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    status: Mapped[AcceptanceStatus] = mapped_column(
        Enum(AcceptanceStatus), default=AcceptanceStatus.PENDING
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)

    proposal: Mapped["CompensationProposal"] = relationship(
        back_populates="acceptances"
    )
    company: Mapped["Company"] = relationship()
