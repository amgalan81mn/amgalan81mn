"""Жолооч, зорчигчийн аяллын API. Апп одоогоор хэдэн секунд тутам асууж (polling) төлөвөө шинэчилнэ."""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import geo, ledger, market, pricing, rides
from ..config import get_settings
from ..deps import Conf, CurrentUser, Db
from ..models import (
    PUBLIC_DOCUMENTS,
    Booking,
    BookingStatus,
    Document,
    DocumentKind,
    DriverRoute,
    Hold,
    Journey,
    JourneyStatus,
    RequestStatus,
    RideRequest,
    RouteStatus,
    User,
    Vehicle,
)

router = APIRouter(tags=["rides"])
T = TypeVar("T")


def run(db: Db, fn: Callable[[], T]) -> T:
    try:
        result = fn()
        db.commit()
        return result
    except rides.RideError as e:
        db.rollback()
        raise HTTPException(e.status, {"code": e.code, "message": e.message, **e.extra}) from e
    except ledger.LedgerError as e:
        db.rollback()
        raise HTTPException(409, {"code": e.code, "message": e.message, **e.extra}) from e


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


def _public_docs(db: Db, user_id: str, vehicle_id: str | None) -> dict[str, str]:
    rows = db.scalars(
        select(Document).where(
            Document.user_id == user_id,
            Document.vehicle_id == vehicle_id,
            Document.kind.in_(PUBLIC_DOCUMENTS),
        )
    ).all()
    return {d.kind.value: d.id for d in rows}


def booking_view(db: Db, b: Booking, viewer: User) -> dict:
    route = db.get(DriverRoute, b.route_id)
    req = db.get(RideRequest, b.request_id)
    pts = rides._points(route)
    cum = geo.cumulative(pts)
    drop = geo.project(pts, cum, (req.dropoff_lat, req.dropoff_lng), b.pickup_along_m)
    hold = db.get(Hold, b.hold_id)
    view = {
        "id": b.id,
        "status": b.status.value,
        "seats": b.seats,
        "agreed_seat_price": b.agreed_seat_price,
        "agreed_total": b.agreed_seat_price * b.seats,
        "agreed_distance_m": b.agreed_distance_m,
        # Апп энэ дугаараар аялгуу, өнгө сонгоно. Хоёр утсанд ижил.
        "tune": b.tune,
        "pickup": {"lat": req.pickup_lat, "lng": req.pickup_lng},
        "dropoff_on_route": {"lat": drop.point[0], "lng": drop.point[1]} if drop else None,
        "fare_total": b.fare_total,
        # Аянд «буцсан» мөнгө хэтэвчинд биш, дараагийн машинд зориулж түгжээтэй үлдэнэ
        "refund": None
        if b.fare_total is None
        else (b.agreed_seat_price * b.seats if b.journey_id else hold.amount) - b.fare_total,
        "cancelled_by": b.cancelled_by,
        "journey_id": b.journey_id,
    }
    if b.status == BookingStatus.boarded:
        view["jammed"] = rides.route_jammed(db, route, get_settings())
    if viewer.id == b.passenger_id:
        driver = db.get(User, b.driver_id)
        vehicle = db.get(Vehicle, route.vehicle_id)
        view["driver"] = {
            "first_name": driver.first_name,
            "last_name": driver.last_name,
            "photos": _public_docs(db, driver.id, None),
            "position": {"lat": route.last_lat, "lng": route.last_lng, "at": route.last_seen_at.isoformat()}
            if route.last_seen_at
            else None,
        }
        view["vehicle"] = {
            "plate": vehicle.plate,
            "make": vehicle.make,
            "model": vehicle.model,
            "color": vehicle.color,
            "seats_free": route.seats_free,
            "photos": _public_docs(db, driver.id, vehicle.id),
        }
    else:
        passenger = db.get(User, b.passenger_id)
        view["passenger"] = {
            "first_name": passenger.first_name,
            "last_name": passenger.last_name,
            "photos": _public_docs(db, passenger.id, None),
        }
        if b.fare_total is not None:
            view["driver_earned"] = b.fare_total - (b.commission or 0)
    return view


def route_view(r: DriverRoute) -> dict:
    return {
        "id": r.id,
        "status": r.status.value,
        "vehicle_id": r.vehicle_id,
        "length_m": r.length_m,
        "progress_m": round(r.progress_m),
        "price_factor": r.price_factor,
        "seats_free": r.seats_free,
    }


# ------------------------------------------------------------------ жолооч


class RouteIn(BaseModel):
    vehicle_id: str
    polyline: list[list[float]]
    price_factor: float = 1.0
    seats_free: int | None = None


