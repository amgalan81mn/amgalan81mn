'use strict';
// Барааны үнэлгээ, эвдрэлийн статистик, жагсаалт.
//
// Цөөн сэтгэгдэлтэй бараа "азаар" дээгүүр гарахаас сэргийлж Байесын дундажийг
// ашиглана: сэтгэгдэл бүр нэмэгдэх тусам бодит өгөгдөл рүү ойртоно.

const PRIOR_RATING = 3.0;   // сэтгэгдэлгүй барааны "дунд зэрэг" гэсэн таамаг
const PRIOR_RATING_WEIGHT = 3;
const PRIOR_FAIL_RATE = 0.25;
const PRIOR_FAIL_WEIGHT = 3;

function normalizePart(s) {
  return String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

/**
 * @param {Array<{rating:number, broke:number|boolean, broken_part?:string,
 *   months_used?:number|null, would_buy_again?:number|null}>} reviews
 */
function computeStats(reviews) {
  const n = reviews.length;
  const sumRating = reviews.reduce((a, r) => a + r.rating, 0);
  const broken = reviews.filter((r) => r.broke);
  const avgRating = n ? sumRating / n : null;
  const failRate = n ? broken.length / n : null;

  const bayesRating =
    (PRIOR_RATING * PRIOR_RATING_WEIGHT + sumRating) / (PRIOR_RATING_WEIGHT + n);
  const bayesFail =
    (PRIOR_FAIL_RATE * PRIOR_FAIL_WEIGHT + broken.length) / (PRIOR_FAIL_WEIGHT + n);

  // 0–100 оноо: сэтгэл ханамж 50%, найдвартай байдал (эвдрэхгүй) 50%.
  // Сэтгэгдэлгүй бараанд оноо өгөхгүй (хоосон оноо төөрөгдүүлнэ).
  const score = n === 0 ? null : Math.round(100 * (0.5 * ((bayesRating - 1) / 4) + 0.5 * (1 - bayesFail)));

  // Хамгийн их эвдэрдэг хэсгүүд
  const partCounts = new Map();
  for (const r of broken) {
    const p = normalizePart(r.broken_part);
    if (!p) continue;
    partCounts.set(p, (partCounts.get(p) || 0) + 1);
  }
  const topBrokenParts = [...partCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 5)
    .map(([part, count]) => ({ part, count, share: count / broken.length }));

  const failMonths = broken.map((r) => r.months_used).filter((m) => Number.isFinite(m));
  const medianMonthsToFail = failMonths.length ? median(failMonths) : null;

  const answeredAgain = reviews.filter((r) => r.would_buy_again === 0 || r.would_buy_again === 1);
  const buyAgainRate = answeredAgain.length
    ? answeredAgain.filter((r) => r.would_buy_again === 1).length / answeredAgain.length
    : null;

  const distribution = [1, 2, 3, 4, 5].map((s) => reviews.filter((r) => r.rating === s).length);

  return {
    reviewCount: n,
    avgRating,
    failRate,
    brokenCount: broken.length,
    score,
    confidence: confidenceLabel(n),
    topBrokenParts,
    medianMonthsToFail,
    buyAgainRate,
    distribution,
  };
}

function median(arr) {
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function confidenceLabel(n) {
  if (n >= 30) return 'high';
  if (n >= 8) return 'medium';
  if (n >= 1) return 'low';
  return 'none';
}

/**
 * Үнэ цэнэ: ижил ангиллын дундаж үнэтэй харьцуулахад онооны хэмжээ.
 * 1.0 = дундаж, >1 = үнэдээ хүрсэн илүү сайн сонголт.
 */
function valueIndex(score, price, categoryMedianPrice) {
  if (score === null || !price || !categoryMedianPrice) return null;
  return Math.round((score / 60) * Math.sqrt(categoryMedianPrice / price) * 100) / 100;
}

function cosine(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length || !a.length) return null;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (!na || !nb) return null;
  return dot / Math.sqrt(na * nb);
}

module.exports = { computeStats, valueIndex, cosine, median, normalizePart };
