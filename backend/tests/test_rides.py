import math
import threading

from fastapi.testclient import TestClient

from app import geo, ledger
from app.db import SessionLocal
from app.main import app
from app.models import Document, DocumentKind, DriverProfile, ReviewStatus, Vehicle
from app.security import create_token

LAT = 47.92
M_PER_DEG_LNG = 111_320 * math.cos(math.radians(LAT))
CLEAN = {"sum_of_balances": 0, "accounts_off_ledger": 0, "accounts_off_holds": 0}


def at(x_m: float, north_m: float = 0.0) -> dict:
    """Зүүнээс баруун тийш шулуун гудамж: эхлэлээс x_m метрт, хойшоо north_m метрт."""
    return {"lat": LAT + north_m / 111_320, "lng": 106.80 + x_m / M_PER_DEG_LNG}


ROUTE = [[at(x)["lat"], at(x)["lng"]] for x in range(0, 12_001, 500)]


def auth(user) -> dict:
    return {"Authorization": f"Bearer {create_token(user.id)}"}


def driver(db, make_user, settings, *, seats=4, plate="1234УБА"):
    u = make_user(first_name="Болд", last_name="Бат", identity_status=ReviewStatus.approved)
    db.add(DriverProfile(user_id=u.id, license_no="A1", status=ReviewStatus.approved))
    v = Vehicle(
        owner_id=u.id, plate=plate, make="Toyota", model="Prius", color="Цагаан", seats=seats,
        status=ReviewStatus.approved,
    )
    db.add(v)
    db.flush()
    db.add(Document(user_id=u.id, kind=DocumentKind.selfie, path="x", content_type="image/png", sha256="0"))
    db.add(Document(user_id=u.id, vehicle_id=v.id, kind=DocumentKind.car_front, path="x", content_type="image/png", sha256="0"))
    db.commit()
    return u, v


def passenger(db, make_user, settings, money=100_000, name="Сараа"):
    u = make_user(first_name=name, last_name="Дорж", identity_status=ReviewStatus.approved)
    if money:
        ledger.topup(db, u.id, money, f"seed-{u.id}", settings)
        db.commit()
    return u


