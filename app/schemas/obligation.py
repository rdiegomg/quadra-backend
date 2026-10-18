import enum
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import InstallmentStatus, ObligationStatus, PaymentFrequency


class ObligationDirection(str, enum.Enum):
    """Perspective del registrante: RECEIVABLE = me deben (soy acreedor),
    PAYABLE = debo (soy deudor)."""

    RECEIVABLE = "RECEIVABLE"
    PAYABLE = "PAYABLE"


class ObligationCreate(BaseModel):
    counterparty_nit: str = Field(min_length=4, max_length=30)
    direction: ObligationDirection
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999.99"))
    currency: str = Field(default="BOB", min_length=3, max_length=3)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    origin_date: date
    due_date: date
    payment_frequency: PaymentFrequency = PaymentFrequency.ONE_TIME
    reference: str | None = Field(default=None, max_length=60)


class CounterpartyInfo(BaseModel):
    """Datos minimos de la contraparte (RF-07)."""

    id: int
    name: str
    nit: str

    model_config = {"from_attributes": True}


class ObligationResponse(BaseModel):
    id: int
    debtor: CounterpartyInfo
    creditor: CounterpartyInfo
    amount: Decimal
    balance: Decimal
    currency: str
    reference: str | None
    interest_rate: Decimal | None
    origin_date: date
    due_date: date
    payment_frequency: PaymentFrequency
    status: ObligationStatus
    in_chain: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class ObligationStatusUpdate(BaseModel):
    status: ObligationStatus


class PaymentScheduleResponse(BaseModel):
    id: int
    installment_number: int
    due_date: date
    amount: Decimal
    status: InstallmentStatus
    paid_at: datetime | None

    model_config = {"from_attributes": True}


class ObligationEventResponse(BaseModel):
    id: int
    event_type: str
    previous_status: ObligationStatus | None
    new_status: ObligationStatus | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportSkippedRow(BaseModel):
    row: int
    reason: str


class ObligationImportResponse(BaseModel):
    created: int
    skipped: list[ImportSkippedRow]
