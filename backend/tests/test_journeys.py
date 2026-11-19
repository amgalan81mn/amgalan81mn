"""Аян: түгжрэлд бууж явганаар давж, өөр машинаар үргэлжлүүлэх."""

from datetime import timedelta

from app import ledger, rides
from app.models import Booking, JourneyPing, TrackPoint

from .test_rides import CLEAN, at, auth, driver, passenger, wallet


def line(x0: int, x1: int) -> list[list[float]]:
    return [[at(x)["lat"], at(x)["lng"]] for x in range(x0, x1 + 1, 500)]


def start_on(client, d, v, x0, x1, **kw) -> str:
    r = client.post("/driver/routes", headers=auth(d), json={"vehicle_id": v.id, "polyline": line(x0, x1), **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def pos(client, d, route_id, x):
    assert client.post(f"/driver/routes/{route_id}/position", headers=auth(d), json=at(x, 15)).status_code == 200


def journey(client, p):
    return client.get("/rides/journeys/current", headers=auth(p)).json()


def begin(client, p, pick_x=1_000, drop_x=11_000, budget=20_000):
    r = client.post(
        "/rides/requests",
        headers=auth(p),
        json={"pickup": at(pick_x, 60), "dropoff": at(drop_x, 150), "bid_seat_price": budget, "multi_leg": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


def take(client, d, route_id):
    reqs = client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()
    assert reqs, "жолоочид зорчигч харагдах ёстой"
    r = client.post(f"/driver/routes/{route_id}/accept", headers=auth(d), json={"request_id": reqs[0]["request_id"]})
    assert r.status_code == 201, r.text
    return reqs[0], r.json()


def age_completion(db, booking_id, seconds=150):
    b = db.get(Booking, booking_id)
    b.completed_at -= timedelta(seconds=seconds)
    db.commit()
    return b.completed_at


def test_hop_through_a_jam_to_the_destination(client, db, make_user, settings):
    (da, va), (dbb, vb) = driver(db, make_user, settings, plate="1111УБА"), driver(db, make_user, settings, plate="2222УБА")
    p = passenger(db, make_user, settings)
    ra = start_on(client, da, va, 0, 6_000)  # А зөвхөн 6 км хүртэл явна

    begin(client, p)
    assert wallet(db, p) == (100_000, 20_000)  # бүх аяны төсөв нэг удаа түгжигдэв
    j = journey(client, p)
    assert j["request"]["bid_seat_price"] == 20_000 and j["drivers_ahead"]["count"] == 1

    # А очих газар хүртэл хүргэхгүй ч ойртуулна: ойртуулсан хувиар үнэ санал болгоно
    offer, booking = take(client, da, ra)
    assert offer["multi_leg"] and 9_000 <= booking["agreed_seat_price"] <= 11_000
    pos(client, da, ra, 1_000)
    client.post(f"/rides/bookings/{booking['id']}/board", headers=auth(p))
    pos(client, da, ra, 4_500)

    # Түгжрэл: сүүлийн минутад машин хөдлөөгүй (өмнөх цэгүүдийг 5 минутын өмнөх болгоно)
    now = rides._now()
    for tp in db.query(TrackPoint).filter(TrackPoint.route_id == ra).all():
        tp.at = now - timedelta(minutes=5)
    for s in (58, 40, 20, 2):
        db.add(TrackPoint(route_id=ra, lat=at(4_500)["lat"], lng=at(4_500)["lng"], at=now - timedelta(seconds=s)))
    db.commit()
    assert client.get(f"/rides/bookings/{booking['id']}", headers=auth(p)).json()["jammed"] is True

    # Түгжрэлийн цаана Б машин хөдөлж байна: зорчигчид «урд чинь 1 жолооч» харагдана
    rb = start_on(client, dbb, vb, 5_000, 12_000)
    assert journey(client, p)["drivers_ahead"]["count"] == 1

    # Зорчигч «Буулаа»: явсан хэсгийн мөнгө л А-д очно, доод хувь авахгүй
    done = client.post(f"/rides/bookings/{booking['id']}/alight", headers=auth(p), json={"position": at(4_500, 10)}).json()
    leg1 = done["fare_total"]
    assert abs(leg1 - round(booking["agreed_seat_price"] * 3_500 / booking["agreed_distance_m"])) <= 30
    assert done["refund"] == booking["agreed_seat_price"] - leg1

    # Дараагийн хүсэлт автоматаар үүссэн, үлдсэн төсөв түгжээтэй хэвээр
    j = journey(client, p)
    assert j["status"] == "active" and len(j["legs"]) == 1 and j["request"]["status"] == "open"
    assert j["budget_left"] == 20_000 - leg1
    assert wallet(db, p) == (100_000 - leg1, 20_000 - leg1)

    # Явган түгжрэлийг давж байна: суух цэг зорчигчийг дагаж шилжинэ
    j = client.post(f"/rides/journeys/{j['id']}/position", headers=auth(p), json=at(5_400, 30)).json()
    assert abs(j["request"]["pickup"]["lng"] - at(5_400)["lng"]) < 1e-9

    # Б авна: үлдсэн замыг бүтэн хүргэх тул үлдсэн төсвөөр
    offer2, booking2 = take(client, dbb, rb)
    assert booking2["agreed_seat_price"] == j["request"]["bid_seat_price"]
    mine = journey(client, p)["request"]["booking"]
    assert (mine["vehicle"]["plate"], mine["tune"]) == ("2222УБА", booking2["tune"])
    pos(client, dbb, rb, 5_500)
    client.post(f"/rides/bookings/{booking2['id']}/board", headers=auth(p))
    for x in (8_000, 11_000):
        pos(client, dbb, rb, x)
    done2 = client.post(f"/rides/bookings/{booking2['id']}/alight", headers=auth(p), json={"position": at(11_000, 120)}).json()

    j = journey(client, p)
    assert j["status"] == "finished" and len(j["legs"]) == 2
    paid = leg1 + done2["fare_total"]
    assert paid <= 20_000
    assert wallet(db, p) == (100_000 - paid, 0)  # үлдсэн нь буцсан
    assert ledger.check_integrity(db) == CLEAN


def test_riding_on_after_pressing_alight_is_caught(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start_on(client, d, v, 0, 12_000)
    begin(client, p)
    _, booking = take(client, d, route_id)
    pos(client, d, route_id, 1_000)
    client.post(f"/rides/bookings/{booking['id']}/board", headers=auth(p))
    pos(client, d, route_id, 1_500)
    done = client.post(f"/rides/bookings/{booking['id']}/alight", headers=auth(p)).json()
    assert abs(done["fare_total"] - max(500, round(booking["agreed_seat_price"] * 500 / booking["agreed_distance_m"]))) <= 5

    # Буулаа гэж дараад тэр машинаараа үргэлжлүүлэв: 2 минутын дараа хоёр утас хамт 3 км урагшилсан
    t = age_completion(db, booking["id"]) + timedelta(seconds=130)
    db.add(TrackPoint(route_id=route_id, lat=at(4_500)["lat"], lng=at(4_500)["lng"], at=t))
    j = journey(client, p)
    db.add(JourneyPing(journey_id=j["id"], lat=at(4_500, 20)["lat"], lng=at(4_500, 20)["lng"], at=t))
    db.commit()
    client.post(f"/rides/journeys/{j['id']}/position", headers=auth(p), json=at(4_600, 20))

    db.expire_all()
    b = db.get(Booking, booking["id"])
    floor = round(booking["agreed_seat_price"] * settings.early_exit_min_fraction)
    assert b.hop_check == "suspect" and b.fare_total == floor  # эрт буусны доод төлбөр нэмж суутгагдав
    assert client.get("/admin/hop-suspects", headers=auth(p)).status_code == 403
    assert ledger.check_integrity(db) == CLEAN


def test_walking_away_is_not_penalised(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start_on(client, d, v, 0, 12_000)
    begin(client, p)
    _, booking = take(client, d, route_id)
    pos(client, d, route_id, 1_000)
    client.post(f"/rides/bookings/{booking['id']}/board", headers=auth(p))
    pos(client, d, route_id, 2_000)
    fare = client.post(f"/rides/bookings/{booking['id']}/alight", headers=auth(p)).json()["fare_total"]

    t = age_completion(db, booking["id"]) + timedelta(seconds=130)
    db.add(TrackPoint(route_id=route_id, lat=at(5_000)["lat"], lng=at(5_000)["lng"], at=t))
    j = journey(client, p)
    db.add(JourneyPing(journey_id=j["id"], lat=at(2_300, 40)["lat"], lng=at(2_300, 40)["lng"], at=t))
    db.commit()
    # Жолоочийн байршил ирэхэд ч шалгалт ажиллана
    pos(client, d, route_id, 5_100)
    db.expire_all()
    b = db.get(Booking, booking["id"])
    assert b.hop_check == "ok" and b.fare_total == fare


def test_partial_rides_only_for_journeys(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    single, multi = passenger(db, make_user, settings, name="Нэг"), passenger(db, make_user, settings, name="Аян")
    route_id = start_on(client, d, v, 0, 6_000)
    client.post(
        "/rides/requests",
        headers=auth(single),
        json={"pickup": at(1_000, 60), "dropoff": at(11_000, 150), "bid_seat_price": 20_000},
    )
    begin(client, multi)
    names = [r["passenger_first_name"] for r in client.get(f"/driver/routes/{route_id}/requests", headers=auth(d)).json()]
    assert names == ["Аян"]  # ганц машинаар хүрэх хүнийг дутуу дөхүүлэх санал болгохгүй


def test_switching_cars_before_boarding_and_finishing_early(client, db, make_user, settings):
    (d1, v1), (d2, v2) = driver(db, make_user, settings, plate="1111УБА"), driver(db, make_user, settings, plate="2222УБА")
    p = passenger(db, make_user, settings)
    r1, r2 = start_on(client, d1, v1, 0, 12_000), start_on(client, d2, v2, 0, 12_000)
    begin(client, p)
    _, b1 = take(client, d1, r1)
    # Зорчигч энэ машинаас татгалзав: аян үргэлжилж, хүсэлт дахин нээгдэнэ (тэр жолоочид дахин харагдахгүй)
    client.post(f"/rides/bookings/{b1['id']}/cancel", headers=auth(p))
    assert journey(client, p)["request"]["status"] == "open"
    assert client.get(f"/driver/routes/{r1}/requests", headers=auth(d1)).json() == []
    _, b2 = take(client, d2, r2)
    assert client.post(f"/driver/bookings/{b2['id']}/headcount", headers=auth(d2), json={"seats": 2}).status_code == 409
    j = journey(client, p)
    # Аяныг гараар дуусгавал хүлээж буй машин цуцлагдаж, мөнгө бүтэн буцна
    assert client.post(f"/rides/journeys/{j['id']}/finish", headers=auth(p)).json()["status"] == "finished"
    assert client.get(f"/rides/bookings/{b2['id']}", headers=auth(p)).json()["status"] == "cancelled"
    assert wallet(db, p) == (100_000, 0)
    assert ledger.check_integrity(db) == CLEAN


def test_cannot_finish_while_on_board(client, db, make_user, settings):
    d, v = driver(db, make_user, settings)
    p = passenger(db, make_user, settings)
    route_id = start_on(client, d, v, 0, 12_000)
    begin(client, p)
    _, b = take(client, d, route_id)
    client.post(f"/rides/bookings/{b['id']}/board", headers=auth(p))
    j = journey(client, p)
    assert client.post(f"/rides/journeys/{j['id']}/finish", headers=auth(p)).status_code == 409
    # Жолооч маршрутаа дуусгавал зорчигч буулгагдаж, аян дараагийн машин хайж үргэлжилнэ
    pos(client, d, route_id, 4_000)
    client.post(f"/driver/routes/{route_id}/end", headers=auth(d))
    j = journey(client, p)
    assert j["status"] == "active" and j["request"]["status"] == "open" and len(j["legs"]) == 1
