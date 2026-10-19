from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.user import User

REGISTER_BODY = {
    "company_name": "Constructora Andina SRL",
    "nit": "1020304050",
    "legal_type": "SRL",
    "sector_id": 0,  # se reemplaza en cada test con el id real
    "email": "contacto@andina.bo",
    "password": "secreto123",
}


def register(client: TestClient, sector: Sector, **overrides) -> object:
    body = {**REGISTER_BODY, "sector_id": sector.id, **overrides}
    return client.post("/api/auth/register", json=body)


def test_register_creates_company_user(client: TestClient, sector: Sector) -> None:
    r = register(client, sector)
    assert r.status_code == 201
    data = r.json()
    assert data["role"] == "COMPANY"
    assert data["email"] == "contacto@andina.bo"
    assert data["company_name"] == "Constructora Andina SRL"
    assert data["company_id"] is not None


def test_register_rejects_duplicate_nit(client: TestClient, sector: Sector) -> None:
    assert register(client, sector).status_code == 201
    r = register(client, sector, email="otro@andina.bo")
    assert r.status_code == 409


def test_register_rejects_duplicate_email(client: TestClient, sector: Sector) -> None:
    assert register(client, sector).status_code == 201
    r = register(client, sector, nit="9999999999")
    assert r.status_code == 409


def test_register_rejects_unknown_sector(client: TestClient) -> None:
    r = client.post(
        "/api/auth/register", json={**REGISTER_BODY, "sector_id": 999}
    )
    assert r.status_code == 400


def test_login_returns_token_and_me_works(
    client: TestClient, sector: Sector
) -> None:
    register(client, sector)
    r = client.post(
        "/api/auth/login",
        data={"username": "contacto@andina.bo", "password": "secreto123"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "contacto@andina.bo"
    assert r.json()["role"] == "COMPANY"


def test_login_rejects_wrong_password(client: TestClient, sector: Sector) -> None:
    register(client, sector)
    r = client.post(
        "/api/auth/login",
        data={"username": "contacto@andina.bo", "password": "incorrecta"},
    )
    assert r.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_admin_login_and_role(
    client: TestClient, admin_user: User
) -> None:
    r = client.post(
        "/api/auth/login",
        data={"username": "admin@quadra.com", "password": "admin1234"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["role"] == "ADMIN"
    assert r.json()["company_id"] is None
