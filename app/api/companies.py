from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from decimal import Decimal

from app.api.deps import get_db, require_admin, require_company_user
from app.graph.analysis import (
    COMMISSION_RATE,
    anonymized_label,
    find_company_chains,
    my_counterparties,
)
from app.graph.builder import build_debt_graph, edge_balance
from app.graph.cycles import find_cycles
from app.models.company import Company
from app.models.enums import ObligationStatus
from app.models.obligation import Obligation
from app.models.user import User
from app.schemas.company import (
    CompanyResponse,
    CompanySummaryResponse,
    CompensationProposalResponse,
    MyChainResponse,
    MyNetworkEdge,
    MyNetworkNode,
    MyNetworkResponse,
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


@router.get("/me/chains", response_model=list[MyChainResponse])
def get_my_chains(
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> list[MyChainResponse]:
    """Ciclos y cadenas donde participa la empresa, anonimizados.

    Vista tipo 'Tus cadenas' del prototipo: la empresa ve su propia
    posicion, el monto que se le cancela y el detalle por eslabon.
    """
    graph = build_debt_graph(db)
    me = current_user.company_id
    chains = find_company_chains(graph, me)

    # Primer vencimiento: min due_date de las obligaciones del tramo.
    obligation_ids = {
        oid
        for chain in chains
        for i in range(len(chain["company_ids"]) - 1)
        for oid in graph.edges[
            chain["company_ids"][i], chain["company_ids"][i + 1]
        ]["obligation_ids"]
    } | {
        oid
        for chain in chains
        if chain["kind"] == "cycle"
        for oid in graph.edges[
            chain["company_ids"][-1], chain["company_ids"][0]
        ]["obligation_ids"]
    }
    due_dates: dict[int, date] = {}
    if obligation_ids:
        for oid, due in db.execute(
            select(Obligation.id, Obligation.due_date).where(
                Obligation.id.in_(obligation_ids)
            )
        ):
            due_dates[oid] = due

    responses = []
    for chain in chains:
        ids_in_chain = {
            oid
            for i in range(len(chain["company_ids"]) - 1)
            for oid in graph.edges[
                chain["company_ids"][i], chain["company_ids"][i + 1]
            ]["obligation_ids"]
        }
        if chain["kind"] == "cycle":
            ids_in_chain |= set(
                graph.edges[
                    chain["company_ids"][-1], chain["company_ids"][0]
                ]["obligation_ids"]
            )
        first_due = min(
            (due_dates[oid] for oid in ids_in_chain if oid in due_dates),
            default=None,
        )
        responses.append(
            MyChainResponse(
                kind=chain["kind"],
                labels=chain["labels"],
                named_participants=chain["named_participants"],
                anonymized_count=chain["anonymized_count"],
                length=chain["length"],
                my_position=chain["my_position"],
                cancelled_amount=chain["cancelled_amount"],
                receivable_forgone=chain["receivable_forgone"],
                potential_compensation=chain["potential_compensation"],
                commission=(
                    chain["potential_compensation"] * COMMISSION_RATE
                ).quantize(Decimal("0.01")),
                status=chain["status"],
                first_due_date=first_due,
                edges=chain["edges"],
                currency="BOB",
            )
        )
    return responses


@router.get("/me/network", response_model=MyNetworkResponse)
def get_my_network(
    current_user: User = Depends(require_company_user),
    db: Session = Depends(get_db),
) -> MyNetworkResponse:
    """Mapa privado de la empresa: ella y sus contrapartes nombradas,
    el resto de la red anonimizado ('Identidad protegida')."""
    graph = build_debt_graph(db)
    me = current_user.company_id
    if me not in graph:
        return MyNetworkResponse(nodes=[], edges=[])

    counterparties = my_counterparties(graph, me)

    # Nodos visibles: yo + contrapartes + empresas que comparten una
    # cadena/ciclo conmigo (anonimizadas).
    chain_mates: set[int] = set()
    cycle_edges: set[tuple[int, int]] = set()
    chain_edges: set[tuple[int, int]] = set()
    for chain in find_company_chains(graph, me):
        chain_mates.update(chain["company_ids"])
        bucket = cycle_edges if chain["kind"] == "cycle" else chain_edges
        for e in chain["edges"]:
            bucket.add((e["debtor_id"], e["creditor_id"]))

    visible_nodes = {me} | counterparties | chain_mates

    nodes = []
    for node_id in visible_nodes:
        data = graph.nodes[node_id]
        is_cp = node_id in counterparties
        named = node_id == me or is_cp
        nodes.append(
            MyNetworkNode(
                id=str(node_id),
                label=data["name"] if named else anonymized_label(node_id, graph),
                sector=data.get("sector"),
                is_me=node_id == me,
                is_counterparty=is_cp,
                anonymous=not named,
            )
        )

    edges = []
    for i, (u, v, data) in enumerate(graph.edges(data=True)):
        if u not in visible_nodes or v not in visible_nodes:
            continue
        if (u, v) in cycle_edges:
            role = "cycle"
        elif (u, v) in chain_edges:
            role = "chain"
        else:
            role = "other"
        edges.append(
            MyNetworkEdge(
                id=f"e{i}",
                source=str(u),
                target=str(v),
                balance=edge_balance(data) if me in (u, v) else None,
                role=role,
            )
        )

    return MyNetworkResponse(nodes=nodes, edges=edges)


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
