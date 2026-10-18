"""Construccion del grafo dirigido de obligaciones entre empresas.

Cada empresa es un nodo; las obligaciones abiertas (PENDING, PARTIAL,
OVERDUE) se agregan en una unica arista dirigida deudor -> acreedor con
el balance total y la lista de obligaciones originales.
"""

from decimal import Decimal

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.company import Company
from app.models.enums import ObligationStatus
from app.models.obligation import Obligation

OPEN_STATUSES = (
    ObligationStatus.PENDING,
    ObligationStatus.PARTIAL,
    ObligationStatus.OVERDUE,
)


def build_debt_graph(db: Session) -> nx.DiGraph:
    """Grafo dirigido de deuda abierta.

    Nodos: empresas con atributos name/nit/sector.
    Aristas (deudor -> acreedor): balance total, cantidad e ids de
    obligaciones, moneda (las obligaciones demo comparten BOB).
    """
    obligations = list(
        db.scalars(
            select(Obligation)
            .where(Obligation.status.in_(OPEN_STATUSES))
            .options(
                joinedload(Obligation.debtor).joinedload(Company.sector),
                joinedload(Obligation.creditor).joinedload(Company.sector),
            )
        )
    )

    graph = nx.DiGraph()

    for obligation in obligations:
        for company in (obligation.debtor, obligation.creditor):
            if company.id not in graph:
                graph.add_node(
                    company.id,
                    name=company.name,
                    nit=company.nit,
                    sector=company.sector_name,
                )

        u, v = obligation.debtor_company_id, obligation.creditor_company_id
        if graph.has_edge(u, v):
            edge = graph.edges[u, v]
            edge["balance"] += obligation.balance
            edge["count"] += 1
            edge["obligation_ids"].append(obligation.id)
        else:
            graph.add_edge(
                u,
                v,
                balance=obligation.balance,
                count=1,
                obligation_ids=[obligation.id],
                currency=obligation.currency,
            )

    return graph


def edge_balance(data: dict) -> Decimal:
    """Balance agregado de una arista (Decimal)."""
    return Decimal(str(data["balance"]))