@router.post("/driver/routes", status_code=201)
def start_route(body: RouteIn, user: CurrentUser, db: Db, settings: Conf) -> dict:
    route = run(
        db,
        lambda: rides.start_route(
            db,
            user,
            vehicle_id=body.vehicle_id,
            polyline=body.polyline,
            price_factor=body.price_factor,
            seats_free=body.seats_free,
            settings=settings,
        ),
    )
    return route_view(route)


@router.get("/driver/routes/current")
def current_route(user: CurrentUser, db: Db) -> dict | None:
    r = db.scalars(
        select(DriverRoute).where(DriverRoute.driver_id == user.id, DriverRoute.status == RouteStatus.active)
    ).first()
    if r is None:
        return None
    bookings = db.scalars(
        select(Booking)
        .where(Booking.route_id == r.id, Booking.status.in_(rides.ACTIVE_BOOKING))
        .order_by(Booking.created_at)
    ).all()
    return {**route_view(r), "bookings": [booking_view(db, b, user) for b in bookings]}


@router.post("/driver/routes/{route_id}/position")
def position(route_id: str, body: LatLng, user: CurrentUser, db: Db) -> dict:
    def go():
        route = rides.own_route(db, user, route_id, lock=True)
        return rides.update_position(db, route, body.lat, body.lng)

    return route_view(run(db, go))


@router.get("/driver/routes/{route_id}/requests")
def route_requests(route_id: str, user: CurrentUser, db: Db, settings: Conf) -> list[dict]:
    return run(db, lambda: rides.matching_requests(db, rides.own_route(db, user, route_id), settings))


class AcceptIn(BaseModel):
    request_id: str


@router.post("/driver/routes/{route_id}/accept", status_code=201)
def accept(route_id: str, body: AcceptIn, user: CurrentUser, db: Db, settings: Conf) -> dict:
    """«Энэ хэрэглэгчийг авна»: хоёр утсанд `tune` дугаартай аялгуу тоглоно."""

    def go():
        route = rides.own_route(db, user, route_id, lock=True)
        return rides.accept(db, route, body.request_id, settings)

    return booking_view(db, run(db, go), user)


@router.post("/driver/routes/{route_id}/end")
def end_route(route_id: str, user: CurrentUser, db: Db, settings: Conf) -> dict:
    def go():
        route = rides.own_route(db, user, route_id, lock=True)
        return rides.end_route(db, route, settings)

    return route_view(run(db, go))


def _driver_booking(db: Db, user: User, booking_id: str) -> tuple[Booking, DriverRoute]:
    booking, route = rides.lock_booking(db, booking_id)
    if booking.driver_id != user.id:
        raise rides.RideError(404, "booking", "Аялал олдсонгүй")
    return booking, route


def _passenger_booking(db: Db, user: User, booking_id: str) -> tuple[Booking, DriverRoute]:
    booking, route = rides.lock_booking(db, booking_id)
    if booking.passenger_id != user.id:
        raise rides.RideError(404, "booking", "Аялал олдсонгүй")
    return booking, route


class HeadcountIn(BaseModel):
    seats: int = Field(ge=1, le=8)


@router.post("/driver/bookings/{booking_id}/headcount")
def headcount(booking_id: str, body: HeadcountIn, user: CurrentUser, db: Db, settings: Conf) -> dict:
    def go():
        booking, route = _driver_booking(db, user, booking_id)
        return rides.change_headcount(db, route, booking, body.seats, settings)

    return booking_view(db, run(db, go), user)


class AlightIn(BaseModel):
    position: LatLng | None = None


def _at(body: AlightIn | None) -> tuple[float, float] | None:
    return (body.position.lat, body.position.lng) if body and body.position else None


@router.post("/driver/bookings/{booking_id}/alight")
def driver_alight(booking_id: str, user: CurrentUser, db: Db, settings: Conf, body: AlightIn | None = None) -> dict:
    def go():
        booking, route = _driver_booking(db, user, booking_id)
        return rides.alight(db, booking, route, settings, _at(body))

    return booking_view(db, run(db, go), user)


@router.post("/driver/bookings/{booking_id}/cancel")
def driver_cancel(booking_id: str, user: CurrentUser, db: Db) -> dict:
    def go():
        booking, route = _driver_booking(db, user, booking_id)
        return rides.cancel_booking(db, booking, route, "driver")

    return booking_view(db, run(db, go), user)


# ------------------------------------------------------------------ зорчигч


class RequestIn(BaseModel):
    pickup: LatLng
    dropoff: LatLng
    seats: int = Field(1, ge=1, le=8, description="Өөрөө болон дагалдах хүмүүс")
    bid_seat_price: int = Field(gt=0, description="Аян бол очих газар хүртэлх нийт төсөв (нэг хүнд)")
    multi_leg: bool = Field(False, description="Олон машинаар дамжиж болно (аян)")


