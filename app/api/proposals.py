from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.enums import ProposalStatus, UserRole
from app.models.proposal import CompensationProposal
from app.models.user import User
from app.schemas.proposal import (
    ActaResponse,
    ProposalRespondRequest,
    ProposalStateResponse,
)
from app.services import proposals as svc

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _get_proposal(db: Session, proposal_id: int) -> CompensationProposal:
    proposal = db.get(CompensationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Propuesta no encontrada"
        )
    return proposal


def _require_participant(
    proposal: CompensationProposal, user: User
) -> None:
    if user.role == UserRole.ADMIN:
        return
    if user.company_id not in (proposal.company_ids or []):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Propuesta no encontrada"
        )


def _state(proposal: CompensationProposal, company_id: int | None) -> ProposalStateResponse:
    my_acc = (
        svc.acceptance_for(proposal, company_id) if company_id else None
    )
    return ProposalStateResponse(
        proposal_id=proposal.id,
        status=proposal.status.value,
        acceptances_done=sum(
            1
            for a in proposal.acceptances
            if a.status.value == "ACCEPTED"
        ),
        acceptances_total=len(proposal.acceptances),
        my_decision=my_acc.status.value if my_acc else None,
        executed_at=proposal.executed_at,
    )


@router.get("/{proposal_id}", response_model=ProposalStateResponse)
def get_proposal_state(
    proposal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProposalStateResponse:
    proposal = _get_proposal(db, proposal_id)
    _require_participant(proposal, current_user)
    return _state(proposal, current_user.company_id)


@router.post("/{proposal_id}/respond", response_model=ProposalStateResponse)
def respond_to_proposal(
    proposal_id: int,
    payload: ProposalRespondRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProposalStateResponse:
    """Acepta o rechaza la propuesta como la empresa del usuario.

    Si al aceptar todos los participantes ya aceptaron, ejecuta la
    compensacion sobre los saldos en la misma transaccion.
    """
    proposal = _get_proposal(db, proposal_id)
    _require_participant(proposal, current_user)
    if current_user.role == UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "El administrador no puede responder propuestas",
        )
    try:
        svc.respond(db, proposal, current_user.company_id, payload.action)
    except ValueError as exc:
        # Si caduco al validar saldos, el estado STALE queda persistido.
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.commit()
    db.refresh(proposal)
    return _state(proposal, current_user.company_id)


@router.get("/{proposal_id}/acta", response_model=ActaResponse)
def get_acta(
    proposal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Acta de compensacion emitida al ejecutarse la propuesta."""
    proposal = _get_proposal(db, proposal_id)
    _require_participant(proposal, current_user)
    if proposal.status != ProposalStatus.EXECUTED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El acta se emite cuando la compensacion se ejecuta",
        )
    return svc.build_acta(db, proposal)
