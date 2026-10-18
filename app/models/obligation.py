from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    InstallmentStatus,
    ObligationStatus,
    PaymentFrequency,
)

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.document import Document
    from app.models.user import User


class Obligation(Base):
    """Una obligacion es una cuenta por pagar para el deudor
    y una cuenta por cobrar para el acreedor."""

    __tablename__ = "obligations"
    __table_args__ = (
        CheckConstraint("debtor_company_id <> creditor_company_id", name="ck_obligation_no_self_debt"),
        CheckConstraint("amount > 0", name="ck_obligation_positive_amount"),
        CheckConstraint("balance >= 0", name="ck_obligation_non_negative_balance"),
        CheckConstraint("balance <= amount", name="ck_obligation_balance_lte_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    debtor_company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    creditor_company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(default="BOB")
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    origin_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_frequency: Mapped[PaymentFrequency] = mapped_column(
        Enum(PaymentFrequency), default=PaymentFrequency.ONE_TIME
    )
    status: Mapped[ObligationStatus] = mapped_column(
        Enum(ObligationStatus), default=ObligationStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    debtor: Mapped["Company"] = relationship(
        back_populates="debts", foreign_keys=[debtor_company_id]
    )
    creditor: Mapped["Company"] = relationship(
        back_populates="credits", foreign_keys=[creditor_company_id]
    )
    payment_schedules: Mapped[list["PaymentSchedule"]] = relationship(
        back_populates="obligation", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="obligation", cascade="all, delete-orphan"
    )
    events: Mapped[list["ObligationEvent"]] = relationship(
        back_populates="obligation", cascade="all, delete-orphan"
    )


class PaymentSchedule(Base):
    __tablename__ = "payment_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    obligation_id: Mapped[int] = mapped_column(
        ForeignKey("obligations.id"), nullable=False, index=True
    )
    installment_number: Mapped[int] = mapped_column(nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[InstallmentStatus] = mapped_column(
        Enum(InstallmentStatus), default=InstallmentStatus.PENDING
    )
    paid_at: Mapped[datetime | None] = mapped_column()

    obligation: Mapped["Obligation"] = relationship(back_populates="payment_schedules")


class ObligationEvent(Base):
    """Historial append-only de cambios en una obligacion (RF-06)."""

    __tablename__ = "obligation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    obligation_id: Mapped[int] = mapped_column(
        ForeignKey("obligations.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    previous_status: Mapped[ObligationStatus | None] = mapped_column(
        Enum(ObligationStatus)
    )
    new_status: Mapped[ObligationStatus | None] = mapped_column(Enum(ObligationStatus))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    obligation: Mapped["Obligation"] = relationship(back_populates="events")
    actor: Mapped["User | None"] = relationship()
