import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_db, require_company_user
from app.graph.analysis import compensable_obligation_ids
from app.graph.builder import build_debt_graph
from app.models.company import Company
from app.models.enums import ObligationStatus, UserRole
from app.models.obligation import Obligation, ObligationEvent, PaymentSchedule
from app.models.user import User
from app.schemas.obligation import (
    ObligationCreate,
    ObligationDirection,
    ObligationEventResponse,
    ObligationImportResponse,
    ObligationResponse,
    ObligationStatusUpdate,
    PaymentScheduleResponse,
)
from app.services.schedules import generate_schedule

router = APIRouter(prefix="/obligations", tags=["obligations"])

MAX_IMPORT_ROWS = 500
MAX_IMPORT_BYTES = 1_000_000

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


def _mark_in_chain(db: Session, obligations: list[Obligation]) -> list[Obligation]:
    """Marca obligaciones que participan en algun ciclo o cadena."""
    in_chain = compensable_obligation_ids(build_debt_graph(db))
    for obligation in obligations:
        obligation.in_chain = obligation.id in in_chain
    return obligations


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
    return _mark_in_chain(db, list(db.scalars(stmt)))


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
    return _mark_in_chain(db, list(db.scalars(stmt)))


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
        reference=payload.reference,
        status=ObligationStatus.PENDING,
    )
    db.add(obligation)
    db.flush()
    generate_schedule(db, obligation)
    _record_event(db, obligation, "CREATED", None, obligation.status, current_user)
    db.commit()
    return get_obligation_for_user(db, obligation.id, current_user)


REQUIRED_CSV_COLUMNS = {
    "tipo",
    "nit_contraparte",
    "monto",
    "fecha_emision",
    "fecha_vencimiento",
}


@router.post("/import", response_model=ObligationImportResponse)
async def import_obligations(
    file: UploadFile = File(...),
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> ObligationImportResponse:
    """Carga masiva de cuentas desde una planilla CSV.

    Columnas: tipo (cobrar|pagar), nit_contraparte, monto,
    fecha_emision, fecha_vencimiento; opcionales: nro_factura, moneda,
    razon_social (informativa). Filas con NIT no registrado se omiten.
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Solo se aceptan planillas .csv"
        )
    raw = await file.read()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "La planilla supera 1 MB"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "La planilla no es UTF-8 valido"
        ) from None

    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED_CSV_COLUMNS - {c.strip() for c in (reader.fieldnames or [])}
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Columnas faltantes: {', '.join(sorted(missing))}",
        )

    nit_cache: dict[str, Company | None] = {}

    def find_company(nit: str) -> Company | None:
        if nit not in nit_cache:
            nit_cache[nit] = db.scalar(
                select(Company).where(Company.nit == nit)
            )
        return nit_cache[nit]

    created = 0
    skipped = []
    for row_num, row in enumerate(reader, start=2):
        if row_num - 1 > MAX_IMPORT_ROWS:
            skipped.append(
                {"row": row_num, "reason": "Limite de 500 filas alcanzado"}
            )
            break
        try:
            tipo = (row.get("tipo") or "").strip().lower()
            nit = (row.get("nit_contraparte") or "").strip()
            amount = Decimal((row.get("monto") or "").strip().replace(",", ""))
            origin = date.fromisoformat((row.get("fecha_emision") or "").strip())
            due = date.fromisoformat((row.get("fecha_vencimiento") or "").strip())
            reference = (row.get("nro_factura") or "").strip() or None
            currency = (row.get("moneda") or "BOB").strip().upper()[:3] or "BOB"

            if tipo not in ("cobrar", "pagar"):
                raise ValueError("tipo debe ser 'cobrar' o 'pagar'")
            if amount <= 0:
                raise ValueError("monto debe ser positivo")
            if due < origin:
                raise ValueError("fecha_vencimiento anterior a fecha_emision")

            counterparty = find_company(nit)
            if counterparty is None:
                raise ValueError(f"NIT {nit} no registrado en la red")
            if counterparty.id == current_user.company_id:
                raise ValueError("deuda consigo misma")

            if tipo == "cobrar":
                debtor_id, creditor_id = counterparty.id, current_user.company_id
            else:
                debtor_id, creditor_id = current_user.company_id, counterparty.id

            obligation = Obligation(
                debtor_company_id=debtor_id,
                creditor_company_id=creditor_id,
                amount=amount,
                balance=amount,
                currency=currency,
                origin_date=origin,
                due_date=due,
                reference=reference,
                status=ObligationStatus.PENDING,
            )
            db.add(obligation)
            db.flush()
            generate_schedule(db, obligation)
            _record_event(
                db, obligation, "CREATED", None, obligation.status, current_user
            )
            created += 1
        except (ValueError, InvalidOperation, KeyError) as exc:
            skipped.append({"row": row_num, "reason": str(exc)})

    db.commit()
    return ObligationImportResponse(created=created, skipped=skipped)


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
