"""Барааны оноо, эвдрэлийн статистик.

Цөөн сэтгэгдэлтэй бараа азаар дээгүүр гарахаас сэргийлж Байесын дундажийг
ашиглана: сэтгэгдэл нэмэгдэх тусам бодит өгөгдөл рүү ойртоно.
"""
from __future__ import annotations

import math
from collections import Counter
from statistics import median

PRIOR_RATING = 3.0
PRIOR_RATING_WEIGHT = 3
PRIOR_FAIL_RATE = 0.25
PRIOR_FAIL_WEIGHT = 3


def normalize_part(s: str | None) -> str:
    return " ".join(str(s or "").lower().split())


def confidence(n: int) -> str:
    if n >= 30:
        return "high"
    if n >= 8:
        return "medium"
    if n >= 1:
        return "low"
    return "none"


def compute_stats(reviews: list[dict]) -> dict:
    n = len(reviews)
    sum_rating = sum(r["rating"] for r in reviews)
    broken = [r for r in reviews if r.get("broke")]

    bayes_rating = (PRIOR_RATING * PRIOR_RATING_WEIGHT + sum_rating) / (PRIOR_RATING_WEIGHT + n)
    bayes_fail = (PRIOR_FAIL_RATE * PRIOR_FAIL_WEIGHT + len(broken)) / (PRIOR_FAIL_WEIGHT + n)
    # 0–100: сэтгэл ханамж 50% + эвдрэхгүй байх магадлал 50%. Сэтгэгдэлгүй бол оноо өгөхгүй.
    score = None if n == 0 else round(100 * (0.5 * (bayes_rating - 1) / 4 + 0.5 * (1 - bayes_fail)))

    counts = Counter(p for p in (normalize_part(r.get("broken_part")) for r in broken) if p)
    top_parts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    fail_months = [r["months_used"] for r in broken if r.get("months_used") is not None]
    answered = [r for r in reviews if r.get("would_buy_again") in (0, 1)]

    return {
        "review_count": n,
        "avg_rating": sum_rating / n if n else None,
        "fail_rate": len(broken) / n if n else None,
        "broken_count": len(broken),
        "score": score,
        "confidence": confidence(n),
        "top_broken_parts": [
            {"part": p, "count": c, "share": c / len(broken)} for p, c in top_parts
        ],
        "median_months_to_fail": median(fail_months) if fail_months else None,
        "buy_again_rate": (
            sum(1 for r in answered if r["would_buy_again"] == 1) / len(answered) if answered else None
        ),
        "distribution": [sum(1 for r in reviews if r["rating"] == s) for s in range(1, 6)],
    }


def value_index(score: int | None, price: int | None, category_median_price: float | None) -> float | None:
    """1.0 = ангиллын дундаж, >1 = үнэдээ хүрсэн илүү сайн сонголт."""
    if score is None or not price or not category_median_price:
        return None
    return round((score / 60) * math.sqrt(category_median_price / price), 2)
