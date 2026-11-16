"""Зах зээлийн үнэ ба лааны график.

Хэлцэл бүрийн үнийг үндсэн тарифтай харьцуулсан «индекс»-ээр хэмжинэ (1.00 = үндсэн тариф).
Ингэснээр урт, богино, ганц, хуваалцсан аяллууд нэг графикт харьцуулагдана.
"""

from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import geo, pricing
from .config import Settings
from .models import Booking, RideRequest

INTERVALS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
# Хэт зөрүүтэй хэлцлийг (хуурамч хэлцлээр үнэ хөдөлгөх оролдлого) тооцохгүй
MIN_INDEX, MAX_INDEX = 0.2, 5.0
# Хэлцэл энэ тоонд хүрэх хүртэл лавлах үнийг үндсэн тариф руу татна
FULL_TRUST_DEALS = 20


def _deals(
    db: Session, since: datetime, settings: Settings, near: tuple[float, float] | None, radius_m: float
) -> list[tuple[datetime, float]]:
    rows = db.execute(
        select(
            Booking.created_at,
            Booking.agreed_seat_price,
            Booking.agreed_distance_m,
            Booking.occupancy_at_agreement,
            Booking.driver_id,
            Booking.passenger_id,
            RideRequest.pickup_lat,
            RideRequest.pickup_lng,
        )
        .join(RideRequest, RideRequest.id == Booking.request_id)
        .where(Booking.created_at >= since)
        .order_by(Booking.created_at)
    ).all()
    out = []
    pairs: set[tuple[str, str]] = set()
    for r in rows:
        if near and geo.haversine_m(near, (r.pickup_lat, r.pickup_lng)) > radius_m:
            continue
        # Нэг хос хэрэглэгчийн давтан хэлцэл тухайн хугацаанд нэг л удаа тоологдоно
        pair = (r.driver_id, r.passenger_id)
        if pair in pairs:
            continue
        pairs.add(pair)
        base = pricing.base_seat_price(r.agreed_distance_m, r.occupancy_at_agreement, settings)
        index = r.agreed_seat_price / base
        if MIN_INDEX <= index <= MAX_INDEX:
            out.append((r.created_at, index))
    return out


def candles(
    db: Session,
    settings: Settings,
    *,
    interval: str = "1h",
    count: int = 48,
    near: tuple[float, float] | None = None,
    radius_m: float = 5000,
) -> dict:
    step = INTERVALS[interval]
    now = datetime.now(timezone.utc)
    epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = epoch + ((now - epoch) // step + 1) * step
    start = end - step * count
    buckets: dict[int, list[float]] = {}
    for at, index in _deals(db, start, settings, near, radius_m):
        buckets.setdefault(int((at - start) // step), []).append(index)
    out = []
    for i in sorted(buckets):
        v = buckets[i]
        out.append(
            {
                "start": (start + step * i).isoformat(),
                "open": round(v[0], 3),
                "high": round(max(v), 3),
                "low": round(min(v), 3),
                "close": round(v[-1], 3),
                "deals": len(v),
            }
        )
    return {
        "interval": interval,
        "band_low": settings.band_low,
        "band_high": settings.band_high,
        "taxi_rate_per_km": settings.taxi_rate_per_km,
        "candles": out,
    }


def reference_index(
    db: Session, settings: Settings, near: tuple[float, float] | None = None, radius_m: float = 5000
) -> dict:
    """Сүүлийн 1 цагийн хэлцлийн медиан. Хэлцэл цөөн бол үндсэн тариф (1.0) руу татна."""
    deals = [i for _, i in _deals(db, datetime.now(timezone.utc) - timedelta(hours=1), settings, near, radius_m)]
    if not deals:
        return {"index": 1.0, "deals": 0}
    weight = min(1.0, len(deals) / FULL_TRUST_DEALS)
    return {"index": round(1.0 + (median(deals) - 1.0) * weight, 3), "deals": len(deals)}
