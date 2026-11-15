import threading

import pytest

from app import ledger
from app.db import SessionLocal
from app.models import HoldStatus, PayoutStatus

CLEAN = {"sum_of_balances": 0, "accounts_off_ledger": 0, "accounts_off_holds": 0}


def _balances(db, user):
    db.expire_all()
    w = ledger.get_wallet(db, user.id)
    return w.balance, w.held


def test_topup_is_idempotent(db, make_user, settings):
    u = make_user()
    for _ in range(3):  # төлбөрийн мэдэгдэл давхар ирсэн
        ledger.topup(db, u.id, 10_000, "invoice-1", settings)
        db.commit()
    assert _balances(db, u) == (10_000, 0)
    assert ledger.check_integrity(db) == CLEAN


def test_topup_daily_limit(db, make_user, settings):
    u = make_user()
    ledger.topup(db, u.id, settings.max_topup_per_day, "a", settings)
    db.commit()
    with pytest.raises(ledger.LedgerError) as e:
        ledger.topup(db, u.id, 1, "b", settings)
    assert e.value.code == "topup_limit"


def test_hold_reports_shortfall(db, make_user, settings):
    u = make_user()
    ledger.topup(db, u.id, 3_000, "a", settings)
    with pytest.raises(ledger.LedgerError) as e:
        ledger.place_hold(db, u.id, 5_000, "trip-1")
    assert e.value.code == "insufficient_funds" and e.value.extra == {"shortfall": 2_000}


def test_held_money_cannot_be_held_twice(db, make_user, settings):
    u = make_user()
    ledger.topup(db, u.id, 5_000, "a", settings)
    ledger.place_hold(db, u.id, 4_000, "trip-1")
    assert ledger.place_hold(db, u.id, 4_000, "trip-1").amount == 4_000  # ижил түлхүүр: шинээр түгжихгүй
    with pytest.raises(ledger.LedgerError):
        ledger.place_hold(db, u.id, 4_000, "trip-2")
    db.commit()
    assert _balances(db, u) == (5_000, 4_000)


def test_settlement_splits_fare_and_refunds_the_rest(db, make_user, settings):
    passenger, driver = make_user(), make_user()
    ledger.topup(db, passenger.id, 10_000, "a", settings)
    hold = ledger.place_hold(db, passenger.id, 6_000, "trip-1", reference="trip-1")
    # 6,000₮ түгжээд дутуу хүрсэн тул 2,400₮ л төлнө; шимтгэл 10% = 240₮
    _, fee = ledger.settle_hold(db, hold.id, 2_400, driver.id, settings)
    db.commit()
    assert fee == 240
    assert _balances(db, passenger) == (7_600, 0)
    assert _balances(db, driver) == (2_160, 0)
    assert ledger.check_integrity(db) == CLEAN


def test_settlement_is_idempotent(db, make_user, settings):
    passenger, driver = make_user(), make_user()
    ledger.topup(db, passenger.id, 10_000, "a", settings)
    hold = ledger.place_hold(db, passenger.id, 6_000, "trip-1")
    first = ledger.settle_hold(db, hold.id, 6_000, driver.id, settings)[1]
    again = ledger.settle_hold(db, hold.id, 6_000, driver.id, settings)[1]
    db.commit()
    assert first == again == 570  # 500 + 1,000-ийн 7%
    assert _balances(db, driver) == (5_430, 0)
    assert _balances(db, passenger) == (4_000, 0)


def test_cannot_settle_more_than_held_or_to_self(db, make_user, settings):
    passenger, driver = make_user(), make_user()
    ledger.topup(db, passenger.id, 10_000, "a", settings)
    hold = ledger.place_hold(db, passenger.id, 6_000, "trip-1")
    with pytest.raises(ledger.LedgerError):
        ledger.settle_hold(db, hold.id, 6_001, driver.id, settings)
    with pytest.raises(ledger.LedgerError) as e:
        ledger.settle_hold(db, hold.id, 6_000, passenger.id, settings)
    assert e.value.code == "self_dealing"


def test_release_returns_everything(db, make_user, settings):
    u, driver = make_user(), make_user()
    ledger.topup(db, u.id, 5_000, "a", settings)
    hold = ledger.place_hold(db, u.id, 5_000, "trip-1")
    ledger.release_hold(db, hold.id)
    assert ledger.release_hold(db, hold.id).status == HoldStatus.released
    with pytest.raises(ledger.LedgerError):
        ledger.settle_hold(db, hold.id, 1_000, driver.id, settings)
    db.commit()
    assert _balances(db, u) == (5_000, 0)
    assert ledger.check_integrity(db) == CLEAN


def test_payout_and_failed_payout_reversal(db, make_user, settings):
    u = make_user()
    ledger.topup(db, u.id, 50_000, "a", settings)
    p1 = ledger.request_payout(db, u.id, 20_000, "k1", "5001234567", "Бат Дорж", settings)
    assert ledger.request_payout(db, u.id, 20_000, "k1", "5001234567", "Бат Дорж", settings).id == p1.id
    with pytest.raises(ledger.LedgerError) as e:
        ledger.request_payout(db, u.id, 40_000, "k2", "5001234567", "Бат Дорж", settings)
    assert e.value.code == "insufficient_funds"
    db.commit()
    assert _balances(db, u) == (30_000, 0)

    assert ledger.close_payout(db, p1.id, paid=False).status == PayoutStatus.failed
    ledger.close_payout(db, p1.id, paid=False)  # давтахад хоёр дахин буцаахгүй
    db.commit()
    assert _balances(db, u) == (50_000, 0)
    assert ledger.check_integrity(db) == CLEAN


def test_held_money_cannot_be_withdrawn(db, make_user, settings):
    u = make_user()
    ledger.topup(db, u.id, 10_000, "a", settings)
    ledger.place_hold(db, u.id, 8_000, "trip-1")
    with pytest.raises(ledger.LedgerError):
        ledger.request_payout(db, u.id, 5_000, "k", "5001234567", "Бат Дорж", settings)


def test_concurrent_holds_cannot_overspend(db, make_user, settings):
    """Нэг үлдэгдлийг зэрэг хоёр аялалд зарцуулах оролдлого: зөвхөн нэг нь амжина."""
    u = make_user()
    ledger.topup(db, u.id, 5_000, "a", settings)
    db.commit()
    barrier = threading.Barrier(8)
    results: list[str] = []

    def attempt(i: int) -> None:
        with SessionLocal() as s:
            barrier.wait()
            try:
                ledger.place_hold(s, u.id, 4_000, f"trip-{i}")
                s.commit()
                results.append("ok")
            except ledger.LedgerError as e:
                s.rollback()
                results.append(e.code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("insufficient_funds") == 7
    assert _balances(db, u) == (5_000, 4_000)
