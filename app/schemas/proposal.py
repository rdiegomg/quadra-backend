from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class ProposalRespondRequest(BaseModel):
    action: Literal["accept", "reject"]


class ProposalStateResponse(BaseModel):
    """Estado de la propuesta tras responder (o al consultarla)."""

    proposal_id: int
    status: str  # "PENDING" | "EXECUTED" | "REJECTED"
    acceptances_done: int
    acceptances_total: int
    my_decision: str | None
    executed_at: datetime | None


class ActaParty(BaseModel):
    id: int
    name: str | None
    nit: str | None
    legal_type: str | None


class ActaTranche(BaseModel):
    debtor_id: int
    creditor_id: int
    debtor_name: str
    creditor_name: str
    balance_before: Decimal
    cancelled: Decimal
    residual: Decimal


class AdminProposalResponse(BaseModel):
    """Fila del historial de propuestas para el administrador."""

    id: int
    kind: str
    status: str
    companies: list[str]
    length: int
    compensation: Decimal
    currency: str
    acta_number: str | None
    acceptances_done: int
    acceptances_total: int
    created_at: datetime | None
    executed_at: datetime | None


class ActaResponse(BaseModel):
    """Acta de compensacion multilateral (documento legal emitido
    cuando todos los participantes aceptaron)."""

    acta_number: str
    proposal_id: int
    kind: str
    executed_at: datetime | None
    currency: str
    companies: list[ActaParty]
    tranches: list[ActaTranche]
    total_cancelled: Decimal
    all_accepted: bool
