"""Generador de datos ficticios de QUADRA (datos de demostracion, no reales).

Uso:  python -m scripts.seed_demo [--fresh]

Genera de forma determinista (semilla fija):
- 100 empresas ficticias con NIT DEMO-XXXXXX y un usuario COMPANY c/u
- ~300 obligaciones entre ellas (PENDING, OVERDUE, PARTIAL, PAID)
- 6 ciclos de deuda intencionales y 4 cadenas abiertas, sobre
  obligaciones abiertas (detectables por el motor de grafos)
- Cuotas en payment_schedules para obligaciones con periodicidad
- Algunos documentos PDF ficticios
- Una red 'QUADRA Demo' con todas las empresas

Sin --fresh aborta si ya existen empresas. Con --fresh elimina todos
los datos de negocio (conserva el usuario ADMIN) y regenera.
"""

import argparse
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from faker import Faker
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.company import Company
from app.models.document import Document
from app.models.enums import (
    InstallmentStatus,
    ObligationStatus,
    PaymentFrequency,
    UserRole,
)
from app.models.network import Network, NetworkMember
from app.models.obligation import Obligation, ObligationEvent, PaymentSchedule
from app.models.sector import Sector
from app.models.user import User

SEED = 42
NUM_COMPANIES = 100
NUM_RANDOM_OBLIGATIONS = 260
CYCLES = [(3, 4), (4, 2), (5, 0)]  # (longitud, cantidad) -> 6 ciclos, 13 aristas
CHAINS = [(3, 2), (4, 2)]  # (longitud, cantidad) -> 4 cadenas, 10 aristas
NUM_DEMO_DOCUMENTS = 12
DEMO_PASSWORD = "demo1234"

fake = Faker("es_MX")
fake.seed_instance(SEED)
rng = random.Random(SEED)


def wipe(db) -> None:
    """Elimina datos de negocio conservando usuarios ADMIN."""
    for model in (
        Document,
        ObligationEvent,
        PaymentSchedule,
        Obligation,
        NetworkMember,
        Network,
        User,
        Company,
    ):
        if model is User:
            db.execute(delete(User).where(User.role == UserRole.COMPANY))
        else:
            db.execute(delete(model))
    db.commit()


def create_companies(db, sectors) -> list[Company]:
    shared_hash = hash_password(DEMO_PASSWORD)
    companies = []
    for i in range(NUM_COMPANIES):
        legal_type = rng.choice(["SRL", "SA", "SA", "SRL", "SCA"])
        company = Company(
            name=f"{fake.company()} {legal_type}",
            nit=f"DEMO-{i + 1:06d}",
            legal_type=legal_type,
            sector_id=rng.choice(sectors).id,
        )
        db.add(company)
        db.flush()
        db.add(
            User(
                company_id=company.id,
                email=f"empresa{i + 1:03d}@quadra.demo",
                password_hash=shared_hash,
                role=UserRole.COMPANY,
            )
        )
        companies.append(company)
    return companies


def random_obligation_dates() -> tuple[date, date]:
    origin = date.today() - timedelta(days=rng.randint(10, 300))
    due = origin + timedelta(days=rng.randint(15, 365))
    return origin, due


def pick_status(due: date) -> tuple[ObligationStatus, Decimal | None]:
    """Devuelve (status, fraccion_pagada o None)."""
    r = rng.random()
    if r < 0.60:
        status = ObligationStatus.PENDING
    elif r < 0.75:
        status = ObligationStatus.OVERDUE if due < date.today() else ObligationStatus.PENDING
    elif r < 0.88:
        status = ObligationStatus.PARTIAL
    else:
        status = ObligationStatus.PAID
    fraction = Decimal("0.4") if status == ObligationStatus.PARTIAL else None
    return status, fraction


def add_obligation(
    db,
    debtor: Company,
    creditor: Company,
    status: ObligationStatus | None = None,
    amount: Decimal | None = None,
    due: date | None = None,
) -> Obligation:
    if amount is None:
        amount = Decimal(rng.randint(500, 120000)).quantize(Decimal("0.01"))
    origin, computed_due = random_obligation_dates()
    if due is not None:
        computed_due = due

    if status is None:
        status, fraction = pick_status(computed_due)
    else:
        fraction = Decimal("0.5") if status == ObligationStatus.PARTIAL else None

    balance = Decimal("0") if status == ObligationStatus.PAID else amount
    if fraction:
        balance = (amount * (1 - fraction)).quantize(Decimal("0.01"))

    frequency = (
        rng.choice(list(PaymentFrequency))
        if rng.random() < 0.15
        else PaymentFrequency.ONE_TIME
    )

    obligation = Obligation(
        debtor_company_id=debtor.id,
        creditor_company_id=creditor.id,
        amount=amount,
        balance=balance,
        currency="BOB",
        interest_rate=Decimal(rng.uniform(1, 12)).quantize(Decimal("0.01"))
        if rng.random() < 0.4
        else None,
        origin_date=origin,
        due_date=computed_due,
        payment_frequency=frequency,
        status=status,
    )
    db.add(obligation)
    db.flush()
    db.add(
        ObligationEvent(
            obligation_id=obligation.id,
            event_type="CREATED",
            new_status=status,
        )
    )
    if status in (ObligationStatus.PAID, ObligationStatus.CANCELLED):
        db.add(
            ObligationEvent(
                obligation_id=obligation.id,
                event_type="STATUS_CHANGED",
                previous_status=ObligationStatus.PENDING,
                new_status=status,
            )
        )
    if frequency != PaymentFrequency.ONE_TIME:
        add_installments(db, obligation)
    return obligation


