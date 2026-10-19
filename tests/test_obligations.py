from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.sector import Sector


def register_company(
    client: TestClient, sector: Sector, nit: str, email: str, name: str
) -> str:
    r = client.post(
        "/api/auth/register",
        json={
            "company_name": name,
            "nit": nit,
            "legal_type": "SRL",
            "sector_id": sector.id,
            "email": email,
            "password": "secreto123",
        },
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login", data={"username": email, "password": "secreto123"}
    )
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def admin_token(client: TestClient) -> str:
    r = client.post(
        "/api/auth/login",
        data={"username": "admin@quadra.com", "password": "admin1234"},
    )
    return r.json()["access_token"]


OBLIGATION_BODY = {
    "direction": "PAYABLE",
    "amount": "50000.00",
    "currency": "BOB",
    "interest_rate": "5.00",
    "origin_date": str(date.today() - timedelta(days=30)),
    "due_date": str(date.today() + timedelta(days=60)),
    "payment_frequency": "ONE_TIME",
}


def create_obligation(client, token, counterparty_nit, **overrides):
    return client.post(
        "/api/obligations",
        json={**OBLIGATION_BODY, "counterparty_nit": counterparty_nit, **overrides},
        headers=auth(token),
    )


def test_create_and_list_obligations(client: TestClient, sector: Sector) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")

    r = create_obligation(client, token_a, "2222")  # A debe a B
    assert r.status_code == 201
    data = r.json()
    assert data["debtor"]["nit"] == "1111"
    assert data["creditor"]["nit"] == "2222"
    assert data["status"] == "PENDING"
    assert data["balance"] == "50000.00"

    # B la ve como por cobrar, A como por pagar
    token_b = client.post(
        "/api/auth/login", data={"username": "b@x.bo", "password": "secreto123"}
    ).json()["access_token"]
    assert len(client.get("/api/obligations/receivable", headers=auth(token_b)).json()) == 1
    assert len(client.get("/api/obligations/payable", headers=auth(token_a)).json()) == 1
    assert len(client.get("/api/obligations/receivable", headers=auth(token_a)).json()) == 0


def test_unknown_counterparty_and_self_debt(client, sector) -> None:
    token = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    assert create_obligation(client, token, "9999").status_code == 404
    assert create_obligation(client, token, "1111").status_code == 400


def test_privacy_third_company_gets_404(client, sector) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    token_c = register_company(client, sector, "3333", "c@x.bo", "Empresa C")

    ob_id = create_obligation(client, token_a, "2222").json()["id"]
    assert client.get(f"/api/obligations/{ob_id}", headers=auth(token_c)).status_code == 404


