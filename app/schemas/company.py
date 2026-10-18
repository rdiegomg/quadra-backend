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
