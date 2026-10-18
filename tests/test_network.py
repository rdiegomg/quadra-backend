from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models.sector import Sector


def register(client: TestClient, sector: Sector, nit: str, email: str) -> str:
    client.post(
        "/api/auth/register",
        json={
            "company_name": f"Empresa {nit}",
            "nit": nit,
            "legal_type": "SRL",
            "sector_id": sector.id,
            "email": email,
            "password": "secreto123",
        },
    )
    return client.post(
        "/api/auth/login", data={"username": email, "password": "secreto123"}
    ).json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_debt(client: TestClient, token: str, counterparty_nit: str, amount: str) -> dict:
    """El usuario con `token` registra una deuda PAYABLE hacia counterparty."""
    r = client.post(
        "/api/obligations",
        json={
            "counterparty_nit": counterparty_nit,
            "direction": "PAYABLE",
            "amount": amount,
            "currency": "BOB",
            "origin_date": str(date.today() - timedelta(days=10)),
            "due_date": str(date.today() + timedelta(days=30)),
            "payment_frequency": "ONE_TIME",
        },
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def network_data(client: TestClient, sector: Sector, admin_user) -> dict:
    """Ciclo A->B->C->A (deudas 10k, 20k, 30k) + cadena abierta D->E->F.

    Compensacion potencial esperada del ciclo: min(10k, 20k, 30k) = 10k.
    """
    ta = register(client, sector, "1001", "a@d.bo")
    tb = register(client, sector, "1002", "b@d.bo")
    tc = register(client, sector, "1003", "c@d.bo")
    td = register(client, sector, "1004", "d@d.bo")
    te = register(client, sector, "1005", "e@d.bo")
    register(client, sector, "1006", "f@d.bo")   # F no debe a nadie

    create_debt(client, ta, "1002", "10000.00")  # A -> B
    create_debt(client, tb, "1003", "20000.00")  # B -> C
    create_debt(client, tc, "1001", "30000.00")  # C -> A  (cierra el ciclo)
    create_debt(client, td, "1005", "5000.00")   # D -> E
    create_debt(client, te, "1006", "7000.00")   # E -> F  (cadena abierta)

    admin = client.post(
        "/api/auth/login",
        data={"username": "admin@quadra.demo", "password": "admin1234"},
    ).json()["access_token"]
    return {"admin": admin, "company_token": ta}


def test_network_graph_elements(client, network_data) -> None:
    r = client.get("/api/admin/network", headers=auth(network_data["admin"]))
    assert r.status_code == 200
    data = r.json()
    assert len(data["nodes"]) == 6
    assert len(data["edges"]) == 5
    ids_in_cycle = {n["data"]["id"] for n in data["nodes"] if n["data"]["in_cycle"]}
    assert len(ids_in_cycle) == 3


def test_cycle_detection_and_compensation(client, network_data) -> None:
    r = client.get("/api/admin/network/cycles", headers=auth(network_data["admin"]))
    assert r.status_code == 200
    cycles = r.json()
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle["length"] == 3
    assert cycle["potential_compensation"] == "10000.00"
    assert cycle["total_volume"] == "60000.00"
    assert len(cycle["edges"]) == 3


def test_open_chains(client, network_data) -> None:
    r = client.get("/api/admin/network/open-chains", headers=auth(network_data["admin"]))
    assert r.status_code == 200
    chains = r.json()
    assert len(chains) == 1
    chain = chains[0]
    assert chain["length"] == 3          # D -> E -> F
    assert chain["ends_in_cycle"] is False
    assert chain["total_volume"] == "12000.00"
    # compensacion sobre cadena: min(5000, 7000)
    assert chain["potential_compensation"] == "5000.00"


def test_statistics(client, network_data) -> None:
    r = client.get("/api/admin/network/statistics", headers=auth(network_data["admin"]))
    assert r.status_code == 200
    stats = r.json()
    assert stats["companies_in_network"] == 6
    assert stats["open_connections"] == 5
    assert stats["companies_in_cycles"] == 3
    assert stats["top_creditors"]
    # volumen compensable = ciclo (10k) + cadena disjunta (5k) = 15k
    assert stats["compensable_volume"] == "15000.00"
    # tasa = 15000 / 72000
    assert float(stats["compensation_rate"]) == pytest.approx(15000 / 72000)
    assert stats["estimated_commission"] == "225.00"  # 1.5% de 15000


def test_company_proposal_and_simulation(client, network_data) -> None:
    company = network_data["company_token"]

    # la empresa A participa del ciclo: propuesta con cancelado = 10k
    r = client.get("/api/companies/me/proposal", headers=auth(company))
    assert r.status_code == 200
    proposal = r.json()
    assert proposal["cancelled_amount"] == "10000.00"
    assert proposal["receivable_forgone"] == "10000.00"
    assert proposal["cycle_length"] == 3
    assert proposal["commission"] == "150.00"          # 1.5%
    assert proposal["est_financial_savings"] == "250.00"  # 2.5%

    # D no esta en ningun ciclo: sin propuesta (null)
    td = client.post(
        "/api/auth/login", data={"username": "d@d.bo", "password": "secreto123"}
    ).json()["access_token"]
    r = client.get("/api/companies/me/proposal", headers=auth(td))
    assert r.status_code == 200 and r.json() is None

    # simulacion admin: 1 ciclo + 1 cadena, 15000 cancelados
    sim = client.get(
        "/api/admin/network/simulation", headers=auth(network_data["admin"])
    ).json()
    assert sim["cycles_used"] == 1
    assert sim["chains_used"] == 1
    assert sim["total_cancelled"] == "15000.00"
    assert sim["estimated_commission"] == "225.00"


def test_network_endpoints_require_admin(client, network_data) -> None:
    company = network_data["company_token"]
    for path in (
        "/api/admin/network",
        "/api/admin/network/cycles",
        "/api/admin/network/open-chains",
        "/api/admin/network/statistics",
        "/api/admin/network/simulation",
    ):
        assert client.get(path, headers=auth(company)).status_code == 403
        assert client.get(path).status_code == 401