def start(client, d, v, **kw):
    r = client.post("/driver/routes", headers=auth(d), json={"vehicle_id": v.id, "polyline": ROUTE, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def request(client, p, pick_x, drop_x, bid=10_000, seats=1):
    r = client.post(
        "/rides/requests",
        headers=auth(p),
        json={"pickup": at(pick_x, 80), "dropoff": at(drop_x, 300), "seats": seats, "bid_seat_price": bid},
    )
    return r


def move(client, d, route_id, x):
    r = client.post(f"/driver/routes/{route_id}/position", headers=auth(d), json=at(x, 15))
    assert r.status_code == 200, r.text
    return r.json()


def wallet(db, user):
    db.expire_all()
    w = ledger.get_wallet(db, user.id)
    db.commit()
    return w.balance, w.held


def test_projection_on_a_straight_street():
    pts = [(p[0], p[1]) for p in ROUTE]
    cum = geo.cumulative(pts)
    assert abs(cum[-1] - 12_000) < 30
    pr = geo.project(pts, cum, (at(3_250, 100)["lat"], at(3_250, 100)["lng"]))
    assert abs(pr.along_m - 3_250) < 15 and abs(pr.offset_m - 100) < 5
    # Жолоочийн өнгөрсөн хэсгийг тооцохгүй
    assert geo.project(pts, cum, (at(1_000)["lat"], at(1_000)["lng"]), min_along=5_000).along_m >= 5_000


def test_full_ride(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start(client, d, v)

    r = request(client, p, 2_000, 8_000)
    assert r.status_code == 201, r.text
    assert wallet(db, p) == (100_000, 10_000)  # захиалах үед түгжигдсэн

    listed = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()
    assert len(listed) == 1 and listed[0]["passenger_first_name"] == "Сараа"
    assert abs(listed[0]["distance_m"] - 6_000) < 50

    booking = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": listed[0]["request_id"]}).json()
    assert booking["tune"] == 0 and booking["passenger"]["first_name"] == "Сараа"

    # Зорчигчийн дэлгэц: жолоочийн нэр, машины дугаар, өнгө, сул суудал, аялгуу
    mine = client.get("/rides/requests/current", headers=auth(p)).json()["booking"]
    assert mine["tune"] == 0
    assert mine["driver"]["first_name"] == "Болд"
    assert (mine["vehicle"]["plate"], mine["vehicle"]["color"], mine["vehicle"]["seats_free"]) == ("1234УБА", "Цагаан", 3)
    # Аялалд хамт буй үед жолоочийн нүүр зураг, машины зургийг харах эрхтэй (файл энэ тестэд байхгүй тул 404 биш 500 гарахгүйг шалгахгүй)
    from app.routers.rides import shares_trip
    assert shares_trip(db, p.id, d.id)

    # Жагсаалтаас алга болсон, өөр жолооч авч чадахгүй
    assert client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json() == []

    move(client, d, route_id, 2_000)
    assert client.post(f"/rides/bookings/{booking['id']}/board", headers=auth(p)).json()["status"] == "boarded"
    for x in (4_000, 6_000, 8_000):
        move(client, d, route_id, x)
    done = client.post(f"/driver/bookings/{booking['id']}/alight", headers=auth(d)).json()
    assert done["status"] == "completed" and done["fare_total"] == 10_000 and done["refund"] == 0
    fee = 500 + 350  # 10,000₮: эхний 5,000-аас 10%, дараагийн 5,000-аас 7%
    assert done["driver_earned"] == 10_000 - fee
    assert wallet(db, p) == (90_000, 0)
    assert wallet(db, d) == (10_000 - fee, 0)
    assert not shares_trip(db, p.id, d.id)  # аялал дууссаны дараа зураг нээлттэй байхгүй
    assert ledger.check_integrity(db) == CLEAN


def test_price_must_meet_driver_ask(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start(client, d, v, price_factor=2.0)  # жолооч өндөр үнэ тавьсан
    request(client, p, 2_000, 8_000, bid=3_000)
    assert client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json() == []
    # Зорчигч өндөр үнэ санал болговол таарна
    client.post(f"/rides/requests/{client.get('/rides/requests/current', headers=auth(p)).json()['id']}/cancel", headers=auth(p))
    request(client, p, 2_000, 8_000, bid=20_000)
    assert len(client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()) == 1


def test_geometry_filters(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p1, p2, p3 = (passenger(db, make_user, settings, name=n) for n in ("А", "Б", "В"))
    route_id = start(client, d, v)
    move(client, d, route_id, 3_000)
    request(client, p1, 1_000, 8_000)  # жолооч аль хэдийн өнгөрсөн
    client.post("/rides/requests", headers=auth(p2), json={"pickup": at(5_000, 900), "dropoff": at(9_000), "bid_seat_price": 10_000})
    request(client, p3, 8_000, 5_000)  # эсрэг чиглэл
    assert client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json() == []


def test_higher_bid_listed_first(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    low, high = passenger(db, make_user, settings, name="Бага"), passenger(db, make_user, settings, name="Өндөр")
    route_id = start(client, d, v)
    request(client, low, 2_000, 8_000, bid=9_000)
    request(client, high, 3_000, 8_000, bid=12_000)
    names = [r["passenger_first_name"] for r in client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()]
    assert names == ["Өндөр", "Бага"]


def test_insufficient_funds_asks_for_topup(client, db, make_user, settings):
    p = passenger(db, make_user, settings, money=4_000)
    r = request(client, p, 2_000, 8_000, bid=10_000)
    assert r.status_code == 402 and r.json()["detail"]["shortfall"] == 6_000


def test_unverified_passenger_cannot_request(client, make_user):
    p = make_user()
    assert request(client, p, 2_000, 8_000).status_code == 403


def test_group_booking_takes_seats_and_pays_for_all(client, db, make_user, settings):
    d, v = driver(db, make_user, settings, seats=3)
    p = passenger(db, make_user, settings)
    route_id = start(client, d, v)
    request(client, p, 2_000, 8_000, bid=6_000, seats=4)
    assert client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json() == []  # 3 суудалтай
    client.post(f"/rides/requests/{client.get('/rides/requests/current', headers=auth(p)).json()['id']}/cancel", headers=auth(p))
    request(client, p, 2_000, 8_000, bid=6_000, seats=3)
    rid = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    b = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid}).json()
    assert client.get("/driver/routes/current", headers=auth(d)).json()["seats_free"] == 0
    move(client, d, route_id, 2_000)
    client.post(f"/rides/bookings/{b['id']}/board", headers=auth(p))
    move(client, d, route_id, 8_000)
    done = client.post(f"/rides/bookings/{b['id']}/alight", headers=auth(p)).json()
    assert done["fare_total"] == 18_000  # гэр бүл 3 суудал, суудал бүр 6,000₮


def test_headcount_increase_needs_funds_and_seats(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings, money=20_000)
    route_id = start(client, d, v)
    request(client, p, 2_000, 8_000, bid=9_000)
    rid = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    b = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid}).json()
    r = client.post(f"/driver/bookings/{b['id']}/headcount", headers=auth(d), json={"seats": 3})
    assert r.status_code == 402 and r.json()["detail"]["shortfall"] == 7_000
    assert wallet(db, p) == (20_000, 9_000)  # амжилтгүй үед хуучин түгжээ хэвээр
    r = client.post(f"/driver/bookings/{b['id']}/headcount", headers=auth(d), json={"seats": 2})
    assert r.json()["seats"] == 2 and wallet(db, p) == (20_000, 18_000)
    assert client.get("/driver/routes/current", headers=auth(d)).json()["seats_free"] == 2


def test_later_passenger_lowers_earlier_fare(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    a, b = passenger(db, make_user, settings, name="А"), passenger(db, make_user, settings, name="Б")
    route_id = start(client, d, v)
    request(client, a, 1_000, 9_000, bid=12_000)
    ra = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    ba = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": ra}).json()
    move(client, d, route_id, 1_000)
    client.post(f"/rides/bookings/{ba['id']}/board", headers=auth(a))

    move(client, d, route_id, 3_000)
    request(client, b, 5_000, 11_000, bid=12_000)
    rb = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    bb = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rb}).json()
    move(client, d, route_id, 5_000)
    client.post(f"/rides/bookings/{bb['id']}/board", headers=auth(b))
    move(client, d, route_id, 9_000)
    done_a = client.post(f"/rides/bookings/{ba['id']}/alight", headers=auth(a)).json()
    # А: 8 км-ийн 4 км нь ганцаараа, 4 км нь хоёр хүнтэй
    expected = round(12_000 * 0.5 + 12_000 * 0.5 * 0.55 / 0.70)
    assert abs(done_a["fare_total"] - expected) <= 15 and done_a["refund"] > 0
    move(client, d, route_id, 11_000)
    done_b = client.post(f"/rides/bookings/{bb['id']}/alight", headers=auth(b)).json()
    # Б: тохиролцох үед машинд 2 хүн байсан, дараа нь ганцаараа үлдсэн ч үнэ нэмэгдэхгүй
    assert done_b["fare_total"] == 12_000
    assert ledger.check_integrity(db) == CLEAN


def test_early_exit_charges_distance_travelled(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start(client, d, v)
    request(client, p, 1_000, 11_000, bid=15_000)
    rid = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    b = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid}).json()
    move(client, d, route_id, 1_000)
    client.post(f"/rides/bookings/{b['id']}/board", headers=auth(p))
    move(client, d, route_id, 5_000)
    # Зорчигч өөрийн утасны байршлаар буулаа гэж дарав (жолоочийн сүүлийн GPS-ээс урагш)
    done = client.post(f"/rides/bookings/{b['id']}/alight", headers=auth(p), json={"position": at(5_000, 20)}).json()
    assert abs(done["fare_total"] - 6_000) <= 30 and done["refund"] == 15_000 - done["fare_total"]


