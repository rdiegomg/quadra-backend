"""Deteccion de ciclos dirigidos de deuda (A -> B -> C -> A).

La compensacion potencial de un ciclo es simulada: es el minimo balance
de sus aristas, es decir, el monto que podria compensarse multilateralmente
si todas las partes aceptaran. NO modifica las obligaciones reales.
"""

from decimal import Decimal

import networkx as nx

from app.graph.builder import edge_balance

DEFAULT_MAX_LENGTH = 6
DEFAULT_LIMIT = 50


def _cycle_edges(graph: nx.DiGraph, nodes: list[int]) -> list[tuple[int, int, dict]]:
    """Aristas del ciclo en orden, cerrando sobre el primer nodo."""
    return [
        (nodes[i], nodes[(i + 1) % len(nodes)], graph.edges[nodes[i], nodes[(i + 1) % len(nodes)]])
        for i in range(len(nodes))
    ]


def find_cycles(
    graph: nx.DiGraph,
    max_length: int = DEFAULT_MAX_LENGTH,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Ciclos simples ordenados por compensacion potencial descendente.

    limit acota la cantidad de resultados para evitar explosiones
    combinatorias en grafos densos.
    """
    cycles = []
    for nodes in nx.simple_cycles(graph, length_bound=max_length):
        edges = _cycle_edges(graph, nodes)
        balances = [edge_balance(data) for _, _, data in edges]
        cycles.append(
            {
                "company_ids": nodes,
                "companies": [graph.nodes[n]["name"] for n in nodes],
                "length": len(nodes),
                "potential_compensation": min(balances),
                "total_volume": sum(balances),
                "edges": [
                    {
                        "debtor_id": u,
                        "creditor_id": v,
                        "debtor_name": graph.nodes[u]["name"],
                        "creditor_name": graph.nodes[v]["name"],
                        "balance": edge_balance(data),
                        "obligation_ids": data["obligation_ids"],
                    }
                    for u, v, data in edges
                ],
            }
        )
        if len(cycles) >= limit:
            break

    cycles.sort(key=lambda c: c["potential_compensation"], reverse=True)
    return cycles
