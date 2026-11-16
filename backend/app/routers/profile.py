"""Хэрэглэгч, жолооч, машины бүртгэл. Мэдээллээ бүрдүүлээд «илгээх» дарахад админы шалгалтад орно."""

from fastapi import APIRouter, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..deps import Conf, CurrentUser, Db, can_drive
from ..models import (
    DRIVER_DOCUMENTS,
    PUBLIC_DOCUMENTS,
    USER_DOCUMENTS,
    VEHICLE_DOCUMENTS,
    AuditLog,
    Document,
    DocumentKind,
    DriverProfile,
    ReviewStatus,
    User,
    Vehicle,
)
from ..security import normalize_plate, normalize_register_no
from ..storage import read_document, save_document

router = APIRouter(tags=["profile"])

_LOCKED = {ReviewStatus.pending, ReviewStatus.approved}
_LOCKED_MSG = "Шалгагдаж байгаа эсвэл зөвшөөрөгдсөн мэдээллийг өөрчлөх боломжгүй"


def _kinds(db: Db, user_id: str, vehicle_id: str | None = None) -> set[DocumentKind]:
    q = select(Document.kind).where(Document.user_id == user_id, Document.vehicle_id == vehicle_id)
    return set(db.scalars(q).all())


def _vehicle_out(v: Vehicle, kinds: set[DocumentKind]) -> dict:
    return {
        "id": v.id,
        "plate": v.plate,
        "make": v.make,
        "model": v.model,
        "color": v.color,
        "seats": v.seats,
        "status": v.status.value,
        "reject_reason": v.reject_reason,
        "missing_documents": sorted(k.value for k in VEHICLE_DOCUMENTS - kinds),
    }


@router.get("/me")
def me(user: CurrentUser, db: Db) -> dict:
    kinds = _kinds(db, user.id)
    d = user.driver
    return {
        "id": user.id,
        "phone": user.phone,
        "last_name": user.last_name,
        "first_name": user.first_name,
        "register_no": user.register_no,
        "identity_status": user.identity_status.value,
        "identity_reject_reason": user.identity_reject_reason,
        "missing_identity_documents": sorted(k.value for k in USER_DOCUMENTS - kinds),
        "driver": None
        if d is None
        else {
            "license_no": d.license_no,
            "bank_name": d.bank_name,
            "bank_account_no": d.bank_account_no,
            "bank_account_holder": d.bank_account_holder,
            "status": d.status.value,
            "reject_reason": d.reject_reason,
            "missing_documents": sorted(k.value for k in DRIVER_DOCUMENTS - kinds),
        },
        # Апп энэ утгаар «Жолооч» горимын товчийг идэвхжүүлнэ
        "can_drive": can_drive(db, user),
        "is_admin": user.is_admin,
    }


class IdentityIn(BaseModel):
    last_name: str = Field(min_length=1, max_length=80)
    first_name: str = Field(min_length=1, max_length=80)
    register_no: str


@router.put("/me/identity")
def set_identity(body: IdentityIn, user: CurrentUser, db: Db) -> dict:
    if user.identity_status in _LOCKED:
        raise HTTPException(409, _LOCKED_MSG)
    try:
        user.register_no = normalize_register_no(body.register_no)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    user.last_name = body.last_name.strip()
    user.first_name = body.first_name.strip()
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "Энэ регистрийн дугаар өөр бүртгэлд ашиглагдсан байна") from e
    return {"ok": True}


@router.post("/me/documents/{kind}")
def upload_my_document(kind: DocumentKind, file: UploadFile, user: CurrentUser, db: Db, settings: Conf) -> dict:
    if kind in USER_DOCUMENTS:
        if user.identity_status in _LOCKED:
            raise HTTPException(409, _LOCKED_MSG)
    elif kind in DRIVER_DOCUMENTS:
        if user.driver is not None and user.driver.status in _LOCKED:
            raise HTTPException(409, _LOCKED_MSG)
    else:
        raise HTTPException(400, "Машины зургийг машины хэсгээр оруулна уу")
    doc = save_document(db, settings, user_id=user.id, kind=kind, upload=file)
    db.commit()
    return {"id": doc.id, "kind": doc.kind.value}


@router.post("/me/identity/submit")
def submit_identity(user: CurrentUser, db: Db) -> dict:
    if user.identity_status in _LOCKED:
        raise HTTPException(409, _LOCKED_MSG)
    if not (user.last_name and user.first_name and user.register_no):
        raise HTTPException(400, "Овог, нэр, регистрийн дугаараа оруулна уу")
    missing = USER_DOCUMENTS - _kinds(db, user.id)
    if missing:
        raise HTTPException(400, {"message": "Зураг дутуу байна", "missing": sorted(k.value for k in missing)})
    user.identity_status = ReviewStatus.pending
    user.identity_reject_reason = None
    db.commit()
    return {"identity_status": user.identity_status.value}


class DriverIn(BaseModel):
    license_no: str = Field(min_length=3, max_length=32)
    bank_name: str = Field(min_length=2, max_length=60)
    bank_account_no: str = Field(min_length=6, max_length=34, pattern=r"^[0-9A-Za-z]+$")
    bank_account_holder: str = Field(min_length=2, max_length=160)


