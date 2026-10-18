"""Analisis de la red de deuda: cadenas abiertas y estadisticas.

Una cadena abierta es un camino dirigido que NO cierra ciclo
(A -> B -> C -> D). No representan una compensacion completa sin un
mecanismo adicional de liquidacion - se reportan solo como contexto.
"""

from collections import Counter, defaultdict
from decimal import Decimal

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.graph.builder import edge_balance
from app.models.company import Company
from app.models.enums import ObligationStatus
from app.models.obligation import Obligation

MAX_CHAIN_LENGTH = 8
MAX_CHAINS = 25


def nodes_in_cycles(graph: nx.DiGraph) -> set[int]:
    """Nodos que pertenecen a algun ciclo (SCC no triviales)."""
    in_cycle = set()
    for scc in nx.strongly_connected_components(graph):
        if len(scc) > 1:
            in_cycle.update(scc)
    return in_cycle


def find_open_chains(
    graph: nx.DiGraph,
    max_length: int = MAX_CHAIN_LENGTH,
    limit: int = MAX_CHAINS,
) -> list[dict]:
    """Cadenas abiertas desde nodos fuente (in-degree 0).

    Camino greedy siguiendo la arista de mayor balance. Si el ultimo
    nodo pertenece a un ciclo, ends_in_cycle=True.
    """
    in_cycle = nodes_in_cycles(graph)
    chains = []

    sources = [n for n in graph.nodes if graph.in_degree(n) == 0]
    sources.sort(key=lambda n: -graph.out_degree(n))

    for source in sources:
        visited = {source}
        path = [source]
        current = source

        while len(path) < max_length:
            candidates = [
                (edge_balance(data), v)
                for _, v, data in graph.out_edges(current, data=True)
                if v not in visited
            ]
            if not candidates:
                break
            _, nxt = max(candidates)
            path.append(nxt)
            visited.add(nxt)
            current = nxt

        if len(path) < 2:
            continue

        volume = Decimal("0")
        edges = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            data = graph.edges[u, v]
            bal = edge_balance(data)
            volume += bal
            edges.append(
                {
                    "debtor_id": u,
                    "creditor_id": v,
                    "debtor_name": graph.nodes[u]["name"],
                    "creditor_name": graph.nodes[v]["name"],
                    "balance": bal,
                }
            )

        chains.append(
            {
                "company_ids": path,
                "companies": [graph.nodes[n]["name"] for n in path],
                "length": len(path),
                "total_volume": volume,
                "ends_in_cycle": path[-1] in in_cycle,
                "edges": edges,
            }
        )
        if len(chains) >= limit:
            break

    chains.sort(key=lambda c: (c["length"], c["total_volume"]), reverse=True)
    return chains


def network_statistics(graph: nx.DiGraph, db: Session) -> dict:
    """Metricas globales de la red para el dashboard admin."""
    in_cycle = nodes_in_cycles(graph)
    total_volume = sum((edge_balance(d) for _, _, d in graph.edges(data=True)), Decimal("0"))

    # top deudores y acreedores por balance abierto
    debt_by_node: dict[int, Decimal] = defaultdict(Decimal)
    credit_by_node: dict[int, Decimal] = defaultdict(Decimal)
    for u, v, data in graph.edges(data=True):
        bal = edge_balance(data)
        debt_by_node[u] += bal
        credit_by_node[v] += bal

    def top(d: dict[int, Decimal], n: int = 5) -> list[dict]:
        return [
            {
                "company_id": cid,
                "company_name": graph.nodes[cid]["name"],
                "amount": amt,
            }
            for cid, amt in sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
        ]

    companies_by_sector = Counter(
        graph.nodes[n].get("sector") or "Sin rubro" for n in graph.nodes
    )

    obligations_total = db.scalar(select(func.count(Obligation.id)))
    obligations_open = db.scalar(
        select(func.count(Obligation.id)).where(
            Obligation.status.in_(
                (
                    ObligationStatus.PENDING,
                    ObligationStatus.PARTIAL,
                    ObligationStatus.OVERDUE,
                )
            )
        )
    )

    return {
        "companies_in_network": graph.number_of_nodes(),
        "companies_total": db.scalar(select(func.count(Company.id))),
        "open_connections": graph.number_of_edges(),
        "obligations_total": obligations_total,
        "obligations_open": obligations_open,
        "total_open_volume": total_volume,
        "companies_in_cycles": len(in_cycle),
        "top_debtors": top(debt_by_node),
        "top_creditors": top(credit_by_node),
        "companies_by_sector": dict(companies_by_sector),
    }
