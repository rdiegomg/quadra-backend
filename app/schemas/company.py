from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class CompanyResponse(BaseModel):
    id: int
    name: str
    nit: str
    legal_type: str
    sector_id: int
    sector_name: str | None

    model_config = {"from_attributes": True}


class CompanySummaryResponse(BaseModel):
    company_id: int
    total_receivable: Decimal
    total_payable: Decimal
    net_balance: Decimal
    pending_obligations: int
    overdue_obligations: int


class CompensationProposalResponse(BaseModel):
    """Propuesta individual de compensacion (paso 4 del flujo operativo).

    La empresa ve solo SU resultado: cuanta deuda se le cancela y cuanta
    acreencia deja de cobrar. En un ciclo ambos montos son iguales
    (posicion neta preservada). Todo simulado: no modifica obligaciones.
    """

    cycle_companies: list[str]
    cycle_length: int
    cancelled_amount: Decimal
    receivable_forgone: Decimal
    commission: Decimal
    est_financial_savings: Decimal
    currency: str


class MyChainEdgeResponse(BaseModel):
    """Un eslabon de la cadena visto por la empresa.

    balance/remainder son None cuando la empresa no es parte de esa
    arista: monto privado, como en el mapa del prototipo.
    """

    debtor_label: str
    creditor_label: str
    debtor_is_me: bool
    creditor_is_me: bool
    balance: Decimal | None
    cancelled: Decimal
    remainder: Decimal | None


class MyChainResponse(BaseModel):
    """Cadena (cerrada=ciclo, abierta=camino) donde participa la empresa.

    Privacidad: solo se nombran mi empresa y mis contrapartes directas;
    el resto aparece anonimizado como 'Empresa de <rubro>'.
    """

    kind: str  # "cycle" | "chain"
    labels: list[str]
    named_participants: list[str]
    anonymized_count: int
    length: int
    my_position: str  # "member" | "source" | "middle" | "sink"
    cancelled_amount: Decimal
    receivable_forgone: Decimal
    potential_compensation: Decimal
    commission: Decimal
    est_savings: Decimal
    status: str  # "ready" | "compensable"
    first_due_date: date | None
    edges: list[MyChainEdgeResponse]
    currency: str
    # Propuesta multilateral persistida (None si no se pudo materializar)
    proposal_id: int | None
    proposal_status: str | None  # "PENDING" | "EXECUTED" | "REJECTED"
    acceptances_done: int
    acceptances_total: int
    my_decision: str | None  # "ACCEPTED" | "REJECTED" | None (pendiente)
    executed_at: datetime | None


class OpportunityResponse(BaseModel):
    """Eslabon faltante que cerraria una cadena abierta como ciclo.

    La empresa ve a quien corresponde la deuda que faltaria: es SU
    propia contraparte potencial (si la deuda existe en la realidad,
    ya la conoce). Al registrarla, el circulo se cierra solo.
    """

    direction: str  # "payable" (yo le debo) | "receivable" (me debe)
    counterparty_id: int
    counterparty_name: str
    counterparty_nit: str
    counterparty_sector: str | None
    chain_length: int
    potential_compensation: Decimal
    currency: str


class MyNetworkNode(BaseModel):
    id: str
    label: str
    sector: str | None
    is_me: bool
    is_counterparty: bool
    anonymous: bool


class MyNetworkEdge(BaseModel):
    id: str
    source: str
    target: str
    balance: Decimal | None  # None = "Monto privado"
    role: str  # "cycle" | "chain" | "other"


class MyNetworkResponse(BaseModel):
    """Subgrafo de la empresa: ella y sus contrapartes con nombre real,
    el resto de la red anonimizado."""

    nodes: list[MyNetworkNode]
    edges: list[MyNetworkEdge]