@router.get("/rides/quote")
def ride_quote(
    db: Db,
    settings: Conf,
    pickup_lat: float = Query(ge=-90, le=90),
    pickup_lng: float = Query(ge=-180, le=180),
    dropoff_lat: float = Query(ge=-90, le=90),
    dropoff_lng: float = Query(ge=-180, le=180),
    seats: int = Query(1, ge=1, le=8),
) -> dict:
    """Зорчигчид санал болгох үнэ. Замын урт тодорхойгүй тул шулуун зайг 1.3-аар үржүүлж тооцно."""
    pickup, dropoff = (pickup_lat, pickup_lng), (dropoff_lat, dropoff_lng)
    distance = max(1, round(geo.haversine_m(pickup, dropoff) * 1.3))
    ref = market.reference_index(db, settings, near=pickup)
    base = pricing.base_seat_price(distance, seats, settings)
    low, high = pricing.price_band(distance, seats, settings)
    return {
        "estimated_distance_m": distance,
        "base_seat_price": base,
        "suggested_seat_price": round(base * ref["index"]),
        "band_low": low,
        "band_high": high,
        "market_index": ref["index"],
        "recent_deals": ref["deals"],
    }


def request_view(db: Db, req: RideRequest, user: User) -> dict:
    booking = db.scalars(
        select(Booking).where(Booking.request_id == req.id, Booking.status != BookingStatus.cancelled)
    ).first()
    return {
        "id": req.id,
        "status": req.status.value,
        "seats": req.seats,
        "bid_seat_price": req.bid_seat_price,
        "pickup": {"lat": req.pickup_lat, "lng": req.pickup_lng},
        "dropoff": {"lat": req.dropoff_lat, "lng": req.dropoff_lng},
        "expires_at": req.expires_at.isoformat(),
        "booking": booking_view(db, booking, user) if booking else None,
    }


@router.post("/rides/requests", status_code=201)
def create_request(body: RequestIn, user: CurrentUser, db: Db, settings: Conf) -> dict:
    req = run(
        db,
        lambda: rides.create_request(
            db,
            user,
            pickup=(body.pickup.lat, body.pickup.lng),
            dropoff=(body.dropoff.lat, body.dropoff.lng),
            seats=body.seats,
            bid_seat_price=body.bid_seat_price,
            settings=settings,
            multi_leg=body.multi_leg,
        ),
    )
    return request_view(db, req, user)


@router.get("/rides/requests/current")
def current_request(user: CurrentUser, db: Db) -> dict | None:
    run(db, lambda: rides.expire_requests(db))
    active_booking = db.scalars(
        select(Booking)
        .where(Booking.passenger_id == user.id, Booking.status.in_(rides.ACTIVE_BOOKING))
        .order_by(Booking.created_at.desc())
    ).first()
    if active_booking:
        return request_view(db, db.get(RideRequest, active_booking.request_id), user)
    req = db.scalars(
        select(RideRequest).where(RideRequest.passenger_id == user.id, RideRequest.status == RequestStatus.open)
    ).first()
    return request_view(db, req, user) if req else None


@router.post("/rides/requests/{request_id}/cancel")
def cancel_request(request_id: str, user: CurrentUser, db: Db) -> dict:
    def go():
        req = db.scalars(select(RideRequest).where(RideRequest.id == request_id).with_for_update()).first()
        if req is None or req.passenger_id != user.id:
            raise rides.RideError(404, "request", "Захиалга олдсонгүй")
        return rides.cancel_request(db, req)

    return request_view(db, run(db, go), user)


@router.get("/rides/bookings/{booking_id}")
def get_booking(booking_id: str, user: CurrentUser, db: Db) -> dict:
    b = db.get(Booking, booking_id)
    if b is None or user.id not in (b.passenger_id, b.driver_id):
        raise HTTPException(404, "Аялал олдсонгүй")
    return booking_view(db, b, user)


@router.post("/rides/bookings/{booking_id}/board")
def board(booking_id: str, user: CurrentUser, db: Db) -> dict:
    """Зорчигч «Суулаа» дарав."""

    def go():
        booking, route = _passenger_booking(db, user, booking_id)
        return rides.board(db, booking, route)

    return booking_view(db, run(db, go), user)


@router.post("/rides/bookings/{booking_id}/alight")
def passenger_alight(
    booking_id: str, user: CurrentUser, db: Db, settings: Conf, body: AlightIn | None = None
) -> dict:
    def go():
        booking, route = _passenger_booking(db, user, booking_id)
        return rides.alight(db, booking, route, settings, _at(body))

    return booking_view(db, run(db, go), user)


@router.post("/rides/bookings/{booking_id}/cancel")
def passenger_cancel(booking_id: str, user: CurrentUser, db: Db) -> dict:
    def go():
        booking, route = _passenger_booking(db, user, booking_id)
        return rides.cancel_booking(db, booking, route, "passenger")

    return booking_view(db, run(db, go), user)


# ------------------------------------------------------------------ аян


