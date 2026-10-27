"""Logica de propuestas de compensacion multilateral.

Flujo (doc §3.2): QUADRA detecta una cadena/ciclo y materializa una
propuesta; cada participante acepta o rechaza; solo cuando TODOS aceptan
se ejecuta la compensacion sobre los saldos reales y se emite el acta.

Las aceptaciones de las empresas ficticias del seed se simulan al crear
la propuesta (todas aceptadas salvo la empresa que la descubre, que queda
PENDING esperando su decision real).
"""

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.enums import AcceptanceStatus, ObligationStatus, ProposalStatus
from app.models.obligation import Obligation, ObligationEvent
from app.models.proposal import CompensationProposal, ProposalAcceptance


def _signature(kind: str, edges: list[dict], compensation: Decimal) -> str:
    """Firma determinista del estado del grafo para esta propuesta.

    Cambia si cambia cualquier eslabon (empresas, obligaciones o saldos),
    de modo que una cadena ya ejecutada no recicle una propuesta vieja.
    """
    raw = f"{kind}|{compensation}|" + ";".join(
        f"{e['debtor_id']}>{e['creditor_id']}"
        f"[{','.join(map(str, sorted(e['obligation_ids'])))}]"
        f"={e['balance']}"
        for e in edges
    )
    return hashlib.sha1(raw.encode()).hexdigest()


def get_or_create_proposal(
    db: Session,
    kind: str,
    company_ids: list[int],
    edges: list[dict],
    compensation: Decimal,
    currency: str,
    viewer_company_id: int,
) -> CompensationProposal:
    """Materializa la propuesta si no existe.

    `edges` = [{debtor_id, creditor_id, debtor_name, creditor_name,
    balance, cancelled, obligation_ids}] con datos reales (snapshot para
    la ejecucion y el acta). El espectador queda PENDING; el resto de
    participantes (ficticios) se marca ACCEPTED, simulando que ya
    respondieron en el ciclo.
    """
    key = _signature(kind, edges, compensation)
    proposal = db.scalar(
        select(CompensationProposal).where(CompensationProposal.key == key)
    )
    if proposal is not None:
        return proposal

    now = datetime.now(timezone.utc)
    proposal = CompensationProposal(
        key=key,
        kind=kind,
        status=ProposalStatus.PENDING,
        company_ids=company_ids,
        edge_payload=edges,
        compensation=compensation,
        currency=currency,
    )
    db.add(proposal)
    db.flush()
    for cid in company_ids:
        decided = cid != viewer_company_id
        db.add(
            ProposalAcceptance(
                proposal_id=proposal.id,
                company_id=cid,
                status=(
                    AcceptanceStatus.ACCEPTED
                    if decided
                    else AcceptanceStatus.PENDING
                ),
                decided_at=now if decided else None,
            )
        )
    db.flush()
    return proposal


def acceptance_for(
    proposal: CompensationProposal, company_id: int
) -> ProposalAcceptance | None:
    for acc in proposal.acceptances:
        if acc.company_id == company_id:
            return acc
    return None


def respond(
    db: Session,
    proposal: CompensationProposal,
    company_id: int,
    action: str,
) -> CompensationProposal:
    """Registra la decision de una empresa. Lanza ValueError si la
    propuesta no esta pendiente o la empresa no participa / ya decidio.

    Con `action="accept"` y todos los demas aceptados, ejecuta la
    compensacion en la misma transaccion.
    """
    if proposal.status != ProposalStatus.PENDING:
        raise ValueError("La propuesta ya no esta pendiente")
    acceptance = acceptance_for(proposal, company_id)
    if acceptance is None:
        raise ValueError("La empresa no participa en esta propuesta")
    if acceptance.status != AcceptanceStatus.PENDING:
        raise ValueError("La empresa ya respondio esta propuesta")

    now = datetime.now(timezone.utc)
    if action == "reject":
        acceptance.status = AcceptanceStatus.REJECTED
        acceptance.decided_at = now
        proposal.status = ProposalStatus.REJECTED
        return proposal

    acceptance.status = AcceptanceStatus.ACCEPTED
    acceptance.decided_at = now
    if all(
        a.status == AcceptanceStatus.ACCEPTED for a in proposal.acceptances
    ):
        _execute(db, proposal)
    return proposal


