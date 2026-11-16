from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://quadra:quadra@localhost:5432/quadra"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:4200"
    environment: str = "development"
    upload_dir: str = "uploads"
    # Demo: al materializar una propuesta, las demas empresas quedan
    # ACCEPTED automaticamente (solo para datos ficticios).
    demo_auto_accept: bool = True
    # Credenciales del usuario admin creado por scripts.seed_base.
    admin_email: str = "admin@quadra.com"
    admin_password: str = "admin1234"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
