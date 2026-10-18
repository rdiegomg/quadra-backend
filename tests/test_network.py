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


def test_my_chains_cycle_privacy(client, network_data) -> None:
    """A ve su ciclo; las aristas donde no es parte ocultan el monto."""
    r = client.get(
        "/api/companies/me/chains", headers=auth(network_data["company_token"])
    )
    assert r.status_code == 200
    chains = r.json()
    assert len(chains) == 1
    chain = chains[0]
    assert chain["kind"] == "cycle"
    assert chain["status"] == "ready"
    assert chain["cancelled_amount"] == "10000.00"
    assert chain["receivable_forgone"] == "10000.00"
    assert chain["commission"] == "150.00"
    assert len(chain["edges"]) == 3
    # en A->B->C->A las aristas A->B y C->A son visibles; B->C es privada
    visible = [e["balance"] for e in chain["edges"] if e["balance"] is not None]
    assert sorted(visible) == ["10000.00", "30000.00"]
    assert any(e["balance"] is None for e in chain["edges"])


def test_my_chains_positions(client, network_data) -> None:
    """Posicion en la cadena abierta D->E->F cambia el efecto."""
    td = client.post(
        "/api/auth/login", data={"username": "d@d.bo", "password": "secreto123"}
    ).json()["access_token"]
    te = client.post(
        "/api/auth/login", data={"username": "e@d.bo", "password": "secreto123"}
    ).json()["access_token"]

    d_chains = client.get("/api/companies/me/chains", headers=auth(td)).json()
    assert len(d_chains) == 1
    assert d_chains[0]["my_position"] == "source"
    assert d_chains[0]["cancelled_amount"] == "5000.00"
    assert d_chains[0]["receivable_forgone"] == "0.00"

    e_chains = client.get("/api/companies/me/chains", headers=auth(te)).json()
    assert len(e_chains) == 1
    assert e_chains[0]["my_position"] == "middle"
    assert e_chains[0]["cancelled_amount"] == "5000.00"
    assert e_chains[0]["receivable_forgone"] == "5000.00"


def test_my_network_privacy(client, network_data) -> None:
    """D ve a su contraparte E con nombre, pero F aparece anonimizado
    y la arista E->F con monto privado."""
    td = client.post(
        "/api/auth/login", data={"username": "d@d.bo", "password": "secreto123"}
    ).json()["access_token"]
    r = client.get("/api/companies/me/network", headers=auth(td))
    assert r.status_code == 200
    data = r.json()

    labels = {n["label"] for n in data["nodes"]}
    assert "Empresa 1005" in labels            # contraparte E, nombrada
    assert "Empresa 1006" not in labels        # F es anonima
    assert any(n["anonymous"] for n in data["nodes"])

    visible = [e for e in data["edges"] if e["balance"] is not None]
    private = [e for e in data["edges"] if e["balance"] is None]
    assert len(visible) == 1 and visible[0]["balance"] == "5000.00"
    assert len(private) == 1                    # E->F: monto privado


def test_import_csv(client, network_data) -> None:
    """Carga de planilla CSV: crea validas, omite NITs inexistentes."""
    csv_data = (
        "tipo,nit_contraparte,monto,fecha_emision,fecha_vencimiento,nro_factura\n"
        f"pagar,1005,1500.50,{date.today() - timedelta(days=5)},"
        f"{date.today() + timedelta(days=40)},9901\n"
        "cobrar,9999,100,2026-10-01,2026-11-01,777\n"
        "pagar,1005,-50,2026-10-01,2026-11-01,888\n"
    )
    r = client.post(
        "/api/obligations/import",
        files={"file": ("planilla.csv", csv_data, "text/csv")},
        headers=auth(network_data["company_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert len(body["skipped"]) == 2            # NIT inexistente + monto negativo

    payables = client.get(
        "/api/obligations/payable", headers=auth(network_data["company_token"])
    ).json()
    imported = [o for o in payables if o["reference"] == "9901"]
    assert len(imported) == 1
    assert imported[0]["amount"] == "1500.50"


def test_obligations_in_chain_flag(client, network_data) -> None:
    """Las obligaciones del ciclo llegan marcadas in_chain."""
    r = client.get(
        "/api/obligations/receivable", headers=auth(network_data["company_token"])
    )
    assert r.status_code == 200
    items = r.json()
    # A solo tiene una acreencia (C->A, la de 30000) y esta en el ciclo
    assert len(items) == 1
    assert items[0]["in_chain"] is True


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