def add_installments(db, obligation: Obligation) -> None:
    months = {
        PaymentFrequency.MONTHLY: 1,
        PaymentFrequency.QUARTERLY: 3,
        PaymentFrequency.SEMIANNUAL: 6,
        PaymentFrequency.ANNUAL: 12,
    }[obligation.payment_frequency]
    count = rng.randint(2, 4)
    installment = (obligation.amount / count).quantize(Decimal("0.01"))
    for n in range(1, count + 1):
        due = obligation.origin_date + timedelta(days=30 * months * n)
        db.add(
            PaymentSchedule(
                obligation_id=obligation.id,
                installment_number=n,
                due_date=due,
                amount=installment,
                status=InstallmentStatus.PAID
                if obligation.status == ObligationStatus.PAID
                else InstallmentStatus.PENDING,
            )
        )


def create_cycles(db, companies) -> list[Obligation]:
    """Ciclos garantizados sobre obligaciones abiertas."""
    pool = rng.sample(companies, 30)
    idx = 0
    created = []
    for length, count in CYCLES:
        for _ in range(count):
            nodes = pool[idx : idx + length]
            if len(nodes) < length:
                nodes = nodes + pool[: length - len(nodes)]
            idx += length
            for i in range(length):
                debtor, creditor = nodes[i], nodes[(i + 1) % length]
                status = ObligationStatus.OVERDUE if rng.random() < 0.3 else ObligationStatus.PENDING
                created.append(
                    add_obligation(
                        db, debtor, creditor, status=status,
                        amount=Decimal(rng.randint(20000, 80000)).quantize(Decimal("0.01")),
                    )
                )
    return created


def create_chains(db, companies) -> list[Obligation]:
    """Cadenas abiertas garantizadas: A -> B -> C -> (D sin retorno)."""
    pool = rng.sample(companies, 20)
    idx = 0
    created = []
    for length, count in CHAINS:
        for _ in range(count):
            nodes = pool[idx : idx + length]
            idx += length
            for i in range(length - 1):
                created.append(
                    add_obligation(db, nodes[i], nodes[i + 1], status=ObligationStatus.PENDING)
                )
    return created


def create_random_obligations(db, companies) -> None:
    pairs = set()
    attempts = 0
    while len(pairs) < NUM_RANDOM_OBLIGATIONS and attempts < NUM_RANDOM_OBLIGATIONS * 10:
        attempts += 1
        debtor, creditor = rng.sample(companies, 2)
        pair = (debtor.id, creditor.id)
        if pair in pairs:
            continue
        pairs.add(pair)
        add_obligation(db, debtor, creditor)


MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
trailer<</Size 4/Root 1 0 R>>
%%EOF"""


def create_demo_documents(db, obligations) -> None:
    upload_root = Path(get_settings().upload_dir)
    for obligation in rng.sample(list(obligations), NUM_DEMO_DOCUMENTS):
        dest_dir = upload_root / str(obligation.id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stored = f"factura_demo_{uuid.uuid4().hex[:8]}.pdf"
        (dest_dir / stored).write_bytes(MINIMAL_PDF)
        db.add(
            Document(
                obligation_id=obligation.id,
                filename=f"factura-{obligation.id}.pdf",
                file_path=str(dest_dir / stored),
                mime_type="application/pdf",
            )
        )


def create_network(db, companies) -> None:
    network = Network(name="QUADRA Demo")
    db.add(network)
    db.flush()
    for company in companies:
        db.add(NetworkMember(network_id=network.id, company_id=company.id))


def run(fresh: bool) -> None:
    db = SessionLocal()
    try:
        sectors = list(db.scalars(select(Sector)))
        if not sectors:
            raise SystemExit("Sin rubros: ejecuta primero scripts/seed_base.py")

        if db.scalar(select(func.count(Company.id))) and not fresh:
            raise SystemExit("Ya existen empresas. Usa --fresh para regenerar.")
        if fresh:
            wipe(db)

        companies = create_companies(db, sectors)
        db.flush()

        cycle_obligations = create_cycles(db, companies)
        chain_obligations = create_chains(db, companies)
        create_random_obligations(db, companies)
        db.flush()

        all_obligations = list(db.scalars(select(Obligation)))
        create_demo_documents(db, all_obligations)
        create_network(db, companies)

        db.commit()
        print(
            f"Seed demo listo: {len(companies)} empresas, "
            f"{len(all_obligations)} obligaciones, "
            f"{len(cycle_obligations)} aristas de ciclo, "
            f"{len(chain_obligations)} aristas de cadena abierta."
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    run(args.fresh)