def _own_journey(db: Db, user: User, journey_id: str) -> Journey:
    j = db.scalars(select(Journey).where(Journey.id == journey_id).with_for_update()).first()
    if j is None or j.passenger_id != user.id:
        raise rides.RideError(404, "journey", "Аян олдсонгүй")
    return j


def journey_view(db: Db, j: Journey, user: User, settings) -> dict:
    hold = db.get(Hold, j.hold_id)
    legs = db.scalars(
        select(Booking).where(Booking.journey_id == j.id, Booking.status == BookingStatus.completed).order_by(Booking.completed_at)
    ).all()
    req = rides.journey_request(db, j) if j.status == JourneyStatus.active else None
    active = db.scalars(
        select(Booking).where(Booking.journey_id == j.id, Booking.status.in_(rides.ACTIVE_BOOKING))
    ).first()
    ahead = None
    if j.status == JourneyStatus.active:
        if active and active.status == BookingStatus.boarded:
            route = db.get(DriverRoute, active.route_id)
            if route.last_lat is not None:
                ahead = rides.drivers_ahead(db, j, (route.last_lat, route.last_lng), route.id, settings)
        elif req is not None and req.status == RequestStatus.open:
            ahead = rides.drivers_ahead(db, j, (req.pickup_lat, req.pickup_lng), None, settings)
    return {
        "id": j.id,
        "status": j.status.value,
        "seats": j.seats,
        "dropoff": {"lat": j.dropoff_lat, "lng": j.dropoff_lng},
        "budget_seat_price": j.bid_seat_price,
        "budget_left": hold.amount if hold.status.value == "active" else 0,
        "remaining_m": round(geo.haversine_m((req.pickup_lat, req.pickup_lng), (j.dropoff_lat, j.dropoff_lng)))
        if req
        else None,
        "legs": [
            {
                "booking_id": b.id,
                "plate": db.get(Vehicle, db.get(DriverRoute, b.route_id).vehicle_id).plate,
                "fare_total": b.fare_total,
                "distance_m": round((b.alight_along_m or 0) - (b.board_along_m or 0)),
            }
            for b in legs
        ],
        "request": request_view(db, req, user) if req else None,
        # Түгжрэлд байх үед: урд нь таныг дөхүүлж чадах хэдэн жолооч байна
        "drivers_ahead": ahead,
    }


@router.get("/rides/journeys/current")
def current_journey(user: CurrentUser, db: Db, settings: Conf) -> dict | None:
    run(db, lambda: rides.expire_requests(db))
    j = rides.active_journey(db, user.id)
    if j is None:
        j = db.scalars(
            select(Journey).where(Journey.passenger_id == user.id).order_by(Journey.created_at.desc())
        ).first()
        if j is None or j.finished_at is None or (rides._now() - j.finished_at).total_seconds() > 600:
            return None
    return journey_view(db, j, user, settings)


@router.post("/rides/journeys/{journey_id}/position")
def journey_position(journey_id: str, body: LatLng, user: CurrentUser, db: Db, settings: Conf) -> dict:
    """Аяны үед зорчигчийн утас байршлаа тогтмол илгээнэ (явган явах үед суух цэг хамт шилжинэ)."""

    def go():
        j = _own_journey(db, user, journey_id)
        rides.journey_ping(db, j, body.lat, body.lng, settings)
        return j

    return journey_view(db, run(db, go), user, settings)


@router.post("/rides/journeys/{journey_id}/finish")
def finish_journey(journey_id: str, user: CurrentUser, db: Db, settings: Conf) -> dict:
    j = run(db, lambda: rides.finish_journey(db, _own_journey(db, user, journey_id), settings))
    return journey_view(db, j, user, settings)


# ------------------------------------------------------------------ зах зээл


@router.get("/market/candles")
def market_candles(
    db: Db,
    settings: Conf,
    interval: str = Query("1h", pattern="^(15m|1h|1d)$"),
    count: int = Query(48, ge=1, le=500),
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radius_m: float = Query(5000, gt=0, le=100_000),
) -> dict:
    near = (lat, lng) if lat is not None and lng is not None else None
    return market.candles(db, settings, interval=interval, count=count, near=near, radius_m=radius_m)


def shares_trip(db: Db, viewer_id: str, owner_id: str) -> bool:
    """Хоёр хэрэглэгч идэвхтэй эсвэл саяхны аялалтай бол бие биеийн нийтийн зургийг харж болно."""
    q = select(Booking.id).where(
        ((Booking.driver_id == viewer_id) & (Booking.passenger_id == owner_id))
        | ((Booking.driver_id == owner_id) & (Booking.passenger_id == viewer_id)),
        Booking.status.in_(rides.ACTIVE_BOOKING),
    )
    return db.scalars(q).first() is not None


__all__ = ["router", "shares_trip", "DocumentKind"]
