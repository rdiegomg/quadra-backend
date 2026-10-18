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
from app.graph.cycles import find_cycles
from app.models.company import Company
from app.models.enums import ObligationStatus
from app.models.obligation import Obligation

MAX_CHAIN_LENGTH = 8
MAX_CHAINS = 25

# Comision simulada del modelo de negocio: ~1.5% sobre deuda cancelada.
COMMISSION_RATE = Decimal("0.015")


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
        min_balance: Decimal | None = None
        edges = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            data = graph.edges[u, v]
            bal = edge_balance(data)
            volume += bal
            min_balance = bal if min_balance is None else min(min_balance, bal)
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
                # Compensacion simulada sobre la cadena (path-enabled):
                # minimo balance de sus aristas preserva la posicion neta
                # de los nodos intermedios.
                "potential_compensation": min_balance,
                "ends_in_cycle": path[-1] in in_cycle,
                "edges": edges,
            }
        )
        if len(chains) >= limit:
            break

    chains.sort(key=lambda c: (c["length"], c["total_volume"]), reverse=True)
    return chains


def anonymized_label(node_id: int, graph: nx.DiGraph) -> str:
    """Etiqueta privada: 'Empresa de <rubro>' (identidad protegida)."""
    sector = graph.nodes[node_id].get("sector") or "rubro desconocido"
    return f"Empresa de {sector}"


def my_counterparties(graph: nx.DiGraph, me: int) -> set[int]:
    """Vecinos directos (deudores y acreedores) de mi empresa."""
    if me not in graph:
        return set()
    return set(graph.predecessors(me)) | set(graph.successors(me))


def find_company_chains(graph: nx.DiGraph, me: int) -> list[dict]:
    """Ciclos y cadenas donde participa la empresa, con privacidad.

    Reglas de privacidad (como el mapa del prototipo):
    - Mi empresa y mis contrapartes directas ven nombre real.
    - El resto de empresas aparece como 'Empresa de <rubro>'.
    - El balance de una arista solo es visible si yo soy parte de ella.
    """
    if me not in graph:
        return []

    counterparties = my_counterparties(graph, me)

    def label(node_id: int) -> str:
        if node_id == me:
            return graph.nodes[node_id]["name"]
        if node_id in counterparties:
            return graph.nodes[node_id]["name"]
        return anonymized_label(node_id, graph)

    def edge_detail(u: int, v: int, balance: Decimal, cancelled: Decimal) -> dict:
        visible = me in (u, v)
        return {
            "debtor_id": u,
            "creditor_id": v,
            "debtor_label": label(u),
            "creditor_label": label(v),
            "debtor_is_me": u == me,
            "creditor_is_me": v == me,
            "balance": balance if visible else None,
            "cancelled": cancelled,
            "remainder": (balance - cancelled) if visible else None,
            "obligation_ids": graph.edges[u, v]["obligation_ids"] if visible else [],
        }

    results = []

    for cycle in find_cycles(graph):
        if me not in cycle["company_ids"]:
            continue
        comp = cycle["potential_compensation"]
        named = [
            graph.nodes[n]["name"]
            for n in cycle["company_ids"]
            if n == me or n in counterparties
        ]
        results.append(
            {
                "kind": "cycle",
                "company_ids": cycle["company_ids"],
                "labels": [label(n) for n in cycle["company_ids"]],
                "named_participants": named,
                "anonymized_count": len(cycle["company_ids"]) - len(named),
                "length": cycle["length"],
                "my_position": "member",
                "cancelled_amount": comp,
                "receivable_forgone": comp,
                "potential_compensation": comp,
                "status": "ready",
                "edges": [
                    edge_detail(
                        e["debtor_id"], e["creditor_id"], e["balance"], comp
                    )
                    for e in cycle["edges"]
                ],
            }
        )

    for chain in find_open_chains(graph):
        if me not in chain["company_ids"]:
            continue
        path = chain["company_ids"]
        comp = chain["potential_compensation"]
        named = [
            graph.nodes[n]["name"]
            for n in path
            if n == me or n in counterparties
        ]
        # En una cadena abierta los extremos no son neutros:
        # la fuente paga menos; el sumidero cobra menos; los del medio
        # quedan igual (pagan menos y cobran menos).
        if me == path[0]:
            position, cancelled, forgone = "source", comp, Decimal("0.00")
        elif me == path[-1]:
            position, cancelled, forgone = "sink", Decimal("0.00"), comp
        else:
            position, cancelled, forgone = "middle", comp, comp
        results.append(
            {
                "kind": "chain",
                "company_ids": path,
                "labels": [label(n) for n in path],
                "named_participants": named,
                "anonymized_count": len(path) - len(named),
                "length": len(path),
                "my_position": position,
                "cancelled_amount": cancelled,
                "receivable_forgone": forgone,
                "potential_compensation": comp,
                "status": "compensable",
                "edges": [
                    edge_detail(
                        e["debtor_id"], e["creditor_id"], e["balance"], comp
                    )
                    for e in chain["edges"]
                ],
            }
        )

    results.sort(
        key=lambda c: (c["kind"] != "cycle", -c["potential_compensation"])
    )
    return results


def compensable_obligation_ids(graph: nx.DiGraph) -> set[int]:
    """Ids de obligaciones que participan en algun ciclo o cadena."""
    ids: set[int] = set()
    for cycle in find_cycles(graph):
        for e in cycle["edges"]:
            ids.update(e["obligation_ids"])
    for chain in find_open_chains(graph):
        for i in range(len(chain["company_ids"]) - 1):
            u = chain["company_ids"][i]
            v = chain["company_ids"][i + 1]
            ids.update(graph.edges[u, v]["obligation_ids"])
    return ids


def estimate_compensable_volume(graph: nx.DiGraph) -> tuple[Decimal, int, int]:
    """Estimacion greedy del volumen compensable en un ciclo mensual.

    Toma ciclos disjuntos por nodos (ordenados por compensacion) y luego
    cadenas abiertas disjuntas. Es una cota conservadora: el motor real
    optimizaria sobre el grafo completo. Devuelve (volumen, n_ciclos,
    n_cadenas).
    """
    used: set[int] = set()
    volume = Decimal("0")
    n_cycles = 0
    n_chains = 0

    for cycle in find_cycles(graph):
        ids = set(cycle["company_ids"])
        if ids & used:
            continue
        used |= ids
        volume += cycle["potential_compensation"]
        n_cycles += 1

    for chain in find_open_chains(graph):
        ids = set(chain["company_ids"])
        if ids & used:
            continue
        used |= ids
        volume += chain["potential_compensation"]
        n_chains += 1

    return volume, n_cycles, n_chains


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

    compensable, n_cycles, n_chains = estimate_compensable_volume(graph)
    compensation_rate = (
        (compensable / total_volume) if total_volume > 0 else Decimal("0")
    )

    return {
        "companies_in_network": graph.number_of_nodes(),
        "companies_total": db.scalar(select(func.count(Company.id))),
        "open_connections": graph.number_of_edges(),
        "obligations_total": obligations_total,
        "obligations_open": obligations_open,
        "total_open_volume": total_volume,
        "companies_in_cycles": len(in_cycle),
        "compensable_volume": compensable,
        "compensation_rate": compensation_rate,
        "estimated_commission": (compensable * COMMISSION_RATE).quantize(
            Decimal("0.01")
        ),
        "cycles_in_estimate": n_cycles,
        "chains_in_estimate": n_chains,
        "top_debtors": top(debt_by_node),
        "top_creditors": top(credit_by_node),
        "companies_by_sector": dict(companies_by_sector),
    }