def _execute(db: Session, proposal: CompensationProposal) -> None:
    """Aplica la compensacion sobre los saldos reales (doc §3.2 paso 6).

    Por cada eslabon se distribuye el monto cancelado sobre sus
    obligaciones subyacentes (vencimiento mas proximo primero). El
    residuo queda vivo con sus condiciones originales; si queda en cero,
    la obligacion pasa a PAID.
    """
    now = datetime.now(timezone.utc)
    for edge in proposal.edge_payload:
        remaining = Decimal(str(edge["cancelled"]))
        obligations = sorted(
            (
                ob
                for oid in edge["obligation_ids"]
                if (ob := db.get(Obligation, oid)) is not None
            ),
            key=lambda o: (o.due_date, o.id),
        )
        if not obligations:
            raise ValueError(
                f"Eslabon {edge['debtor_id']}->{edge['creditor_id']} "
                "sin obligaciones vigentes"
            )
        if sum(Decimal(str(o.balance)) for o in obligations) < remaining:
            raise ValueError(
                f"Eslabon {edge['debtor_id']}->{edge['creditor_id']} "
                "ya no tiene saldo suficiente"
            )
        for obligation in obligations:
            if remaining <= 0:
                break
            cut = min(Decimal(str(obligation.balance)), remaining)
            previous = obligation.status
            obligation.balance = Decimal(str(obligation.balance)) - cut
            remaining -= cut
            obligation.status = (
                ObligationStatus.PAID
                if obligation.balance <= 0
                else ObligationStatus.PARTIAL
            )
            db.add(
                ObligationEvent(
                    obligation_id=obligation.id,
                    event_type="COMPENSATED",
                    previous_status=previous,
                    new_status=obligation.status,
                )
            )

    proposal.status = ProposalStatus.EXECUTED
    proposal.executed_at = now
    proposal.acta_number = proposal.id


def build_acta(db: Session, proposal: CompensationProposal) -> dict:
    """Acta de compensacion (doc §3.2 paso 6 / §10.2): documento legal
    con todas las partes reales, tramos compensados y residuos."""
    companies = {
        c.id: c
        for c in db.scalars(
            select(Company).where(Company.id.in_(proposal.company_ids))
        )
    }
    tranches = []
    for edge in proposal.edge_payload:
        balance = Decimal(str(edge["balance"]))
        cancelled = Decimal(str(edge["cancelled"]))
        tranches.append(
            {
                "debtor_id": edge["debtor_id"],
                "creditor_id": edge["creditor_id"],
                "debtor_name": edge["debtor_name"],
                "creditor_name": edge["creditor_name"],
                "balance_before": balance,
                "cancelled": cancelled,
                "residual": balance - cancelled,
            }
        )
    return {
        "acta_number": f"AC-{proposal.acta_number:05d}",
        "proposal_id": proposal.id,
        "kind": proposal.kind,
        "executed_at": proposal.executed_at,
        "currency": proposal.currency,
        "companies": [
            {
                "id": cid,
                "name": companies[cid].name if cid in companies else None,
                "nit": companies[cid].nit if cid in companies else None,
                "legal_type": (
                    companies[cid].legal_type if cid in companies else None
                ),
            }
            for cid in proposal.company_ids
        ],
        "tranches": tranches,
        "total_cancelled": Decimal(str(proposal.compensation)),
        "all_accepted": all(
            a.status == AcceptanceStatus.ACCEPTED for a in proposal.acceptances
        ),
    }
