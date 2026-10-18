from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.company import Company


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    members: Mapped[list["NetworkMember"]] = relationship(
        back_populates="network", cascade="all, delete-orphan"
    )


class NetworkMember(Base):
    __tablename__ = "network_members"

    network_id: Mapped[int] = mapped_column(
        ForeignKey("networks.id"), primary_key=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())

    network: Mapped["Network"] = relationship(back_populates="members")
    company: Mapped["Company"] = relationship(back_populates="network_memberships")
