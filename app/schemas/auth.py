from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class RegisterRequest(BaseModel):
    """Registro de una empresa nueva junto con su usuario COMPANY."""

    company_name: str = Field(min_length=2, max_length=150)
    nit: str = Field(min_length=4, max_length=30)
    legal_type: str = Field(min_length=2, max_length=20)
    sector_id: int
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    role: UserRole
    company_id: int | None
    company_name: str | None

    model_config = {"from_attributes": True}
