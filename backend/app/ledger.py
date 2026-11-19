"""Хэтэвч ба гүйлгээний дэвтэр.

Дүрмүүд:
- Мөнгөний хөдөлгөөн бүр LedgerTx + LedgerEntry болж бичигдэнэ, мөрүүдийн нийлбэр 0.
- Үлдэгдлийг зөвхөн энэ модулиар өөрчилнө.
- Үйлдэл бүр idempotency_key-тэй: давхар ирсэн хүсэлт давхар мөнгө хөдөлгөхгүй.
- Дансуудыг id-ийн дарааллаар түгжинэ (deadlock-оос сэргийлнэ).
- Функцууд commit хийхгүй, дуудсан тал хийнэ.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import pricing
from .config import Settings
from .models import (
    Account,
    AccountKind,
    Hold,
    HoldKind,
    HoldStatus,
    LedgerEntry,
    LedgerTx,
    Payout,
    PayoutStatus,
    TxKind,
)


class LedgerError(Exception):
    def __init__(self, code: str, message: str, **extra: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


SYSTEM_IDS = {AccountKind.platform_revenue: "platform_revenue", AccountKind.clearing: "clearing"}


def _ensure_wallet(db: Session, user_id: str) -> None:
    db.execute(
        insert(Account)
        .values(id=f"wallet:{user_id}", kind=AccountKind.user_wallet, user_id=user_id, balance=0, held=0)
        .on_conflict_do_nothing()
    )


def _ensure_system(db: Session, kind: AccountKind) -> None:
    db.execute(
        insert(Account).values(id=SYSTEM_IDS[kind], kind=kind, balance=0, held=0).on_conflict_do_nothing()
    )


def _lock(db: Session, account_ids: list[str]) -> dict[str, Account]:
    rows = db.scalars(
        select(Account)
        .where(Account.id.in_(account_ids))
        .order_by(Account.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return {a.id: a for a in rows}


def wallet_id(user_id: str) -> str:
    return f"wallet:{user_id}"


def get_wallet(db: Session, user_id: str) -> Account:
    _ensure_wallet(db, user_id)
    return db.scalars(select(Account).where(Account.id == wallet_id(user_id))).one()


def _post(
    db: Session, kind: TxKind, key: str, reference: str | None, moves: dict[Account, int]
) -> LedgerTx:
    if sum(moves.values()) != 0:
        raise AssertionError("ledger entries must sum to zero")
    tx = LedgerTx(kind=kind, idempotency_key=key, reference=reference)
    db.add(tx)
    db.flush()
    for account, amount in moves.items():
        if amount == 0:
            continue
        account.balance += amount
        db.add(LedgerEntry(tx_id=tx.id, account_id=account.id, amount=amount))
    db.flush()
    return tx


def _existing_tx(db: Session, key: str) -> LedgerTx | None:
    return db.scalars(select(LedgerTx).where(LedgerTx.idempotency_key == key)).first()


def _moved_since(db: Session, account_id: str, kind: TxKind, since: datetime) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(func.abs(LedgerEntry.amount)), 0))
        .join(LedgerTx, LedgerTx.id == LedgerEntry.tx_id)
        .where(LedgerEntry.account_id == account_id, LedgerTx.kind == kind, LedgerTx.created_at >= since)
    )
    return int(total or 0)


def _day_ago() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=1)


def topup(
    db: Session, user_id: str, amount: int, key: str, settings: Settings, reference: str | None = None
) -> LedgerTx:
    """Цэнэглэлт. Төлбөрийн систем төлбөр орсныг баталсны дараа л дуудна."""
    if amount <= 0:
        raise LedgerError("invalid_amount", "Дүн эерэг байх ёстой")
    key = f"topup:{key}"
    _ensure_wallet(db, user_id)
    _ensure_system(db, AccountKind.clearing)
    acc = _lock(db, [wallet_id(user_id), SYSTEM_IDS[AccountKind.clearing]])
    if tx := _existing_tx(db, key):
        return tx
    wallet = acc[wallet_id(user_id)]
    used = _moved_since(db, wallet.id, TxKind.topup, _day_ago())
    if used + amount > settings.max_topup_per_day:
        raise LedgerError("topup_limit", "Өдрийн цэнэглэх хязгаар хэтэрлээ", limit=settings.max_topup_per_day)
    return _post(db, TxKind.topup, key, reference, {wallet: amount, acc["clearing"]: -amount})


def place_hold(
    db: Session,
    user_id: str,
    amount: int,
    key: str,
    kind: HoldKind = HoldKind.trip,
    reference: str | None = None,
) -> Hold:
    """Хэтэвчинд дүн түгжинэ. Хүрэлцэхгүй бол дутуу дүнг `shortfall`-д буцаана."""
    if amount <= 0:
        raise LedgerError("invalid_amount", "Дүн эерэг байх ёстой")
    _ensure_wallet(db, user_id)
    wallet = _lock(db, [wallet_id(user_id)])[wallet_id(user_id)]
    existing = db.scalars(select(Hold).where(Hold.idempotency_key == key)).first()
    if existing:
        return existing
    available = wallet.balance - wallet.held
    if available < amount:
        raise LedgerError(
            "insufficient_funds", "Хэтэвчний үлдэгдэл хүрэлцэхгүй байна", shortfall=amount - available
        )
    wallet.held += amount
    hold = Hold(account_id=wallet.id, kind=kind, amount=amount, idempotency_key=key, reference=reference)
    db.add(hold)
    db.flush()
    return hold


def _lock_hold(db: Session, hold_id: str) -> Hold:
    hold = db.scalars(
        select(Hold).where(Hold.id == hold_id).with_for_update().execution_options(populate_existing=True)
    ).first()
    if hold is None:
        raise LedgerError("hold_not_found", "Түгжсэн дүн олдсонгүй")
    return hold


def release_hold(db: Session, hold_id: str) -> Hold:
    """Түгжээг бүтнээр чөлөөлнө (цуцлалт). Давтан дуудахад аюулгүй."""
    hold = _lock_hold(db, hold_id)
    if hold.status == HoldStatus.released:
        return hold
    if hold.status == HoldStatus.settled:
        raise LedgerError("hold_closed", "Энэ түгжээнээс аль хэдийн төлбөр хийгдсэн")
    wallet = _lock(db, [hold.account_id])[hold.account_id]
    wallet.held -= hold.amount
    hold.status = HoldStatus.released
    hold.closed_at = datetime.now(timezone.utc)
    db.flush()
    return hold


def settle_hold(
    db: Session, hold_id: str, fare: int, driver_user_id: str, settings: Settings
) -> tuple[Hold, int]:
    """Аялал дуусахад: `fare`-г зорчигчоос авч, шимтгэлээ суутгаад жолоочид өгнө, үлдсэн түгжээг чөлөөлнө.

    Буцаах утга: (hold, шимтгэл). Давтан дуудахад эхний үр дүнг буцаана.
    """
    hold = _lock_hold(db, hold_id)
    key = f"settle:{hold.id}"
    if hold.status == HoldStatus.settled:
        tx = _existing_tx(db, key)
        fee = 0
        if tx:
            fee = sum(e.amount for e in tx.entries if e.account_id == SYSTEM_IDS[AccountKind.platform_revenue])
        return hold, fee
    if hold.status == HoldStatus.released:
        raise LedgerError("hold_closed", "Энэ түгжээ аль хэдийн чөлөөлөгдсөн")
    if fare < 0 or fare > hold.amount:
        raise LedgerError("invalid_amount", "Төлбөр түгжсэн дүнгээс хэтэрч болохгүй")
    driver_wallet_id = wallet_id(driver_user_id)
    if driver_wallet_id == hold.account_id:
        raise LedgerError("self_dealing", "Жолооч, зорчигч нэг хүн байж болохгүй")

    _ensure_wallet(db, driver_user_id)
    _ensure_system(db, AccountKind.platform_revenue)
    acc = _lock(db, [hold.account_id, driver_wallet_id, SYSTEM_IDS[AccountKind.platform_revenue]])
    passenger = acc[hold.account_id]
    fee = pricing.commission(fare, settings)

    passenger.held -= hold.amount
    if fare > 0:
        _post(
            db,
            TxKind.trip_settlement,
            key,
            hold.reference,
            {passenger: -fare, acc[driver_wallet_id]: fare - fee, acc["platform_revenue"]: fee},
        )
    hold.status = HoldStatus.settled
    hold.closed_at = datetime.now(timezone.utc)
    db.flush()
    return hold, fee


def capture_from_hold(
    db: Session, hold_id: str, fare: int, driver_user_id: str, key: str, settings: Settings
) -> tuple[Hold, int]:
    """Аяны нэг хэсэг: түгжээг хаалгүйгээр `fare`-г авч жолоочид шилжүүлнэ. Үлдсэн нь дараагийн хэсэгт түгжээтэй үлдэнэ.

    Буцаах утга: (hold, шимтгэл). Ижил `key`-ээр давтан дуудахад эхний үр дүнг буцаана.
    """
    hold = _lock_hold(db, hold_id)
    key = f"capture:{key}"
    if tx := _existing_tx(db, key):
        fee = sum(e.amount for e in tx.entries if e.account_id == SYSTEM_IDS[AccountKind.platform_revenue])
        return hold, fee
    if hold.status != HoldStatus.active:
        raise LedgerError("hold_closed", "Түгжээ хаагдсан байна")
    if fare < 0 or fare > hold.amount:
        raise LedgerError("invalid_amount", "Төлбөр түгжсэн дүнгээс хэтэрч болохгүй")
    driver_wallet_id = wallet_id(driver_user_id)
    if driver_wallet_id == hold.account_id:
        raise LedgerError("self_dealing", "Жолооч, зорчигч нэг хүн байж болохгүй")
    if fare == 0:
        return hold, 0
    _ensure_wallet(db, driver_user_id)
    _ensure_system(db, AccountKind.platform_revenue)
    acc = _lock(db, [hold.account_id, driver_wallet_id, SYSTEM_IDS[AccountKind.platform_revenue]])
    passenger = acc[hold.account_id]
    fee = pricing.commission(fare, settings)
    passenger.held -= fare
    hold.amount -= fare
    _post(
        db,
        TxKind.trip_settlement,
        key,
        hold.reference,
        {passenger: -fare, acc[driver_wallet_id]: fare - fee, acc["platform_revenue"]: fee},
    )
    if hold.amount == 0:
        hold.status = HoldStatus.settled
        hold.closed_at = datetime.now(timezone.utc)
    db.flush()
    return hold, fee


def request_payout(
    db: Session,
    user_id: str,
    amount: int,
    key: str,
    bank_account_no: str,
    bank_account_holder: str,
    settings: Settings,
) -> Payout:
    """Жолооч хэтэвчнээсээ банк руу татна. Мөнгө шууд хасагдаж, шилжүүлэг хүлээгдэнэ."""
    if amount <= 0:
        raise LedgerError("invalid_amount", "Дүн эерэг байх ёстой")
    key = f"payout:{key}"
    _ensure_wallet(db, user_id)
    _ensure_system(db, AccountKind.clearing)
    acc = _lock(db, [wallet_id(user_id), SYSTEM_IDS[AccountKind.clearing]])
    if tx := _existing_tx(db, key):
        return db.get(Payout, tx.reference)
    wallet = acc[wallet_id(user_id)]
    available = wallet.balance - wallet.held
    if available < amount:
        raise LedgerError("insufficient_funds", "Татах дүн үлдэгдлээс их байна", shortfall=amount - available)
    used = _moved_since(db, wallet.id, TxKind.payout, _day_ago())
    if used + amount > settings.max_payout_per_day:
        raise LedgerError("payout_limit", "Өдрийн татах хязгаар хэтэрлээ", limit=settings.max_payout_per_day)
    payout = Payout(
        user_id=user_id, amount=amount, bank_account_no=bank_account_no, bank_account_holder=bank_account_holder
    )
    db.add(payout)
    db.flush()
    _post(db, TxKind.payout, key, payout.id, {wallet: -amount, acc["clearing"]: amount})
    return payout


def close_payout(db: Session, payout_id: str, paid: bool) -> Payout:
    """Банкны шилжүүлгийн үр дүн. Амжилтгүй бол мөнгийг хэтэвчинд буцаана."""
    payout = db.scalars(
        select(Payout).where(Payout.id == payout_id).with_for_update().execution_options(populate_existing=True)
    ).first()
    if payout is None:
        raise LedgerError("payout_not_found", "Таталт олдсонгүй")
    if payout.status != PayoutStatus.pending:
        return payout
    if not paid:
        acc = _lock(db, [wallet_id(payout.user_id), SYSTEM_IDS[AccountKind.clearing]])
        _post(
            db,
            TxKind.payout_reversal,
            f"payout_reversal:{payout.id}",
            payout.id,
            {acc[wallet_id(payout.user_id)]: payout.amount, acc["clearing"]: -payout.amount},
        )
    payout.status = PayoutStatus.paid if paid else PayoutStatus.failed
    payout.closed_at = datetime.now(timezone.utc)
    db.flush()
    return payout


def check_integrity(db: Session) -> dict[str, int]:
    """Өдөр тутмын тулгалт: бүх дансны нийлбэр 0, данс бүрийн үлдэгдэл дэвтэртэйгээ таарах ёстой."""
    total = int(db.scalar(select(func.coalesce(func.sum(Account.balance), 0))) or 0)
    mismatched = db.execute(
        select(func.count())
        .select_from(Account)
        .where(
            Account.balance
            != select(func.coalesce(func.sum(LedgerEntry.amount), 0))
            .where(LedgerEntry.account_id == Account.id)
            .scalar_subquery()
        )
    ).scalar_one()
    active_holds = (
        select(func.coalesce(func.sum(Hold.amount), 0))
        .where(Hold.account_id == Account.id, Hold.status == HoldStatus.active)
        .scalar_subquery()
    )
    bad_holds = db.execute(select(func.count()).select_from(Account).where(Account.held != active_holds)).scalar_one()
    return {"sum_of_balances": total, "accounts_off_ledger": mismatched, "accounts_off_holds": bad_holds}
