'use strict';
const express = require('express');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { openDb } = require('./db');
const { computeStats, valueIndex, cosine, median } = require('./scoring');

const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const ALLOWED_IMAGE = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp' };
// Зураг "ижил бараа" гэж үзэх босго (хээний төрөл тус бүрээр)
const MATCH_THRESHOLD = { ml: 0.8, basic: 0.9 };

function createApp({ dbFile, uploadsDir }) {
  const db = openDb(dbFile);
  fs.mkdirSync(uploadsDir, { recursive: true });

  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '4mb' }));
  app.use('/uploads', express.static(uploadsDir, { maxAge: '7d' }));
  app.use(express.static(path.join(__dirname, '..', 'public')));

  // ---------- туслах функцууд ----------
  const q = (sql) => db.prepare(sql);

  function reviewsFor(productId) {
    return q('SELECT * FROM reviews WHERE product_id = ? ORDER BY created_at DESC, id DESC').all(productId);
  }

  function imagesFor(productId) {
    return q('SELECT id, file FROM product_images WHERE product_id = ? ORDER BY id').all(productId)
      .map((i) => ({ id: i.id, url: '/uploads/' + i.file }));
  }

  function categoryMedianPrice(category) {
    const prices = q('SELECT price FROM products WHERE category = ? AND price > 0').all(category).map((r) => r.price);
    return prices.length ? median(prices) : null;
  }

  function summarize(p, medianCache = new Map()) {
    const stats = computeStats(reviewsFor(p.id));
    if (!medianCache.has(p.category)) medianCache.set(p.category, categoryMedianPrice(p.category));
    const images = imagesFor(p.id);
    return {
      ...p,
      image: images[0]?.url || null,
      stats,
      value: valueIndex(stats.score, p.price, medianCache.get(p.category)),
    };
  }

  function getProduct(id) {
    return q('SELECT * FROM products WHERE id = ?').get(id);
  }

  // ---------- API ----------
  app.get('/api/categories', (_req, res) => {
    res.json(q('SELECT category, COUNT(*) AS count FROM products GROUP BY category ORDER BY count DESC, category').all());
  });

  app.get('/api/products', (req, res) => {
    const term = str(req.query.q, 100);
    const category = str(req.query.category, 60);
    const sort = ['score', 'value', 'reviews', 'failRate', 'new'].includes(req.query.sort) ? req.query.sort : 'score';
    let sql = 'SELECT * FROM products WHERE 1=1';
    const args = [];
    if (term) {
      sql += ' AND (name LIKE ? OR brand LIKE ? OR model LIKE ? OR category LIKE ?)';
      const like = '%' + term.replace(/[%_]/g, '') + '%';
      args.push(like, like, like, like);
    }
    if (category) { sql += ' AND category = ?'; args.push(category); }
    sql += ' ORDER BY id DESC LIMIT 200';
    const cache = new Map();
    const list = q(sql).all(...args).map((p) => summarize(p, cache));
    list.sort(sorters[sort]);
    res.json(list);
  });

  app.get('/api/products/:id', (req, res) => {
    const p = getProduct(Number(req.params.id));
    if (!p) return res.status(404).json({ error: 'Бараа олдсонгүй' });
    const cache = new Map();
    const product = summarize(p, cache);
    const reviews = reviewsFor(p.id).map((r) => ({
      ...r,
      better_alt: r.better_alt_id ? pick(getProduct(r.better_alt_id), ['id', 'name', 'brand', 'model']) : null,
    }));

    // Ижил ангиллын жагсаалт ба энэ барааны байр
    const peers = q('SELECT * FROM products WHERE category = ?').all(p.category).map((x) => summarize(x, cache));
    peers.sort(sorters.score);
    const rank = peers.findIndex((x) => x.id === p.id) + 1;
    const betterAlternatives = peers.filter((x) => x.id !== p.id && (x.stats.score ?? -1) > (product.stats.score ?? -1)).slice(0, 4);

    // Энэ барааны оронд хэрэглэгчдийн санал болгосон бараанууд
    const recommendedInstead = q(`
      SELECT better_alt_id AS id, COUNT(*) AS votes FROM reviews
      WHERE product_id = ? AND better_alt_id IS NOT NULL
      GROUP BY better_alt_id ORDER BY votes DESC LIMIT 5`).all(p.id)
      .map((r) => ({ ...summarize(getProduct(r.id), cache), votes: r.votes }));

    res.json({
      product: { ...product, images: imagesFor(p.id) },
      reviews,
      rank,
      categorySize: peers.length,
      betterAlternatives,
      recommendedInstead,
    });
  });

  app.post('/api/products', (req, res) => {
    const b = req.body || {};
    const name = str(b.name, 120);
    const category = str(b.category, 60);
    if (!name || !category) return res.status(400).json({ error: 'Нэр болон ангилал заавал шаардлагатай' });

    let image = null;
    if (b.image) {
      image = saveImage(b.image);
      if (image.error) return res.status(400).json({ error: image.error });
    }

    const info = q(`INSERT INTO products (name, brand, model, category, price, description)
      VALUES (?, ?, ?, ?, ?, ?)`).run(
      name, str(b.brand, 60), str(b.model, 60), category, int(b.price, 0, 1e10), str(b.description, 2000),
    );
    const id = Number(info.lastInsertRowid);
    if (image) {
      q('INSERT INTO product_images (product_id, file, emb_basic, emb_ml) VALUES (?, ?, ?, ?)').run(
        id, image.file, vec(b.embBasic), vec(b.embMl),
      );
    }
    res.status(201).json({ id });
  });

  // Бараанд нэмэлт зураг оруулах (өөр өнцгөөс авсан зураг таних чадварыг сайжруулна)
  app.post('/api/products/:id/images', (req, res) => {
    const p = getProduct(Number(req.params.id));
    if (!p) return res.status(404).json({ error: 'Бараа олдсонгүй' });
    const image = saveImage(req.body?.image);
    if (image.error) return res.status(400).json({ error: image.error });
    q('INSERT INTO product_images (product_id, file, emb_basic, emb_ml) VALUES (?, ?, ?, ?)').run(
      p.id, image.file, vec(req.body.embBasic), vec(req.body.embMl),
    );
    res.status(201).json({ ok: true });
  });

  app.post('/api/products/:id/reviews', (req, res) => {
    const p = getProduct(Number(req.params.id));
    if (!p) return res.status(404).json({ error: 'Бараа олдсонгүй' });
    const b = req.body || {};
    const rating = int(b.rating, 1, 5);
    if (!rating) return res.status(400).json({ error: 'Үнэлгээ (1–5 од) өгнө үү' });
    const broke = b.broke ? 1 : 0;
    let betterAlt = int(b.betterAltId, 1, 1e12);
    if (betterAlt) {
      const alt = getProduct(betterAlt);
      if (!alt || alt.id === p.id) betterAlt = null;
    }
    const wba = b.wouldBuyAgain === true ? 1 : b.wouldBuyAgain === false ? 0 : null;
    q(`INSERT INTO reviews (product_id, rating, broke, broken_part, months_used, price_paid,
        would_buy_again, pros, cons, body, better_alt_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      p.id, rating, broke, broke ? str(b.brokenPart, 80) : '', int(b.monthsUsed, 0, 600),
      int(b.pricePaid, 0, 1e10), wba, str(b.pros, 1000), str(b.cons, 1000), str(b.body, 4000), betterAlt,
    );
    res.status(201).json({ ok: true });
  });

  // Зургаар хайх: хөтөч дээр тооцоолсон хээг хадгалсан зургуудтай харьцуулна.
  app.post('/api/search/image', (req, res) => {
    const embMl = arr(req.body?.embMl);
    const embBasic = arr(req.body?.embBasic);
    if (!embMl && !embBasic) return res.status(400).json({ error: 'Зургийн хээ ирсэнгүй' });

    const best = new Map(); // product_id -> {sim, kind}
    for (const img of q('SELECT product_id, emb_basic, emb_ml FROM product_images').all()) {
      let sim = null, kind = null;
      // Ухаалаг (ML) хээ хоёр талд байвал түүнийг, үгүй бол энгийн хээг ашиглана
      if (embMl && img.emb_ml) { sim = cosine(embMl, JSON.parse(img.emb_ml)); kind = 'ml'; }
      if (sim === null && embBasic && img.emb_basic) { sim = cosine(embBasic, JSON.parse(img.emb_basic)); kind = 'basic'; }
      if (sim === null) continue;
      const prev = best.get(img.product_id);
      if (!prev || sim > prev.sim) best.set(img.product_id, { sim, kind });
    }

    const cache = new Map();
    const results = [...best.entries()]
      .sort((a, b) => b[1].sim - a[1].sim)
      .slice(0, 12)
      .map(([id, { sim, kind }]) => ({
        ...summarize(getProduct(id), cache),
        similarity: Math.round(sim * 1000) / 1000,
        matchKind: kind,
        isMatch: sim >= MATCH_THRESHOLD[kind],
      }));
    res.json(results);
  });

  app.get('/api/parts', (req, res) => {
    // Тухайн бараан дээр бусдын бичсэн эвдрэлийн нэрс — нэг ижил нэрээр бичүүлэхэд тусална
    const id = Number(req.query.productId);
    res.json(q(`SELECT DISTINCT broken_part AS part FROM reviews
      WHERE product_id = ? AND broken_part != '' ORDER BY part`).all(id).map((r) => r.part));
  });

  app.use('/api', (_req, res) => res.status(404).json({ error: 'Олдсонгүй' }));
  app.use((err, _req, res, _next) => {
    if (err.type === 'entity.too.large') return res.status(413).json({ error: 'Файл хэт том байна' });
    if (err.type === 'entity.parse.failed') return res.status(400).json({ error: 'Буруу хүсэлт' });
    console.error(err);
    res.status(500).json({ error: 'Серверийн алдаа' });
  });

  function saveImage(dataUrl) {
    const m = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$/.exec(String(dataUrl || ''));
    if (!m) return { error: 'Зураг JPEG, PNG эсвэл WebP байх ёстой' };
    const buf = Buffer.from(m[2], 'base64');
    if (buf.length > MAX_IMAGE_BYTES) return { error: 'Зураг 2MB-аас бага байх ёстой' };
    const file = crypto.randomUUID() + '.' + ALLOWED_IMAGE[m[1]];
    fs.writeFileSync(path.join(uploadsDir, file), buf);
    return { file };
  }

  app.locals.db = db;
  return app;
}

const sorters = {
  score: (a, b) => (b.stats.score ?? -1) - (a.stats.score ?? -1) || b.stats.reviewCount - a.stats.reviewCount,
  value: (a, b) => (b.value ?? -1) - (a.value ?? -1) || (b.stats.score ?? -1) - (a.stats.score ?? -1),
  reviews: (a, b) => b.stats.reviewCount - a.stats.reviewCount,
  failRate: (a, b) => (b.stats.failRate ?? -1) - (a.stats.failRate ?? -1),
  new: (a, b) => b.id - a.id,
};

// ---------- оролт шалгах ----------
function str(v, max) {
  return typeof v === 'string' ? v.trim().slice(0, max) : '';
}
function int(v, min, max) {
  const n = Number(v);
  if (v === null || v === undefined || v === '' || !Number.isFinite(n)) return null;
  const r = Math.round(n);
  return r < min || r > max ? null : r;
}
function arr(v) {
  return Array.isArray(v) && v.length > 0 && v.length <= 4096 && v.every((x) => Number.isFinite(x)) ? v : null;
}
function vec(v) {
  const a = arr(v);
  return a ? JSON.stringify(a.map((x) => Math.round(x * 1e5) / 1e5)) : null;
}
function pick(o, keys) {
  return o ? Object.fromEntries(keys.map((k) => [k, o[k]])) : null;
}

module.exports = { createApp };

if (require.main === module) {
  const dataDir = process.env.DATA_DIR || path.join(__dirname, '..', 'data');
  const app = createApp({
    dbFile: path.join(dataDir, 'baraa.db'),
    uploadsDir: path.join(dataDir, 'uploads'),
  });
  const port = Number(process.env.PORT) || 3000;
  app.listen(port, () => console.log(`Бараа толь: http://localhost:${port}`));
}
