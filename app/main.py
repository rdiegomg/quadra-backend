from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="QUADRA API",
    description="API para gestion y analisis de obligaciones financieras entre empresas.",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "version": __version__, "environment": settings.environment}
