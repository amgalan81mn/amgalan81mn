"""Зураг хадгалах. Одоогоор серверийн хавтас; дараа үүлэн сан руу солиход зөвхөн энэ файл өөрчлөгдөнө."""

import hashlib
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Document, DocumentKind, new_id
from .security import decrypt_bytes, encrypt_bytes

# Файлын эхний байтуудаар төрлийг шалгана (хэрэглэгчийн хэлсэн төрөлд итгэхгүй)
_SIGNATURES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}


def _sniff(data: bytes) -> str:
    for magic, mime in _SIGNATURES.items():
        if data.startswith(magic):
            return mime
    raise HTTPException(415, "Зөвхөн JPEG эсвэл PNG зураг оруулна уу")


def save_document(
    db: Session,
    settings: Settings,
    *,
    user_id: str,
    kind: DocumentKind,
    upload: UploadFile,
    vehicle_id: str | None = None,
) -> Document:
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Зураг хэт том байна")
    if not data:
        raise HTTPException(400, "Хоосон файл")
    mime = _sniff(data)

    doc_id = new_id()
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{doc_id}.bin").write_bytes(encrypt_bytes(data))

    # Нэг төрлийн хуучин зургийг шинээр солино
    old = db.scalars(
        select(Document).where(
            Document.user_id == user_id, Document.kind == kind, Document.vehicle_id == vehicle_id
        )
    ).all()
    for doc in old:
        (root / doc.path).unlink(missing_ok=True)
        db.delete(doc)

    doc = Document(
        id=doc_id,
        user_id=user_id,
        vehicle_id=vehicle_id,
        kind=kind,
        path=f"{doc_id}.bin",
        content_type=mime,
        sha256=hashlib.sha256(data).hexdigest(),
    )
    db.add(doc)
    db.flush()
    return doc


def read_document(settings: Settings, doc: Document) -> bytes:
    return decrypt_bytes((Path(settings.upload_dir) / doc.path).read_bytes())
