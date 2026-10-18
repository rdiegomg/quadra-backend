from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.company import Company
from app.models.enums import UserRole
from app.models.sector import Sector
from app.models.user import User
from app.schemas.auth import RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    if db.scalar(select(Sector).where(Sector.id == payload.sector_id)) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "sector_id no existe")
    if db.scalar(select(Company).where(Company.nit == payload.nit)):
        raise HTTPException(status.HTTP_409_CONFLICT, "El NIT ya esta registrado")
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "El email ya esta registrado")

    company = Company(
        name=payload.company_name,
        nit=payload.nit,
        legal_type=payload.legal_type.upper(),
        sector_id=payload.sector_id,
    )
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.COMPANY,
        company=company,
    )
    db.add_all([company, user])
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == form.username))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Email o contrasena incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value)
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
