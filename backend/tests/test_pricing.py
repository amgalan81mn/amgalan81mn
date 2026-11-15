import pytest

from app import pricing
from app.pricing import Segment


def test_shared_factor_drops_as_car_fills(settings):
    factors = [pricing.shared_factor(n, settings) for n in range(1, 7)]
    assert factors == sorted(factors, reverse=True)
    assert factors[4] == factors[3]  # хүснэгтээс хэтэрсэн тоо сүүлийн утгыг авна


def test_each_passenger_pays_less_but_driver_earns_more(settings):
    taxi = settings.taxi_rate_per_km * 10
    seat = [pricing.base_seat_price(10_000, n, settings) for n in (1, 2, 3, 4)]
    assert all(p < taxi for p in seat)  # хүн бүр таксинаас хямд
    totals = [p * n for p, n in zip(seat, (1, 2, 3, 4))]
    assert totals == sorted(totals)
    assert totals[1] > taxi  # хоёр хүнээс эхлээд жолооч таксинаас илүү олно


def test_min_fare_applies_to_short_trips(settings):
    assert pricing.base_seat_price(300, 1, settings) == settings.min_fare


def test_band_surrounds_base(settings):
    base = pricing.base_seat_price(10_000, 1, settings)
    low, high = pricing.price_band(10_000, 1, settings)
    assert low < base < high


def test_commission_examples(settings):
    assert pricing.commission(0, settings) == 0
    assert pricing.commission(5_000, settings) == 500  # 10%
    assert pricing.commission(20_000, settings) == 500 + 1_050  # + 15,000-ийн 7%
    assert pricing.commission(30_000, settings) == 500 + 1_050 + 500  # + 10,000-ийн 5%


def test_commission_has_no_cliff_and_rate_falls(settings):
    prev_net, prev_rate = -1, 1.0
    for amount in range(100, 60_000, 100):
        fee = pricing.commission(amount, settings)
        net = amount - fee
        assert net > prev_net  # их дүнтэй аялал жолоочид үргэлж илүү мөнгө өгнө
        assert fee / amount <= prev_rate + 1e-9  # дүн өсөх тусам хувь буурна
        prev_net, prev_rate = net, fee / amount


def _fare(settings, segments, *, price=7_000, dist=10_000, occ0=1, seats=1):
    return pricing.final_fare(
        agreed_seat_price=price,
        agreed_distance_m=dist,
        occupancy_at_agreement=occ0,
        seats=seats,
        segments=segments,
        settings=settings,
    )


def test_full_trip_alone_pays_agreed_price(settings):
    fare = _fare(settings, [Segment(10_000, 1)])
    assert (fare.total, fare.refund, fare.early_exit) == (7_000, 0, False)


def test_price_drops_for_km_shared_with_a_later_passenger(settings):
    # 10 км-ийн сүүлийн 6 км-т хоёр дахь зорчигч суусан
    fare = _fare(settings, [Segment(4_000, 1), Segment(6_000, 2)])
    # 4 км бүтэн үнээр + 6 км 0.55/0.70 харьцаагаар
    assert fare.total == round(7_000 * 0.4 + 7_000 * 0.6 * 0.55 / 0.70)
    assert fare.refund == 7_000 - fare.total > 0


def test_price_never_rises_when_others_leave(settings):
    # Гурван хүнтэй байхад тохирсон, дараа нь ганцаараа үлдсэн
    fare = _fare(settings, [Segment(5_000, 3), Segment(5_000, 1)], occ0=3)
    assert fare.total == 7_000


def test_early_exit_charged_by_distance_travelled(settings):
    # 10 км-т 6,000₮ тохироод 4 км яваад буусан -> 2,400₮
    fare = _fare(settings, [Segment(4_000, 1)], price=6_000)
    assert (fare.total, fare.refund, fare.early_exit) == (2_400, 3_600, True)


def test_early_exit_has_a_floor(settings):
    fare = _fare(settings, [Segment(500, 1)], price=6_000)
    assert fare.total == round(6_000 * settings.early_exit_min_fraction)


def test_driving_past_the_agreed_distance_costs_nothing_extra(settings):
    fare = _fare(settings, [Segment(25_000, 1)])
    assert fare.total == 7_000 and fare.travelled_m == 10_000


def test_group_booking_pays_per_seat(settings):
    # Нэг хүн апп-аар 4 суудал авсан: суудал бүр тохирсон үнээр, жолооч бүгдийг авна
    fare = _fare(settings, [Segment(10_000, 4)], price=4_000, occ0=4, seats=4)
    assert (fare.per_seat, fare.total) == (4_000, 16_000)


def test_never_exceeds_the_hold(settings):
    for segs in ([Segment(3_333, 1), Segment(3_333, 2), Segment(3_334, 5)], [Segment(1, 1)], []):
        fare = _fare(settings, segs, price=6_999, seats=3, occ0=3)
        assert 0 <= fare.total <= 6_999 * 3 and fare.refund >= 0


def test_rejects_bad_input(settings):
    with pytest.raises(ValueError):
        _fare(settings, [Segment(1_000, 1)], seats=2, occ0=1)
    with pytest.raises(ValueError):
        pricing.base_seat_price(0, 1, settings)