@router.put("/me/driver")
def set_driver(body: DriverIn, user: CurrentUser, db: Db) -> dict:
    d = user.driver
    if d is not None and d.status in _LOCKED:
        raise HTTPException(409, _LOCKED_MSG)
    if d is None:
        d = DriverProfile(user_id=user.id, license_no=body.license_no)
        db.add(d)
    d.license_no = body.license_no.strip()
    d.bank_name = body.bank_name.strip()
    d.bank_account_no = body.bank_account_no
    d.bank_account_holder = body.bank_account_holder.strip()
    db.commit()
    return {"ok": True}


@router.post("/me/driver/submit")
def submit_driver(user: CurrentUser, db: Db) -> dict:
    d = user.driver
    if d is None:
        raise HTTPException(400, "Жолоочийн мэдээллээ оруулна уу")
    if d.status in _LOCKED:
        raise HTTPException(409, _LOCKED_MSG)
    if user.identity_status not in _LOCKED:
        raise HTTPException(400, "Эхлээд хувийн бүртгэлээ илгээнэ үү")
    missing = DRIVER_DOCUMENTS - _kinds(db, user.id)
    if missing:
        raise HTTPException(400, {"message": "Зураг дутуу байна", "missing": sorted(k.value for k in missing)})
    has_vehicle = db.scalars(
        select(Vehicle).where(Vehicle.owner_id == user.id, Vehicle.status.in_(_LOCKED))
    ).first()
    if not has_vehicle:
        raise HTTPException(400, "Эхлээд машинаа бүртгүүлж илгээнэ үү")
    d.status = ReviewStatus.pending
    d.reject_reason = None
    db.commit()
    return {"status": d.status.value}


class VehicleIn(BaseModel):
    plate: str
    make: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=40)
    color: str = Field(min_length=1, max_length=30)
    seats: int = Field(ge=1, le=8)


def _own_vehicle(db: Db, user: User, vehicle_id: str) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if v is None or v.owner_id != user.id:
        raise HTTPException(404, "Машин олдсонгүй")
    return v


@router.post("/me/vehicles", status_code=201)
def add_vehicle(body: VehicleIn, user: CurrentUser, db: Db) -> dict:
    try:
        plate = normalize_plate(body.plate)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    v = Vehicle(
        owner_id=user.id,
        plate=plate,
        make=body.make.strip(),
        model=body.model.strip(),
        color=body.color.strip(),
        seats=body.seats,
    )
    db.add(v)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "Энэ улсын дугаартай машин аль хэдийн бүртгэгдсэн байна") from e
    return _vehicle_out(v, set())


@router.get("/me/vehicles")
def my_vehicles(user: CurrentUser, db: Db) -> list[dict]:
    vehicles = db.scalars(select(Vehicle).where(Vehicle.owner_id == user.id).order_by(Vehicle.created_at)).all()
    return [_vehicle_out(v, _kinds(db, user.id, v.id)) for v in vehicles]


@router.post("/me/vehicles/{vehicle_id}/documents/{kind}")
def upload_vehicle_document(
    vehicle_id: str, kind: DocumentKind, file: UploadFile, user: CurrentUser, db: Db, settings: Conf
) -> dict:
    v = _own_vehicle(db, user, vehicle_id)
    if kind not in VEHICLE_DOCUMENTS:
        raise HTTPException(400, "Энэ төрлийн зураг машинд хамаарахгүй")
    if v.status in _LOCKED:
        raise HTTPException(409, _LOCKED_MSG)
    doc = save_document(db, settings, user_id=user.id, kind=kind, upload=file, vehicle_id=v.id)
    db.commit()
    return {"id": doc.id, "kind": doc.kind.value}


@router.post("/me/vehicles/{vehicle_id}/submit")
def submit_vehicle(vehicle_id: str, user: CurrentUser, db: Db) -> dict:
    v = _own_vehicle(db, user, vehicle_id)
    if v.status in _LOCKED:
        raise HTTPException(409, _LOCKED_MSG)
    missing = VEHICLE_DOCUMENTS - _kinds(db, user.id, v.id)
    if missing:
        raise HTTPException(400, {"message": "Зураг дутуу байна", "missing": sorted(k.value for k in missing)})
    v.status = ReviewStatus.pending
    v.reject_reason = None
    db.commit()
    return _vehicle_out(v, VEHICLE_DOCUMENTS)


@router.get("/documents/{document_id}")
def get_document(document_id: str, user: CurrentUser, db: Db, settings: Conf) -> Response:
    """Зургийг зөвхөн эзэн нь эсвэл админ үзнэ. Админы үзсэн бүрийг бүртгэнэ."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Зураг олдсонгүй")
    allowed = doc.user_id == user.id or user.is_admin
    # Аялалд хамт буй хүн нүүр зураг, машины зургийг харна (бие биеэ таних)
    if not allowed and doc.kind in PUBLIC_DOCUMENTS:
        from .rides import shares_trip

        allowed = shares_trip(db, user.id, doc.user_id)
    if not allowed:
        raise HTTPException(404, "Зураг олдсонгүй")
    if doc.user_id != user.id and user.is_admin:
        db.add(AuditLog(actor_id=user.id, action="view_document", target=doc.id, detail=doc.kind.value))
        db.commit()
    return Response(read_document(settings, doc), media_type=doc.content_type)
