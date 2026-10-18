from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_db, require_company_user
from app.models.company import Company
from app.models.enums import ObligationStatus, UserRole
from app.models.obligation import Obligation, ObligationEvent, PaymentSchedule
from app.models.user import User
from app.schemas.obligation import (
    ObligationCreate,
    ObligationDirection,
    ObligationEventResponse,
    ObligationResponse,
    ObligationStatusUpdate,
    PaymentScheduleResponse,
)
from app.services.schedules import generate_schedule

router = APIRouter(prefix="/obligations", tags=["obligations"])

# Transiciones permitidas en modo demostracion
ALLOWED_TRANSITIONS = {
    ObligationStatus.PENDING: {ObligationStatus.PAID, ObligationStatus.CANCELLED},
    ObligationStatus.PARTIAL: {ObligationStatus.PAID, ObligationStatus.CANCELLED},
    ObligationStatus.OVERDUE: {ObligationStatus.PAID, ObligationStatus.CANCELLED},
    ObligationStatus.PAID: set(),
    ObligationStatus.CANCELLED: set(),
}


def _load_parties(stmt):
    return stmt.options(
        joinedload(Obligation.debtor), joinedload(Obligation.creditor)
    )


def get_obligation_for_user(
    db: Session, obligation_id: int, user: User
) -> Obligation:
    """RF-07: devuelve 404 si el usuario no es parte de la obligacion,
    salvo ADMIN que ve toda la red."""
    obligation = db.scalar(
        _load_parties(select(Obligation)).where(Obligation.id == obligation_id)
    )
    if obligation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Obligacion no encontrada")
    if user.role == UserRole.ADMIN:
        return obligation
    parties = {obligation.debtor_company_id, obligation.creditor_company_id}
    if user.company_id not in parties:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Obligacion no encontrada")
    return obligation


def _record_event(
    db: Session,
    obligation: Obligation,
    event_type: str,
    previous: ObligationStatus | None,
    new: ObligationStatus | None,
    actor: User,
) -> None:
    db.add(
        ObligationEvent(
            obligation_id=obligation.id,
            event_type=event_type,
            previous_status=previous,
            new_status=new,
            actor_user_id=actor.id,
        )
    )


@router.get("/receivable", response_model=list[ObligationResponse])
def list_receivable(
    status_filter: ObligationStatus | None = None,
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> list[Obligation]:
    stmt = _load_parties(
        select(Obligation).where(
            Obligation.creditor_company_id == current_user.company_id
        )
    ).order_by(Obligation.due_date)
    if status_filter:
        stmt = stmt.where(Obligation.status == status_filter)
    return list(db.scalars(stmt))


@router.get("/payable", response_model=list[ObligationResponse])
def list_payable(
    status_filter: ObligationStatus | None = None,
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> list[Obligation]:
    stmt = _load_parties(
        select(Obligation).where(
            Obligation.debtor_company_id == current_user.company_id
        )
    ).order_by(Obligation.due_date)
    if status_filter:
        stmt = stmt.where(Obligation.status == status_filter)
    return list(db.scalars(stmt))


@router.post("", response_model=ObligationResponse, status_code=status.HTTP_201_CREATED)
def create_obligation(
    payload: ObligationCreate,
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> Obligation:
    counterparty = db.scalar(
        select(Company).where(Company.nit == payload.counterparty_nit)
    )
    if counterparty is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No existe una empresa registrada con ese NIT",
        )
    if counterparty.id == current_user.company_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No se puede registrar una deuda consigo misma",
        )
    if payload.due_date < payload.origin_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La fecha de vencimiento debe ser posterior a la de origen",
        )

    if payload.direction == ObligationDirection.RECEIVABLE:
        debtor_id, creditor_id = counterparty.id, current_user.company_id
    else:
        debtor_id, creditor_id = current_user.company_id, counterparty.id

    obligation = Obligation(
        debtor_company_id=debtor_id,
        creditor_company_id=creditor_id,
        amount=payload.amount,
        balance=payload.amount,
        currency=payload.currency.upper(),
        interest_rate=payload.interest_rate,
        origin_date=payload.origin_date,
        due_date=payload.due_date,
        payment_frequency=payload.payment_frequency,
        status=ObligationStatus.PENDING,
    )
    db.add(obligation)
    db.flush()
    generate_schedule(db, obligation)
    _record_event(db, obligation, "CREATED", None, obligation.status, current_user)
    db.commit()
    return get_obligation_for_user(db, obligation.id, current_user)


@router.get("/{obligation_id}", response_model=ObligationResponse)
def get_obligation(
    obligation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Obligation:
    return get_obligation_for_user(db, obligation_id, current_user)


@router.get("/{obligation_id}/events", response_model=list[ObligationEventResponse])
def list_obligation_events(
    obligation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ObligationEvent]:
    get_obligation_for_user(db, obligation_id, current_user)
    return list(
        db.scalars(
            select(ObligationEvent)
            .where(ObligationEvent.obligation_id == obligation_id)
            .order_by(ObligationEvent.created_at)
        )
    )


@router.get("/{obligation_id}/schedules", response_model=list[PaymentScheduleResponse])
def list_payment_schedules(
    obligation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PaymentSchedule]:
    """Plan de cuotas (amortizacion simulada) de la obligacion."""
    get_obligation_for_user(db, obligation_id, current_user)
    return list(
        db.scalars(
            select(PaymentSchedule)
            .where(PaymentSchedule.obligation_id == obligation_id)
            .order_by(PaymentSchedule.installment_number)
        )
    )


@router.patch("/{obligation_id}/status", response_model=ObligationResponse)
def update_obligation_status(
    obligation_id: int,
    payload: ObligationStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Obligation:
    obligation = get_obligation_for_user(db, obligation_id, current_user)

    if payload.status not in ALLOWED_TRANSITIONS.get(obligation.status, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Transicion no permitida: {obligation.status.value} -> {payload.status.value}",
        )

    previous = obligation.status
    obligation.status = payload.status
    if payload.status == ObligationStatus.PAID:
        obligation.balance = 0
    _record_event(db, obligation, "STATUS_CHANGED", previous, payload.status, current_user)
    db.commit()
    db.refresh(obligation)
    return obligation
