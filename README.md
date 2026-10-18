# QUADRA — Backend

API REST de QUADRA: plataforma de gestion y analisis de obligaciones financieras
entre empresas, con deteccion de ciclos de deuda compensables mediante grafos dirigidos.

## Stack

- FastAPI + Python
- SQLAlchemy (ORM) + Alembic (migraciones)
- PostgreSQL
- NetworkX (analisis de grafos)
- Pytest (pruebas)

## Estructura

```
app/
  api/           # Routers y endpoints
  core/          # Configuracion, seguridad, base de datos
  models/        # Modelos SQLAlchemy
  schemas/       # Esquemas Pydantic
  repositories/  # Acceso a datos
  services/      # Logica de negocio
  graph/         # Motor de grafos (builder, cycles, analysis)
scripts/         # seed_demo.py y utilidades
tests/           # Pruebas Pytest
postman/         # Coleccion QUADRA API
alembic/         # Migraciones
```

## Desarrollo local

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
copy .env.example .env

docker compose up -d db       # PostgreSQL local
uvicorn app.main:app --reload
```

Verificar: http://localhost:8000/health y documentacion en
http://localhost:8000/docs

## Pruebas

```bash
pytest
```
