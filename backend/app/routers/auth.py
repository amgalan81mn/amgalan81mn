from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import Conf, Db
from ..models import OtpCode, User
from ..security import create_token, hash_otp, new_otp, normalize_phone

router = APIRouter(prefix="/auth", tags=["auth"])


class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/otp/request")
def request_otp(body: OtpRequest, db: Db, settings: Conf) -> dict:
    phone = _phone(body.phone)
    now = datetime.now(timezone.utc)
    recent = db.scalars(
        select(OtpCode).where(OtpCode.phone == phone, OtpCode.created_at > now - timedelta(seconds=30))
    ).first()
    if recent:
        raise HTTPException(429, "Код дөнгөж илгээгдсэн. 30 секундын дараа дахин оролдоно уу")
    code = new_otp()
    db.add(
        OtpCode(
            phone=phone,
            code_hash=hash_otp(phone, code),
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        )
    )
    db.commit()
    if settings.sms_mode == "dev":
        return {"sent": True, "dev_code": code}
    # TODO(SMS): үйлчилгээ үзүүлэгчтэй гэрээ хийсний дараа энд илгээнэ
    raise HTTPException(503, "SMS үйлчилгээ тохируулагдаагүй байна")


@router.post("/otp/verify")
def verify_otp(body: OtpVerify, db: Db, settings: Conf) -> dict:
    phone = _phone(body.phone)
    now = datetime.now(timezone.utc)
    otp = db.scalars(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.consumed.is_(False), OtpCode.expires_at > now)
        .order_by(OtpCode.created_at.desc())
        .with_for_update()
    ).first()
    if otp is None:
        raise HTTPException(400, "Код хүчингүй эсвэл хугацаа дууссан")
    if otp.attempts >= settings.otp_max_attempts:
        raise HTTPException(429, "Оролдлогын тоо хэтэрлээ. Шинэ код авна уу")
    if otp.code_hash != hash_otp(phone, body.code.strip()):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, "Код буруу байна")
    otp.consumed = True
    user = db.scalars(select(User).where(User.phone == phone)).first()
    if user is None:
        user = User(phone=phone)
        db.add(user)
        db.flush()
    if user.is_blocked:
        db.commit()
        raise HTTPException(403, "Таны бүртгэл хаагдсан байна")
    db.commit()
    return {"token": create_token(user.id), "user_id": user.id}
