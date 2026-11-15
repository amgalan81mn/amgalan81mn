"""Админы шалгалт: хүн нүдээр зураг, мэдээллийг тулгаж зөвшөөрнө эсвэл татгалзана."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from .. import ledger
from ..deps import AdminUser, Db
from ..models import AuditLog, Document, DriverProfile, Payout, PayoutStatus, ReviewStatus, User, Vehicle

router = APIRouter(prefix="/admin", tags=["admin"])


class Review(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _reason_required(self) -> "Review":
        if not self.approve and not (self.reason and self.reason.strip()):
            raise ValueError("Татгалзсан шалтгаанаа бичнэ үү")
        return self


def _docs(db: Db, user_id: str, vehicle_id: str | None) -> list[dict]:
    rows = db.scalars(
        select(Document).where(Document.user_id == user_id, Document.vehicle_id == vehicle_id)
    ).all()
    return [{"id": d.id, "kind": d.kind.value} for d in rows]


def _audit(db: Db, admin: User, action: str, target: str, body: Review) -> None:
    detail = "approved" if body.approve else f"rejected: {body.reason}"
    db.add(AuditLog(actor_id=admin.id, action=action, target=target, detail=detail[:300]))


@router.get("/reviews")
def pending_reviews(admin: AdminUser, db: Db) -> dict:
    users = db.scalars(select(User).where(User.identity_status == ReviewStatus.pending)).all()
    drivers = db.scalars(select(DriverProfile).where(DriverProfile.status == ReviewStatus.pending)).all()
    vehicles = db.scalars(select(Vehicle).where(Vehicle.status == ReviewStatus.pending)).all()
    return {
        "identities": [
            {
                "user_id": u.id,
                "phone": u.phone,
                "last_name": u.last_name,
                "first_name": u.first_name,
                "register_no": u.register_no,
                "documents": _docs(db, u.id, None),
            }
            for u in users
        ],
        "drivers": [
            {
                "user_id": d.user_id,
                "license_no": d.license_no,
                "bank_account_holder": d.bank_account_holder,
                "identity_status": d.user.identity_status.value,
                "registered_name": f"{d.user.last_name} {d.user.first_name}",
                "documents": _docs(db, d.user_id, None),
            }
            for d in drivers
        ],
        "vehicles": [
            {
                "vehicle_id": v.id,
                "owner_id": v.owner_id,
                "plate": v.plate,
                "make": v.make,
                "model": v.model,
                "color": v.color,
                "seats": v.seats,
                "documents": _docs(db, v.owner_id, v.id),
            }
            for v in vehicles
        ],
    }


@router.post("/users/{user_id}/identity/review")
def review_identity(user_id: str, body: Review, admin: AdminUser, db: Db) -> dict:
    user = db.get(User, user_id)
    if user is None or user.identity_status != ReviewStatus.pending:
        raise HTTPException(404, "Шалгах хүсэлт олдсонгүй")
    user.identity_status = ReviewStatus.approved if body.approve else ReviewStatus.rejected
    user.identity_reject_reason = None if body.approve else body.reason
    _audit(db, admin, "review_identity", user.id, body)
    db.commit()
    return {"identity_status": user.identity_status.value}


@router.post("/drivers/{user_id}/review")
def review_driver(user_id: str, body: Review, admin: AdminUser, db: Db) -> dict:
    d = db.get(DriverProfile, user_id)
    if d is None or d.status != ReviewStatus.pending:
        raise HTTPException(404, "Шалгах хүсэлт олдсонгүй")
    if body.approve and d.user.identity_status != ReviewStatus.approved:
        raise HTTPException(409, "Эхлээд хувийн бүртгэлийг нь зөвшөөрнө үү")
    d.status = ReviewStatus.approved if body.approve else ReviewStatus.rejected
    d.reject_reason = None if body.approve else body.reason
    d.reviewed_by = admin.id
    d.reviewed_at = datetime.now(timezone.utc)
    _audit(db, admin, "review_driver", user_id, body)
    db.commit()
    return {"status": d.status.value}


@router.post("/vehicles/{vehicle_id}/review")
def review_vehicle(vehicle_id: str, body: Review, admin: AdminUser, db: Db) -> dict:
    v = db.get(Vehicle, vehicle_id)
    if v is None or v.status != ReviewStatus.pending:
        raise HTTPException(404, "Шалгах хүсэлт олдсонгүй")
    v.status = ReviewStatus.approved if body.approve else ReviewStatus.rejected
    v.reject_reason = None if body.approve else body.reason
    v.reviewed_by = admin.id
    v.reviewed_at = datetime.now(timezone.utc)
    _audit(db, admin, "review_vehicle", v.id, body)
    db.commit()
    return {"status": v.status.value}


class Block(BaseModel):
    blocked: bool
    reason: str = Field(min_length=1, max_length=300)


@router.post("/users/{user_id}/block")
def block_user(user_id: str, body: Block, admin: AdminUser, db: Db) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Хэрэглэгч олдсонгүй")
    if user.id == admin.id:
        raise HTTPException(400, "Өөрийгөө хааж болохгүй")
    user.is_blocked = body.blocked
    db.add(
        AuditLog(
            actor_id=admin.id,
            action="block_user" if body.blocked else "unblock_user",
            target=user.id,
            detail=body.reason,
        )
    )
    db.commit()
    return {"is_blocked": user.is_blocked}


@router.get("/payouts")
def pending_payouts(admin: AdminUser, db: Db) -> list[dict]:
    rows = db.scalars(select(Payout).where(Payout.status == PayoutStatus.pending).order_by(Payout.created_at)).all()
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "amount": p.amount,
            "bank_account_no": p.bank_account_no,
            "bank_account_holder": p.bank_account_holder,
        }
        for p in rows
    ]


class PayoutResult(BaseModel):
    paid: bool


@router.post("/payouts/{payout_id}/close")
def close_payout(payout_id: str, body: PayoutResult, admin: AdminUser, db: Db) -> dict:
    """Банкны шилжүүлэг хийгдсэн эсвэл буцсаныг тэмдэглэнэ (буцсан бол мөнгө хэтэвчинд буцна)."""
    try:
        payout = ledger.close_payout(db, payout_id, body.paid)
    except ledger.LedgerError as e:
        raise HTTPException(404, e.message) from e
    db.add(AuditLog(actor_id=admin.id, action="close_payout", target=payout.id, detail=payout.status.value))
    db.commit()
    return {"status": payout.status.value}


@router.get("/ledger/integrity")
def ledger_integrity(admin: AdminUser, db: Db) -> dict:
    """Тулгалт: гурван тоо бүгд 0 байх ёстой."""
    return ledger.check_integrity(db)
