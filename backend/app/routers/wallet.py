from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from typing import Annotated

from .. import ledger, pricing
from ..deps import Conf, CurrentUser, Db, can_drive
from ..models import LedgerEntry, LedgerTx

router = APIRouter(tags=["wallet"])

_STATUS = {"insufficient_funds": 402, "topup_limit": 429, "payout_limit": 429}


def _http(e: ledger.LedgerError) -> HTTPException:
    return HTTPException(_STATUS.get(e.code, 400), {"code": e.code, "message": e.message, **e.extra})


@router.get("/wallet")
def wallet(user: CurrentUser, db: Db) -> dict:
    w = ledger.get_wallet(db, user.id)
    db.commit()
    return {"balance": w.balance, "held": w.held, "available": w.balance - w.held}


@router.get("/wallet/transactions")
def transactions(user: CurrentUser, db: Db, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = db.execute(
        select(LedgerEntry.amount, LedgerTx.kind, LedgerTx.reference, LedgerTx.created_at)
        .join(LedgerTx, LedgerTx.id == LedgerEntry.tx_id)
        .where(LedgerEntry.account_id == ledger.wallet_id(user.id))
        .order_by(LedgerEntry.id.desc())
        .limit(limit)
    ).all()
    return [
        {"amount": r.amount, "kind": r.kind.value, "reference": r.reference, "at": r.created_at.isoformat()}
        for r in rows
    ]


class Amount(BaseModel):
    amount: int = Field(gt=0)


@router.post("/wallet/topup/dev")
def dev_topup(
    body: Amount, user: CurrentUser, db: Db, settings: Conf, idempotency_key: Annotated[str, Header(min_length=8)]
) -> dict:
    """ЗӨВХӨН ТУРШИЛТ. Жинхэнэ орчинд цэнэглэлт төлбөрийн системийн баталгаажсан мэдэгдлээр л орно."""
    if settings.payments_mode != "dev":
        raise HTTPException(404, "Not found")
    try:
        ledger.topup(db, user.id, body.amount, f"dev:{user.id}:{idempotency_key}", settings, reference="dev")
    except ledger.LedgerError as e:
        db.rollback()
        raise _http(e) from e
    db.commit()
    return wallet(user, db)


@router.post("/wallet/payouts", status_code=201)
def request_payout(
    body: Amount, user: CurrentUser, db: Db, settings: Conf, idempotency_key: Annotated[str, Header(min_length=8)]
) -> dict:
    if not can_drive(db, user):
        raise HTTPException(403, "Зөвхөн баталгаажсан жолооч мөнгө татна")
    d = user.driver
    try:
        payout = ledger.request_payout(
            db,
            user.id,
            body.amount,
            f"{user.id}:{idempotency_key}",
            d.bank_account_no,
            d.bank_account_holder,
            settings,
        )
    except ledger.LedgerError as e:
        db.rollback()
        raise _http(e) from e
    db.commit()
    return {"id": payout.id, "amount": payout.amount, "status": payout.status.value}


@router.get("/pricing/quote")
def quote(
    settings: Conf,
    distance_m: int = Query(gt=0, le=2_000_000),
    occupancy: int = Query(1, ge=1, le=8),
) -> dict:
    """Үндсэн тарифын лавлах үнэ ба лааны голын хүрээ (нэг суудлаар)."""
    low, high = pricing.price_band(distance_m, occupancy, settings)
    base = pricing.base_seat_price(distance_m, occupancy, settings)
    return {
        "base_seat_price": base,
        "band_low": low,
        "band_high": high,
        "commission_on_base": pricing.commission(base, settings),
    }