def test_cancellations(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start(client, d, v)
    request(client, p, 2_000, 8_000)
    rid = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    b = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid}).json()
    # Жолооч цуцалбал захиалга дахин нээгдэж, мөнгө түгжээтэй хэвээр
    assert client.post(f"/driver/bookings/{b['id']}/cancel", headers=auth(d)).json()["cancelled_by"] == "driver"
    assert client.get("/rides/requests/current", headers=auth(p)).json()["status"] == "open"
    assert wallet(db, p) == (100_000, 10_000)
    # Цуцалсан жолоочид дахин харагдахгүй, авч чадахгүй; өөр жолооч авч болно
    assert client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json() == []
    b2 = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid})
    assert b2.status_code == 409
    d2, v2 = driver(db, make_user, settings, plate="5555УБА")
    r2 = start(client, d2, v2)
    assert [r["request_id"] for r in client.get(f"/driver/routes/{r2}/requests", headers=auth(d2)).json()] == [rid]
    # Зорчигч цуцалбал бүх мөнгө буцна
    client.post(f"/rides/requests/{rid}/cancel", headers=auth(p))
    assert wallet(db, p) == (100_000, 0)


def test_cannot_board_twice_or_cancel_after_boarding(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start(client, d, v)
    request(client, p, 2_000, 8_000)
    rid = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()[0]["request_id"]
    b = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid}).json()
    client.post(f"/rides/bookings/{b['id']}/board", headers=auth(p))
    assert client.post(f"/rides/bookings/{b['id']}/board", headers=auth(p)).status_code == 409
    assert client.post(f"/rides/bookings/{b['id']}/cancel", headers=auth(p)).status_code == 409
    other = passenger(db, make_user, settings, name="Гадны")
    assert client.post(f"/rides/bookings/{b['id']}/alight", headers=auth(other)).status_code == 404


