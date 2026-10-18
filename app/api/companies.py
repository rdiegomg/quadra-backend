from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from decimal import Decimal

from app.api.deps import get_db, require_admin, require_company_user
from app.graph.analysis import COMMISSION_RATE
from app.graph.builder import build_debt_graph
from app.graph.cycles import find_cycles
from app.models.company import Company
from app.models.enums import ObligationStatus
from app.models.obligation import Obligation
from app.models.user import User
from app.schemas.company import (
    CompanyResponse,
    CompanySummaryResponse,
    CompensationProposalResponse,
)
from app.schemas.obligation import ObligationResponse

# Costo financiero evitado ~2.5% (15% anual x ~60 dias de financiamiento).
SAVINGS_RATE = Decimal("0.025")

router = APIRouter(prefix="/companies", tags=["companies"])

OPEN_STATUSES = (
    ObligationStatus.PENDING,
    ObligationStatus.PARTIAL,
    ObligationStatus.OVERDUE,
)


def _open_balance_sum(db: Session, column, company_id: int):
    return db.scalar(
        select(func.coalesce(func.sum(Obligation.balance), 0)).where(
            column == company_id, Obligation.status.in_(OPEN_STATUSES)
        )
    )


@router.get("/me", response_model=CompanyResponse)
def get_my_company(
    current_user: User = Depends(require_company_user),
) -> Company:
    return current_user.company


@router.get("/me/summary", response_model=CompanySummaryResponse)
def get_my_summary(
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> CompanySummaryResponse:
    cid = current_user.company_id
    today = date.today()

    total_receivable = _open_balance_sum(db, Obligation.creditor_company_id, cid)
    total_payable = _open_balance_sum(db, Obligation.debtor_company_id, cid)

    pending = db.scalar(
        select(func.count(Obligation.id)).where(
            (Obligation.debtor_company_id == cid)
            | (Obligation.creditor_company_id == cid),
            Obligation.status.in_(OPEN_STATUSES),
        )
    )
    overdue = db.scalar(
        select(func.count(Obligation.id)).where(
            (Obligation.debtor_company_id == cid)
            | (Obligation.creditor_company_id == cid),
            Obligation.status.in_(OPEN_STATUSES),
            Obligation.due_date < today,
        )
    )

    return CompanySummaryResponse(
        company_id=cid,
        total_receivable=total_receivable,
        total_payable=total_payable,
        net_balance=total_receivable - total_payable,
        pending_obligations=pending,
        overdue_obligations=overdue,
    )


@router.get("/me/proposal", response_model=CompensationProposalResponse | None)
def get_my_proposal(
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> CompensationProposalResponse | None:
    """Mejor propuesta de compensacion disponible para mi empresa.

    Busca el ciclo mas compensable que incluye a la empresa. Devuelve
    null si no participa en ningun ciclo. Simulado.
    """
    graph = build_debt_graph(db)
    me = current_user.company_id
    proposal_cycle = None
    for cycle in find_cycles(graph):
        if me in cycle["company_ids"]:
            proposal_cycle = cycle
            break
    if proposal_cycle is None:
        return None

    amount = proposal_cycle["potential_compensation"]
    return CompensationProposalResponse(
        cycle_companies=proposal_cycle["companies"],
        cycle_length=proposal_cycle["length"],
        cancelled_amount=amount,
        receivable_forgone=amount,
        commission=(amount * COMMISSION_RATE).quantize(Decimal("0.01")),
        est_financial_savings=(amount * SAVINGS_RATE).quantize(Decimal("0.01")),
        currency="BOB",
    )


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.get("/companies", response_model=list[CompanyResponse])
def list_companies(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[Company]:
    return list(db.scalars(select(Company).order_by(Company.name)))


@admin_router.get("/obligations", response_model=list[ObligationResponse])
def list_obligations_admin(
    status_filter: ObligationStatus | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[Obligation]:
    """Todas las obligaciones de la red. Sin filtro devuelve solo las abiertas."""
    stmt = (
        select(Obligation)
        .options(joinedload(Obligation.debtor), joinedload(Obligation.creditor))
        .order_by(Obligation.due_date)
    )
    stmt = stmt.where(
        Obligation.status == status_filter
        if status_filter
        else Obligation.status.in_(OPEN_STATUSES)
    )
    return list(db.scalars(stmt))
