from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import ReviewStatus, User, Vehicle
from .security import decode_token

Db = Annotated[Session, Depends(get_db)]
Conf = Annotated[Settings, Depends(get_settings)]


def current_user(db: Db, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Нэвтрээгүй байна")
    user_id = decode_token(authorization[7:])
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Нэвтрэлт хүчингүй")
    if user.is_blocked:
        raise HTTPException(403, "Таны бүртгэл хаагдсан байна")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Зөвхөн админ")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def can_drive(db: Session, user: User) -> bool:
    """Жолоочийн горим: хувийн бүртгэл, жолоочийн бүртгэл, дор хаяж нэг машин зөвшөөрөгдсөн байх."""
    if user.is_blocked or user.identity_status != ReviewStatus.approved:
        return False
    if user.driver is None or user.driver.status != ReviewStatus.approved:
        return False
    return (
        db.query(Vehicle).filter(Vehicle.owner_id == user.id, Vehicle.status == ReviewStatus.approved).first()
        is not None
    )
