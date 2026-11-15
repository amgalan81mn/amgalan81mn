"""Үнийн тооцоолол. Өгөгдлийн сан, сүлжээнээс хамааралгүй цэвэр функцууд.

Бүх мөнгөн дүн бүхэл төгрөгөөр. Зайг метрээр авна (бутархай км-ийн алдаанаас зайлсхийх).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .config import Settings


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def shared_factor(occupancy: int, settings: Settings) -> Decimal:
    """Машинд `occupancy` зорчигч байхад нэг суудлын үнэ таксины үнийн хэдэн хувь болох."""
    if occupancy < 1:
        raise ValueError("occupancy must be >= 1")
    factors = settings.shared_factors
    key = min(occupancy, max(factors))
    while key not in factors:  # хүснэгтэд завсар байвал доош хамгийн ойрыг авна
        key -= 1
    return Decimal(str(factors[key]))


def base_seat_price(distance_m: int, occupancy: int, settings: Settings) -> int:
    """Үндсэн тарифаар нэг суудлын лавлах үнэ."""
    if distance_m <= 0:
        raise ValueError("distance must be positive")
    raw = Decimal(settings.taxi_rate_per_km) * Decimal(distance_m) / 1000
    return max(settings.min_fare, _round(raw * shared_factor(occupancy, settings)))


def price_band(distance_m: int, occupancy: int, settings: Settings) -> tuple[int, int]:
    """Лааны гол: ердийн үнийн доод, дээд хязгаар. Үүнээс гадуур үнэ тавихыг хориглохгүй."""
    base = Decimal(base_seat_price(distance_m, occupancy, settings))
    low = max(settings.min_fare, _round(base * Decimal(str(settings.band_low))))
    high = _round(base * Decimal(str(settings.band_high)))
    return low, high


def commission(amount: int, settings: Settings) -> int:
    """Шатлалтай шимтгэл. Хувийг дүнгийн хэсэг тус бүрд тооцно (зааг дээр гажиг гарахгүй)."""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    total = Decimal(0)
    lower = 0
    for upper, rate in settings.commission_brackets:
        if amount <= lower:
            break
        top = amount if upper is None else min(amount, upper)
        total += Decimal(top - lower) * Decimal(str(rate))
        if upper is None:
            break
        lower = upper
    return min(amount, _round(total))


@dataclass(frozen=True)
class Segment:
    """Аяллын нэг хэсэг: энэ зайд машинд нийт хэдэн суудал (апп-аар) эзлэгдсэн байсан."""

    distance_m: int
    occupancy: int


@dataclass(frozen=True)
class Fare:
    per_seat: int
    total: int  # зорчигчийн төлөх нийт дүн (бүх суудал)
    refund: int  # түгжсэн дүнгээс буцах хэсэг
    travelled_m: int
    early_exit: bool


def final_fare(
    *,
    agreed_seat_price: int,
    agreed_distance_m: int,
    occupancy_at_agreement: int,
    seats: int,
    segments: list[Segment],
    settings: Settings,
) -> Fare:
    """Буух үеийн эцсийн төлбөр.

    - `agreed_seat_price` бол дээд хязгаар: үнэ зөвхөн буурна.
    - Хамт явсан хэсэгт суудлын тоо нэмэгдсэн бол тэр хэсгийн км-ийн үнэ
      shared_factor-ийн харьцаагаар буурна.
    - Тохирсон зайд хүрээгүй буусан бол явсан зайгаар тооцно, гэхдээ
      `early_exit_min_fraction`-аас доош буухгүй.
    """
    if agreed_seat_price < 0 or agreed_distance_m <= 0 or seats < 1:
        raise ValueError("invalid agreement")
    if occupancy_at_agreement < seats:
        raise ValueError("occupancy at agreement must include this booking's seats")

    f0 = shared_factor(occupancy_at_agreement, settings)
    price = Decimal(agreed_seat_price)
    remaining = agreed_distance_m  # тохирсон зайнаас илүү явсан ч нэмж авахгүй
    cost = Decimal(0)
    travelled = 0
    for seg in segments:
        if seg.distance_m < 0:
            raise ValueError("segment distance must be >= 0")
        if remaining <= 0:
            break
        d = min(seg.distance_m, remaining)
        remaining -= d
        travelled += d
        ratio = min(Decimal(1), shared_factor(max(seg.occupancy, seats), settings) / f0)
        cost += price * Decimal(d) / Decimal(agreed_distance_m) * ratio

    early = travelled < agreed_distance_m
    per_seat = _round(cost)
    if early:
        floor = _round(price * Decimal(str(settings.early_exit_min_fraction)))
        per_seat = max(per_seat, floor)
    per_seat = min(per_seat, agreed_seat_price)
    total = per_seat * seats
    return Fare(
        per_seat=per_seat,
        total=total,
        refund=agreed_seat_price * seats - total,
        travelled_m=travelled,
        early_exit=early,
    )
