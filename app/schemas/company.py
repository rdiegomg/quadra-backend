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
