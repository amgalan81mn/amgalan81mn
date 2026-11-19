"""Замдаа хүн авах үйл явц.

1. Жолооч маршрутаа зарлана (DriverRoute), явах зуураа байршлаа илгээнэ.
2. Зорчигч «авна» захиалга үүсгэнэ (RideRequest): нэг суудлын дээд үнэ, суудлын тоо. Мөнгө тэр даруй түгжигдэнэ.
3. Жолоочид маршрутынхаа урд, ойролцоо, үнэ нь таарсан захиалгууд харагдана.
4. Жолооч нэгийг нь «авна» дарна -> Booking. Хоёр утсанд ижил аялгуу, өнгө оноогдоно.
5. Зорчигч «Суулаа», дараа нь аль нэг нь «Буулаа» -> явсан зай, хамт явсан хүмүүсээр төлбөр тооцож суутгана.

Үнийн дүрэм: жолоочийн үнэ = үндсэн тариф × price_factor. Зорчигчийн санал түүнээс багагүй бол таарна.
Хэлцлийн үнэ нь зорчигчийн саналын үнэ (өндөр санал тавьсан хүн жагсаалтын эхэнд гарна).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import geo, ledger, pricing
from .config import Settings
from .deps import can_drive
from .models import (
    Booking,
    BookingStatus,
    DriverRoute,
    Hold,
    HoldKind,
    HoldStatus,
    Journey,
    JourneyPing,
    JourneyStatus,
    RequestStatus,
    ReviewStatus,
    RideRequest,
    RouteStatus,
    TrackPoint,
    User,
    Vehicle,
    new_id,
)

ACTIVE_BOOKING = (BookingStatus.matched, BookingStatus.boarded)
# GPS-ийн хэлбэлзэл: маршрутаас ийм зайнаас хол бол «урагшиллаа» гэж тооцохгүй
ON_ROUTE_M = 500
# Байршил хэлбэлзэж буцсан мэт харагдахыг тэвчих зай
BACKTRACK_M = 200


class RideError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _points(route: DriverRoute) -> list[geo.Point]:
    return [(float(p[0]), float(p[1])) for p in route.polyline]


def _validate_point(lat: float, lng: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise RideError(422, "bad_point", "Координат буруу байна")


# ------------------------------------------------------------------ жолооч


def start_route(
    db: Session,
    user: User,
    *,
    vehicle_id: str,
    polyline: list[list[float]],
    price_factor: float,
    seats_free: int | None,
    settings: Settings,
) -> DriverRoute:
    if not can_drive(db, user):
        raise RideError(403, "not_driver", "Жолоочийн бүртгэл баталгаажаагүй байна")
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id or vehicle.status != ReviewStatus.approved:
        raise RideError(404, "vehicle", "Баталгаажсан машин олдсонгүй")
    if not 2 <= len(polyline) <= 5000:
        raise RideError(422, "polyline", "Маршрут 2-5000 цэгтэй байна")
    for p in polyline:
        if len(p) != 2:
            raise RideError(422, "polyline", "Маршрутын цэг [lat, lng] хэлбэртэй")
        _validate_point(p[0], p[1])
    if not 0.1 <= price_factor <= 10:
        raise RideError(422, "price_factor", "Үнийн коэффициент 0.1-10 хооронд")
    seats = vehicle.seats if seats_free is None else seats_free
    if not 1 <= seats <= vehicle.seats:
        raise RideError(422, "seats", f"Сул суудал 1-{vehicle.seats} хооронд")
    active = db.scalars(
        select(DriverRoute).where(DriverRoute.driver_id == user.id, DriverRoute.status == RouteStatus.active)
    ).first()
    if active:
        raise RideError(409, "route_active", "Идэвхтэй маршрут байна. Эхлээд дуусгана уу", route_id=active.id)
    pts = [(float(a), float(b)) for a, b in polyline]
    length = geo.cumulative(pts)[-1]
    if length < settings.min_shared_m:
        raise RideError(422, "polyline", "Маршрут хэт богино байна")
    route = DriverRoute(
        driver_id=user.id,
        vehicle_id=vehicle.id,
        polyline=[list(p) for p in pts],
        length_m=round(length),
        price_factor=price_factor,
        seats_free=seats,
        last_lat=pts[0][0],
        last_lng=pts[0][1],
        last_seen_at=_now(),
    )
    db.add(route)
    db.flush()
    return route


def own_route(db: Session, user: User, route_id: str, lock: bool = False) -> DriverRoute:
    q = select(DriverRoute).where(DriverRoute.id == route_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    route = db.scalars(q).first()
    if route is None or route.driver_id != user.id:
        raise RideError(404, "route", "Маршрут олдсонгүй")
    return route


def _require_active(route: DriverRoute) -> None:
    if route.status != RouteStatus.active:
        raise RideError(409, "route_ended", "Маршрут дууссан байна")


def update_position(db: Session, route: DriverRoute, lat: float, lng: float) -> DriverRoute:
    _validate_point(lat, lng)
    _require_active(route)
    pts = _points(route)
    proj = geo.project(pts, geo.cumulative(pts), (lat, lng), max(0.0, route.progress_m - BACKTRACK_M))
    if proj and proj.offset_m <= ON_ROUTE_M:
        route.progress_m = max(route.progress_m, proj.along_m)
    route.last_lat, route.last_lng, route.last_seen_at = lat, lng, _now()
    db.add(TrackPoint(route_id=route.id, lat=lat, lng=lng))
    db.flush()
    check_hops(
        db,
        db.scalars(
            select(Booking).where(
                Booking.route_id == route.id,
                Booking.journey_id.is_not(None),
                Booking.status == BookingStatus.completed,
                Booking.hop_check.is_(None),
            )
        ).all(),
        settings_cache(),
    )
    return route


def _occupied(db: Session, route_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Booking.seats), 0)).where(
                Booking.route_id == route_id, Booking.status.in_(ACTIVE_BOOKING)
            )
        )
        or 0
    )


def driver_ask(distance_m: int, occupancy: int, factor: float, settings: Settings) -> int:
    return max(1, round(pricing.base_seat_price(distance_m, occupancy, settings) * factor))


def _fit(route: DriverRoute, req: RideRequest, occupied: int, settings: Settings) -> dict | None:
    """Захиалга энэ маршрутад таарах эсэх. Таарвал тооцоолсон утгуудыг буцаана."""
    if req.seats > route.seats_free:
        return None
    pts = _points(route)
    cum = geo.cumulative(pts)
    pick = geo.project(pts, cum, (req.pickup_lat, req.pickup_lng), route.progress_m)
    if pick is None or pick.offset_m > settings.pickup_radius_m:
        return None
    dest = (req.dropoff_lat, req.dropoff_lng)
    drop = geo.project(pts, cum, dest, pick.along_m)
    if drop is None:
        return None
    agreed = req.bid_seat_price
    if req.journey_id is None:
        if drop.offset_m > settings.dropoff_radius_m:
            return None
    else:
        # Аян: очих газар хүртэл хүргэхгүй ч болно, хэр ойртуулснаар нь төлнө («дөхүүлэх»)
        before = geo.haversine_m((req.pickup_lat, req.pickup_lng), dest)
        after = geo.haversine_m(drop.point, dest)
        if after <= settings.arrive_radius_m:
            covered = 1.0
        else:
            covered = max(0.0, min(1.0, (before - after) / before)) if before > 0 else 0.0
        if covered < settings.min_leg_progress:
            return None
        agreed = max(1, round(req.bid_seat_price * covered))
    distance = round(drop.along_m - pick.along_m)
    if distance < settings.min_shared_m:
        return None
    occupancy = occupied + req.seats
    ask = driver_ask(distance, occupancy, route.price_factor, settings)
    if agreed < ask:
        return None
    return {
        "pickup": pick,
        "dropoff": drop,
        "distance_m": distance,
        "occupancy": occupancy,
        "ask_seat_price": ask,
        "agreed_seat_price": agreed,
        "away_m": round(max(0.0, pick.along_m - route.progress_m)),
    }


def expire_requests(db: Session) -> int:
    rows = db.scalars(
        select(RideRequest)
        .where(RideRequest.status == RequestStatus.open, RideRequest.expires_at <= _now())
        .with_for_update(skip_locked=True)
    ).all()
    for req in rows:
        req.status = RequestStatus.expired
        if req.journey_id:
            _finish_journey(db, db.get(Journey, req.journey_id))
        else:
            ledger.release_hold(db, req.hold_id)
    db.flush()
    return len(rows)


def _dropped_before(db: Session, route: DriverRoute, request_id: str) -> bool:
    """Энэ маршрут энэ захиалгыг өмнө нь авч цуцалсан бол дахин санал болгохгүй."""
    return (
        db.scalars(select(Booking.id).where(Booking.route_id == route.id, Booking.request_id == request_id)).first()
        is not None
    )


def matching_requests(db: Session, route: DriverRoute, settings: Settings) -> list[dict]:
    _require_active(route)
    expire_requests(db)
    pts = _points(route)
    lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
    pad = settings.pickup_radius_m / 111_000 * 2  # градусаар, өргөргийн нөлөөг тооцоод илүүтэй
    rows = db.scalars(
        select(RideRequest).where(
            RideRequest.status == RequestStatus.open,
            RideRequest.passenger_id != route.driver_id,
            RideRequest.pickup_lat.between(min(lats) - pad, max(lats) + pad),
            RideRequest.pickup_lng.between(min(lngs) - pad * 2, max(lngs) + pad * 2),
        )
    ).all()
    occupied = _occupied(db, route.id)
    out = []
    for req in rows:
        fit = _fit(route, req, occupied, settings)
        if fit is None or _dropped_before(db, route, req.id):
            continue
        passenger = db.get(User, req.passenger_id)
        out.append(
            {
                "request_id": req.id,
                "passenger_first_name": passenger.first_name,
                "seats": req.seats,
                "bid_seat_price": fit["agreed_seat_price"],
                "ask_seat_price": fit["ask_seat_price"],
                "multi_leg": req.journey_id is not None,
                "distance_m": fit["distance_m"],
                "away_m": fit["away_m"],
                "pickup": {"lat": req.pickup_lat, "lng": req.pickup_lng},
                "dropoff_on_route": {"lat": fit["dropoff"].point[0], "lng": fit["dropoff"].point[1]},
            }
        )
    # Өндөр үнэ санал болгосон, ойр зогсож байгаа хүн эхэнд
    out.sort(key=lambda r: (-r["bid_seat_price"], r["away_m"]))
    return out


def _pick_tune(db: Session, req: RideRequest, settings: Settings) -> int:
    """Ойролцоо уулзаж буй хосуудын аялгуутай давхцахгүй аялгуу сонгоно."""
    others = db.execute(
        select(Booking.tune, RideRequest.pickup_lat, RideRequest.pickup_lng)
        .join(RideRequest, RideRequest.id == Booking.request_id)
        .where(Booking.status == BookingStatus.matched)
    ).all()
    used = {
        t
        for t, lat, lng in others
        if geo.haversine_m((lat, lng), (req.pickup_lat, req.pickup_lng)) <= settings.tune_radius_m
    }
    for t in range(settings.tune_count):
        if t not in used:
            return t
    # Бүх аялгуу ашиглагдаж байвал хамгийн цөөн давтагдсаныг авна
    counts = {t: 0 for t in range(settings.tune_count)}
    for t, lat, lng in others:
        if t in counts and geo.haversine_m((lat, lng), (req.pickup_lat, req.pickup_lng)) <= settings.tune_radius_m:
            counts[t] += 1
    return min(counts, key=counts.get)


def accept(db: Session, route: DriverRoute, request_id: str, settings: Settings) -> Booking:
    """Жолооч «Энэ хэрэглэгчийг авна» дарав. `route` нь түгжигдсэн байх ёстой."""
    _require_active(route)
    req = db.scalars(
        select(RideRequest)
        .where(RideRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if req is None or req.status != RequestStatus.open or req.expires_at <= _now():
        raise RideError(409, "request_gone", "Энэ захиалгыг өөр жолооч авсан эсвэл цуцлагдсан")
    if req.passenger_id == route.driver_id:
        raise RideError(409, "self", "Өөрийгөө авч болохгүй")
    if _dropped_before(db, route, req.id):
        raise RideError(409, "dropped_before", "Энэ захиалгыг өмнө нь цуцалсан байна")
    fit = _fit(route, req, _occupied(db, route.id), settings)
    if fit is None:
        raise RideError(409, "no_longer_fits", "Захиалга таны маршрут, үнэ, суудалд таарахаа больсон")
    booking = Booking(
        route_id=route.id,
        request_id=req.id,
        driver_id=route.driver_id,
        passenger_id=req.passenger_id,
        seats=req.seats,
        agreed_seat_price=fit["agreed_seat_price"],
        agreed_distance_m=fit["distance_m"],
        occupancy_at_agreement=fit["occupancy"],
        pickup_along_m=fit["pickup"].along_m,
        dropoff_along_m=fit["dropoff"].along_m,
        tune=_pick_tune(db, req, settings),
        hold_id=req.hold_id,
        journey_id=req.journey_id,
    )
    route.seats_free -= req.seats
    req.status = RequestStatus.matched
    db.add(booking)
    db.flush()
    return booking


def change_headcount(db: Session, route: DriverRoute, booking: Booking, seats: int, settings: Settings) -> Booking:
    """Заасан тооноос олон хүн ирвэл жолооч тоог нэмнэ. Нэмэлт мөнгө түгжигдэнэ (хүрэхгүй бол 402)."""
    if booking.status not in ACTIVE_BOOKING:
        raise RideError(409, "booking_closed", "Аялал дууссан эсвэл цуцлагдсан")
    if booking.journey_id:
        raise RideError(409, "journey_seats", "Аянд хүний тоог эхлэхдээ заана")
    if seats <= booking.seats:
        raise RideError(422, "seats", "Зөвхөн нэмэх боломжтой")
    if seats > settings.max_guests_per_booking + 1:
        raise RideError(422, "seats", "Нэг захиалгад хэт олон хүн байна")
    extra = seats - booking.seats
    if extra > route.seats_free:
        raise RideError(409, "no_seats", "Сул суудал хүрэхгүй байна")
    ledger.release_hold(db, booking.hold_id)
    try:
        hold = ledger.place_hold(
            db,
            booking.passenger_id,
            booking.agreed_seat_price * seats,
            f"booking:{booking.id}:seats:{seats}",
            reference=f"booking:{booking.id}",
        )
    except ledger.LedgerError as e:
        raise RideError(402, e.code, "Зорчигчийн хэтэвч хүрэлцэхгүй байна", **e.extra) from e
    booking.hold_id = hold.id
    booking.seats = seats
    booking.occupancy_at_agreement += extra
    route.seats_free -= extra
    db.flush()
    return booking


# ------------------------------------------------------------------ зорчигч


def create_request(
    db: Session,
    user: User,
    *,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    seats: int,
    bid_seat_price: int,
    settings: Settings,
    multi_leg: bool = False,
) -> RideRequest:
    if user.identity_status != ReviewStatus.approved:
        raise RideError(403, "identity", "Хувийн бүртгэлээ баталгаажуулсны дараа захиалах боломжтой")
    _validate_point(*pickup)
    _validate_point(*dropoff)
    if not 1 <= seats <= settings.max_guests_per_booking + 1:
        raise RideError(422, "seats", "Суудлын тоо буруу")
    if bid_seat_price <= 0:
        raise RideError(422, "bid", "Үнэ эерэг байх ёстой")
    direct = round(geo.haversine_m(pickup, dropoff))
    if direct < settings.min_shared_m:
        raise RideError(422, "too_short", "Очих газар хэт ойр байна")
    open_req = db.scalars(
        select(RideRequest).where(RideRequest.passenger_id == user.id, RideRequest.status == RequestStatus.open)
    ).first()
    if open_req:
        raise RideError(409, "request_open", "Идэвхтэй захиалга байна", request_id=open_req.id)
    if active_journey(db, user.id):
        raise RideError(409, "journey_active", "Идэвхтэй аян байна")
    if multi_leg:
        return _start_journey(db, user, pickup, dropoff, seats, bid_seat_price, direct, settings)
    req_id = new_id()
    try:
        hold = ledger.place_hold(
            db, user.id, bid_seat_price * seats, f"request:{req_id}", HoldKind.trip, reference=f"request:{req_id}"
        )
    except ledger.LedgerError as e:
        # Дүн хүрэхгүй бол цэнэглэхийг шаардана: дутуу дүнг буцаана
        raise RideError(402, e.code, "Хэтэвчээ цэнэглэнэ үү", **e.extra) from e
    req = RideRequest(
        id=req_id,
        passenger_id=user.id,
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        direct_m=direct,
        seats=seats,
        bid_seat_price=bid_seat_price,
        hold_id=hold.id,
        expires_at=_now() + timedelta(minutes=settings.request_ttl_minutes),
    )
    db.add(req)
    db.flush()
    return req


def cancel_request(db: Session, req: RideRequest) -> RideRequest:
    if req.status != RequestStatus.open:
        raise RideError(409, "not_open", "Захиалга нээлттэй биш байна")
    ledger.release_hold(db, req.hold_id)
    req.status = RequestStatus.cancelled
    db.flush()
    return req


def lock_booking(db: Session, booking_id: str) -> tuple[Booking, DriverRoute]:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise RideError(404, "booking", "Аялал олдсонгүй")
    # Түгжих дараалал: маршрут -> захиалга (accept-тай ижил)
    route = db.scalars(
        select(DriverRoute)
        .where(DriverRoute.id == booking.route_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    booking = db.scalars(
        select(Booking).where(Booking.id == booking_id).with_for_update().execution_options(populate_existing=True)
    ).one()
    return booking, route


def board(db: Session, booking: Booking, route: DriverRoute) -> Booking:
    if booking.status != BookingStatus.matched:
        raise RideError(409, "not_matched", "Суух боломжгүй төлөвт байна")
    booking.status = BookingStatus.boarded
    booking.board_along_m = route.progress_m
    booking.boarded_at = _now()
    db.flush()
    return booking


def _segments(db: Session, booking: Booking, start: float, end: float, route: DriverRoute) -> list[pricing.Segment]:
    """[start, end] хэсгийг машинд хэдэн суудал эзлэгдсэнээр нь хэсэглэнэ."""
    others = db.scalars(
        select(Booking).where(
            Booking.route_id == booking.route_id,
            Booking.id != booking.id,
            Booking.board_along_m.is_not(None),
        )
    ).all()
    intervals = []
    for o in others:
        o_end = o.alight_along_m if o.alight_along_m is not None else route.progress_m
        lo, hi = max(start, o.board_along_m), min(end, o_end)
        if hi > lo:
            intervals.append((lo, hi, o.seats))
    cuts = sorted({start, end, *(x for lo, hi, _ in intervals for x in (lo, hi))})
    segs = []
    for a, b in zip(cuts, cuts[1:]):
        mid = (a + b) / 2
        occ = booking.seats + sum(s for lo, hi, s in intervals if lo <= mid < hi)
        segs.append(pricing.Segment(round(b - a), occ))
    return segs


def alight(
    db: Session,
    booking: Booking,
    route: DriverRoute,
    settings: Settings,
    at: tuple[float, float] | None = None,
) -> Booking:
    """«Буулаа»: төлбөрийг тооцож, шимтгэл суутгаад жолоочид шилжүүлнэ, үлдсэнийг зорчигчид буцаана."""
    if booking.status != BookingStatus.boarded:
        raise RideError(409, "not_boarded", "Зорчигч суугаагүй байна")
    along = route.progress_m
    if at is not None:
        _validate_point(*at)
        pts = _points(route)
        proj = geo.project(pts, geo.cumulative(pts), at, booking.board_along_m)
        if proj and proj.offset_m <= ON_ROUTE_M:
            along = max(along, proj.along_m)
    start = booking.board_along_m
    end = max(start, along)
    journey = db.get(Journey, booking.journey_id) if booking.journey_id else None
    fare = pricing.final_fare(
        agreed_seat_price=booking.agreed_seat_price,
        agreed_distance_m=booking.agreed_distance_m,
        occupancy_at_agreement=booking.occupancy_at_agreement,
        seats=booking.seats,
        segments=_segments(db, booking, start, end, route),
        settings=settings,
        # Аянд эрт буух нь хэвийн үзэгдэл: доод хувь авахгүй, оронд нь хамт явсан эсэхийг дараа шалгана
        early_exit_floor=0.0 if journey else None,
    )
    pts = _points(route)
    cum = geo.cumulative(pts)
    route_point = _point_at(pts, cum, end)
    booking.alight_lat, booking.alight_lng = at if at is not None else route_point
    if journey:
        total = max(fare.total, min(settings.min_leg_fare, booking.agreed_seat_price) * booking.seats)
        _, fee = ledger.capture_from_hold(db, booking.hold_id, total, booking.driver_id, booking.id, settings)
        fare = pricing.Fare(fare.per_seat, total, booking.agreed_seat_price * booking.seats - total, fare.travelled_m, fare.early_exit)
    else:
        _, fee = ledger.settle_hold(db, booking.hold_id, fare.total, booking.driver_id, settings)
    booking.alight_along_m = end
    booking.status = BookingStatus.completed
    booking.completed_at = _now()
    booking.fare_total = fare.total
    booking.commission = fee
    route.seats_free += booking.seats
    db.flush()
    if journey:
        _next_leg(db, journey, (booking.alight_lat, booking.alight_lng), settings)
    return booking


def cancel_booking(db: Session, booking: Booking, route: DriverRoute, by: str) -> Booking:
    """Суухаас өмнө цуцлах. Зорчигч цуцалбал мөнгө буцна; жолооч цуцалбал захиалга дахин нээгдэнэ."""
    if booking.status != BookingStatus.matched:
        raise RideError(409, "cannot_cancel", "Суусны дараа цуцлах боломжгүй, «Буулаа» дарна уу")
    req = db.scalars(select(RideRequest).where(RideRequest.id == booking.request_id).with_for_update()).one()
    booking.status = BookingStatus.cancelled
    booking.cancelled_by = by
    route.seats_free += booking.seats
    if by == "passenger" and not booking.journey_id:
        ledger.release_hold(db, booking.hold_id)
        req.status = RequestStatus.cancelled
    else:
        # Жолооч цуцалсан, эсвэл аянд зорчигч энэ машинаас татгалзсан: хүсэлт дахин нээгдэж өөр машин хайна
        req.status = RequestStatus.open
        req.hold_id = booking.hold_id  # суудлын тоо нэмэгдсэн байж болно
        req.seats = booking.seats
        req.expires_at = max(req.expires_at, _now() + timedelta(minutes=10))
    db.flush()
    return booking


def end_route(db: Session, route: DriverRoute, settings: Settings) -> DriverRoute:
    """Маршрут дуусгах: сууж буй хүмүүсийг одоогийн цэгт буулгаж тооцоо хийнэ, хүлээж буйг цуцална."""
    _require_active(route)
    for b in db.scalars(
        select(Booking)
        .where(Booking.route_id == route.id, Booking.status.in_(ACTIVE_BOOKING))
        .order_by(Booking.created_at)
        .with_for_update()
    ).all():
        if b.status == BookingStatus.boarded:
            alight(db, b, route, settings)
        else:
            cancel_booking(db, b, route, "driver")
    route.status = RouteStatus.ended
    route.ended_at = _now()
    db.flush()
    return route


# ------------------------------------------------------------------ аян


def settings_cache() -> Settings:
    from .config import get_settings

    return get_settings()


def _point_at(pts: list[geo.Point], cum: list[float], along: float) -> geo.Point:
    for i in range(len(pts) - 1):
        if cum[i + 1] >= along:
            seg = cum[i + 1] - cum[i]
            t = 0.0 if seg == 0 else (along - cum[i]) / seg
            a, b = pts[i], pts[i + 1]
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return pts[-1]


def active_journey(db: Session, user_id: str) -> Journey | None:
    return db.scalars(
        select(Journey).where(Journey.passenger_id == user_id, Journey.status == JourneyStatus.active)
    ).first()


def _start_journey(
    db: Session,
    user: User,
    pickup: tuple[float, float],
    dropoff: tuple[float, float],
    seats: int,
    bid_seat_price: int,
    direct: int,
    settings: Settings,
) -> RideRequest:
    journey_id = new_id()
    try:
        hold = ledger.place_hold(
            db,
            user.id,
            bid_seat_price * seats,
            f"journey:{journey_id}",
            HoldKind.trip,
            reference=f"journey:{journey_id}",
        )
    except ledger.LedgerError as e:
        raise RideError(402, e.code, "Хэтэвчээ цэнэглэнэ үү", **e.extra) from e
    journey = Journey(
        id=journey_id,
        passenger_id=user.id,
        origin_lat=pickup[0],
        origin_lng=pickup[1],
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        direct_m=direct,
        seats=seats,
        bid_seat_price=bid_seat_price,
        hold_id=hold.id,
    )
    db.add(journey)
    db.flush()
    req = _next_leg(db, journey, pickup, settings)
    assert req is not None
    return req


def _next_leg(db: Session, journey: Journey, pickup: tuple[float, float], settings: Settings) -> RideRequest | None:
    """Аяны дараагийн хэсгийн хүсэлт. Очих газарт хүрсэн эсвэл төсөв дууссан бол аяныг дуусгана."""
    dest = (journey.dropoff_lat, journey.dropoff_lng)
    remaining = geo.haversine_m(pickup, dest)
    hold = db.get(Hold, journey.hold_id)
    per_seat_left = hold.amount // journey.seats if hold.status == HoldStatus.active else 0
    if remaining <= settings.arrive_radius_m or per_seat_left < settings.min_leg_fare:
        _finish_journey(db, journey)
        return None
    # Үлдсэн замд ногдох төсөв: эхний төсвийг үлдсэн зайд хувь тэнцүүлнэ
    bid = round(journey.bid_seat_price * remaining / max(journey.direct_m, 1))
    bid = max(settings.min_leg_fare, min(bid, per_seat_left))
    req = RideRequest(
        passenger_id=journey.passenger_id,
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        dropoff_lat=journey.dropoff_lat,
        dropoff_lng=journey.dropoff_lng,
        direct_m=round(remaining),
        seats=journey.seats,
        bid_seat_price=bid,
        hold_id=journey.hold_id,
        journey_id=journey.id,
        expires_at=_now() + timedelta(minutes=settings.request_ttl_minutes),
    )
    db.add(req)
    db.flush()
    return req


def _finish_journey(db: Session, journey: Journey) -> Journey:
    if journey.status == JourneyStatus.finished:
        return journey
    hold = db.get(Hold, journey.hold_id)
    if hold.status == HoldStatus.active:
        ledger.release_hold(db, hold.id)
    journey.status = JourneyStatus.finished
    journey.finished_at = _now()
    db.flush()
    return journey


def finish_journey(db: Session, journey: Journey, settings: Settings) -> Journey:
    """Зорчигч аяныг гараар дуусгах (жишээ нь үлдсэн замаа явганаар явна). Үлдсэн мөнгө буцна."""
    if journey.status != JourneyStatus.active:
        return journey
    boarded = db.scalars(
        select(Booking).where(Booking.journey_id == journey.id, Booking.status == BookingStatus.boarded)
    ).first()
    if boarded:
        raise RideError(409, "on_board", "Эхлээд машинаасаа «Буулаа» дарна уу")
    for b in db.scalars(
        select(Booking).where(Booking.journey_id == journey.id, Booking.status == BookingStatus.matched)
    ).all():
        booking, route = lock_booking(db, b.id)
        cancel_booking(db, booking, route, "passenger")
    for req in db.scalars(
        select(RideRequest).where(RideRequest.journey_id == journey.id, RideRequest.status == RequestStatus.open)
    ).all():
        req.status = RequestStatus.cancelled
    return _finish_journey(db, journey)


def journey_request(db: Session, journey: Journey) -> RideRequest | None:
    """Аяны одоогийн (сүүлийн) хүсэлт."""
    return db.scalars(
        select(RideRequest)
        .where(RideRequest.journey_id == journey.id, RideRequest.status.in_((RequestStatus.open, RequestStatus.matched)))
        .order_by(RideRequest.created_at.desc())
    ).first()


def journey_ping(db: Session, journey: Journey, lat: float, lng: float, settings: Settings) -> None:
    """Зорчигчийн байршил. Явганаар түгжрэлийг давж байх үед хүсэлтийн суух цэг хамт шилжинэ."""
    _validate_point(lat, lng)
    if journey.status != JourneyStatus.active:
        raise RideError(409, "journey_finished", "Аян дууссан байна")
    db.add(JourneyPing(journey_id=journey.id, lat=lat, lng=lng))
    req = db.scalars(
        select(RideRequest)
        .where(RideRequest.journey_id == journey.id, RideRequest.status == RequestStatus.open)
        .with_for_update()
    ).first()
    if req is not None:
        req.pickup_lat, req.pickup_lng = lat, lng
        req.direct_m = round(geo.haversine_m((lat, lng), (journey.dropoff_lat, journey.dropoff_lng)))
    db.flush()
    check_hops(
        db,
        db.scalars(
            select(Booking).where(
                Booking.journey_id == journey.id,
                Booking.status == BookingStatus.completed,
                Booking.hop_check.is_(None),
            )
        ).all(),
        settings,
    )


def check_hops(db: Session, bookings: list[Booking], settings: Settings) -> None:
    """Буусан зорчигч үнэхээр салсан уу, эсвэл аппаас гадуур тэр машинаараа үргэлжлүүлсэн үү.

    Жолооч хангалттай зай явсны дараа хоёр утасны байршлыг ижил агшинд харьцуулна.
    Хамт явж байвал «suspect» гэж тэмдэглээд, эрт буусны доод төлбөрийг аяны төсвөөс нэмж суутгана.
    """
    now = _now()
    for b in bookings:
        if b.completed_at is None or (now - b.completed_at).total_seconds() < settings.hop_check_after_s:
            continue
        tps = db.scalars(
            select(TrackPoint)
            .where(TrackPoint.route_id == b.route_id, TrackPoint.at > b.completed_at)
            .order_by(TrackPoint.at)
        ).all()
        far = [t for t in tps if geo.haversine_m((b.alight_lat, b.alight_lng), (t.lat, t.lng)) >= settings.hop_driver_moved_m]
        if not far:
            if (now - b.completed_at).total_seconds() > 15 * 60:
                b.hop_check = "ok"  # жолооч хөдлөөгүй (эсвэл апп хаасан) – шалгах боломжгүй, сэжиггүй гэж үзнэ
            continue
        tp = far[0]
        pings = db.scalars(
            select(JourneyPing).where(
                JourneyPing.journey_id == b.journey_id,
                JourneyPing.at.between(tp.at - timedelta(seconds=60), tp.at + timedelta(seconds=60)),
            )
        ).all()
        if not pings:
            if (now - tp.at).total_seconds() > 5 * 60:
                b.hop_check = "unverified"  # зорчигчийн утас байршил илгээгээгүй
            continue
        ping = min(pings, key=lambda p: abs((p.at - tp.at).total_seconds()))
        together = geo.haversine_m((ping.lat, ping.lng), (tp.lat, tp.lng)) <= settings.hop_together_m
        b.hop_check = "suspect" if together else "ok"
        if together:
            _charge_hop_penalty(db, b, settings)
    db.flush()


def _charge_hop_penalty(db: Session, b: Booking, settings: Settings) -> None:
    floor = round(b.agreed_seat_price * settings.early_exit_min_fraction) * b.seats
    extra = floor - (b.fare_total or 0)
    hold = db.get(Hold, b.hold_id)
    if extra <= 0 or hold.status != HoldStatus.active:
        return
    extra = min(extra, hold.amount)
    _, fee = ledger.capture_from_hold(db, hold.id, extra, b.driver_id, f"hop:{b.id}", settings)
    b.fare_total = (b.fare_total or 0) + extra
    b.commission = (b.commission or 0) + fee


def route_jammed(db: Session, route: DriverRoute, settings: Settings) -> bool:
    """Сүүлийн `jam_window_s` секундэд машин бараг хөдлөөгүй бол түгжирсэн гэж үзнэ."""
    since = _now() - timedelta(seconds=settings.jam_window_s)
    tps = db.scalars(select(TrackPoint).where(TrackPoint.route_id == route.id, TrackPoint.at >= since)).all()
    if len(tps) < 2:
        return False
    span = (max(t.at for t in tps) - min(t.at for t in tps)).total_seconds()
    if span < settings.jam_window_s * 0.7:
        return False
    last = max(tps, key=lambda t: t.at)
    return all(geo.haversine_m((t.lat, t.lng), (last.lat, last.lng)) < settings.jam_move_m for t in tps)


def drivers_ahead(
    db: Session, journey: Journey, at: tuple[float, float], exclude_route: str | None, settings: Settings
) -> dict:
    """Энэ цэгээс очих газар руу дөхүүлж чадах, үнэ таарах идэвхтэй жолооч нар."""
    hold = db.get(Hold, journey.hold_id)
    per_seat_left = hold.amount // journey.seats if hold.status == HoldStatus.active else 0
    dest = (journey.dropoff_lat, journey.dropoff_lng)
    remaining = geo.haversine_m(at, dest)
    bid = max(settings.min_leg_fare, min(round(journey.bid_seat_price * remaining / max(journey.direct_m, 1)), per_seat_left))
    probe = RideRequest(  # хадгалахгүй: зөвхөн тааруулалтыг шалгах
        pickup_lat=at[0],
        pickup_lng=at[1],
        dropoff_lat=dest[0],
        dropoff_lng=dest[1],
        seats=journey.seats,
        bid_seat_price=bid,
        journey_id=journey.id,
    )
    q = select(DriverRoute).where(DriverRoute.status == RouteStatus.active, DriverRoute.driver_id != journey.passenger_id)
    if exclude_route:
        q = q.where(DriverRoute.id != exclude_route)
    prices = []
    walking = settings.model_copy(update={"pickup_radius_m": settings.walk_radius_m})
    for route in db.scalars(q).all():
        fit = _fit(route, probe, _occupied(db, route.id), walking)
        if fit:
            prices.append(fit["agreed_seat_price"])
    return {"count": len(prices), "best_seat_price": min(prices) if prices else None}
