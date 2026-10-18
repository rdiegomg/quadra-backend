from decimal import Decimal

from pydantic import BaseModel


# --- Grafo en formato Cytoscape.js (elements) ---


class CytoscapeElement(BaseModel):
    data: dict


class NetworkGraphResponse(BaseModel):
    nodes: list[CytoscapeElement]
    edges: list[CytoscapeElement]


# --- Ciclos ---


class CycleEdgeResponse(BaseModel):
    debtor_id: int
    creditor_id: int
    debtor_name: str
    creditor_name: str
    balance: Decimal
    obligation_ids: list[int]


class CycleResponse(BaseModel):
    company_ids: list[int]
    companies: list[str]
    length: int
    potential_compensation: Decimal
    total_volume: Decimal
    edges: list[CycleEdgeResponse]


# --- Cadenas abiertas ---


class ChainEdgeResponse(BaseModel):
    debtor_id: int
    creditor_id: int
    debtor_name: str
    creditor_name: str
    balance: Decimal


class ChainResponse(BaseModel):
    company_ids: list[int]
    companies: list[str]
    length: int
    total_volume: Decimal
    potential_compensation: Decimal
    ends_in_cycle: bool
    edges: list[ChainEdgeResponse]


# --- Estadisticas ---


class TopCompanyResponse(BaseModel):
    company_id: int
    company_name: str
    amount: Decimal


class NetworkStatisticsResponse(BaseModel):
    companies_in_network: int
    companies_total: int
    open_connections: int
    obligations_total: int
    obligations_open: int
    total_open_volume: Decimal
    companies_in_cycles: int
    compensable_volume: Decimal
    compensation_rate: Decimal
    estimated_commission: Decimal
    cycles_in_estimate: int
    chains_in_estimate: int
    top_debtors: list[TopCompanyResponse]
    top_creditors: list[TopCompanyResponse]
    companies_by_sector: dict[str, int]


class SimulationResponse(BaseModel):
    """Resultado de un ciclo mensual de compensacion SIMULADO."""

    cycles_used: int
    chains_used: int
    companies_participating: int
    total_cancelled: Decimal
    estimated_commission: Decimal
    currency: str = "BOB"
    note: str = "Simulacion: no modifica obligaciones ni saldos."
