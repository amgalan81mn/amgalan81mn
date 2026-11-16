"""Газарзүйн тооцоолол. Google-ээс авсан маршрутын цэгүүд дээр ажиллана.

Одоогоор цэвэр Python. Хэрэглэгч олширвол PostGIS-ийн индекс рүү шилжүүлнэ.
"""

import math
from dataclasses import dataclass

EARTH_R = 6_371_000.0

Point = tuple[float, float]  # (lat, lng)


def haversine_m(a: Point, b: Point) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def cumulative(points: list[Point]) -> list[float]:
    out = [0.0]
    for a, b in zip(points, points[1:]):
        out.append(out[-1] + haversine_m(a, b))
    return out


@dataclass(frozen=True)
class Projection:
    along_m: float  # маршрутын эхнээс хэдэн метрт
    offset_m: float  # маршрутаас хэр хол
    point: Point  # маршрут дээрх хамгийн ойр цэг


def project(points: list[Point], cum: list[float], p: Point, min_along: float = 0.0) -> Projection | None:
    """`p`-г маршрут дээр буулгана. `min_along`-оос өмнөх хэсгийг тооцохгүй (жолооч өнгөрсөн зам)."""
    best: Projection | None = None
    for i, (a, b) in enumerate(zip(points, points[1:])):
        seg_len = cum[i + 1] - cum[i]
        if cum[i + 1] < min_along:
            continue
        # a цэгийг төв болгосон хавтгай координат (метр)
        k = math.cos(math.radians(a[0]))
        bx, by = math.radians(b[1] - a[1]) * k * EARTH_R, math.radians(b[0] - a[0]) * EARTH_R
        px, py = math.radians(p[1] - a[1]) * k * EARTH_R, math.radians(p[0] - a[0]) * EARTH_R
        denom = bx * bx + by * by
        t = 0.0 if denom == 0 else max(0.0, min(1.0, (px * bx + py * by) / denom))
        if seg_len > 0:
            t = max(t, (min_along - cum[i]) / seg_len)
            t = min(t, 1.0)
        dx, dy = px - t * bx, py - t * by
        offset = math.hypot(dx, dy)
        if best is None or offset < best.offset_m:
            point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            best = Projection(cum[i] + t * seg_len, offset, point)
    return best
