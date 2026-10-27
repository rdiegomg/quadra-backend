"""Flujo 1-2-3 del documento (§3.2): propuesta multilateral persistente,
aceptacion de todos los participantes, ejecucion real sobre saldos y
acta de compensacion."""

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.test_obligations import auth, create_obligation, register_company


def _triangle(client: TestClient, sector) -> tuple[str, str, str]:
    """Ciclo A -> B -> C -> A, cada eslabon con distinto saldo."""
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    token_b = register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    token_c = register_company(client, sector, "3333", "c@x.bo", "Empresa C")

    create_obligation(client, token_a, "2222", amount="30000.00")   # A -> B
    create_obligation(client, token_b, "3333", amount="20000.00")   # B -> C
    create_obligation(client, token_c, "1111", amount="25000.00")   # C -> A
    return token_a, token_b, token_c


def _chains(client: TestClient, token: str) -> list[dict]:
    return client.get(
        "/api/companies/me/chains", headers=auth(token)
    ).json()


def test_proposal_materializes_with_pending_viewer(
    client: TestClient, sector
) -> None:
    token_a, _, _ = _triangle(client, sector)

    chains = _chains(client, token_a)
    cycle = next(c for c in chains if c["kind"] == "cycle")

    assert cycle["proposal_id"] is not None
    assert cycle["proposal_status"] == "PENDING"
    # A queda pendiente; B y C simuladas ya aceptaron
    assert cycle["my_decision"] is None
    assert cycle["acceptances_done"] == 2
    assert cycle["acceptances_total"] == 3


def test_accept_executes_and_acta_is_issued(
    client: TestClient, sector
) -> None:
    token_a, token_b, _ = _triangle(client, sector)

    cycle = next(c for c in _chains(client, token_a) if c["kind"] == "cycle")
    pid = cycle["proposal_id"]

    r = client.post(
        f"/api/proposals/{pid}/respond",
        json={"action": "accept"},
        headers=auth(token_a),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "EXECUTED"
    assert r.json()["acceptances_done"] == 3
    assert r.json()["executed_at"] is not None

    # Saldos reales reducidos por el minimo del ciclo (20000)
    obs_a = client.get(
        "/api/obligations/payable", headers=auth(token_a)
    ).json()
    assert obs_a[0]["status"] == "PARTIAL"
    assert obs_a[0]["balance"] == "10000.00"  # 30000 - 20000, residuo vivo

    obs_b = client.get(
        "/api/obligations/payable", headers=auth(token_b)
    ).json()
    assert obs_b[0]["status"] == "PAID"  # 20000 - 20000 = cancelado total

    # Acta disponible para cualquier participante
    acta = client.get(f"/api/proposals/{pid}/acta", headers=auth(token_b)).json()
    assert acta["acta_number"].startswith("AC-")
    assert acta["all_accepted"] is True
    assert acta["total_cancelled"] == "20000.00"
    assert len(acta["companies"]) == 3
    assert len(acta["tranches"]) == 3
    assert {t["debtor_name"] for t in acta["tranches"]} == {
        "Empresa A",
        "Empresa B",
        "Empresa C",
    }


def test_reject_blocks_execution(client: TestClient, sector) -> None:
    token_a, _, _ = _triangle(client, sector)

    cycle = next(c for c in _chains(client, token_a) if c["kind"] == "cycle")
    pid = cycle["proposal_id"]

    r = client.post(
        f"/api/proposals/{pid}/respond",
        json={"action": "reject"},
        headers=auth(token_a),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "REJECTED"

    # Saldos intactos
    obs = client.get(
        "/api/obligations/payable", headers=auth(token_a)
    ).json()
    assert obs[0]["balance"] == "30000.00"

    # No se puede volver a responder ni ver acta
    r = client.post(
        f"/api/proposals/{pid}/respond",
        json={"action": "accept"},
        headers=auth(token_a),
    )
    assert r.status_code == 409
    assert (
        client.get(f"/api/proposals/{pid}/acta", headers=auth(token_a)).status_code
        == 409
    )


def test_non_participant_cannot_respond_or_view(
    client: TestClient, sector
) -> None:
    token_a, _, _ = _triangle(client, sector)
    token_d = register_company(client, sector, "4444", "d@x.bo", "Empresa D")

    pid = next(c for c in _chains(client, token_a) if c["kind"] == "cycle")[
        "proposal_id"
    ]

    assert (
        client.post(
            f"/api/proposals/{pid}/respond",
            json={"action": "accept"},
            headers=auth(token_d),
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/proposals/{pid}", headers=auth(token_d)).status_code
        == 404
    )


def test_executed_proposal_is_immutable_and_full_cancel_marks_paid(
    client: TestClient, sector
) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    token_b = register_company(client, sector, "2222", "b@x.bo", "Empresa B")

    # Ciclo de 2: A -> B y B -> A con el mismo monto = cancelacion total
    create_obligation(client, token_a, "2222", amount="15000.00")
    create_obligation(client, token_b, "1111", amount="15000.00")

    cycle = next(
        c for c in _chains(client, token_a) if c["kind"] == "cycle"
    )
    pid = cycle["proposal_id"]

    assert client.post(
        f"/api/proposals/{pid}/respond",
        json={"action": "accept"},
        headers=auth(token_a),
    ).json()["status"] == "EXECUTED"

    obs = client.get(
        "/api/obligations/payable", headers=auth(token_a)
    ).json()
    assert obs[0]["balance"] == "0.00"
    assert obs[0]["status"] == "PAID"

    # Evento COMPENSATED registrado
    events = client.get(
        f"/api/obligations/{obs[0]['id']}/events", headers=auth(token_a)
    ).json()
    assert "COMPENSATED" in [e["event_type"] for e in events]

    # Doble ejecucion imposible: responder de nuevo es 409
    assert (
        client.post(
            f"/api/proposals/{pid}/respond",
            json={"action": "accept"},
            headers=auth(token_a),
        ).status_code
        == 409
    )
