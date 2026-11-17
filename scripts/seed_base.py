"""Datos base minimos: rubros empresariales y un usuario ADMIN de demostracion.

Uso:  python -m scripts.seed_base
El script completo de datos ficticios (empresas, obligaciones, ciclos)
es scripts/seed_demo.py (fase 3).
"""

import os

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.sector import Sector
from app.models.user import User

SECTORS = [
    ("Construccion", "Obras, materiales y servicios de construccion"),
    ("Transporte", "Logistica, flotas y transporte de carga"),
    ("Comercio y distribucion", "Comercializacion y distribucion de productos"),
    ("Automotriz y repuestos", "Venta de vehiculos, repuestos y talleres"),
    ("Alimentos", "Produccion y comercializacion de alimentos"),
    ("Ferreterias y materiales", "Ferreterias, importadoras de filtros, llantas y materiales de construccion"),
    ("Importadoras y exportadoras", "Comercio exterior, importacion y exportacion de bienes"),
    ("Agroindustria", "Produccion agropecuaria, agroprocesamiento y granos"),
    ("Manufactura e industria", "Produccion industrial, fabricacion y ensamble"),
    ("Tecnologia y software", "Desarrollo de software, TI y servicios digitales"),
    ("Fintech y servicios financieros", "Pagos, creditos, seguros y tecnologia financiera"),
    ("Servicios profesionales", "Consultoria, contabilidad, legal y servicios a empresas"),
    ("Salud y farmaceutica", "Clinicas, farmacias, laboratorios y servicios de salud"),
    ("Turismo y gastronomia", "Hoteles, restaurantes, catering y servicios turisticos"),
    ("Energia y mineria", "Energia, gas, mineria y recursos naturales"),
    ("Educacion", "Institutos, universidades y servicios educativos"),
    ("Otro", "Otros sectores no listados"),
]

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@quadra.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")


def run() -> None:
    db = SessionLocal()
    try:
        for name, description in SECTORS:
            if db.scalar(select(Sector).where(Sector.name == name)) is None:
                db.add(Sector(name=name, description=description))

        if db.scalar(select(User).where(User.email == ADMIN_EMAIL)) is None:
            db.add(
                User(
                    email=ADMIN_EMAIL,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    role=UserRole.ADMIN,
                )
            )

        db.commit()
        print("Seed base aplicado: rubros y admin listos.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