def test_nearby_matches_get_different_tunes(client, db, make_user, settings):
    pairs = []
    for i in range(3):
        d, v = driver(db, make_user, settings, plate=f"12{i}0УБА")
        p = passenger(db, make_user, settings, name=f"З{i}")
        route_id = start(client, d, v)
        request(client, p, 2_000 + i * 50, 8_000)
        pairs.append((d, route_id))
    tunes = []
    for i, (d, route_id) in enumerate(pairs):
        reqs = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()
        mine = [r for r in reqs if r["passenger_first_name"] == f"З{i}"][0]
        tunes.append(client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": mine["request_id"]}).json()["tune"])
    assert len(set(tunes)) == 3


def test_two_drivers_race_for_one_passenger(client, db, make_user, settings):
    (d1, v1), (d2, v2) = driver(db, make_user, settings, plate="1111УБА"), driver(db, make_user, settings, plate="2222УБА")
    p = passenger(db, make_user, settings)
    r1, r2 = start(client, d1, v1), start(client, d2, v2)
    request(client, p, 2_000, 8_000)
    rid = client.get(f"/driver/routes/{r1}/requests", headers=auth(d1)).json()[0]["request_id"]
    barrier, codes = threading.Barrier(2), []

    def go(d, route_id):
        c = TestClient(app)
        barrier.wait()
        codes.append(c.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid}).status_code)

    ts = [threading.Thread(target=go, args=a) for a in ((d1, r1), (d2, r2))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [201, 409]


def test_ending_route_settles_riders_and_releases_waiting(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    a, b = passenger(db, make_user, settings, name="А"), passenger(db, make_user, settings, name="Б")
    route_id = start(client, d, v)
    request(client, a, 1_000, 9_000, bid=12_000)
    request(client, b, 6_000, 11_000)
    for r in client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json():
        client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": r["request_id"]})
    ba = client.get("/rides/requests/current", headers=auth(a)).json()["booking"]["id"]
    move(client, d, route_id, 1_000)
    client.post(f"/rides/bookings/{ba}/board", headers=auth(a))
    move(client, d, route_id, 5_000)
    assert client.post(f"/driver/routes/{route_id}/end", headers=auth(d)).json()["status"] == "ended"
    assert client.get(f"/rides/bookings/{ba}", headers=auth(a)).json()["status"] == "completed"
    assert client.get("/rides/requests/current", headers=auth(b)).json()["status"] == "open"  # Б дахин хүлээнэ
    assert ledger.check_integrity(db) == CLEAN


def test_driver_must_be_verified_and_use_own_car(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    stranger = passenger(db, make_user, settings)
    r = client.post("/driver/routes", headers=auth(stranger), json={"vehicle_id": v.id, "polyline": ROUTE})
    assert r.status_code == 403
    start(client, d, v)
    assert client.post("/driver/routes", headers=auth(d), json={"vehicle_id": v.id, "polyline": ROUTE}).status_code == 409


def test_market_candles_and_quote(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    route_id = start(client, d, v)
    for i, bid in enumerate((9_000, 11_000, 10_000)):
        p = passenger(db, make_user, settings, name=f"П{i}")
        request(client, p, 2_000 + i * 100, 8_000, bid=bid)
        rid = [r for r in client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json() if r["passenger_first_name"] == f"П{i}"][0]["request_id"]
        client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": rid})
    c = client.get("/market/candles", params={"interval": "1h", "count": 2}).json()
    candle = c["candles"][-1]
    assert candle["deals"] == 3 and candle["low"] <= candle["open"] <= candle["high"]
    assert candle["high"] > candle["low"]
    q = client.get(
        "/rides/quote",
        params={"pickup_lat": at(2_000)["lat"], "pickup_lng": at(2_000)["lng"], "dropoff_lat": at(8_000)["lat"], "dropoff_lng": at(8_000)["lng"]},
    ).json()
    assert q["recent_deals"] == 3 and q["band_low"] < q["base_seat_price"] < q["band_high"]
    # 3 хэлцэл цөөн тул лавлах үнэ үндсэн тарифт ойр хэвээр
    assert abs(q["market_index"] - 1.0) < 0.5
