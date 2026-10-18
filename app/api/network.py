from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.graph.analysis import (
    find_open_chains,
    network_statistics,
    nodes_in_cycles,
)
from app.graph.builder import build_debt_graph, edge_balance
from app.graph.cycles import DEFAULT_LIMIT, DEFAULT_MAX_LENGTH, find_cycles
from app.models.user import User
from app.schemas.network import (
    ChainResponse,
    CycleResponse,
    CytoscapeElement,
    NetworkGraphResponse,
    NetworkStatisticsResponse,
)

router = APIRouter(
    prefix="/admin/network",
    tags=["network"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=NetworkGraphResponse)
def get_network_graph(
    current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> NetworkGraphResponse:
    """Grafo completo de deuda abierta en formato Cytoscape.js."""
    graph = build_debt_graph(db)
    in_cycle = nodes_in_cycles(graph)

    nodes = [
        CytoscapeElement(
            data={
                "id": str(n),
                "label": graph.nodes[n]["name"],
                "nit": graph.nodes[n]["nit"],
                "sector": graph.nodes[n].get("sector"),
                "in_cycle": n in in_cycle,
            }
        )
            for n in graph.nodes
    ]
    edges = [
        CytoscapeElement(
            data={
                "id": f"{u}-{v}",
                "source": str(u),
                "target": str(v),
                "balance": edge_balance(data),
                "count": data["count"],
                "obligation_ids": data["obligation_ids"],
                "currency": data["currency"],
            }
        )
        for u, v, data in graph.edges(data=True)
    ]
    return NetworkGraphResponse(nodes=nodes, edges=edges)


@router.get("/cycles", response_model=list[CycleResponse])
def get_cycles(
    max_length: int = Query(default=DEFAULT_MAX_LENGTH, ge=2, le=10),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Ciclos de deuda con compensacion potencial SIMULADA.

    La compensacion no modifica obligaciones: es el minimo balance
    de las aristas del ciclo."""
    graph = build_debt_graph(db)
    return find_cycles(graph, max_length=max_length, limit=limit)


@router.get("/open-chains", response_model=list[ChainResponse])
def get_open_chains(
    current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict]:
    """Cadenas de deuda abiertas (no compensables por si solas)."""
    graph = build_debt_graph(db)
    return find_open_chains(graph)


@router.get("/statistics", response_model=NetworkStatisticsResponse)
def get_statistics(
    current_user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    graph = build_debt_graph(db)
    return network_statistics(graph, db)