def test_status_transition_records_event(client, sector) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    ob_id = create_obligation(client, token_a, "2222").json()["id"]

    r = client.patch(
        f"/api/obligations/{ob_id}/status",
        json={"status": "PAID"},
        headers=auth(token_a),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PAID"
    assert r.json()["balance"] == "0.00"

    events = client.get(f"/api/obligations/{ob_id}/events", headers=auth(token_a)).json()
    assert [e["event_type"] for e in events] == ["CREATED", "STATUS_CHANGED"]
    assert events[1]["previous_status"] == "PENDING"
    assert events[1]["new_status"] == "PAID"

    # ya pagada: no acepta otra transicion
    r = client.patch(
        f"/api/obligations/{ob_id}/status",
        json={"status": "CANCELLED"},
        headers=auth(token_a),
    )
    assert r.status_code == 409


def test_summary(client, sector) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")

    create_obligation(client, token_a, "2222", amount="10000.00")          # A debe 10k
    create_obligation(client, token_a, "2222", direction="RECEIVABLE",
                      amount="4000.00")                                   # B debe a A

    s = client.get("/api/companies/me/summary", headers=auth(token_a)).json()
    assert s["total_payable"] == "10000.00"
    assert s["total_receivable"] == "4000.00"
    assert s["net_balance"] == "-6000.00"
    assert s["pending_obligations"] == 2


def test_admin_endpoints(client, sector, admin_user) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    ob_id = create_obligation(client, token_a, "2222").json()["id"]

    admin = admin_token(client)
    # admin ve cualquier obligacion y todas las empresas
    assert client.get(f"/api/obligations/{ob_id}", headers=auth(admin)).status_code == 200
    companies = client.get("/api/admin/companies", headers=auth(admin)).json()
    assert len(companies) == 2

    # empresa no puede usar endpoints admin
    assert client.get("/api/admin/companies", headers=auth(token_a)).status_code == 403


def test_payment_schedule_generated_and_private(client, sector) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    token_c = register_company(client, sector, "3333", "c@x.bo", "Empresa C")

    origin = date.today()
    due = origin + timedelta(days=200)
    ob_id = create_obligation(
        client,
        token_a,
        "2222",
        amount="9000.00",
        origin_date=str(origin),
        due_date=str(due),
        payment_frequency="MONTHLY",
    ).json()["id"]

    schedules = client.get(
        f"/api/obligations/{ob_id}/schedules", headers=auth(token_a)
    ).json()
    assert len(schedules) >= 2
    # la suma de cuotas cubre exactamente el monto y la ultima vence en due_date
    assert sum(Decimal(s["amount"]) for s in schedules) == Decimal("9000.00")
    assert schedules[-1]["due_date"] == str(due)
    assert all(s["status"] == "PENDING" for s in schedules)

    # pago unico genera una sola cuota en la fecha de vencimiento
    ob2 = create_obligation(client, token_a, "2222", amount="1000.00").json()["id"]
    s2 = client.get(f"/api/obligations/{ob2}/schedules", headers=auth(token_a)).json()
    assert len(s2) == 1

    # tercero no puede ver el plan
    assert (
        client.get(f"/api/obligations/{ob_id}/schedules", headers=auth(token_c)).status_code
        == 404
    )


def test_admin_obligations_list(client, sector, admin_user) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    ob_id = create_obligation(client, token_a, "2222").json()["id"]
    create_obligation(client, token_a, "2222")

    admin = admin_token(client)
    open_list = client.get("/api/admin/obligations", headers=auth(admin)).json()
    assert len(open_list) == 2  # ambas abiertas
    assert {o["debtor"]["nit"] for o in open_list} == {"1111"}

    # al pagar una deja de aparecer entre las abiertas por defecto
    client.patch(
        f"/api/obligations/{ob_id}/status",
        json={"status": "PAID"},
        headers=auth(admin),
    )
    open_list = client.get("/api/admin/obligations", headers=auth(admin)).json()
    assert len(open_list) == 1
    # filtro explicito por estado
    paid = client.get(
        "/api/admin/obligations?status_filter=PAID", headers=auth(admin)
    ).json()
    assert len(paid) == 1 and paid[0]["id"] == ob_id

    assert client.get("/api/admin/obligations", headers=auth(token_a)).status_code == 403


def test_document_upload_list_download(client, sector, tmp_path) -> None:
    token_a = register_company(client, sector, "1111", "a@x.bo", "Empresa A")
    register_company(client, sector, "2222", "b@x.bo", "Empresa B")
    token_c = register_company(client, sector, "3333", "c@x.bo", "Empresa C")
    ob_id = create_obligation(client, token_a, "2222").json()["id"]

    # mime no permitido
    r = client.post(
        f"/api/obligations/{ob_id}/documents",
        files={"file": ("evil.exe", b"MZ", "application/x-msdownload")},
        headers=auth(token_a),
    )
    assert r.status_code == 415

    # pdf valido
    r = client.post(
        f"/api/obligations/{ob_id}/documents",
        files={"file": ("factura.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=auth(token_a),
    )
    assert r.status_code == 201
    doc_id = r.json()["id"]

    docs = client.get(f"/api/obligations/{ob_id}/documents", headers=auth(token_a)).json()
    assert len(docs) == 1 and docs[0]["filename"] == "factura.pdf"

    r = client.get(f"/api/documents/{doc_id}/download", headers=auth(token_a))
    assert r.status_code == 200 and r.content == b"%PDF-1.4 fake"

    # tercero no puede descargar
    assert client.get(
        f"/api/documents/{doc_id}/download", headers=auth(token_c)
    ).status_code == 404
