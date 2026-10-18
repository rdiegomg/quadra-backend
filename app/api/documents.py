import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.obligations import get_obligation_for_user
from app.core.config import get_settings
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse

router = APIRouter(tags=["documents"])
settings = get_settings()

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _safe_filename(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    return f"{uuid.uuid4().hex}_{stem}"


def _get_document_for_user(db: Session, doc_id: int, user: User) -> Document:
    document = db.get(Document, doc_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
    # reutiliza la verificacion de acceso sobre la obligacion asociada
    get_obligation_for_user(db, document.obligation_id, user)
    return document


@router.post(
    "/obligations/{obligation_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    obligation_id: int,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    obligation = get_obligation_for_user(db, obligation_id, current_user)

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Solo se permiten PDF o imagenes (png, jpeg, webp)",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Maximo 10 MB")

    dest_dir = Path(settings.upload_dir) / str(obligation.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = _safe_filename(file.filename or "documento")
    (dest_dir / stored_name).write_bytes(content)

    document = Document(
        obligation_id=obligation.id,
        filename=file.filename or stored_name,
        file_path=str(dest_dir / stored_name),
        mime_type=file.content_type,
        uploaded_by=current_user.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.get(
    "/obligations/{obligation_id}/documents",
    response_model=list[DocumentResponse],
)
def list_documents(
    obligation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Document]:
    get_obligation_for_user(db, obligation_id, current_user)
    return list(
        db.scalars(
            select(Document)
            .where(Document.obligation_id == obligation_id)
            .order_by(Document.created_at)
        )
    )


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    document = _get_document_for_user(db, document_id, current_user)
    path = Path(document.file_path)
    if not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Archivo no disponible en el servidor"
        )
    return FileResponse(path, media_type=document.mime_type, filename=document.filename)
