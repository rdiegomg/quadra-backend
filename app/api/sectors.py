from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.sector import Sector

router = APIRouter(prefix="/sectors", tags=["sectors"])


class SectorResponse(BaseModel):
    id: int
    name: str
    description: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[SectorResponse])
def list_sectors(db: Session = Depends(get_db)) -> list[Sector]:
    return list(db.scalars(select(Sector).order_by(Sector.name)))
