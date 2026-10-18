from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.network import NetworkMember
    from app.models.obligation import Obligation
    from app.models.sector import Sector
    from app.models.user import User


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    nit: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    legal_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SRL, SA, etc.
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    sector: Mapped["Sector"] = relationship(back_populates="companies")
    users: Mapped[list["User"]] = relationship(back_populates="company")
    debts: Mapped[list["Obligation"]] = relationship(
        back_populates="debtor", foreign_keys="Obligation.debtor_company_id"
    )
    credits: Mapped[list["Obligation"]] = relationship(
        back_populates="creditor", foreign_keys="Obligation.creditor_company_id"
    )
    network_memberships: Mapped[list["NetworkMember"]] = relationship(
        back_populates="company"
    )

    @property
    def sector_name(self) -> str | None:
        return self.sector.name if self.sector else None
